"""ID3v2.3 tagger and lyrics writer for downloaded tracks.

Pure Python / standard library only.
Writes Title, Artist, Album, Track number, Disc number, Year, Cover image (APIC),
and Lyrics (USLT) to MP3 files, and saves synchronized lyrics (.lrc).
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional, Union


def _encode_synchsafe(size: int) -> bytes:
    """Encode an integer into a 4-byte ID3 synchsafe integer (7 bits per byte)."""
    return bytes([
        (size >> 21) & 0x7F,
        (size >> 14) & 0x7F,
        (size >> 7) & 0x7F,
        size & 0x7F,
    ])


def _decode_synchsafe(raw: bytes) -> int:
    """Decode 4 synchsafe bytes into an integer."""
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _text_frame(frame_id: str, text: str) -> bytes:
    """Create an ID3v2.3 text frame with UTF-16 with BOM (encoding 0x01)."""
    if not text:
        return b""
    payload = b"\x01" + text.encode("utf-16")
    header = frame_id.encode("ascii") + struct.pack(">IH", len(payload), 0)
    return header + payload


def _apic_frame(image_bytes: bytes, mime: str = "image/jpeg") -> bytes:
    """Create an ID3v2.3 APIC (Attached picture) frame for front cover (type 0x03)."""
    if not image_bytes:
        return b""
    # encoding (0 = ISO-8859-1), mime\0, pic_type (3 = Cover front), desc\0, image data
    payload = b"\x00" + mime.encode("ascii") + b"\x00\x03\x00" + image_bytes
    header = b"APIC" + struct.pack(">IH", len(payload), 0)
    return header + payload


def _uslt_frame(lyrics: str, lang: str = "eng") -> bytes:
    """Create an ID3v2.3 USLT (Unsynchronized lyrics) frame."""
    if not lyrics:
        return b""
    # encoding (1 = UTF-16), 3-byte lang, empty descriptor (UTF-16 BOM + null), lyrics
    payload = b"\x01" + lang[:3].encode("ascii") + b"\xff\xfe\x00\x00" + lyrics.encode("utf-16")
    header = b"USLT" + struct.pack(">IH", len(payload), 0)
    return header + payload


def build_id3v23_tag(
    title: str = "",
    artist: str = "",
    album: str = "",
    track_number: Optional[int] = None,
    track_total: Optional[int] = None,
    disc_number: Optional[int] = None,
    year: str = "",
    cover_bytes: Optional[bytes] = None,
    lyrics: str = "",
) -> bytes:
    """Build a complete ID3v2.3 tag binary header and frames."""
    frames = []

    if title:
        frames.append(_text_frame("TIT2", title))
    if artist:
        frames.append(_text_frame("TPE1", artist))
    if album:
        frames.append(_text_frame("TALB", album))
    if track_number is not None and track_number > 0:
        val = f"{track_number}/{track_total}" if track_total else str(track_number)
        frames.append(_text_frame("TRCK", val))
    if disc_number is not None and disc_number > 0:
        frames.append(_text_frame("TPOS", str(disc_number)))
    if year:
        frames.append(_text_frame("TYER", str(year)[:4]))
    if cover_bytes:
        frames.append(_apic_frame(cover_bytes))
    if lyrics:
        frames.append(_uslt_frame(lyrics))

    body = b"".join(frames)
    if not body:
        return b""

    header = b"ID3\x03\x00\x00" + _encode_synchsafe(len(body))
    return header + body


def apply_mp3_tags(
    mp3_path: Union[str, Path],
    title: str = "",
    artist: str = "",
    album: str = "",
    track_number: Optional[int] = None,
    track_total: Optional[int] = None,
    disc_number: Optional[int] = None,
    year: str = "",
    cover_bytes: Optional[bytes] = None,
    lyrics: str = "",
) -> None:
    """Write ID3v2.3 tags to an MP3 file, replacing any existing ID3v2 header."""
    path = Path(mp3_path)
    data = path.read_bytes()

    # Strip existing ID3v2 tag if present at start of file
    offset = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        tag_size = _decode_synchsafe(data[6:10])
        offset = 10 + tag_size
        audio_data = data[offset:]
    else:
        audio_data = data

    new_tag = build_id3v23_tag(
        title=title,
        artist=artist,
        album=album,
        track_number=track_number,
        track_total=track_total,
        disc_number=disc_number,
        year=year,
        cover_bytes=cover_bytes,
        lyrics=lyrics,
    )

    path.write_bytes(new_tag + audio_data)


def save_lrc_file(lrc_path: Union[str, Path], lines: list[dict]) -> Path:
    """Save synchronized lyrics to a standard .lrc file.

    `lines` is a list of dicts with 'lrcTimestamp' (e.g. '[00:12.34]') and 'line'.
    """
    path = Path(lrc_path)
    content = []
    for item in lines:
        ts = item.get("lrcTimestamp") or item.get("timestamp") or ""
        text = item.get("line") or item.get("text") or ""
        if ts:
            content.append(f"{ts}{text}")
        else:
            content.append(text)
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return path
