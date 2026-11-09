"""Minimal Deezer client.

Private gw-light API authenticated by the ``arl`` cookie (ported from
refreezer ``lib/api/deezer.dart``) plus the public API, used for album genres.
Stdlib only, so it runs on a bare Windows Python install.
"""

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie, CookieJar

GW_URL = "https://www.deezer.com/ajax/gw-light.php"
PUBLIC_URL = "https://api.deezer.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Playlist status values accepted by playlist.create
STATUS_PUBLIC = 0
STATUS_PRIVATE = 1

# Public API error codes
_QUOTA_EXCEEDED = 4
_NO_DATA = 800


class DeezerError(Exception):
    pass


class AuthError(DeezerError):
    pass


def _cookie(name, value, domain=".deezer.com"):
    return Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain=domain, domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True, secure=True, expires=None, discard=False,
        comment=None, comment_url=None, rest={},
    )


class DeezerClient:
    def __init__(self, arl, lang="en", timeout=30, public_min_interval=0.12, opener=None, sleep=time.sleep):
        arl = (arl or "").strip()
        if not arl:
            raise AuthError("ARL is empty")
        self.arl = arl
        self.lang = lang
        self.timeout = timeout
        self.jar = CookieJar()
        self.jar.set_cookie(_cookie("arl", arl))
        # The cookie processor also keeps the "sid" cookie set by deezer.getUserData
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._sleep = sleep
        # Public API allows ~50 requests / 5 s
        self._public_min_interval = public_min_interval
        self._last_public = 0.0
        self.token = None
        self.user_id = None
        self.user_name = None
        self.loved_tracks_id = None
        self.license_token = None

    # ---- transport -------------------------------------------------------

    def _request(self, url, data=None):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": f"{self.lang},en-US;q=0.8,en;q=0.7",
        }
        if data is not None:
            headers["Content-Type"] = "text/plain;charset=UTF-8"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as res:
                raw = res.read()
        except urllib.error.HTTPError as e:
            raise DeezerError(f"HTTP {e.code} for {url.split('?')[0]}") from e
        except urllib.error.URLError as e:
            raise DeezerError(f"Network error: {e.reason}") from e
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise DeezerError(f"Invalid JSON from {url.split('?')[0]}") from e

    def gw(self, method, params=None, _retried=False, gateway_input=None):
        """Call the private gw-light API and return its ``results``.

        ``gateway_input`` (a JSON string) is what page.get needs, e.g. for the home page.
        """
        if method == "deezer.getUserData":
            token = "null"
        else:
            if self.token is None:
                self.login()
            token = self.token
        query = {
            "api_version": "1.0",
            "api_token": token,
            "input": "3",
            "method": method,
            "cid": str(random.randint(0, 10**9)),
        }
        if gateway_input is not None:
            query["gateway_input"] = gateway_input
        qs = urllib.parse.urlencode(query)
        body = self._request(f"{GW_URL}?{qs}", data=json.dumps(params or {}).encode("utf-8"))
        err = body.get("error")
        if err:
            # Stale CSRF token: re-login once and retry, like refreezer does
            if isinstance(err, dict) and "VALID_TOKEN_REQUIRED" in err and not _retried and method != "deezer.getUserData":
                self.token = None
                return self.gw(method, params, _retried=True, gateway_input=gateway_input)
            raise DeezerError(f"{method} failed: {err}")
        return body.get("results")

    def public(self, path, max_attempts=4):
        for attempt in range(1, max_attempts + 1):
            wait = self._public_min_interval - (time.monotonic() - self._last_public)
            if wait > 0:
                self._sleep(wait)
            self._last_public = time.monotonic()
            data = self._request(PUBLIC_URL + path)
            err = data.get("error") if isinstance(data, dict) else None
            if err and err.get("code") == _QUOTA_EXCEEDED and attempt < max_attempts:
                self._sleep(5 * attempt)
                continue
            return data
        return data

    # ---- auth ------------------------------------------------------------

    def login(self):
        results = self.gw("deezer.getUserData")
        user = (results or {}).get("USER") or {}
        if int(user.get("USER_ID") or 0) == 0:
            raise AuthError("ARL is invalid or expired (Deezer returned USER_ID 0)")
        self.token = results["checkForm"]
        self.user_id = str(user["USER_ID"])
        self.user_name = user.get("BLOG_NAME")
        self.loved_tracks_id = str(user.get("LOVEDTRACKS_ID") or "")
        self.license_token = (user.get("OPTIONS") or {}).get("license_token") or ""
        return self

    # ---- endpoints -------------------------------------------------------

    def playlist_page(self, playlist_id, start, nb):
        """Return (songs, total) for one page of a playlist."""
        r = self.gw("deezer.pagePlaylist", {
            "playlist_id": playlist_id, "lang": self.lang, "nb": nb,
            "start": start, "tags": True, "header": True,
        })
        songs = (r or {}).get("SONGS") or {}
        return songs.get("data") or [], int(songs.get("total") or 0)

    def album_genres(self, album_id):
        """Genre names of an album from the public API; [] when Deezer has none."""
        data = self.public(f"album/{album_id}")
        err = data.get("error")
        if err:
            if err.get("code") == _NO_DATA:
                return []
            raise DeezerError(f"album/{album_id}: {err}")
        return [g["name"] for g in (data.get("genres") or {}).get("data") or [] if g.get("name")]

    def create_playlist(self, title, song_ids, description="", status=STATUS_PRIVATE):
        r = self.gw("playlist.create", {
            "title": title,
            "description": description,
            "songs": [[int(s), i] for i, s in enumerate(song_ids)],
            "status": status,
        })
        return str(r)

    def add_songs(self, playlist_id, song_ids):
        self.gw("playlist.addSongs", {
            "playlist_id": playlist_id,
            "songs": [[int(s), 0] for s in song_ids],
            "offset": -1,
        })
