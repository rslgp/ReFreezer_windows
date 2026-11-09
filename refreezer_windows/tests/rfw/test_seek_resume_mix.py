"""Tests for the seek bar, the play queue kept between runs, and Settings > Mix."""

import json
import tempfile
import time
import types
import unittest
from pathlib import Path

from rfw.core.mix import MIX_DEFAULTS, PlaylistMix, mix_options
from rfw.core.playqueue import PlayQueue
from rfw.core.queue_store import QueueStore
from rfw.deezer.api import Track
from rfw.media.player import PreviewPlayer
from rfw.services.mix_settings import MixSettingsController
from rfw.services.queue_persist import SAVE_EVERY_S, QueuePersistence
from rfw.win.hotkeys import DEFAULT_SETTINGS

from .test_mix import fake_mix, tracks
from .test_playqueue import FakeDownloader, FakeMci


def songs(n):
    return [Track(id=str(i), title=f"S{i}", artist="A", duration=200, track_token=f"tok{i}") for i in range(n)]


class SeekPlayerTests(unittest.TestCase):
    def test_position_length_and_seek_keep_pause(self):
        mci = FakeMci()
        p = PreviewPlayer(mci=mci)
        self.assertEqual((p.position(), p.length()), (0, 0))  # nothing open
        p.play("x.mp3")
        self.assertIn("set rfwpreview time format milliseconds", mci.log)
        p.seek(42_000)
        self.assertEqual((p.position(), p.length()), (42_000, 180_000))
        p.pause()
        p.seek(10_000)
        self.assertEqual(mci.log[-2:], ["play rfwpreview from 10000", "pause rfwpreview"])
        self.assertEqual(p.state(), "paused")

    def test_fmt_time(self):
        try:
            from rfw.ui.player_bar import fmt_time
        except Exception:
            self.skipTest("Tkinter not available")
        self.assertEqual([fmt_time(0), fmt_time(65_400), fmt_time(3_725_000)], ["0:00", "1:05", "1:02:05"])


class QueueDataTests(unittest.TestCase):
    def test_round_trip_keeps_order_position_and_removed(self):
        q = PlayQueue(songs(6), start=2, shuffle=True, seed=11)
        q.next()
        q.remove(4)
        back = PlayQueue.from_dict(json.loads(json.dumps(q.to_dict())))
        self.assertEqual([t.id for _, t in back.entries()], [t.id for _, t in q.entries()])
        self.assertEqual((back.pos, back.seed, back.shuffle, back._removed), (q.pos, 11, True, q._removed))
        self.assertEqual(back.current, q.current)
        self.assertEqual(back.current.track_token, "")  # expired by the next run: fetched again
        back.set_shuffle(True)  # a removed song stays out after a reshuffle
        self.assertEqual(len(back.order), 5)

    def test_bad_data_raises_value_error(self):
        good = PlayQueue(songs(3)).to_dict()
        for bad in ({}, dict(good, order=[0, 9]), dict(good, pos=5), dict(good, tracks=[{"nope": 1}]),
                    dict(good, tracks=[])):
            with self.assertRaises(ValueError):
                PlayQueue.from_dict(bad)


class QueueStoreTests(unittest.TestCase):
    def test_per_user_and_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            store = QueueStore(Path(d) / "sub" / "queue.json")
            self.assertIsNone(store.load("u1"))
            store.save("u1", {"a": 1})
            self.assertEqual(store.load("u1"), {"a": 1})
            self.assertIsNone(store.load("u2"))  # another account never gets it
            store.path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(store.load("u1"))
            store.clear()
            store.clear()
            self.assertFalse(store.path.exists())


class FakePlayback:
    def __init__(self):
        self.playq, self.snap, self.restored = None, None, []

    def snapshot(self):
        return self.snap

    def restore(self, data):
        self.restored.append(data)
        self.playq = PlayQueue(songs(2))
        return True


class FakeStore:
    def __init__(self, saved=None):
        self.saved, self.writes, self.cleared = saved, [], 0

    def load(self, user_id):
        return self.saved

    def save(self, user_id, snap):
        self.writes.append((user_id, snap))

    def clear(self):
        self.cleared += 1


