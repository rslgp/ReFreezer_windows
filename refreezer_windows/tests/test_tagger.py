import tempfile
import unittest
from pathlib import Path

from rfw.tagger import (
    _decode_synchsafe,
    _encode_synchsafe,
    apply_mp3_tags,
    build_id3v23_tag,
    save_lrc_file,
)


class TaggerTests(unittest.TestCase):
    def test_synchsafe_roundtrip(self):
        for val in (0, 127, 256, 10000, 2000000):
            encoded = _encode_synchsafe(val)
            self.assertEqual(len(encoded), 4)
            self.assertEqual(_decode_synchsafe(encoded), val)

    def test_build_id3v23_tag(self):
        tag = build_id3v23_tag(
            title="My Title",
            artist="My Artist",
            album="My Album",
            track_number=3,
            track_total=10,
            disc_number=1,
            year="2023",
            cover_bytes=b"\xFF\xD8\xFFfakejpeg",
            lyrics="Hello world",
        )
        self.assertTrue(tag.startswith(b"ID3\x03\x00\x00"))
        self.assertIn(b"TIT2", tag)
        self.assertIn(b"TPE1", tag)
        self.assertIn(b"TALB", tag)
        self.assertIn(b"TRCK", tag)
        self.assertIn(b"APIC", tag)
        self.assertIn(b"USLT", tag)

    def test_apply_mp3_tags_preserves_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp3_file = Path(tmp) / "song.mp3"
            dummy_audio = b"\xFF\xFB\x90\x64" + b"\x00" * 100
            mp3_file.write_bytes(dummy_audio)

            apply_mp3_tags(mp3_file, title="Test", artist="Artist")

            data = mp3_file.read_bytes()
            self.assertTrue(data.startswith(b"ID3"))
            self.assertTrue(data.endswith(dummy_audio))

    def test_apply_mp3_tags_replaces_existing_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp3_file = Path(tmp) / "song.mp3"
            dummy_audio = b"\xFF\xFB\x90\x64" + b"\x00" * 100
            mp3_file.write_bytes(dummy_audio)

            # Apply tag 1
            apply_mp3_tags(mp3_file, title="First Title")
            # Apply tag 2
            apply_mp3_tags(mp3_file, title="Second Title")

            data = mp3_file.read_bytes()
            # Only one ID3 tag at the beginning
            self.assertEqual(data.count(b"ID3"), 1)
            self.assertIn("Second Title".encode("utf-16"), data)
            self.assertTrue(data.endswith(dummy_audio))

    def test_save_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            lrc_file = Path(tmp) / "song.lrc"
            lines = [
                {"lrcTimestamp": "[00:01.00]", "line": "First line"},
                {"lrcTimestamp": "[00:05.50]", "line": "Second line"},
            ]
            save_lrc_file(lrc_file, lines)
            content = lrc_file.read_text(encoding="utf-8")
            self.assertIn("[00:01.00]First line\n[00:05.50]Second line\n", content)


if __name__ == "__main__":
    unittest.main()
