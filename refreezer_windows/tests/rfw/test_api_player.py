import tempfile
import unittest
from pathlib import Path

from rfw.deezer import api
from rfw.deezer.api import Album, Artist, Library, Playlist, Track, _data
from rfw.media.player import PlayerError, PreviewPlayer


class FakeLibrary(Library):
    """Library with gw/public replaced by a script: method -> results."""

    def __init__(self, replies):
        super().__init__("x")
        self.replies, self.calls = replies, []
        self.token, self.user_id, self.loved_tracks_id = "t", "7", "99"

    def gw(self, method, params=None, _retried=False):
        self.calls.append((method, params))
        r = self.replies.get(method)
        return r(params) if callable(r) else r

    def public(self, path, max_attempts=4):
        self.calls.append(("public", path))
        return self.replies.get("public:" + path, {})


SONG = {"SNG_ID": "1", "SNG_TITLE": "Song", "VERSION": "(Live)", "ARTISTS": [{"ART_NAME": "A"}, {"ART_NAME": "B"}],
        "ALB_TITLE": "Alb", "ALB_ID": 5, "DURATION": "125", "EXPLICIT_LYRICS": "1",
        "MEDIA": [{"TYPE": "preview", "HREF": "https://cdn/p.mp3"}]}


class ModelTests(unittest.TestCase):
    def test_track_from_gw(self):
        t = Track.from_gw(SONG)
        self.assertEqual((t.id, t.title, t.artist, t.album_id, t.duration, t.explicit, t.preview),
                         ("1", "Song (Live)", "A, B", "5", 125, True, "https://cdn/p.mp3"))
        self.assertEqual(Track.from_gw({"SNG_ID": 2, "SNG_TITLE": "x", "ART_NAME": "Solo"}).artist, "Solo")

    def test_data_tolerates_missing_levels(self):
        self.assertEqual(_data(None, "TAB", "x"), [])
        self.assertEqual(_data({"TAB": {"x": {"data": [1]}}}, "TAB", "x"), [1])
        self.assertEqual(_data({"TAB": []}, "TAB", "x"), [])

    def test_other_models(self):
        self.assertEqual(Album.from_gw({"ALB_ID": 3, "ALB_TITLE": "T", "ART_NAME": "A", "NUMBER_TRACK": "9"}),
                         Album("3", "T", "A", 9))
        self.assertEqual(Artist.from_gw({"ART_ID": 4, "ART_NAME": "N", "NB_FAN": 10}), Artist("4", "N", 10))
        p = Playlist.from_gw({"PLAYLIST_ID": 8, "TITLE": "P", "NB_SONG": 2, "PARENT_USER_ID": 7})
        self.assertEqual((p.id, p.owner_id, p.url), ("8", "7", "https://www.deezer.com/playlist/8"))


class LibraryTests(unittest.TestCase):
    def test_playlists_skip_favorites_and_ownership(self):
        lib = FakeLibrary({"deezer.pageProfile": {"TAB": {"playlists": {"data": [
            {"PLAYLIST_ID": 99, "TITLE": "Loved", "PARENT_USER_ID": 7},
            {"PLAYLIST_ID": 1, "TITLE": "Mine", "PARENT_USER_ID": 7},
            {"PLAYLIST_ID": 2, "TITLE": "Theirs", "PARENT_USER_ID": 3}]}}}})
        pls = lib.playlists()
        self.assertEqual([p.title for p in pls], ["Mine", "Theirs"])
        self.assertEqual([lib.is_own(p) for p in pls], [True, False])

    def test_playlist_tracks_paginates(self):
        songs = [dict(SONG, SNG_ID=str(i)) for i in range(7)]
        lib = FakeLibrary({})
        lib.playlist_page = lambda pid, start, nb: (songs[start:start + 3], len(songs))
        self.assertEqual([t.id for t in lib.playlist_tracks("1")], [str(i) for i in range(7)])

    def test_search_and_pages(self):
        lib = FakeLibrary({
            "deezer.pageSearch": {"TRACK": {"data": [SONG]}, "ALBUM": {"data": []}, "ARTIST": {"data": []}},
            "deezer.pageAlbum": {"SONGS": {"data": [SONG]}},
            "deezer.pageArtist": {"TOP": {"data": [SONG, SONG]}},
            "user.getAllFeedbacks": {"FAVORITES": {"SONGS": {"data": [{"SNG_ID": 1}, {"SNG_ID": "2"}]}}},
        })
        res = lib.search("q")
        self.assertEqual((len(res["tracks"]), res["playlists"]), (1, []))
        self.assertEqual(len(lib.album_tracks("5")), 1)
        self.assertEqual(len(lib.artist_top("4")), 2)
        self.assertEqual(lib.favorite_ids(), {"1", "2"})

    def test_preview_url_fallback(self):
        lib = FakeLibrary({"public:track/9": {"preview": "https://cdn/9.mp3"}, "public:track/8": {}})
        self.assertEqual(lib.preview_url(Track("1", "t", "a", preview="https://cdn/p.mp3")), "https://cdn/p.mp3")
        self.assertEqual(lib.preview_url(Track("9", "t", "a")), "https://cdn/9.mp3")
        with self.assertRaises(api.DeezerError):
            lib.preview_url(Track("8", "t", "a"))

    def test_write_calls(self):
        lib = FakeLibrary({})
        lib.add_favorites(["1", "2"])
        lib.remove_songs("10", ["3"])
        lib.delete_playlist("10")
        lib.follow_playlist("11")
        self.assertEqual(lib.calls, [
            ("favorite_song.add", {"SNG_ID": "1"}), ("favorite_song.add", {"SNG_ID": "2"}),
            ("playlist.deleteSongs", {"playlist_id": "10", "songs": [[3, 0]]}),
            ("playlist.delete", {"playlist_id": "10"}),
            ("playlist.addFavorite", {"parent_playlist_id": 11}),
        ])


class PlayerTests(unittest.TestCase):
    def test_play_stop_and_state(self):
        cmds = []

        def mci(cmd):
            cmds.append(cmd)
            if cmd.startswith("status"):
                return "playing"
            return ""

        with tempfile.TemporaryDirectory() as d:
            p = PreviewPlayer(cache_dir=d, mci=mci)
            self.assertEqual(p.state(), "")
            p.play(Path(d) / "1.mp3", "track")
            self.assertEqual(p.state(), "playing")
            p.play(Path(d) / "2.mp3", "track2")  # closes the previous one first
            p.stop()
            self.assertIsNone(p.current)
        self.assertEqual([c.split()[0] for c in cmds], ["open", "play", "status", "close", "open", "play", "close"])

    def test_stop_ignores_mci_errors(self):
        def mci(cmd):
            if cmd.startswith("close"):
                raise PlayerError("gone")
            return ""

        p = PreviewPlayer(cache_dir=tempfile.gettempdir(), mci=mci)
        p.play("x.mp3")
        p.stop()
        self.assertEqual(p.state(), "")


if __name__ == "__main__":
    unittest.main()
