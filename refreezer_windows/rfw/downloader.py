"""Track and playlist download manager for ReFreezer.

Matches refreezer download behavior:
- Queries https://media.deezer.com/v1/get_url with BF_CBC_STRIPE cipher
- Fallback quality logic: FLAC -> MP3_320 -> MP3_128
- Pure-Python Blowfish chunk decryption
- ID3v2.3 metadata tagging and synchronized .lrc lyrics
- Destination directory and playlist subfolder structure
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from .api import Library, Playlist, Track
from .blowfish import decrypt_file
from .tagger import apply_mp3_tags, save_lrc_file

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

QUALITY_FALLBACKS = {
    "FLAC": ["FLAC", "MP3_320", "MP3_128"],
    "MP3_320": ["MP3_320", "MP3_128"],
    "MP3_128": ["MP3_128"],
}

# Tracks downloaded at the same time per playlist; more risks Deezer throttling
DOWNLOAD_WORKERS = 4

# Quality choices shown in every download menu/dialog: (label, quality name)
QUALITIES = (("MP3 320 kbps", "MP3_320"), ("MP3 128 kbps", "MP3_128"), ("FLAC", "FLAC"))


def default_download_dir() -> Path:
    """Default download directory: Music/ReFreezer or Downloads/ReFreezer."""
    music = Path.home() / "Music" / "ReFreezer"
    try:
        music.mkdir(parents=True, exist_ok=True)
        return music
    except Exception:
        downloads = Path.home() / "Downloads" / "ReFreezer"
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads


def sanitize_filename(name: str) -> str:
    """Sanitize strings to be safe for Windows file and folder names."""
    if not name:
        return "untitled"
    # Remove Windows invalid chars: \ / ? * : % < > | "
    cleaned = re.sub(r'[\\/?*:%<>|"]', "", name)
    cleaned = cleaned.replace("$", "")
    # Remove leading/trailing dots and spaces
    cleaned = cleaned.strip(" .")
    return cleaned or "untitled"


class DownloadError(Exception):
    pass


class Downloader:
    def __init__(self, library: Library):
        self.library = library

    def _call_get_url(self, track_token: str, format_name: str) -> Optional[Tuple[str, str, bool]]:
        """Call media.deezer.com/v1/get_url for a single format."""
        license_token = getattr(self.library, "license_token", None)
        if not license_token:
            # Try to fetch license_token
            res = self.library.gw("deezer.getUserData")
            user = (res or {}).get("USER") or {}
            license_token = (user.get("OPTIONS") or {}).get("license_token")
            self.library.license_token = license_token

        if not license_token:
            return None

        payload = json.dumps({
            "license_token": license_token,
            "media": [{
                "type": "FULL",
                "formats": [{"cipher": "BF_CBC_STRIPE", "format": format_name}],
            }],
            "track_tokens": [track_token],
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://media.deezer.com/v1/get_url",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Cookie": f"arl={self.library.arl}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            raise DownloadError(f"HTTP {e.code} from get_url") from e
        except Exception as e:
            raise DownloadError(f"Network error from get_url: {e}") from e

        data_list = data.get("data") or []
        if not data_list:
            return None
        media_list = data_list[0].get("media") or []
        if not media_list:
            return None
        sources = media_list[0].get("sources") or []
        if not sources:
            return None

        url = sources[0].get("url")
        cipher_type = (media_list[0].get("cipher") or {}).get("type", "")
        is_encrypted = cipher_type == "BF_CBC_STRIPE"
        return url, format_name, is_encrypted

    def get_stream_info(self, track: Track, pref_quality: str = "MP3_320") -> Tuple[str, str, bool]:
        """Resolve streaming URL with automatic quality fallback."""
        track_token = track.track_token
        if not track_token:
            # Retrieve fresh track token from song.getListData
            fresh = self.library.get_track_data(track.id)
            track_token = fresh.get("TRACK_TOKEN") or ""

        if not track_token:
            raise DownloadError(f"Could not retrieve track token for track {track.id}")

        candidates = QUALITY_FALLBACKS.get(pref_quality, ["MP3_320", "MP3_128"])

        # Attempt formats in fallback order
        for fmt in candidates:
            res = self._call_get_url(track_token, fmt)
            if res:
                return res

        # If all failed, attempt 1 refresh of track token via song.getListData
        fresh = self.library.get_track_data(track.id)
        refreshed_token = fresh.get("TRACK_TOKEN") or ""
        if refreshed_token and refreshed_token != track_token:
            for fmt in candidates:
                res = self._call_get_url(refreshed_token, fmt)
                if res:
                    return res

        raise DownloadError(f"No stream available for track '{track.title}' (requested {pref_quality})")

    def _fallback_track(self, track: Track) -> Optional[Track]:
        """Licensed alternate Deezer offers for a region-blocked track (gw FALLBACK)."""
        fb = self.library.get_track_data(track.id).get("FALLBACK") or {}
        if not fb.get("SNG_ID") or str(fb["SNG_ID"]) == str(track.id):
            return None
        return Track.from_gw(fb)

    def download_track(
        self,
        track: Track,
        dest_dir: Union[str, Path],
        track_num: Optional[int] = None,
        total_tracks: Optional[int] = None,
        pref_quality: str = "MP3_320",
        save_cover: bool = True,
        save_lyrics: bool = True,
        overwrite: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Download and decrypt a single track, apply ID3 tags and save lyrics."""
        if is_cancelled and is_cancelled():
            raise InterruptedError("Download cancelled")

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Resolve stream; a region-blocked track falls back to its licensed alternate.
        # The Blowfish key derives from the id of the track actually streamed.
        key_id = track.id
        try:
            stream_url, format_name, is_encrypted = self.get_stream_info(track, pref_quality)
        except DownloadError:
            alt = self._fallback_track(track)
            if alt is None:
                raise
            stream_url, format_name, is_encrypted = self.get_stream_info(alt, pref_quality)
            key_id = alt.id
        ext = "flac" if format_name == "FLAC" else "mp3"

        # Build clean filename: e.g. "01 - Artist - Title.mp3"
        safe_artist = sanitize_filename(track.artist)
        safe_title = sanitize_filename(track.title)
        prefix = f"{track_num:02d} - " if track_num is not None else ""
        out_name = f"{prefix}{safe_artist} - {safe_title}.{ext}"
        final_path = dest_dir / out_name

        if final_path.exists() and not overwrite:
            if progress_cb:
                progress_cb(f"Already exists: {final_path.name}")
            return final_path

        # Position in the name too: parallel workers may get the same track twice in a playlist
        tmp_stem = f".tmp_{track_num or 0}_{track.id}"
        tmp_enc = dest_dir / f"{tmp_stem}.enc"
        tmp_dec = dest_dir / f"{tmp_stem}.dec"

        try:
            # Download stream
            req = urllib.request.Request(stream_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_enc, "wb") as fout:
                while True:
                    if is_cancelled and is_cancelled():
                        raise InterruptedError("Download cancelled")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fout.write(chunk)

            # Decrypt if encrypted
            if is_encrypted:
                decrypt_file(key_id, tmp_enc, tmp_dec)
                try:
                    tmp_enc.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                tmp_enc.replace(tmp_dec)

            # Cover art & Lyrics
            cover_bytes = None
            if save_cover and track.album_picture:
                cover_bytes = self.library.get_cover_bytes(track.album_picture)

            lyrics_text = ""
            if save_lyrics:
                lyrics_info = self.library.get_lyrics(track.id)
                if lyrics_info:
                    lyrics_text = lyrics_info.get("text") or ""
                    sync_lines = lyrics_info.get("sync") or []
                    if sync_lines:
                        lrc_path = dest_dir / f"{prefix}{safe_artist} - {safe_title}.lrc"
                        try:
                            save_lrc_file(lrc_path, sync_lines)
                        except Exception:
                            pass

            # Tag MP3
            if ext == "mp3":
                apply_mp3_tags(
                    tmp_dec,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    track_number=track_num or track.track_number,
                    track_total=total_tracks,
                    disc_number=track.disk_number,
                    cover_bytes=cover_bytes,
                    lyrics=lyrics_text,
                )

            # Rename to final filename
            tmp_dec.replace(final_path)
            return final_path

        finally:
            # Cleanup temp files
            for p in (tmp_enc, tmp_dec):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    def download_playlist(
        self,
        playlist: Playlist,
        tracks: Optional[List[Track]] = None,
        dest_root: Optional[Union[str, Path]] = None,
        pref_quality: str = "MP3_320",
        save_cover: bool = True,
        save_lyrics: bool = True,
        overwrite: bool = False,
        progress_cb: Optional[Callable[[int, int, Track, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        workers: int = DOWNLOAD_WORKERS,
    ) -> dict:
        """Download an entire playlist to a dedicated subfolder, ``workers`` tracks at a time.

        ``progress_cb(done, total, track, msg)`` fires from worker threads as each track ends.
        """
        if dest_root is None:
            dest_root = default_download_dir()
        dest_root = Path(dest_root)

        # Playlist subfolder
        folder_name = sanitize_filename(playlist.title)
        playlist_dir = dest_root / folder_name
        playlist_dir.mkdir(parents=True, exist_ok=True)

        # Fetch tracks if not preloaded
        if tracks is None:
            tracks = self.library.playlist_tracks(playlist.id)

        total = len(tracks)
        downloaded = []
        errors = []

        # Download playlist/album cover if possible
        if save_cover and tracks:
            first_pic = next((t.album_picture for t in tracks if t.album_picture), None)
            if first_pic:
                cover_data = self.library.get_cover_bytes(first_pic, size=1000)
                if cover_data:
                    try:
                        (playlist_dir / "cover.jpg").write_bytes(cover_data)
                    except Exception:
                        pass

        lock = threading.Lock()
        done = 0

        def run(idx: int, track: Track) -> None:
            nonlocal done
            if is_cancelled and is_cancelled():
                return
            try:
                path = self.download_track(
                    track=track,
                    dest_dir=playlist_dir,
                    track_num=idx,
                    total_tracks=total,
                    pref_quality=pref_quality,
                    save_cover=save_cover,
                    save_lyrics=save_lyrics,
                    overwrite=overwrite,
                    is_cancelled=is_cancelled,
                )
                status = "Downloaded"
            except InterruptedError:
                return
            except Exception as e:
                path, status = None, "Failed"
                err = str(e)
            with lock:
                if path is None:
                    errors.append((idx, track, err))
                else:
                    downloaded.append(path)
                done += 1
                n = done
            if progress_cb:
                progress_cb(n, total, track, f"[{n}/{total}] {status}: {track.artist} - {track.title}")

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for idx, track in enumerate(tracks, start=1):
                pool.submit(run, idx, track)

        errors = [(t, e) for _, t, e in sorted(errors, key=lambda x: x[0])]
        return {
            "folder": playlist_dir,
            "total": total,
            "downloaded": len(downloaded),
            "errors": errors,
            "cancelled": bool(is_cancelled and is_cancelled()),
        }
