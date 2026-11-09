"""Tests for global hotkey parsing and the settings file."""

import tempfile
import unittest
from pathlib import Path

from rfw.hotkeys import DEFAULT_SETTINGS, HotkeyError, load_settings, parse_hotkey, save_settings


class ParseHotkeyTests(unittest.TestCase):
    def test_letters_digits_function_and_named_keys(self):
        self.assertEqual(parse_hotkey("ctrl+alt+L"), (0x3, ord("L")))
        self.assertEqual(parse_hotkey("Ctrl + Shift + 5"), (0x6, ord("5")))
        self.assertEqual(parse_hotkey("win+F9"), (0x8, 0x78))
        self.assertEqual(parse_hotkey("alt+space"), (0x1, 0x20))

    def test_rejects_bad_combinations(self):
        for bad in ("L", "ctrl+alt", "ctrl+A+B", "ctrl+nope", "", "ctrl+F25"):
            with self.assertRaises(HotkeyError, msg=bad):
                parse_hotkey(bad)

    def test_defaults_parse(self):
        self.assertNotEqual(parse_hotkey(DEFAULT_SETTINGS["hotkey_like"]),
                            parse_hotkey(DEFAULT_SETTINGS["hotkey_dislike"]))


class SettingsTests(unittest.TestCase):
    def test_missing_or_broken_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_settings(Path(d) / "none.json"), DEFAULT_SETTINGS)
            bad = Path(d) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_settings(bad), DEFAULT_SETTINGS)

    def test_round_trip_ignores_unknown_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "settings.json"
            save_settings({"hotkey_like": "ctrl+shift+F9", "junk": 1}, p)
            s = load_settings(p)
            self.assertEqual(s["hotkey_like"], "ctrl+shift+F9")
            self.assertEqual(s["hotkey_dislike"], DEFAULT_SETTINGS["hotkey_dislike"])
            self.assertNotIn("junk", s)


if __name__ == "__main__":
    unittest.main()
