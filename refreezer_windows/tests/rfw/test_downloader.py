"""Unit tests for downloader and downloader UI in rfw."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rfw.deezer.api import Library, Playlist, Track
from rfw.media.downloader import (
    Downloader,
    DownloadError,
    default_download_dir,
    sanitize_filename,
)


class FakeLibrary:
    def __init__(self):
        self.arl = "dummy_arl"
        self.license_token = "dummy_license"
        self.user_name = "Test User"
        self.user_id = "12345"
        self.loved_tracks_id = "99999"
        self.calls = []

    def is_own(self, playlist):
        return playlist.owner_id == self.user_id

    def gw(self, method, params=None):
        self.calls.append((method, params))
        if method == "deezer.getUserData":
            return {"USER": {"OPTIONS": {"license_token": "dummy_license"}}}
        return {}

    def get_track_data(self, track_id):
        return {"TRACK_TOKEN": f"fresh_token_{track_id}"}

    def get_cover_bytes(self, md5_image, size=500):
        return b"\xff\xd8\xff\xe0fake_jpeg_bytes"

    def get_lyrics(self, track_id):
        return {
            "text": "La la la",
            "sync": [{"lrcTimestamp": "[00:10.00]", "line": "La la la"}],
        }

    def playlist_tracks(self, playlist_id):
        return [
            Track(
                id="101",
                title="Song One",
                artist="Artist A",
                album="Album 1",
                album_picture="art1",
                track_token="token_101",
            ),
            Track(
                id="102",
                title="Song Two",
                artist="Artist B",
                album="Album 1",
                album_picture="art1",
                track_token="token_102",
            ),
        ]


class DownloaderTests(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("AC/DC: Back in Black?"), "ACDC Back in Black")
        self.assertEqual(sanitize_filename('Foo "Bar" <Baz> | Test *'), "Foo Bar Baz  Test")
        self.assertEqual(sanitize_filename("...Leading and Trailing. "), "Leading and Trailing")
        self.assertEqual(sanitize_filename(""), "untitled")
        self.assertEqual(sanitize_filename("$$$"), "untitled")

    def test_default_download_dir(self):
        d = default_download_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.is_absolute())

    def test_get_stream_info_fallback(self):
        lib = FakeLibrary()
        dl = Downloader(lib)

        # Mock _call_get_url to return None for FLAC and succeed for MP3_320
        def fake_call(token, fmt):
            if fmt == "FLAC":
                return None
            if fmt == "MP3_320":
                return ("https://cdn.deezer.com/stream/320", "MP3_320", True)
            return None

        dl._call_get_url = MagicMock(side_effect=fake_call)

        track = Track(id="1", title="Test", artist="Art", track_token="tok1")
        url, fmt, is_enc = dl.get_stream_info(track, pref_quality="FLAC")

        self.assertEqual(url, "https://cdn.deezer.com/stream/320")
        self.assertEqual(fmt, "MP3_320")
        self.assertTrue(is_enc)
        # Should have called FLAC first, then MP3_320
        self.assertEqual(dl._call_get_url.call_count, 2)

    def test_get_stream_info_failure(self):
        lib = FakeLibrary()
        dl = Downloader(lib)
        dl._call_get_url = MagicMock(return_value=None)

        track = Track(id="1", title="Test", artist="Art", track_token="tok1")
        with self.assertRaises(DownloadError):
            dl.get_stream_info(track, pref_quality="MP3_128")

    def test_download_track_cancellation(self):
        lib = FakeLibrary()
        dl = Downloader(lib)
        track = Track(id="1", title="Test", artist="Art", track_token="tok1")

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(InterruptedError):
                dl.download_track(
                    track=track,
                    dest_dir=tmpdir,
                    is_cancelled=lambda: True,
                )

    @patch("urllib.request.urlopen")
    @patch("rfw.media.downloader.decrypt_file")
    @patch("rfw.media.downloader.apply_mp3_tags")
    def test_download_track_success(self, mock_tags, mock_decrypt, mock_urlopen):
        lib = FakeLibrary()
        dl = Downloader(lib)
        dl.get_stream_info = MagicMock(return_value=("https://cdn/stream.mp3", "MP3_320", True))

        # Mock urllib urlopen response stream
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [b"chunk1", b"chunk2", b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        def fake_decrypt(track_id, in_p, out_p):
            Path(out_p).write_bytes(b"decrypted_audio")

        mock_decrypt.side_effect = fake_decrypt

        with tempfile.TemporaryDirectory() as tmpdir:
            track = Track(id="1", title="My Song", artist="Artist", album_picture="cov1")
            out = dl.download_track(track, tmpdir, track_num=1, total_tracks=1)

            self.assertTrue(out.exists())
            self.assertEqual(out.name, "01 - Artist - My Song.mp3")
            mock_tags.assert_called_once()

    @patch("urllib.request.urlopen")
    @patch("rfw.media.downloader.decrypt_file")
    @patch("rfw.media.downloader.apply_mp3_tags")
    def test_download_track_region_blocked_uses_fallback(self, mock_tags, mock_decrypt, mock_urlopen):
        lib = FakeLibrary()
        lib.get_track_data = lambda tid: {"FALLBACK": {"SNG_ID": "777", "SNG_TITLE": "Alt", "TRACK_TOKEN": "alt_tok"}}
        dl = Downloader(lib)

        def fake_stream(track, pref_quality="MP3_320"):
            if track.id == "777":
                return ("https://cdn/alt.mp3", "MP3_128", True)
            raise DownloadError("blocked")

        dl.get_stream_info = MagicMock(side_effect=fake_stream)
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [b"chunk", b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        mock_decrypt.side_effect = lambda tid, i, o: Path(o).write_bytes(b"audio")

        with tempfile.TemporaryDirectory() as tmpdir:
            track = Track(id="1", title="Blocked", artist="Artist")
            out = dl.download_track(track, tmpdir, track_num=1, save_lyrics=False)
            # Key comes from the streamed (fallback) id; name keeps the original title
            self.assertEqual(mock_decrypt.call_args[0][0], "777")
            self.assertEqual(out.name, "01 - Artist - Blocked.mp3")

    @patch("urllib.request.urlopen")
    @patch("rfw.media.downloader.decrypt_file")
    @patch("rfw.media.downloader.apply_mp3_tags")
    def test_download_track_fetches_cover_and_lyrics_during_audio(self, mock_tags, mock_decrypt, mock_urlopen):
        import threading

        lib = FakeLibrary()
        cover_started, lyrics_started = threading.Event(), threading.Event()
        get_cover, get_lyrics = lib.get_cover_bytes, lib.get_lyrics
        lib.get_cover_bytes = lambda md5, size=500: (cover_started.set(), get_cover(md5, size))[1]
        lib.get_lyrics = lambda tid: (lyrics_started.set(), get_lyrics(tid))[1]
        dl = Downloader(lib)
        dl.get_stream_info = MagicMock(return_value=("https://cdn/stream.mp3", "MP3_320", True))
        seen = []

        def read(_n):
            # The audio is still downloading: both lookups must already be running
            if not seen:
                seen.append(cover_started.wait(2) and lyrics_started.wait(2))
                return b"chunk"
            return b""

        mock_resp = MagicMock()
        mock_resp.read.side_effect = read
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        mock_decrypt.side_effect = lambda tid, i, o: Path(o).write_bytes(b"audio")

        with tempfile.TemporaryDirectory() as tmpdir:
            out = dl.download_track(Track(id="1", title="S", artist="A", album_picture="cov"), tmpdir, track_num=1)
            self.assertTrue(out.exists())
            self.assertTrue((Path(tmpdir) / "01 - A - S.lrc").exists())
        self.assertEqual(seen, [True])
        kwargs = mock_tags.call_args.kwargs
        self.assertEqual((kwargs["cover_bytes"], kwargs["lyrics"]), (b"\xff\xd8\xff\xe0fake_jpeg_bytes", "La la la"))

    def test_download_track_blocked_without_fallback_raises(self):
        lib = FakeLibrary()
        dl = Downloader(lib)
        dl.get_stream_info = MagicMock(side_effect=DownloadError("blocked"))
        with tempfile.TemporaryDirectory() as tmpdir, self.assertRaises(DownloadError):
            dl.download_track(Track(id="1", title="X", artist="Y"), tmpdir)

    def test_download_playlist_runs_tracks_in_parallel(self):
        import threading
        import time

        lib = FakeLibrary()
        dl = Downloader(lib)
        tracks = [Track(id=str(i), title=f"S{i}", artist="A") for i in range(1, 9)]
        active, peak, lock = [0], [0], threading.Lock()

        def fake_download_track(track, dest_dir, track_num, **kwargs):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            if track.id in ("6", "2"):
                raise DownloadError(f"boom {track.id}")
            return Path(dest_dir) / f"{track_num:02d}.mp3"

        dl.download_track = MagicMock(side_effect=fake_download_track)
        progress = []
        with tempfile.TemporaryDirectory() as tmpdir:
            res = dl.download_playlist(Playlist(id="1", title="P"), tracks=tracks, dest_root=tmpdir,
                                       save_cover=False, workers=4,
                                       progress_cb=lambda n, t, tr, m: progress.append(n))
        self.assertEqual(peak[0], 4)
        self.assertEqual(res["downloaded"], 6)
        # Errors come back in playlist order, not completion order
        self.assertEqual([t.id for t, _ in res["errors"]], ["2", "6"])
        self.assertEqual(sorted(progress), list(range(1, 9)))

    def test_download_playlist_cancel_skips_pending_tracks(self):
        lib = FakeLibrary()
        dl = Downloader(lib)
        tracks = [Track(id=str(i), title=f"S{i}", artist="A") for i in range(1, 21)]
        cancelled = [False]

        def fake_download_track(track, dest_dir, track_num, **kwargs):
            cancelled[0] = True  # first finished track presses Cancel
            return Path(dest_dir) / f"{track_num:02d}.mp3"

        dl.download_track = MagicMock(side_effect=fake_download_track)
        with tempfile.TemporaryDirectory() as tmpdir:
            res = dl.download_playlist(Playlist(id="1", title="P"), tracks=tracks, dest_root=tmpdir,
                                       save_cover=False, workers=2, is_cancelled=lambda: cancelled[0])
        self.assertTrue(res["cancelled"])
        self.assertLessEqual(dl.download_track.call_count, 2)

    def test_download_playlist_success_and_cancellation(self):
        lib = FakeLibrary()
        dl = Downloader(lib)

        # Mock download_track to write a dummy file
        def fake_download_track(track, dest_dir, track_num, **kwargs):
            p = Path(dest_dir) / f"{track_num:02d} - {track.artist} - {track.title}.mp3"
            p.write_bytes(b"data")
            return p

        dl.download_track = MagicMock(side_effect=fake_download_track)

        pl = Playlist(id="500", title="Party Hits", tracks=2)

        with tempfile.TemporaryDirectory() as tmpdir:
            progress_calls = []

            def progress_cb(idx, total, track, msg):
                progress_calls.append((idx, total, track.id, msg))

            res = dl.download_playlist(
                playlist=pl,
                dest_root=tmpdir,
                progress_cb=progress_cb,
            )

            self.assertEqual(res["total"], 2)
            self.assertEqual(res["downloaded"], 2)
            self.assertEqual(res["errors"], [])
            self.assertFalse(res["cancelled"])
            self.assertTrue((Path(tmpdir) / "Party Hits").exists())
            self.assertTrue((Path(tmpdir) / "Party Hits" / "cover.jpg").exists())
            self.assertEqual(len(progress_calls), 2)


class DownloaderUITests(unittest.TestCase):
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
            try:
                cls.root.destroy()
            except Exception:
                pass

    def setUp(self):
        if not self.root:
            self.skipTest("Tkinter not available in this environment")

    def test_menu_download_entries(self):
        import tkinter as tk
        from rfw.app import MainWindow

        # Create MainWindow instance
        win = MainWindow(self.root)
        win.session.api = FakeLibrary()

        pl = Playlist(id="123", title="Cool Tunes", tracks=5)
        menu = tk.Menu(self.root)
        win.menus.download_entries(menu, pl)

        # Check that "Download playlist" cascade was added
        found = False
        for i in range(menu.index("end") + 1):
            if menu.type(i) == "cascade" and menu.entrycget(i, "label") == "Download playlist":
                found = True
                break
        self.assertTrue(found, "Download playlist cascade menu entry not found")

    def test_library_entries_includes_download(self):
        import tkinter as tk
        from rfw.app import MainWindow

        win = MainWindow(self.root)
        win.session.api = FakeLibrary()

        pl = Playlist(id="123", title="Cool Tunes", tracks=5)
        menu = tk.Menu(self.root)
        win.menus.library_entries(menu, pl)

        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]
        self.assertIn("Download playlist", labels)

    def test_download_paths_reuse_session_downloader(self):
        from rfw.services import account
        from rfw.ui import download_dialogs as downloader_ui
        from rfw.app import MainWindow
        from rfw.media.downloader import QUALITIES
        from rfw.ui import menus

        # One quality list for every menu/dialog
        self.assertIs(menus.QUALITIES, QUALITIES)
        self.assertIs(downloader_ui.QUALITY_CHOICES, QUALITIES)

        win = MainWindow(self.root)
        win.session.api = FakeLibrary()
        win.session.downloader = Downloader(win.session.api)
        pl = Playlist(id="123", title="Cool Tunes", tracks=5)
        dls = win.downloads
        with patch.object(account, "Downloader", side_effect=AssertionError("new Downloader built")), \
                patch.object(dls, "options_dialog") as dlg, \
                patch.object(dls, "progress_dialog"), patch.object(win.tasks, "run"):
            dls.download_playlist_dialog(pl)
            self.assertIs(dlg.call_args.kwargs["downloader"], win.session.downloader)
            with tempfile.TemporaryDirectory() as tmpdir:
                dls.download_playlist(pl, dest_root=tmpdir)
            dls.cancel = None

    def test_progress_dialog_lifecycle(self):
        from rfw.ui.download_dialogs import DownloadProgressDialog

        pl = Playlist(id="123", title="Cool Tunes", tracks=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            dlg = DownloadProgressDialog(self.root, pl, Path(tmpdir))
            self.assertFalse(dlg.is_cancelled())
            dlg.update_progress(1, 5, None, "Downloading 1/5")
            self.root.update()

            dlg.cancel()
            self.assertTrue(dlg.is_cancelled())

            dlg.on_finished({"cancelled": True, "downloaded": 1, "total": 5, "errors": [], "folder": Path(tmpdir)})
            self.root.update()
            dlg.destroy()


if __name__ == "__main__":
    unittest.main()
