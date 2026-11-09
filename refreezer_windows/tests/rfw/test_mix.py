"""Tests for the playlist mix (recommendations seeded by a playlist's songs)."""

import tempfile
import threading
import time
import unittest

from rfw.core.mix import PlaylistMix
from rfw.deezer.api import Playlist, Track

from .test_playqueue import FakeDownloader, FakeMci


def tracks(prefix, n):
    return [Track(id=f"{prefix}{i}", title=f"{prefix.upper()}{i}", artist="A") for i in range(n)]


def fake_mix(track_id):
    """Seed first (like Deezer), then 5 recommendations unique to that seed."""
    return [Track(id=track_id, title="seed", artist="A")] + tracks(f"r{track_id}-", 5)


class PlaylistMixTests(unittest.TestCase):
    def test_same_seed_same_seed_order(self):
        pl = tracks("p", 10)
        a, b = PlaylistMix(pl, 7), PlaylistMix(pl, 7)
        self.assertEqual([t.id for t in a.next_seeds()], [t.id for t in b.next_seeds()])
        self.assertNotEqual([t.id for t in PlaylistMix(pl, 7)._seeds], [t.id for t in PlaylistMix(pl, 8)._seeds])

    def test_batch_interleaves_and_drops_playlist_songs(self):
        pl = tracks("p", 6)
        mix = PlaylistMix(pl, 1, seeds_per_batch=2, per_seed=10)
        batch = mix.next_batch(fake_mix)
        ids = [t.id for t in batch]
        self.assertFalse(set(ids) & {t.id for t in pl})  # no seed / playlist song comes back
        self.assertEqual(len(ids), 10)
        seeds = {i.split("-")[0] for i in ids}
        self.assertEqual(len(seeds), 2)
        self.assertNotEqual(ids[0].split("-")[0], ids[1].split("-")[0])  # round-robin

    def test_per_seed_cap_and_no_repeats_across_batches(self):
        pl = tracks("p", 4)
        shared = tracks("s", 3)
        mix = PlaylistMix(pl, 1, seeds_per_batch=2, per_seed=2)
        first = mix.next_batch(lambda tid: shared)
        second = mix.next_batch(lambda tid: shared)
        self.assertEqual([t.id for t in first], ["s0", "s1"])
        # the cap counts songs not queued yet, so the 2nd batch gets the one left
        self.assertEqual([t.id for t in second], ["s2"])
        self.assertEqual(mix.remaining_seeds(), 0)
        self.assertEqual(mix.next_batch(lambda tid: shared), [])  # seeds used up

    def test_seed_batches_run_in_parallel_and_failures_are_skipped(self):
        pl = tracks("p", 3)
        barrier = threading.Barrier(3, timeout=2)

        def fetch(tid):
            barrier.wait()  # only passes if all 3 seeds are fetched at the same time
            if tid == pl[0].id:
                raise RuntimeError("boom")
            return fake_mix(tid)

        mix = PlaylistMix(pl, 1, seeds_per_batch=3, per_seed=10)
        batch = mix.next_batch(fetch)
        self.assertEqual(len(batch), 10)  # 2 working seeds x 5

    def test_out_of_seeds_returns_empty(self):
        mix = PlaylistMix(tracks("p", 2), 1, seeds_per_batch=2)
        self.assertTrue(mix.next_batch(fake_mix))
        self.assertEqual(mix.next_batch(fake_mix), [])


class PlaylistMixPlaybackTests(unittest.TestCase):
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

    def test_mix_plays_recommendations_refills_and_stops_when_seeds_run_out(self):
        pl_tracks = tracks("p", 6)  # 2 batches of 3 seeds
        asked = []

        class Api:
            def playlist_tracks(self_inner, playlist_id, progress=None):
                return pl_tracks

            def track_mix(self_inner, tid):
                asked.append(tid)
                return fake_mix(tid)[:2]  # seed + 1 recommendation

        pb = self.win.playback
        self.win.session.api = Api()
        self.win.player_bar.seed_var.set("42")
        pb.play_playlist_mix(Playlist(id="9", title="P"))
        self.pump(lambda: pb.player.current is not None)
        self.assertTrue(pb.flow_mode)
        self.assertNotIn(pb.player.current.id, {t.id for t in pl_tracks})
        # 3 recommendations, 1 playing: 2 left <= FLOW_REFILL_AT, so the 2nd batch was fetched
        self.pump(lambda: len(pb.playq.tracks) == 6)
        self.assertEqual(sorted(asked), sorted(t.id for t in pl_tracks))
        for _ in range(6):  # play through; no seeds left at the end: queue stops, no loop
            if pb.playq is None:
                break
            self.mci.mode = "stopped"
            self.pump(lambda: pb.playq is None or (pb.player.current is not None and self.mci.mode == "playing"))
        self.pump(lambda: pb.playq is None)
        self.assertEqual(len(asked), 6)

    def test_playlist_menu_offers_mix(self):
        import tkinter as tk

        m = tk.Menu(self.root)
        self.win.menus.play_entries(m, Playlist(id="9", title="P"))
        labels = [m.entrycget(i, "label") for i in range(m.index("end") + 1)]
        self.assertIn("Play mix (recommendations)", labels)


if __name__ == "__main__":
    unittest.main()
