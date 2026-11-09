"""Tk-free tests of the GUI components (controllers wired with fakes, no window)."""

import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path

from rfw.services.account import AccountController
from rfw.deezer.api import Album, Artist, Playlist, Track
from rfw.services.hotkey_settings import HotkeyController
from rfw.win.hotkeys import DEFAULT_SETTINGS, HotkeyError
from rfw.services.likes import LikeService
from rfw.services.list_actions import ListActions
from rfw.services.playback import PlaybackController
from rfw.media.player import PreviewPlayer
from rfw.core.session import Session
from rfw.media.stream_cache import StreamCache
from rfw.core.tasks import TaskRunner, gather
from rfw.core.tracklist import TrackList


def tracks(*ids):
    return [Track(id=i, title=f"T{i}", artist="A") for i in ids]


class ManualTasks:
    """TaskRunner stand-in: jobs wait until ``flush`` runs them (fn, then on_ok) in order."""

    def __init__(self):
        self.jobs, self.posted = [], []

    def run(self, fn, on_ok=None, status=None):
        self.jobs.append((fn, on_ok))

    def post(self, fn):
        self.posted.append(fn)

    def progress(self, *a):
        pass

    def flush(self):
        while self.jobs:
            fn, on_ok = self.jobs.pop(0)
            res = fn()
            if on_ok:
                on_ok(res)


class FakeUi:
    def __init__(self):
        self.statuses, self.notes, self.infos = [], [], []
        self.answer = True

    def status(self, text):
        self.statuses.append(text)

    def notify(self, text):
        self.notes.append(text)

    def info(self, title, text):
        self.infos.append(title)

    def warning(self, title, text):
        self.infos.append(title)

    def error(self, title, text):
        self.infos.append(title)

    def confirm(self, title, question):
        return self.answer


class FakeView:
    def __init__(self):
        self.now, self.shuffle, self.seed = "", False, "7"

    def set_now(self, text):
        self.now = text

    def get_shuffle(self):
        return self.shuffle

    def set_shuffle(self, on):
        self.shuffle = on

    def get_seed(self):
        return self.seed

    def set_seed(self, text):
        self.seed = text


class FakeMci:
    def __init__(self):
        self.log, self.mode = [], "playing"

    def __call__(self, cmd):
        self.log.append(cmd)
        return self.mode if cmd.startswith("status") else ""


class FileDownloader:
    def __init__(self, folder):
        self.folder, self.calls = Path(folder), []

    def download_track(self, track, dest_dir, **kwargs):
        self.calls.append(track.id)
        p = self.folder / f"{track.id}.mp3"
        p.write_bytes(b"ID3")
        return p


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.status, self.errors, self.busy = [], [], []
        self.runner = TaskRunner(self.status.append, self.errors.append, self.busy.append, workers=2)

    def tearDown(self):
        self.runner.pool.shutdown(wait=True)

    def drain_until(self, cond):
        for _ in range(500):
            self.runner.drain()
            if cond():
                return
            threading.Event().wait(0.01)
        self.fail("timed out")

    def test_results_errors_status_and_busy(self):
        got = []
        self.runner.run(lambda: 41 + 1, got.append, "Working...")
        self.runner.run(lambda: 1 / 0)
        self.drain_until(lambda: got and self.errors)
        self.assertEqual(got, [42])
        self.assertIsInstance(self.errors[0], ZeroDivisionError)
        self.assertEqual(self.status, ["Working..."])
        self.assertEqual(self.busy, [True, True, False])
        self.assertEqual(self.runner.busy, 0)

    def test_post_from_another_thread_runs_on_drain(self):
        hits = []
        t = threading.Thread(target=lambda: (self.runner.post(lambda: hits.append(threading.current_thread())),
                                             self.runner.progress(2, 5, "Loading")))
        t.start()
        t.join()
        self.assertEqual(hits, [])  # nothing runs until the Tk thread drains
        self.runner.drain()
        self.assertEqual(hits, [threading.current_thread()])
        self.assertEqual(self.status, ["Loading: 2/5"])

    def test_gather_runs_calls_side_by_side_in_order(self):
        barrier = threading.Barrier(3, timeout=2)  # only passes when all three run at once

        def call(v):
            return lambda: (barrier.wait(), v)[1]

        self.assertEqual(gather(call(1), call(2), call(3)), (1, 2, 3))

    def test_gather_reraises_first_failure_in_argument_order(self):
        def boom(msg):
            def fn():
                raise ValueError(msg)
            return fn

        with self.assertRaisesRegex(ValueError, "first"):
            gather(lambda: 1, boom("first"), boom("second"))


