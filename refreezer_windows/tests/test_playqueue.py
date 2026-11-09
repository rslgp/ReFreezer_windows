"""Tests for the streaming play queue (seeded shuffle) and its wiring in the GUI."""

import tempfile
import time
import unittest
from pathlib import Path

from rfw.api import Playlist, Track
from rfw.playqueue import PlayQueue


def tracks(n):
    return [Track(id=str(i), title=f"S{i}", artist="A") for i in range(n)]


class PlayQueueTests(unittest.TestCase):
    def ids(self, q):
        return [q.tracks[i].id for i in q.order]

    def test_in_order_from_start_index(self):
        q = PlayQueue(tracks(4), start=2)
        self.assertEqual(q.current.id, "2")
        self.assertEqual(q.next().id, "3")
        self.assertIsNone(q.next())
        self.assertEqual(q.prev().id, "2")

    def test_same_seed_same_order(self):
        a, b = PlayQueue(tracks(30), shuffle=True, seed=42), PlayQueue(tracks(30), shuffle=True, seed=42)
        self.assertEqual(self.ids(a), self.ids(b))
        self.assertNotEqual(self.ids(a), [str(i) for i in range(30)])
        self.assertEqual(sorted(self.ids(a), key=int), [str(i) for i in range(30)])

    def test_shuffle_from_chosen_track_plays_it_first(self):
        q = PlayQueue(tracks(30), start=7, shuffle=True, seed=1)
        self.assertEqual(q.current.id, "7")
        self.assertEqual(len(set(self.ids(q))), 30)

    def test_reroll_keeps_current_and_changes_order(self):
        q = PlayQueue(tracks(30), shuffle=True, seed=1)
        q.next()
        q.next()
        playing, before = q.current, self.ids(q)
        self.assertEqual(q.reroll(seed=2), 2)
        self.assertIs(q.current, playing)
        self.assertEqual(q.pos, 0)
        self.assertNotEqual(self.ids(q), before)
        self.assertEqual(self.ids(q), self.ids(PlayQueue(tracks(30), start=int(playing.id), shuffle=True, seed=2)))

    def test_reroll_without_seed_draws_new_one(self):
        q = PlayQueue(tracks(5), seed=1)
        self.assertNotEqual(q.reroll(), None)
        self.assertTrue(q.shuffle)

    def test_shuffle_off_returns_to_list_order_at_current(self):
        q = PlayQueue(tracks(10), start=4, shuffle=True, seed=3)
        q.set_shuffle(False)
        self.assertEqual(q.current.id, "4")
        self.assertEqual(q.peek_next().id, "5")

    def test_extend_appends_new_tracks_only(self):
        q = PlayQueue(tracks(3))
        q.next()
        q.extend([Track(id="2", title="dup", artist="A"), Track(id="9", title="new", artist="A")])
        self.assertEqual(self.ids(q), ["0", "1", "2", "9"])
        self.assertEqual(q.remaining(), 2)

    def test_empty_queue_rejected(self):
        with self.assertRaises(ValueError):
            PlayQueue([])


class FakeMci:
    """Stands in for winmm: tracks open/close and answers 'status ... mode'."""

    def __init__(self):
        self.mode = "playing"
        self.log = []

    def __call__(self, cmd):
        self.log.append(cmd)
        if cmd.startswith("status"):
            return self.mode
        if cmd.startswith("pause"):
            self.mode = "paused"
        elif cmd.startswith("resume") or cmd.startswith("play"):
            self.mode = "playing"
        return ""


class FakeDownloader:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.calls = []

    def download_track(self, track, dest_dir, **kwargs):
        self.calls.append((track.id, kwargs.get("pref_quality")))
        if track.id == "bad":
            raise RuntimeError("blocked")
        p = self.folder / f"{track.id}.mp3"
        p.write_bytes(b"ID3")
        return p


