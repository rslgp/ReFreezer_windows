"""Favorites -> genre grouping -> new playlist. UI-agnostic; used by CLI and GUI."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

UNKNOWN_GENRE = "Unknown"
FAVORITES_PAGE_SIZE = 500
ADD_CHUNK_SIZE = 200


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    album_id: str
    album: str

    @classmethod
    def from_gw(cls, j):
        return cls(
            id=str(j.get("SNG_ID", "")),
            title=j.get("SNG_TITLE", ""),
            artist=j.get("ART_NAME", ""),
            album_id=str(j.get("ALB_ID") or "0"),
            album=j.get("ALB_TITLE", ""),
        )


def _noop(*_):
    pass


def default_cache_path():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "genre_playlist_maker" / "album_genres.json"


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, cache):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_favorites(client, page_size=FAVORITES_PAGE_SIZE, progress=_noop):
    """All tracks of the user's Favorites (loved tracks) playlist."""
    if client.loved_tracks_id is None:
        client.login()
    pid = client.loved_tracks_id
    if not pid:
        raise ValueError("Account has no Favorites playlist (LOVEDTRACKS_ID empty)")
    tracks, start, total = [], 0, None
    while total is None or start < total:
        songs, total = client.playlist_page(pid, start, page_size)
        if not songs:
            break
        tracks.extend(Track.from_gw(s) for s in songs)
        start += len(songs)
        progress(min(start, total), total, "Loading favorites")
    return tracks


def resolve_album_genres(client, album_ids, cache, progress=_noop, save=_noop):
    """Map album_id -> [genre names]. Fills ``cache`` in place; skips album 0 (uploads).

    ``save`` is called every 50 lookups so an interrupted run keeps its progress.
    """
    todo = [a for a in dict.fromkeys(album_ids) if a not in cache and a not in ("", "0")]
    try:
        for i, album_id in enumerate(todo, 1):
            cache[album_id] = client.album_genres(album_id)
            progress(i, len(todo), "Resolving album genres")
            if i % 50 == 0:
                save(cache)
    finally:
        # Keep every finished lookup even if the run dies (network error, Ctrl+C)
        if todo:
            save(cache)
    return {a: cache.get(a, []) for a in album_ids}


SOURCES = ("lastfm", "deezer")


def build_genre_map(client, tracks, source="lastfm", lastfm_client=None, top_n=1, min_count=10,
                    deezer_fallback=True, progress=_noop, album_cache_path=None, lastfm_cache_path=None,
                    workers=None):
    """Return (genres_by_track, pending): track id -> [genres] from Last.fm track tags
    (default) or Deezer album genres, and how many Last.fm lookups failed.

    With Last.fm, a track without usable tags falls back to its artist's tags, then
    (``deezer_fallback``) to its Deezer album genres. Failed lookups stay uncached, so
    calling again with the same tracks resumes them.
    """
    if source not in SOURCES:
        raise ValueError(f"Unknown genre source {source!r}; use one of {SOURCES}")
    album_genres = None
    if source == "deezer" or deezer_fallback:
        path = album_cache_path or default_cache_path()
        album_genres = resolve_album_genres(
            client, [t.album_id for t in tracks], load_cache(path),
            progress=progress, save=lambda c: save_cache(path, c),
        )
    if source == "deezer":
        return album_genres_by_track(tracks, album_genres), 0

    from . import lastfm
    if lastfm_client is None:
        raise ValueError("Last.fm source needs an API key (LASTFM_API_KEY or lastfm_api_key.txt)")
    path = lastfm_cache_path or lastfm.default_cache_path()
    cache = load_cache(path)
    pending = lastfm.resolve_track_tags(lastfm_client, tracks, cache, progress=progress,
                                        save=lambda c: save_cache(path, c),
                                        workers=workers or lastfm.DEFAULT_WORKERS)
    genres = lastfm.track_genres_map(tracks, cache, top_n=top_n, min_count=min_count, album_genres=album_genres)
    return genres, pending


def album_genres_by_track(tracks, album_genres):
    """track id -> genres of its Deezer album."""
    return {t.id: list(album_genres.get(t.album_id) or []) for t in tracks}


def track_genres(track, genres_by_track):
    return genres_by_track.get(track.id) or [UNKNOWN_GENRE]


def group_by_genre(tracks, genres_by_track):
    """genre -> tracks. A track counts in every one of its genres."""
    groups = {}
    for t in tracks:
        for g in track_genres(t, genres_by_track):
            groups.setdefault(g, []).append(t)
    return dict(sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())))


def select_tracks(tracks, genres_by_track, genres):
    """Tracks matching any of ``genres`` (case-insensitive), favorites order, no duplicates."""
    wanted = {g.casefold() for g in genres}
    seen, out = set(), []
    for t in tracks:
        if t.id in seen:
            continue
        if any(g.casefold() in wanted for g in track_genres(t, genres_by_track)):
            seen.add(t.id)
            out.append(t)
    return out


def default_title(genres):
    return "Favorites - " + " + ".join(genres)


def create_genre_playlist(client, title, tracks, description="", status=1,
                          chunk_size=ADD_CHUNK_SIZE, progress=_noop):
    """Create the playlist with the first chunk, then append the rest. Returns playlist id."""
    if not tracks:
        raise ValueError("No tracks to add")
    ids = [t.id for t in tracks]
    first, rest = ids[:chunk_size], ids[chunk_size:]
    playlist_id = client.create_playlist(title, first, description=description, status=status)
    done = len(first)
    progress(done, len(ids), "Adding tracks")
    for i in range(0, len(rest), chunk_size):
        part = rest[i:i + chunk_size]
        client.add_songs(playlist_id, part)
        done += len(part)
        progress(done, len(ids), "Adding tracks")
    return playlist_id


def playlist_url(playlist_id):
    return f"https://www.deezer.com/playlist/{playlist_id}"
