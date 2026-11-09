"""Tests for the global player hotkeys (previous / pause / next), registered like like/dislike."""

import tempfile
import time
import unittest

from rfw.deezer.api import Track
from rfw.services.hotkey_settings import ACTIONS, HotkeyController
from rfw.win.hotkeys import DEFAULT_SETTINGS, HotkeyError, parse_hotkey

from .test_playqueue import FakeDownloader, FakeMci


class FakeHotkeys:
    """Stands in for GlobalHotkeys: keeps the bindings instead of calling RegisterHotKey."""

    def __init__(self):
        self.bindings = None

    def start(self, bindings):
        self.bindings = bindings
        return {}

    def running(self):
        return self.bindings is not None

    def stop(self):
        self.bindings = None


class PlayerHotkeyParseTests(unittest.TestCase):
    def test_default_player_keys(self):
        self.assertEqual(parse_hotkey(DEFAULT_SETTINGS["hotkey_prev"]), (0x3, 0x25))
        self.assertEqual(parse_hotkey(DEFAULT_SETTINGS["hotkey_pause"]), (0x3, 0x28))
        self.assertEqual(parse_hotkey(DEFAULT_SETTINGS["hotkey_next"]), (0x3, 0x27))
        defaults = [parse_hotkey(DEFAULT_SETTINGS["hotkey_" + n]) for n in ACTIONS]
        self.assertEqual(len(set(defaults)), len(ACTIONS))

    def test_media_keys_work_alone_but_plain_keys_do_not(self):
        self.assertEqual(parse_hotkey("mediaprev"), (0, 0xB1))
        self.assertEqual(parse_hotkey("MediaPlayPause"), (0, 0xB3))
        self.assertEqual(parse_hotkey("medianext"), (0, 0xB0))
        for plain in ("left", "down", "right", "space"):
            with self.assertRaises(HotkeyError, msg=plain):
                parse_hotkey(plain)


class PlayerHotkeyControllerTests(unittest.TestCase):
    def ctl(self, saved):
        actions = {n: (lambda n=n: None) for n in ACTIONS}
        return HotkeyController(lambda fn: fn(), actions, lambda t: None, hotkeys=FakeHotkeys(),
                                settings=dict(DEFAULT_SETTINGS), save=saved.append)

    def test_all_five_are_registered(self):
        ctl = self.ctl([])
        ctl.apply()
        self.assertEqual(set(ctl.hotkeys.bindings), set(ACTIONS))
        self.assertIn("next ctrl+alt+right", ctl.state())

    def test_save_media_keys_and_reject_repeats(self):
        saved = []
        ctl = self.ctl(saved)
        keys = dict(ctl.keys(), prev="mediaprev", pause="mediaplaypause", next="medianext")
        self.assertEqual(ctl.save(True, keys), {})
        self.assertEqual(saved[-1]["hotkey_pause"], "mediaplaypause")
        self.assertEqual(ctl.hotkeys.bindings["next"][0], "medianext")
        with self.assertRaises(HotkeyError):
            ctl.save(True, dict(keys, next="mediaprev"))
        self.assertEqual(len(saved), 1)


class PlayerHotkeyAppTests(unittest.TestCase):
    """The app's hotkey actions drive the player; the hotkey thread only posts them."""

    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception:
            self.skipTest("Tkinter not available")
        from rfw import app as app_mod
        from rfw.media.player import PreviewPlayer

        self.tmp = tempfile.TemporaryDirectory()
        self.win = app_mod.MainWindow(self.root, settings=dict(DEFAULT_SETTINGS))
        self.win.hotkeys.hotkeys = FakeHotkeys()  # never RegisterHotKey from a test
        self.win.hotkeys.apply()
        self.win.session.api = object()
        self.win.session.downloader = FakeDownloader(self.tmp.name)
        self.mci = FakeMci()
        self.win.playback.player = PreviewPlayer(mci=self.mci)

    def tearDown(self):
        from concurrent.futures import wait

        self.win.playback.stop()
        wait(list(self.win.playback.stream.futures.values()), timeout=5)
        self.root.destroy()
        self.tmp.cleanup()

    def pump(self, until, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if until():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def playing(self):
        cur = self.win.playback.player.current
        return cur.id if cur is not None else None

    def press(self, name):
        """What the hotkey thread does on WM_HOTKEY: call the bound callback."""
        self.win.hotkeys.hotkeys.bindings[name][1]()

    def test_next_prev_pause_from_the_hotkey_thread(self):
        self.win.player_bar.shuffle_var.set(False)
        self.win.playback.play_queue([Track(id=str(i), title=f"S{i}", artist="A") for i in range(3)])
        self.pump(lambda: self.playing() == "0")
        self.press("next")
        self.pump(lambda: self.playing() == "1")
        self.press("prev")
        self.pump(lambda: self.playing() == "0")
        self.press("pause")
        self.pump(lambda: self.mci.mode == "paused")
        self.press("pause")
        self.pump(lambda: self.mci.mode == "playing")

    def test_prev_next_without_a_queue_do_nothing(self):
        self.press("next")
        self.press("prev")
        for _ in range(5):
            self.root.update()
        self.assertIsNone(self.win.playback.playq)

    def test_settings_dialog_lists_all_five(self):
        from rfw.ui.hotkey_dialog import open_hotkey_dialog

        dlg = open_hotkey_dialog(self.root, self.win.hotkeys, lambda t: None)
        entries = [w for w in dlg.winfo_children()[0].winfo_children() if w.winfo_class() == "TEntry"]
        self.assertEqual([e.get() for e in entries], [DEFAULT_SETTINGS["hotkey_" + n] for n in ACTIONS])
        dlg.destroy()


if __name__ == "__main__":
    unittest.main()