class StreamingGuiTests(unittest.TestCase):
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
        from rfw.player import PreviewPlayer

        self.tmp = tempfile.TemporaryDirectory()
        self.win = app_mod.MainWindow(self.root)
        self.win.api = object()
        self.win.downloader = FakeDownloader(self.tmp.name)
        self.mci = FakeMci()
        self.win.player = PreviewPlayer(mci=self.mci)

    def tearDown(self):
        from concurrent.futures import wait

        self.win.stop()
        # Prefetch threads may still be writing into tmp; let them finish first
        wait(list(self.win._stream_futs.values()), timeout=5)
        self.tmp.cleanup()

    def pump(self, until, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if until():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def test_queue_streams_skips_failures_and_advances_on_track_end(self):
        tr = [Track(id="1", title="One", artist="A"), Track(id="bad", title="Bad", artist="A"),
              Track(id="3", title="Three", artist="A")]
        self.win.shuffle_var.set(False)
        self.win.play_queue(tr)
        self.pump(lambda: self.win.player.current is not None)
        self.assertEqual(self.win.player.current.id, "1")
        self.assertEqual(self.win.downloader.calls[0], ("1", "MP3_128"))

        self.mci.mode = "stopped"  # track 1 ends; 'bad' fails and is skipped
        self.pump(lambda: self.win.player.current is not None and self.win.player.current.id == "3")
        self.assertIn("bad", [tid for tid, _ in self.win.downloader.calls])

        self.mci.mode = "stopped"  # last track ends: queue is done
        self.pump(lambda: self.win.playq is None)

    def test_pause_does_not_advance(self):
        self.win.play_queue([Track(id="1", title="One", artist="A"), Track(id="2", title="Two", artist="A")])
        self.pump(lambda: self.win.player.current is not None)
        current = self.win.player.current
        self.win.toggle_pause()
        for _ in range(10):
            self.root.update()
            time.sleep(0.02)
        self.assertIs(self.win.player.current, current)
        self.win.toggle_pause()
        self.assertEqual(self.mci.mode, "playing")

    def test_reroll_sets_seed_and_reshuffles_live_queue(self):
        tr = [Track(id=str(i), title=f"S{i}", artist="A") for i in range(20)]
        self.win.seed_var.set("5")
        self.win.play_queue(tr, shuffle=True)
        self.assertEqual(self.win.playq.seed, 5)
        playing = self.win.playq.current
        self.win.reroll()
        self.assertNotEqual(self.win.seed_var.get(), "5")
        self.assertEqual(self.win.playq.seed, int(self.win.seed_var.get()))
        self.assertIs(self.win.playq.current, playing)

    def test_flow_plays_and_refills_when_running_low(self):
        batches = [[Track(id=f"f{i}", title=f"F{i}", artist="A") for i in range(3)],
                   [Track(id=f"g{i}", title=f"G{i}", artist="A") for i in range(3)]]
        calls = []

        class Api:
            def flow(self_inner, config_id=None):
                calls.append(config_id)
                return batches.pop(0) if batches else []

        self.win.api = Api()
        self.win.play_flow("chill")
        self.pump(lambda: self.win.player.current is not None and len(self.win.playq.tracks) == 6)
        self.assertTrue(self.win.flow_mode)
        self.assertEqual(self.win.player.current.id, "f0")
        # 3 tracks <= 2 left after the first: refilled once, with the same variant
        self.assertEqual(calls, ["chill", "chill"])

    def test_smart_track_list_id_plays_its_tracks_without_refill(self):
        asked = []

        class Api:
            def smart_track_list(self_inner, stl_id):
                asked.append(stl_id)
                return "Mix", [Track(id="s1", title="S1", artist="A"), Track(id="s2", title="S2", artist="A")]

            def flow(self_inner, config_id=None):
                raise AssertionError("smart track list must not call flow")

        self.win.api = Api()
        self.win.play_from_smart_track_list("123")
        self.pump(lambda: self.win.player.current is not None)
        self.assertEqual(asked, ["123"])
        self.assertFalse(self.win.flow_mode)
        self.assertEqual(self.win.status_var.get(), "")

    def test_flow_end_with_no_new_tracks_stops_instead_of_looping(self):
        class Api:
            n = 0

            def flow(self_inner, config_id=None):
                Api.n += 1
                return [Track(id="only", title="Only", artist="A")]

        self.win.api = Api()
        self.win.play_flow()
        self.pump(lambda: self.win.player.current is not None)
        self.mci.mode = "stopped"
        self.pump(lambda: self.win.playq is None)
        self.assertLessEqual(Api.n, 4)

    def test_like_and_dislike_act_on_playing_song(self):
        log = []

        class Api:
            def add_favorites(self_inner, ids):
                log.append(("like", ids))

            def dislike(self_inner, tid):
                log.append(("dislike", tid))

        self.win.api = Api()
        self.win.play_queue([Track(id="1", title="One", artist="A"), Track(id="2", title="Two", artist="A")])
        self.pump(lambda: self.win.player.current is not None)
        self.win.like_current()
        self.pump(lambda: "1" in self.win.favorite_ids)
        self.win.like_current()  # already liked: no second API call
        self.win.dislike_current()
        self.pump(lambda: self.win.player.current is not None and self.win.player.current.id == "2")
        self.assertEqual(log, [("like", ["1"]), ("dislike", "1")])

    def test_like_button_shows_liked_state_of_playing_song(self):
        from rfw.app import LIKE_TEXT

        class Api:
            def add_favorites(self_inner, ids):
                pass

        self.win.api = Api()
        self.win.favorite_ids = {"2"}
        self.win.shuffle_var.set(False)
        self.win.play_queue([Track(id="1", title="One", artist="A"), Track(id="2", title="Two", artist="A")])
        self.pump(lambda: self.win.player.current is not None)
        self.pump(lambda: self.win.like_btn.cget("text") == LIKE_TEXT[False])
        self.win.like_current()  # like the playing song: button flips
        self.pump(lambda: self.win.like_btn.cget("text") == LIKE_TEXT[True])
        self.win.queue_next()  # next song is already a favorite
        self.pump(lambda: self.win.player.current is not None and self.win.player.current.id == "2")
        self.pump(lambda: self.win.like_btn.cget("text") == LIKE_TEXT[True])
        self.win.favorite_ids.discard("2")  # e.g. removed via the track list heart menu
        self.pump(lambda: self.win.like_btn.cget("text") == LIKE_TEXT[False])
        self.win.stop()
        self.pump(lambda: self.win.like_btn.cget("text") == LIKE_TEXT[False])

    def test_hotkey_actions_are_posted_to_tk_thread(self):
        hits = []
        self.win.q.put(("call", lambda: hits.append(1), None))
        self.pump(lambda: hits == [1])

    def test_playlist_menus_offer_play_entries(self):
        import tkinter as tk

        class Api:
            def is_own(self, p):
                return False

        self.win.api = Api()
        m = tk.Menu(self.root)
        self.win._library_entries(m, Playlist(id="9", title="P"))
        labels = [m.entrycget(i, "label") for i in range(m.index("end") + 1) if m.type(i) != "separator"]
        self.assertEqual(labels[:2], ["Play", "Play shuffled"])


if __name__ == "__main__":
    unittest.main()