class AccountTests(unittest.TestCase):
    def test_refresh_library_loads_the_four_lists_concurrently(self):
        barrier = threading.Barrier(4, timeout=2)
        pl, al, ar = Playlist(id="1", title="P"), Album(id="2", title="A", artist="R"), Artist(id="3", name="R")

        class Api:
            def playlists(self):
                barrier.wait()
                return [pl]

            def albums(self):
                barrier.wait()
                return [al]

            def artists(self):
                barrier.wait()
                return [ar]

            def favorite_ids(self):
                barrier.wait()
                return {"9"}

        class Nav:
            filled, selected = None, None

            def fill_library(self, s):
                Nav.filled = s

            def select(self, iid):
                Nav.selected = iid

        session, tasks, ui = Session(), ManualTasks(), FakeUi()
        session.api = Api()
        acc = AccountController(session, tasks, ui, TrackList(session), Nav(), on_login=None)
        acc.refresh_library(open_favorites=True)
        tasks.flush()
        self.assertEqual((session.playlists, session.albums, session.artists, session.favorite_ids),
                         ([pl], [al], [ar], {"9"}))
        self.assertIs(Nav.filled, session)
        self.assertEqual(Nav.selected, "fav")
        self.assertEqual(ui.statuses[-1], "1 favorites, 1 playlists, 1 albums, 1 artists")

    def test_library_writes_pick_the_method_by_item_type(self):
        calls = []

        class Api:
            def __getattr__(self, name):
                return lambda *a: calls.append((name,) + a)

            def playlists(self):
                return []

            albums = artists = playlists

            def favorite_ids(self):
                return set()

        session, tasks = Session(), ManualTasks()
        session.api = Api()

        class Nav:
            def fill_library(self, s):
                pass

        acc = AccountController(session, tasks, FakeUi(), TrackList(session), Nav(), on_login=None)
        acc.save_to_library(Playlist(id="1", title="P"), True)
        acc.save_to_library(Album(id="2", title="A", artist="R"), False)
        acc.save_to_library(Artist(id="3", name="R"), True)
        tasks.flush()
        self.assertEqual(calls, [("follow_playlist", "1"), ("remove_album", "2"), ("follow_artist", "3")])


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session, self.tasks, self.ui, self.view = Session(), ManualTasks(), FakeUi(), FakeView()
        self.session.api = object()
        self.session.downloader = FileDownloader(self.tmp.name)
        self.mci = FakeMci()
        self.pb = PlaybackController(self.session, self.tasks, self.ui, self.view,
                                     player=PreviewPlayer(mci=self.mci))

    def tearDown(self):
        from concurrent.futures import wait

        wait(list(self.pb.stream.futures.values()), timeout=5)
        self.pb.stream.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def test_late_result_after_a_skip_is_dropped(self):
        self.pb.play_queue(tracks("1", "2", "3"))
        self.pb.queue_next()  # user skips while track 1 is still buffering
        self.tasks.flush()
        self.assertEqual(self.pb.player.current.id, "2")
        opened = [c for c in self.mci.log if c.startswith("open")]
        self.assertEqual(len(opened), 1)
        self.assertIn("2.mp3", opened[0])

    def test_finished_track_advances_and_last_one_stops(self):
        self.pb.play_queue(tracks("1", "2"))
        self.tasks.flush()
        self.mci.mode = "stopped"
        self.pb.tick()
        self.mci.mode = "playing"
        self.tasks.flush()
        self.assertEqual(self.pb.player.current.id, "2")
        self.mci.mode = "stopped"
        self.pb.tick()
        self.assertIsNone(self.pb.playq)
        self.assertEqual(self.view.now, "")

    def test_bad_seed_is_replaced_and_used(self):
        self.view.seed = "not a number"
        self.pb.play_queue(tracks("1", "2"), shuffle=True)
        self.assertEqual(self.pb.playq.seed, int(self.view.seed))
        self.assertTrue(self.view.shuffle)

    def test_not_logged_in_tells_the_user(self):
        self.session.api = None
        self.pb.play_queue(tracks("1"))
        self.assertIsNone(self.pb.playq)
        self.assertEqual(self.ui.infos, ["Not logged in"])

    def test_dislike_skips_only_if_still_playing(self):
        log = []

        class Api:
            def dislike(self, tid):
                log.append(tid)

        self.session.api = Api()
        likes = LikeService(self.session, self.tasks, self.ui, self.pb, TrackList(self.session))
        self.pb.play_queue(tracks("1", "2"))
        self.tasks.flush()
        likes.dislike_current()
        self.tasks.flush()
        self.assertEqual(log, ["1"])
        self.assertEqual(self.pb.player.current.id, "2")
        self.assertFalse(likes.current_liked())
        self.session.favorite_ids.add("2")
        self.assertTrue(likes.current_liked())


