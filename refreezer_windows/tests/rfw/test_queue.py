"""Tests for the play queue panel: queue edits (jump, play next, remove) and the side view."""

import tempfile
import time
import unittest

from rfw.core.playqueue import PlayQueue
from rfw.deezer.api import Track

from .test_playqueue import FakeDownloader, FakeMci


def tracks(n):
    return [Track(id=str(i), title=f"S{i}", artist="A") for i in range(n)]


def ids(q):
    return [t.id for _, t in q.entries()]


class QueueEditTests(unittest.TestCase):
    def test_jump_moves_current_and_bumps_version(self):
        q = PlayQueue(tracks(5))
        v = q.version
        self.assertEqual(q.jump(3).id, "3")
        self.assertEqual(q.pos, 3)
        self.assertGreater(q.version, v)

    def test_play_next_from_later_and_from_already_played(self):
        q = PlayQueue(tracks(6), start=2)
        q.play_next(5)
        self.assertEqual(ids(q), ["0", "1", "2", "5", "3", "4"])
        self.assertEqual(q.current.id, "2")
        q.play_next(0)  # an already played track: current must stay the same
        self.assertEqual(q.current.id, "2")
        self.assertEqual(q.peek_next().id, "0")

    def test_remove_keeps_current_and_refuses_playing_track(self):
        q = PlayQueue(tracks(5), start=2)
        self.assertFalse(q.remove(2))
        self.assertTrue(q.remove(0))  # before current: pos shifts, same track playing
        self.assertEqual(q.current.id, "2")
        self.assertTrue(q.remove(q.pos + 1))
        self.assertEqual(ids(q), ["1", "2", "4"])

    def test_removed_tracks_stay_out_after_reshuffle_and_refill(self):
        q = PlayQueue(tracks(8), shuffle=True, seed=3)
        gone = q.entries()[3][1]
        q.remove(3)
        q.reroll(seed=4)
        q.set_shuffle(False)
        q.extend([gone])  # a refill bringing it back is still dropped
        self.assertNotIn(gone.id, ids(q))
        self.assertEqual(len(ids(q)), 7)


class QueuePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception:
            cls.root = None

    @classmethod
    def tearDownClass(cls):
        if cls.root:
            cls.root.destroy()

    def setUp(self):
        if not self.root:
            self.skipTest("Tkinter not available")
        from rfw import app as app_mod
        from rfw.media.player import PreviewPlayer

        self.tmp = tempfile.TemporaryDirectory()
        self.win = app_mod.MainWindow(self.root)
        self.win.session.api = object()
        self.win.session.downloader = FakeDownloader(self.tmp.name)
        self.mci = FakeMci()
        self.win.playback.player = PreviewPlayer(mci=self.mci)

    def tearDown(self):
        from concurrent.futures import wait

        self.win.playback.stop()
        wait(list(self.win.playback.stream.futures.values()), timeout=5)
        self.tmp.cleanup()

    def pump(self, until, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if until():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def rows(self):
        lst = self.win.queue_view.list
        return [(lst.item(i, "values")[1], lst.item(i, "tags")) for i in lst.get_children()]

    def playing_id(self):
        cur = self.win.playback.player.current
        return cur.id if cur is not None else None

    def test_panel_mirrors_queue_and_its_actions(self):
        pb = self.win.playback
        self.win.player_bar.shuffle_var.set(False)
        pb.play_queue(tracks(5))
        self.pump(lambda: self.playing_id() == "0" and len(self.rows()) == 5)
        self.assertEqual(self.rows()[0][1], ("current",))

        pb.jump_to(3)  # double-click / "Play now"
        self.pump(lambda: self.playing_id() == "3" and self.rows()[3][1] == ("current",))
        self.assertEqual(self.rows()[0][1], ("played",))

        pb.play_next(1)
        self.pump(lambda: [r[0] for r in self.rows()] == ["S0", "S2", "S3", "S1", "S4"])

        pb.remove_from_queue(4)  # a later track
        self.pump(lambda: len(self.rows()) == 4)
        pb.remove_from_queue(pb.playq.pos)  # the playing one: skips to the next first
        self.pump(lambda: self.playing_id() == "1" and len(self.rows()) == 3)

        pb.stop()
        self.pump(lambda: self.rows() == [] and self.win.queue_view.title_var.get() == "Queue")

    def test_queue_menu_entries(self):
        import tkinter as tk

        pb = self.win.playback
        pb.play_queue(tracks(3))
        self.pump(lambda: self.playing_id() is not None)

        def labels(pos):
            m = tk.Menu(self.root)
            self.win.menus.queue_entries(m, pos, pb.playq.entries()[pos][1])
            return [m.entrycget(i, "label") for i in range(m.index("end") + 1) if m.type(i) != "separator"]

        other = labels(pb.playq.pos + 1)
        self.assertEqual(other[:3], ["Play now", "Play next", "Remove from queue"])
        self.assertIn("Copy link", other)
        self.assertNotIn("Play from here", other)  # acts on the middle list, not the queue
        self.assertNotIn("Play now", labels(pb.playq.pos))


if __name__ == "__main__":
    unittest.main()