class QueuePersistenceTests(unittest.TestCase):
    def test_nothing_is_written_before_restore(self):
        pb, store = FakePlayback(), FakeStore()
        qp = QueuePersistence(pb, store, lambda t: None)
        qp.tick()
        qp.save_now()
        self.assertEqual((store.writes, store.cleared), ([], 0))

    def test_saves_on_change_every_few_seconds_and_clears_on_stop(self):
        now = [100.0]
        pb, store = FakePlayback(), FakeStore(saved={"q": 1})
        qp = QueuePersistence(pb, store, lambda t: None, clock=lambda: now[0])
        self.assertTrue(qp.restore("u1"))
        self.assertEqual(pb.restored, [{"q": 1}])
        pb.snap = {"s": 1}
        qp.tick()
        self.assertEqual(store.writes, [])  # nothing changed yet
        pb.playq.next()
        qp.tick()
        self.assertEqual(store.writes, [("u1", {"s": 1})])
        now[0] += SAVE_EVERY_S
        qp.tick()  # time in the song moved on
        self.assertEqual(len(store.writes), 2)
        pb.playq, pb.snap = None, None  # Stop
        qp.tick()
        self.assertEqual(store.cleared, 1)


class MixSettingsTests(unittest.TestCase):
    def test_options_are_clamped_and_defaulted(self):
        o = mix_options({"mix_seeds_per_batch": 999, "mix_tracks_per_seed": "x", "mix_interleave": 0})
        self.assertEqual(o["mix_seeds_per_batch"], 20)
        self.assertEqual(o["mix_tracks_per_seed"], MIX_DEFAULTS["mix_tracks_per_seed"])
        self.assertIs(o["mix_interleave"], False)
        self.assertEqual(mix_options({}), MIX_DEFAULTS)

    def test_controller_validates_and_saves(self):
        saved, settings = [], dict(DEFAULT_SETTINGS, **MIX_DEFAULTS)
        ctl = MixSettingsController(settings, save=saved.append)
        with self.assertRaises(ValueError):
            ctl.save(dict(ctl.values(), mix_refill_at="many"))
        with self.assertRaises(ValueError):
            ctl.save(dict(ctl.values(), mix_seeds_per_batch="0"))
        self.assertEqual(saved, [])
        ctl.save(dict(ctl.values(), mix_seeds_per_batch="5", mix_interleave=False))
        self.assertEqual((settings["mix_seeds_per_batch"], settings["mix_interleave"]), (5, False))
        self.assertEqual(saved[-1]["hotkey_like"], DEFAULT_SETTINGS["hotkey_like"])  # other keys kept

    def test_mix_options_change_the_batches(self):
        pl = tracks("p", 4)
        grouped = PlaylistMix(pl, 1, seeds_per_batch=2, per_seed=3, shuffle_seeds=False, interleave=False)
        ids = [t.id for t in grouped.next_batch(fake_mix)]
        self.assertEqual(ids, ["rp0-0", "rp0-1", "rp0-2", "rp1-0", "rp1-1", "rp1-2"])  # playlist order, grouped
        keep = PlaylistMix(pl, 1, seeds_per_batch=1, per_seed=2, shuffle_seeds=False, skip_playlist_songs=False)
        self.assertEqual([t.id for t in keep.next_batch(fake_mix)], ["p0", "rp0-0"])  # seed song allowed
        keep.tune({"mix_seeds_per_batch": 2, "mix_tracks_per_seed": 1})
        self.assertEqual([t.id for t in keep.next_batch(fake_mix)], ["p1", "p2"])
        excl = PlaylistMix(pl, 1, seeds_per_batch=1, per_seed=3, shuffle_seeds=False)
        excl.exclude({"rp0-0"})
        self.assertEqual([t.id for t in excl.next_batch(fake_mix)], ["rp0-1", "rp0-2", "rp0-3"])