class StreamCacheTests(unittest.TestCase):
    def test_one_fetch_per_track_and_cancelled_futures_are_pruned_safely(self):
        with tempfile.TemporaryDirectory() as d:
            dl = FileDownloader(d)
            cache = StreamCache(lambda: dl, folder=d)
            t = tracks("1")[0]
            f1 = cache.fetch(t)
            f1.result(5)
            self.assertIs(cache.fetch(t), f1)  # cached file still there: no second download
            self.assertEqual(dl.calls, ["1"])
            cancelled = Future()
            cancelled.cancel()
            cache.futures["x"] = cancelled
            cache.shutdown()  # must not raise CancelledError
            self.assertEqual(cache.futures, {})
            self.assertFalse(Path(f1.result()).exists())


class TrackListTests(unittest.TestCase):
    def test_rows_filter_marks_favorites_and_drop_redraws(self):
        s = Session()
        s.favorite_ids = {"2"}
        tl = TrackList(s)
        events = []
        tl.subscribe(lambda: events.append("shown"), lambda: events.append("changed"))
        pl = Playlist(id="5", title="P")
        tl.show("tracks", "P", [Track(id="1", title="Rain", artist="A"), Track(id="2", title="Sun", artist="B")],
                ("playlist", pl))
        self.assertEqual([(i, r[0], r[1]) for i, r in tl.rows(" sun ")], [(1, "♥", "Sun")])
        self.assertIs(tl.tracks_of(pl), tl.items)
        self.assertIsNone(tl.tracks_of(Playlist(id="6", title="Q")))
        tl.drop_ids(["1"])
        self.assertEqual([t.id for t in tl.items], ["2"])
        self.assertEqual(events, ["shown", "changed"])

    def test_play_selected_full_streams_from_the_selected_track(self):
        s = Session()
        tl = TrackList(s)
        items = tracks("1", "2", "3")
        tl.show("tracks", "X", items)
        calls = []

        class Pb:
            def play_list_from(self, shown, track, shuffle=None):
                calls.append((len(shown), track.id, shuffle))

        ListActions(tl, lambda: [items[1]], Pb(), browser=None).play_selected_full()
        self.assertEqual(calls, [(3, "2", None)])


class HotkeyControllerTests(unittest.TestCase):
    class FakeHotkeys:
        def __init__(self, fail=None):
            self.bindings, self.fail, self.stops = None, fail or {}, 0

        def start(self, bindings):
            self.bindings = bindings
            return dict(self.fail)

        def running(self):
            return self.bindings is not None

        def stop(self):
            self.stops += 1

    def test_hotkey_thread_only_posts_the_action(self):
        posted, liked, status, saved = [], [], [], []
        fake = self.FakeHotkeys(fail={"dislike": "already used"})
        ctl = HotkeyController(posted.append, {"like": lambda: liked.append(1), "dislike": lambda: None},
                               status.append, hotkeys=fake, settings=dict(DEFAULT_SETTINGS), save=saved.append)
        self.assertEqual(ctl.apply(), {"dislike": "already used"})
        fake.bindings["like"][1]()  # what the hotkey thread calls
        self.assertEqual(liked, [])  # not run there...
        posted[0]()  # ...but on the Tk thread
        self.assertEqual(liked, [1])
        self.assertEqual(status, ["Hotkeys: dislike already used"])
        self.assertIn("NOT active: dislike", ctl.state())
        with self.assertRaises(HotkeyError):
            ctl.save(True, "ctrl+shift+F9", "Ctrl + Shift + F9")
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
