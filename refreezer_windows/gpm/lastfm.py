"""Per-track genres from Last.fm top tags.

Only the API key is needed: track.getTopTags / artist.getTopTags are public
read calls, so the shared secret (used for signed/auth calls) is not used.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_URL = "https://ws.audioscrobbler.com/2.0/"
ENV_VAR = "LASTFM_API_KEY"
DEFAULT_KEY_FILE = Path(__file__).resolve().parent.parent / "lastfm_api_key.txt"

# Last.fm error codes
_NOT_FOUND = 6
_INVALID_KEY = 10
_RATE_LIMITED = 29
_SUSPENDED_KEY = 26

# Tags that describe taste or context, not genre
_NOT_GENRE = {
    "seen live", "favorites", "favourites", "favorite", "favourite", "my favorite", "love", "loved",
    "awesome", "beautiful", "amazing", "cool", "good", "great", "best", "epic", "sexy", "chill",
    "female vocalists", "male vocalists", "female vocalist", "male vocalist", "female", "male",
    "spotify", "albums i own", "under 2000 listeners", "all", "music",
    "american", "british", "brazilian", "brasil", "brazil", "uk", "usa", "english", "canadian",
    "french", "german", "swedish", "australian", "irish", "japanese", "korean", "italian", "spanish",
    "portuguese", "latin american", "mellow", "sad", "happy", "romantic", "party", "summer", "catchy",
    "covers", "cover", "live", "remix", "instrumental", "oldies", "classic", "legend",
}
_DECADE = re.compile(r"^(\d{2}|\d{4})s?$|^\d{4}$")

# Spellings folded into one genre name
_ALIASES = {
    "hip-hop": "hip hop", "hiphop": "hip hop", "rap": "hip hop", "r&b": "rnb", "r and b": "rnb",
    "rhythm and blues": "rnb", "electronica": "electronic", "electro": "electronic",
    "alt-rock": "alternative rock", "post punk": "post-punk", "synth pop": "synthpop", "synth-pop": "synthpop",
    "drum n bass": "drum and bass", "dnb": "drum and bass", "d&b": "drum and bass",
    "musica popular brasileira": "mpb", "bossa-nova": "bossa nova", "trip hop": "trip-hop",
    "ost": "soundtrack", "score": "soundtrack", "film score": "soundtrack",
    "rock n roll": "rock and roll", "rock & roll": "rock and roll",
}

# Suffixes Deezer adds that break Last.fm matching
_TITLE_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*(remaster|live|version|edit|mix|feat|ft\.|deluxe|mono|stereo|bonus|acoustic|demo|"
    r"from|soundtrack|original)[^\)\]]*[\)\]]"
    r"|\s+-\s+.*(remaster|live|version|edit|mix|mono|stereo).*$",
    re.IGNORECASE,
)


DEFAULT_WORKERS = 6
DEFAULT_RATE = 5.0  # Last.fm: at most ~5 requests / second per key


class LastfmError(Exception):
    pass


class LastfmAuthError(LastfmError):
    """Bad or suspended key: retrying cannot help, so it aborts the whole run."""


class RateLimiter:
    """Thread-safe spacing of calls to ``per_second``, shared by all workers."""

    def __init__(self, per_second, sleep=time.sleep, clock=time.monotonic):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self._sleep, self._clock = sleep, clock
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            self._sleep(slot - now)


def find_api_key(key_file=None):
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return value
    try:
        text = Path(key_file or DEFAULT_KEY_FILE).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    return lines[0] if lines else None


def save_api_key(key, path=DEFAULT_KEY_FILE):
    Path(path).write_text(key.strip() + "\n", encoding="utf-8")


def clean_title(title):
    cleaned = _TITLE_NOISE.sub("", title or "").strip()
    return cleaned or (title or "").strip()


def normalize_tag(name):
    tag = re.sub(r"\s+", " ", (name or "").strip().lower())
    return _ALIASES.get(tag, tag)


def pretty(tag):
    """Display form: 'hip hop' -> 'Hip Hop', keep short acronyms upper ('mpb' -> 'MPB')."""
    if tag in ("mpb", "edm", "idm", "rnb"):
        return {"rnb": "R&B"}.get(tag, tag.upper())
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in tag.split(" "))


def genres_from_tags(tags, artist="", top_n=1, min_count=10):
    """Pick up to ``top_n`` genre names from [(name, count)] (already sorted by Last.fm)."""
    artist_norm = normalize_tag(artist)
    out = []
    for name, count in tags:
        if count < min_count:
            continue
        tag = normalize_tag(name)
        if not tag or tag in _NOT_GENRE or _DECADE.match(tag) or tag == artist_norm or len(tag) > 30:
            continue
        g = pretty(tag)
        if g not in out:
            out.append(g)
        if len(out) >= top_n:
            break
    return out


class LastfmClient:
    def __init__(self, api_key, timeout=20, rate=DEFAULT_RATE, opener=None, sleep=time.sleep):
        api_key = (api_key or "").strip()
        if not api_key:
            raise LastfmAuthError("Last.fm API key is empty")
        self.api_key = api_key
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener()
        self._sleep = sleep
        self._limiter = RateLimiter(rate, sleep=sleep)

    def call(self, method, max_attempts=4, **params):
        qs = urllib.parse.urlencode({"method": method, "api_key": self.api_key, "format": "json", **params})
        req = urllib.request.Request(f"{API_URL}?{qs}", headers={"User-Agent": "genre-playlist-maker/0.2"})
        for attempt in range(1, max_attempts + 1):
            self._limiter.wait()
            try:
                with self._opener.open(req, timeout=self.timeout) as res:
                    data = json.loads(res.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                # Last.fm returns its JSON error body with 4xx codes
                try:
                    data = json.loads(e.read().decode("utf-8"))
                except ValueError:
                    if e.code >= 500 and attempt < max_attempts:
                        self._sleep(2 * attempt)
                        continue
                    raise LastfmError(f"HTTP {e.code} for {method}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_attempts:
                    self._sleep(2 * attempt)
                    continue
                raise LastfmError(f"Network error: {e}") from e
            code = data.get("error") if isinstance(data, dict) else None
            if code in (_INVALID_KEY, _SUSPENDED_KEY):
                raise LastfmAuthError(f"Last.fm rejected the API key: {data.get('message')}")
            if code == _RATE_LIMITED and attempt < max_attempts:
                self._sleep(5 * attempt)
                continue
            return data
        return data

    @staticmethod
    def _tags(data):
        if not isinstance(data, dict) or data.get("error"):
            return []
        tag = (data.get("toptags") or {}).get("tag") or []
        if isinstance(tag, dict):  # a single tag comes back as an object
            tag = [tag]
        return [(t.get("name", ""), int(t.get("count") or 0)) for t in tag]

    def track_tags(self, artist, title):
        return self._tags(self.call("track.getTopTags", artist=artist, track=title, autocorrect=1))

    def artist_tags(self, artist):
        return self._tags(self.call("artist.getTopTags", artist=artist, autocorrect=1))


def _track_key(t):
    return f"{t.artist.casefold()}\x1f{t.title.casefold()}"


def _parallel(items, fn, workers, on_done):
    """Run ``fn`` over ``items`` on a thread pool; ``on_done(item, result)`` runs in the
    calling thread, so the cache is only ever written from one thread.

    Returns the items whose call failed with a retryable LastfmError. LastfmAuthError
    (and anything unexpected) cancels the pending calls and propagates.
    """
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(fn, it): it for it in items}
        try:
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    result = fut.result()
                except LastfmAuthError:
                    raise
                except LastfmError:
                    failed.append(item)
                    continue
                on_done(item, result)
        except BaseException:
            for f in futures:
                f.cancel()
            raise
    return failed


def resolve_track_tags(client, tracks, cache, progress=lambda *a: None, save=lambda c: None,
                       workers=DEFAULT_WORKERS):
    """Fill ``cache`` with raw Last.fm tags: 't:<key>' per track, 'a:<artist>' per artist.

    Only uncached items are fetched, so calling it again after failures resumes where
    it stopped. Artist tags are fetched only for tracks whose own tags give no genre.
    Returns the number of lookups that failed (left uncached for the next call).
    """
    unique = {_track_key(t): t for t in reversed(tracks)}  # first occurrence wins
    todo = [t for k, t in reversed(unique.items()) if "t:" + k not in cache]
    done = 0

    def fetch_track(t):
        tags = client.track_tags(t.artist, t.title)
        cleaned = clean_title(t.title)
        if not tags and cleaned != t.title:
            tags = client.track_tags(t.artist, cleaned)
        return tags

    def stored(key_of, total, label):
        def on_done(item, result):
            nonlocal done
            cache[key_of(item)] = result
            done += 1
            progress(done, total, label)
            if done % 50 == 0:
                save(cache)
        return on_done

    try:
        failed = _parallel(todo, fetch_track, workers,
                           stored(lambda t: "t:" + _track_key(t), len(todo), "Last.fm track tags"))
        # Artists of every track still without a genre (also retries earlier failures)
        artists = list(dict.fromkeys(
            t.artist for t in unique.values()
            if "t:" + _track_key(t) in cache
            and not genres_from_tags(cache["t:" + _track_key(t)], t.artist)
            and "a:" + t.artist.casefold() not in cache
        ))
        done = 0
        failed += _parallel(artists, client.artist_tags, workers,
                            stored(lambda a: "a:" + a.casefold(), len(artists), "Last.fm artist tags"))
    finally:
        # Keep every finished lookup even if the run dies (bad key, Ctrl+C)
        save(cache)
    return len(failed)


def track_genres_map(tracks, cache, top_n=1, min_count=10, album_genres=None):
    """track id -> [genres]: track tags, else artist tags, else Deezer album genres."""
    out = {}
    for t in tracks:
        g = genres_from_tags(cache.get("t:" + _track_key(t), []), t.artist, top_n, min_count)
        if not g:
            g = genres_from_tags(cache.get("a:" + t.artist.casefold(), []), t.artist, top_n, min_count)
        if not g and album_genres:
            g = list(album_genres.get(t.album_id) or [])[:top_n]
        out[t.id] = g
    return out


def default_cache_path():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "genre_playlist_maker" / "lastfm_tags.json"
