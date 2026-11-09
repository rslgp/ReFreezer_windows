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


class SingleInstanceTests(unittest.TestCase):
    def test_second_claim_is_refused_until_first_is_released(self):
        import ctypes
        import uuid

        from rfw.hotkeys import claim_single_instance

        name = f"Local\\rfw-test-{uuid.uuid4()}"
        first = claim_single_instance(name, window_title=f"no-such-window-{uuid.uuid4()}")
        self.assertTrue(first)
        self.assertIsNone(claim_single_instance(name, window_title="no-such-window"))
        ctypes.windll.kernel32.CloseHandle(first)
        again = claim_single_instance(name, window_title="no-such-window")
        self.assertTrue(again)
        ctypes.windll.kernel32.CloseHandle(again)


class HotkeyStateTests(unittest.TestCase):
    def test_state_line_reports_active_and_failed_keys(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
        except Exception:
            self.skipTest("Tkinter not available")
        from rfw.app import MainWindow

        try:
            win = MainWindow(root)
            win.settings = dict(DEFAULT_SETTINGS)
            self.assertEqual(win.hotkey_state(), "Not started")
            win.hotkey_errors = {"dislike": "already used by another program (or invalid)"}
            state = win.hotkey_state()
            self.assertIn("Active: like ctrl+alt+L", state)
            self.assertIn("NOT active: dislike", state)
            win.settings["hotkeys_enabled"] = False
            self.assertEqual(win.hotkey_state(), "Off")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