class AppSeekResumeTests(unittest.TestCase):
    """Real MainWindow with a fake account: seek, quit, start again, log in, resume."""

    def setUp(self):
        try:
            import tkinter as tk
            self.tk = tk
            tk.Tk().destroy()
        except Exception:
            self.skipTest("Tkinter not available")
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QueueStore(Path(self.tmp.name) / "queue.json")
        self.windows = []

    def tearDown(self):
        from concurrent.futures import wait

        for root, win in self.windows:
            win.playback.stop()
            wait(list(win.playback.stream.futures.values()), timeout=5)
            try:
                root.after_cancel(win._poll_id)
                root.destroy()
            except self.tk.TclError:
                pass
        self.tmp.cleanup()

    def window(self):
        from rfw import app as app_mod

        root = self.tk.Tk()
        root.withdraw()
        win = app_mod.MainWindow(root, settings=dict(DEFAULT_SETTINGS, **MIX_DEFAULTS), queue_store=self.store)
        win.session.downloader = FakeDownloader(self.tmp.name)
        win.playback.player = PreviewPlayer(mci=FakeMci())
        self.windows.append((root, win))
        return root, win

    def login(self, win):
        """What AccountController does once the ARL login worked."""
        win.session.api = types.SimpleNamespace(user_id="u1", user_name="me", flow=lambda t=None: songs(3))
        win._logged_in("me")

    def pump(self, root, until, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            root.update()
            if until():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def test_seek_then_resume_after_restart(self):
        root, win = self.window()
        self.login(win)
        pb, mci = win.playback, win.playback.player._mci
        pb.play_queue(songs(4), start=1, shuffle=False)
        self.pump(root, lambda: pb.player.current is not None and pb.player.current.id == "1")
        bar = win.player_bar
        bar.seek_scale.winfo_width = lambda: 200
        bar._seek_press(types.SimpleNamespace(x=100))
        bar._seek_release(types.SimpleNamespace(x=100))  # click in the middle of the bar
        self.assertIn("play rfwpreview from 90000", mci.log)
        bar.show_progress(pb.progress())
        self.assertEqual((bar.time_var.get(), bar.length_var.get()), ("1:30", "3:00"))
        win.quit()
        self.assertEqual(self.store.load("u1")["position_ms"], 90_000)

        root2, win2 = self.window()
        self.assertIsNone(win2.playback.playq)  # nothing before login
        win2.queue_persist.tick()
        self.assertTrue(self.store.path.exists())  # starting the app did not wipe it
        self.login(win2)
        pb2 = win2.playback
        self.assertEqual(pb2.playq.current.id, "1")
        self.assertIsNone(pb2.player.current)  # waits, does not play by itself
        self.assertIn("⏯ to continue", win2.player_bar.now_var.get())
        self.assertEqual(pb2.progress(), (90_000, 200_000))
        pb2.toggle_pause()  # the pause key (button or global hotkey) resumes it
        self.pump(root2, lambda: pb2.player.current is not None)
        self.assertEqual(pb2.player.current.id, "1")
        self.assertIn("play rfwpreview from 90000", pb2.player._mci.log)

    def test_restored_flow_keeps_refilling(self):
        q = PlayQueue(songs(2))
        self.store.save("u1", {"queue": q.to_dict(), "position_ms": 0,
                               "endless": {"kind": "flow", "flow_type": "chill"}})
        root, win = self.window()
        self.login(win)
        pb = win.playback
        self.assertTrue(pb.flow_mode)
        self.assertEqual(pb.endless_info, {"kind": "flow", "flow_type": "chill"})
        self.assertEqual(pb.snapshot()["endless"], {"kind": "flow", "flow_type": "chill"})

    def test_mix_dialog_saves(self):
        from rfw.ui.mix_dialog import open_mix_dialog

        root, win = self.window()
        saved = []
        win.mix_settings._save = saved.append
        dlg = open_mix_dialog(root, win.mix_settings, lambda t: None)
        spin = [w for w in dlg.winfo_children()[0].winfo_children() if w.winfo_class() == "TSpinbox"]
        self.assertEqual(len(spin), 3)
        spin[0].set("7")
        buttons = {w.cget("text"): w for w in dlg.winfo_children()[0].winfo_children()[-1].winfo_children()}
        buttons["Save"].invoke()
        self.assertEqual(win.settings["mix_seeds_per_batch"], 7)
        self.assertEqual(len(saved), 1)


if __name__ == "__main__":
    unittest.main()
