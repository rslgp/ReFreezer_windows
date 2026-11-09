import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from gpm import core, lastfm
from gpm.core import Track


def T(i, artist, title, album="1"):
    return Track(str(i), title, artist, album, "")


class FakeLastfm:
    def __init__(self, track_tags, artist_tags=None):
        self.track_tags_map, self.artist_tags_map = track_tags, artist_tags or {}
        self.calls = []

    def track_tags(self, artist, title):
        self.calls.append(("track", artist, title))
        return self.track_tags_map.get((artist, title), [])

    def artist_tags(self, artist):
        self.calls.append(("artist", artist))
        return self.artist_tags_map.get(artist, [])


class TagLogicTests(unittest.TestCase):
    def test_genres_from_tags_filters_noise(self):
        tags = [("seen live", 100), ("Radiohead", 90), ("90s", 80), ("Alternative Rock", 70),
                ("Hip-Hop", 60), ("rock", 5)]
        self.assertEqual(lastfm.genres_from_tags(tags, "Radiohead"), ["Alternative Rock"])
        self.assertEqual(lastfm.genres_from_tags(tags, "Radiohead", top_n=3), ["Alternative Rock", "Hip Hop"])
        self.assertEqual(lastfm.genres_from_tags([("mpb", 100), ("bossa-nova", 50)], top_n=2), ["MPB", "Bossa Nova"])
        self.assertEqual(lastfm.genres_from_tags([("rnb", 100)]), ["R&B"])

    def test_clean_title(self):
        self.assertEqual(lastfm.clean_title("Yesterday (Remastered 2009)"), "Yesterday")
        self.assertEqual(lastfm.clean_title("Song - Live at Wembley"), "Song")
        self.assertEqual(lastfm.clean_title("Help!"), "Help!")

    def test_resolve_and_map_with_fallbacks(self):
        tracks = [
            T(1, "A", "Song (Remastered 2011)"),       # matches only after cleaning
            T(2, "B", "Untagged"),                     # falls back to artist tags
            T(3, "C", "Nothing", album="77"),          # falls back to Deezer album genre
            T(4, "A", "Song (Remastered 2011)"),       # duplicate key, fetched once
            T(5, "D", "Nope"),                         # stays Unknown
        ]
        fake = FakeLastfm({("A", "Song"): [("Jazz", 100)]}, {"B": [("Samba", 100)]})
        cache = {}
        lastfm.resolve_track_tags(fake, tracks, cache)
        track_calls = [c for c in fake.calls if c[0] == "track"]
        self.assertEqual(track_calls.count(("track", "A", "Song (Remastered 2011)")), 1)
        m = lastfm.track_genres_map(tracks, cache, album_genres={"77": ["Rock"]})
        self.assertEqual(m, {"1": ["Jazz"], "2": ["Samba"], "3": ["Rock"], "4": ["Jazz"], "5": []})
        groups = core.group_by_genre(tracks, m)
        self.assertEqual({g: [t.id for t in ts] for g, ts in groups.items()},
                         {"Jazz": ["1", "4"], "Rock": ["3"], "Samba": ["2"], "Unknown": ["5"]})
        # Second run is served from cache
        fake.calls.clear()
        lastfm.resolve_track_tags(fake, tracks, cache)
        self.assertEqual(fake.calls, [])

    def test_network_failures_are_pending_and_resume_fetches_only_them(self):
        class Flaky(FakeLastfm):
            down = True

            def track_tags(self, artist, title):
                if artist == "BOOM" and self.down:
                    raise lastfm.LastfmError("network down")
                return super().track_tags(artist, title)

        fake = Flaky({("A", "S"): [("Pop", 100)], ("BOOM", "X"): [("Rock", 100)]})
        tracks = [T(1, "A", "S"), T(2, "BOOM", "X")]
        cache, saved = {}, []
        pending = lastfm.resolve_track_tags(fake, tracks, cache, save=lambda c: saved.append(dict(c)), workers=4)
        self.assertEqual(pending, 1)
        self.assertEqual(saved[-1], {"t:a\x1fs": [("Pop", 100)]})
        # "Continue": network back, only the failed track is fetched
        fake.down, fake.calls = False, []
        self.assertEqual(lastfm.resolve_track_tags(fake, tracks, cache, workers=4), 0)
        self.assertEqual(fake.calls, [("track", "BOOM", "X")])
        self.assertEqual(lastfm.track_genres_map(tracks, cache), {"1": ["Pop"], "2": ["Rock"]})

    def test_bad_key_aborts_but_keeps_finished_lookups(self):
        class BadKeyLater(FakeLastfm):
            def track_tags(self, artist, title):
                if artist == "BOOM":
                    raise lastfm.LastfmAuthError("Invalid API key")
                return super().track_tags(artist, title)

        saved = []
        tracks = [T(1, "A", "S"), T(2, "BOOM", "X"), T(3, "C", "Z")]
        with self.assertRaises(lastfm.LastfmAuthError):
            lastfm.resolve_track_tags(BadKeyLater({("A", "S"): [("Pop", 100)]}), tracks, {},
                                      save=lambda c: saved.append(dict(c)), workers=1)
        self.assertEqual(saved[-1], {"t:a\x1fs": [("Pop", 100)]})

    def test_parallel_matches_sequential(self):
        tracks = [T(i, f"Art{i % 7}", f"S{i}") for i in range(60)]
        tags = {(t.artist, t.title): [(f"g{int(t.id) % 5}", 100)] for t in tracks}
        seq, par = {}, {}
        lastfm.resolve_track_tags(FakeLastfm(tags), tracks, seq, workers=1)
        lastfm.resolve_track_tags(FakeLastfm(tags), tracks, par, workers=8)
        self.assertEqual(seq, par)
        self.assertEqual(len(par), 60)

    def test_rate_limiter_spaces_calls_across_threads(self):
        clock = [0.0]
        sleeps = []
        rl = lastfm.RateLimiter(5, sleep=sleeps.append, clock=lambda: clock[0])
        for _ in range(4):
            rl.wait()
        self.assertEqual([round(s, 3) for s in sleeps], [0.2, 0.4, 0.6])

    def test_build_genre_map_lastfm_without_fallback(self):
        tracks = [T(1, "A", "S")]
        with tempfile.TemporaryDirectory() as d:
            m, pending = core.build_genre_map(None, tracks, source="lastfm",
                                              lastfm_client=FakeLastfm({("A", "S"): [("Pop", 100)]}),
                                              deezer_fallback=False, lastfm_cache_path=Path(d) / "lf.json")
            self.assertEqual((m, pending), ({"1": ["Pop"]}, 0))
            self.assertTrue((Path(d) / "lf.json").exists())

    def test_build_genre_map_needs_key(self):
        with self.assertRaises(ValueError):
            core.build_genre_map(None, [], source="lastfm", deezer_fallback=False)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class ClientTests(unittest.TestCase):
    def _client(self, replies):
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query))
                return FakeResponse(json.dumps(replies.pop(0)).encode())

        sleeps = []
        return lastfm.LastfmClient("k", opener=Opener(), sleep=sleeps.append, rate=0), calls, sleeps

    def test_track_tags_parse_rate_limit_and_single_tag(self):
        c, calls, sleeps = self._client([
            {"error": 29, "message": "Rate limit"},
            {"toptags": {"tag": [{"name": "rock", "count": 100}, {"name": "pop", "count": "40"}]}},
            {"toptags": {"tag": {"name": "jazz", "count": 100}}},
            {"error": 6, "message": "Track not found"},
        ])
        self.assertEqual(c.track_tags("A", "S"), [("rock", 100), ("pop", 40)])
        self.assertEqual(c.artist_tags("A"), [("jazz", 100)])
        self.assertEqual(c.track_tags("X", "Y"), [])
        self.assertIn(5, sleeps)
        self.assertEqual(calls[0]["method"], ["track.getTopTags"])
        self.assertEqual(calls[0]["autocorrect"], ["1"])
        self.assertEqual(calls[2]["method"], ["artist.getTopTags"])

    def test_invalid_key_raises(self):
        c, _, _ = self._client([{"error": 10, "message": "Invalid API key"}])
        with self.assertRaises(lastfm.LastfmError):
            c.track_tags("A", "S")


if __name__ == "__main__":
    unittest.main()
