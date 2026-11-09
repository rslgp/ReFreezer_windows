import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from gpm import arl, core
from gpm.deezer_client import AuthError, DeezerClient, DeezerError


def gw_song(i, album):
    return {"SNG_ID": str(i), "SNG_TITLE": f"t{i}", "ART_NAME": "a", "ALB_ID": album, "ALB_TITLE": "x"}


class FakeClient:
    def __init__(self, songs, genres):
        self.songs, self.genres = songs, genres
        self.loved_tracks_id = "99"
        self.album_calls, self.created, self.added = [], None, []

    def login(self):
        return self

    def playlist_page(self, pid, start, nb):
        return self.songs[start:start + nb], len(self.songs)

    def album_genres(self, album_id):
        self.album_calls.append(album_id)
        return self.genres.get(album_id, [])

    def create_playlist(self, title, ids, description="", status=1):
        self.created = (title, list(ids), status)
        return "555"

    def add_songs(self, pid, ids):
        self.added.append((pid, list(ids)))


class CoreTests(unittest.TestCase):
    def setUp(self):
        songs = [gw_song(1, "10"), gw_song(2, "20"), gw_song(3, "10"), gw_song(4, "0"), gw_song(5, "30")]
        self.client = FakeClient(songs, {"10": ["Rock"], "20": ["Pop", "Rock"], "30": []})

    def test_fetch_favorites_paginates(self):
        tracks = core.fetch_favorites(self.client, page_size=2)
        self.assertEqual([t.id for t in tracks], ["1", "2", "3", "4", "5"])

    def test_resolve_uses_cache_and_skips_uploads(self):
        cache = {"20": ["Pop", "Rock"]}
        saves = []
        res = core.resolve_album_genres(self.client, ["10", "20", "10", "0", "30"], cache, save=saves.append)
        self.assertEqual(self.client.album_calls, ["10", "30"])
        self.assertEqual(res["0"], [])
        self.assertEqual(res["30"], [])
        self.assertEqual(len(saves), 1)

    def test_group_and_select(self):
        tracks = core.fetch_favorites(self.client)
        album_genres = core.resolve_album_genres(self.client, [t.album_id for t in tracks], {})
        ag = core.album_genres_by_track(tracks, album_genres)
        groups = core.group_by_genre(tracks, ag)
        self.assertEqual(list(groups), ["Rock", "Unknown", "Pop"])
        self.assertEqual([t.id for t in groups["Unknown"]], ["4", "5"])
        sel = core.select_tracks(tracks, ag, ["rock", "POP"])
        self.assertEqual([t.id for t in sel], ["1", "2", "3"])

    def test_create_chunks(self):
        tracks = [core.Track(str(i), "", "", "1", "") for i in range(5)]
        pid = core.create_genre_playlist(self.client, "T", tracks, chunk_size=2)
        self.assertEqual(pid, "555")
        self.assertEqual(self.client.created, ("T", ["0", "1"], 1))
        self.assertEqual(self.client.added, [("555", ["2", "3"]), ("555", ["4"])])

    def test_create_empty_raises(self):
        with self.assertRaises(ValueError):
            core.create_genre_playlist(self.client, "T", [])

    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "c.json"
            core.save_cache(p, {"1": ["Jazz"]})
            self.assertEqual(core.load_cache(p), {"1": ["Jazz"]})
            self.assertEqual(core.load_cache(Path(d) / "missing.json"), {})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeOpener:
    """Replies by gw method / public path from a script of responses."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def open(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        key = urllib.parse.parse_qs(url.query).get("method", [url.path])[0]
        self.calls.append((key, urllib.parse.parse_qs(url.query).get("api_token", [None])[0]))
        return FakeResponse(json.dumps(self.replies[key].pop(0)).encode())


USER_OK = {"error": [], "results": {"checkForm": "tok", "USER": {"USER_ID": 7, "BLOG_NAME": "me", "LOVEDTRACKS_ID": 99}}}


class ClientTests(unittest.TestCase):
    def test_login_and_token_retry(self):
        op = FakeOpener({
            "deezer.getUserData": [USER_OK, USER_OK],
            "deezer.pagePlaylist": [
                {"error": {"VALID_TOKEN_REQUIRED": "Invalid CSRF token"}, "results": {}},
                {"error": [], "results": {"SONGS": {"data": [gw_song(1, "10")], "total": 1}}},
            ],
        })
        c = DeezerClient("x", opener=op)
        songs, total = c.playlist_page("99", 0, 10)
        self.assertEqual((len(songs), total), (1, 1))
        self.assertEqual(c.loved_tracks_id, "99")
        self.assertEqual([k for k, _ in op.calls],
                         ["deezer.getUserData", "deezer.pagePlaylist", "deezer.getUserData", "deezer.pagePlaylist"])
        self.assertEqual(op.calls[0][1], "null")
        self.assertEqual(op.calls[1][1], "tok")

    def test_invalid_arl(self):
        op = FakeOpener({"deezer.getUserData": [{"error": [], "results": {"checkForm": "t", "USER": {"USER_ID": 0}}}]})
        with self.assertRaises(AuthError):
            DeezerClient("x", opener=op).login()

    def test_empty_arl(self):
        with self.assertRaises(AuthError):
            DeezerClient("  ")

    def test_gw_error_raises(self):
        op = FakeOpener({"deezer.getUserData": [USER_OK], "playlist.create": [{"error": {"X": "bad"}, "results": None}]})
        with self.assertRaises(DeezerError):
            DeezerClient("x", opener=op).create_playlist("t", ["1"])

    def test_album_genres_quota_retry_and_no_data(self):
        sleeps = []
        op = FakeOpener({
            "/album/1": [{"error": {"code": 4, "message": "Quota"}},
                         {"genres": {"data": [{"id": 152, "name": "Rock"}]}}],
            "/album/2": [{"error": {"code": 800, "message": "no data"}}],
        })
        c = DeezerClient("x", opener=op, sleep=sleeps.append, public_min_interval=0)
        self.assertEqual(c.album_genres("1"), ["Rock"])
        self.assertEqual(c.album_genres("2"), [])
        self.assertIn(5, sleeps)


class ArlTests(unittest.TestCase):
    def test_read_arl_file_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "arl.txt"
            p.write_text("# comment\n\narl=\"abc\"\n", encoding="utf-8")
            self.assertEqual(arl.read_arl_file(p), "abc")
            self.assertIsNone(arl.read_arl_file(Path(d) / "none.txt"))


if __name__ == "__main__":
    unittest.main()
