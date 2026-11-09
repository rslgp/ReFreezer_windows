"""Library endpoints of refreezer ``lib/api/deezer.dart`` on top of the gpm ARL client.

Covers browsing and managing the account (search, favorites, playlists, albums,
artists). Full-track streaming/downloading is intentionally not ported: Deezer
serves full tracks encrypted, so playback here uses the official 30 s previews.
"""

from dataclasses import dataclass, field
import urllib.request

from gpm.deezer_client import STATUS_PRIVATE, DeezerClient, DeezerError

PAGE_SIZE = 500

# Flow variants: (label, radio.getUserRadio config_id). refreezer reads these from the
# home page's "flow" tiles, which Deezer no longer sends to every account, so they are
# listed here; each id was checked to return its own tracks.
FLOW_TYPES = (
    ("Flow", None),
    ("Motivation", "motivation"),
    ("Party", "party"),
    ("Chill", "chill"),
    ("Melancholy", "melancholy"),
    ("You & me", "you_and_me"),
    ("Focus", "focus"),
)


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    album: str = ""
    album_id: str = ""
    duration: int = 0
    explicit: bool = False
    preview: str = field(default="", compare=False)
    track_token: str = field(default="", compare=False)
    md5_origin: str = field(default="", compare=False)
    media_version: str = field(default="", compare=False)
    album_picture: str = field(default="", compare=False)
    track_number: int = field(default=0, compare=False)
    disk_number: int = field(default=1, compare=False)

    @classmethod
    def from_gw(cls, j):
        title = j.get("SNG_TITLE", "")
        if j.get("VERSION"):
            title = f"{title} {j['VERSION']}"
        artists = ", ".join(a.get("ART_NAME", "") for a in j.get("ARTISTS") or [] if a.get("ART_NAME"))
        preview = next((m.get("HREF", "") for m in j.get("MEDIA") or [] if m.get("TYPE") == "preview"), "")
        return cls(
            id=str(j.get("SNG_ID", "")),
            title=title,
            artist=artists or j.get("ART_NAME", ""),
            album=j.get("ALB_TITLE", ""),
            album_id=str(j.get("ALB_ID") or ""),
            duration=int(j.get("DURATION") or 0),
            explicit=str(j.get("EXPLICIT_LYRICS", "0")) == "1",
            preview=preview,
            track_token=str(j.get("TRACK_TOKEN") or ""),
            md5_origin=str(j.get("MD5_ORIGIN") or ""),
            media_version=str(j.get("MEDIA_VERSION") or ""),
            album_picture=str(j.get("ALB_PICTURE") or ""),
            track_number=int(j.get("TRACK_NUMBER") or 0),
            disk_number=int(j.get("DISK_NUMBER") or 1),
        )

    @property
    def url(self):
        return f"https://www.deezer.com/track/{self.id}"


@dataclass(frozen=True)
class Album:
    id: str
    title: str
    artist: str
    tracks: int = 0

    @classmethod
    def from_gw(cls, j):
        return cls(str(j.get("ALB_ID", "")), j.get("ALB_TITLE", ""), j.get("ART_NAME", ""),
                   int(j.get("NUMBER_TRACK") or j.get("NB_SONG") or 0))

    @property
    def url(self):
        return f"https://www.deezer.com/album/{self.id}"


@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    fans: int = 0

    @classmethod
    def from_gw(cls, j):
        return cls(str(j.get("ART_ID", "")), j.get("ART_NAME", ""), int(j.get("NB_FAN") or 0))

    @property
    def url(self):
        return f"https://www.deezer.com/artist/{self.id}"


@dataclass(frozen=True)
class Playlist:
    id: str
    title: str
    tracks: int = 0
    owner_id: str = ""
    owner: str = ""

    @classmethod
    def from_gw(cls, j):
        return cls(str(j.get("PLAYLIST_ID", "")), j.get("TITLE", ""), int(j.get("NB_SONG") or 0),
                   str(j.get("PARENT_USER_ID") or ""), j.get("PARENT_USERNAME", ""))

    @property
    def url(self):
        return f"https://www.deezer.com/playlist/{self.id}"


def _data(results, *path):
    """results[path...]['data'] as a list; [] when any level is missing."""
    node = results
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    data = node.get("data") if isinstance(node, dict) else None
    return data if isinstance(data, list) else []


class Library(DeezerClient):
    # ---- reading ---------------------------------------------------------

    def _profile_tab(self, tab, nb):
        if self.user_id is None:
            self.login()
        r = self.gw("deezer.pageProfile", {"nb": nb, "tab": tab, "user_id": self.user_id})
        return _data(r, "TAB", tab)

    def playlists(self):
        """User's playlists (own and followed), without the Favorites playlist."""
        items = [Playlist.from_gw(j) for j in self._profile_tab("playlists", 1000)]
        return [p for p in items if p.id != self.loved_tracks_id]

    def albums(self):
        return [Album.from_gw(j) for j in self._profile_tab("albums", 1000)]

    def artists(self):
        return [Artist.from_gw(j) for j in self._profile_tab("artists", 1000)]

    def favorite_ids(self):
        r = self.gw("user.getAllFeedbacks", {"checksums": None})
        return {str(s.get("SNG_ID")) for s in _data(r, "FAVORITES", "SONGS")}

    def playlist_tracks(self, playlist_id, progress=lambda *a: None):
        tracks, start, total = [], 0, None
        while total is None or start < total:
            songs, total = self.playlist_page(playlist_id, start, PAGE_SIZE)
            if not songs:
                break
            tracks.extend(Track.from_gw(s) for s in songs)
            start += len(songs)
            progress(min(start, total), total, "Loading tracks")
        return tracks

    def favorites(self, progress=lambda *a: None):
        if self.loved_tracks_id is None:
            self.login()
        return self.playlist_tracks(self.loved_tracks_id, progress)

    def smart_track_list(self, stl_id):
        """A Deezer smart track list: (title, tracks). Flow is not one, see ``flow``."""
        r = self.gw("deezer.pageSmartTracklist", {"smarttracklist_id": stl_id}) or {}
        data = r.get("DATA") or {}
        return data.get("TITLE") or "Smart track list", [Track.from_gw(j) for j in _data(r, "SONGS")]

    def flow(self, config_id=None):
        """One batch of the user's Flow (endless personal radio); call again for more.

        ``config_id`` picks a variant (see FLOW_TYPES); None is the main Flow.
        """
        if self.user_id is None:
            self.login()
        # gw answers an empty batch now and then for the same request; ask again
        for attempt in range(4):
            r = self.gw("radio.getUserRadio", {"user_id": self.user_id, "config_id": config_id})
            tracks = [Track.from_gw(j) for j in _data(r)]
            if tracks:
                return tracks
            self._sleep(0.5 * (attempt + 1))
        return []

    def album_tracks(self, album_id):
        r = self.gw("deezer.pageAlbum", {"alb_id": album_id, "header": True, "lang": self.lang})
        return [Track.from_gw(j) for j in _data(r, "SONGS")]

    def artist_top(self, artist_id):
        r = self.gw("deezer.pageArtist", {"art_id": artist_id, "lang": self.lang})
        return [Track.from_gw(j) for j in _data(r, "TOP")]

    def search(self, query):
        r = self.gw("deezer.pageSearch", {"nb": 128, "query": query, "start": 0})
        return {
            "tracks": [Track.from_gw(j) for j in _data(r, "TRACK")],
            "albums": [Album.from_gw(j) for j in _data(r, "ALBUM")],
            "artists": [Artist.from_gw(j) for j in _data(r, "ARTIST")],
            "playlists": [Playlist.from_gw(j) for j in _data(r, "PLAYLIST")],
        }

    def preview_url(self, track):
        """Official 30 s preview MP3 (gw MEDIA entry, else public API)."""
        if track.preview:
            return track.preview
        data = self.public(f"track/{track.id}")
        url = data.get("preview") if isinstance(data, dict) else ""
        if not url:
            raise DeezerError("No preview available for this track")
        return url

    def is_own(self, playlist):
        return bool(playlist.owner_id) and playlist.owner_id == self.user_id

    def get_track_data(self, track_id):
        """Fetch fresh track tokens and metadata from gw."""
        try:
            r = self.gw("song.getListData", {"sng_ids": [int(track_id)]})
            items = _data(r)
            if items:
                return items[0]
        except Exception:
            pass
        return {}

    def get_cover_bytes(self, md5_image, size=500):
        """Fetch album/playlist cover JPEG bytes."""
        if not md5_image:
            return None
        url = f"https://e-cdns-images.dzcdn.net/images/cover/{md5_image}/{size}x{size}-000000-80-0-0.jpg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with self._opener.open(req, timeout=15) as res:
                return res.read()
        except Exception:
            return None

    def get_lyrics(self, track_id):
        """Fetch track lyrics (text and synchronized lines if available)."""
        try:
            r = self.gw("deezer.pageTrack", {"sng_id": int(track_id)})
            results = r or {}
            lyrics = results.get("LYRICS")
            if lyrics:
                return {
                    "text": lyrics.get("LYRICS_TEXT") or "",
                    "sync": lyrics.get("SYNC") or [],
                }
        except Exception:
            pass
        return None

    # ---- writing ---------------------------------------------------------

    def add_favorites(self, track_ids):
        for tid in track_ids:
            self.gw("favorite_song.add", {"SNG_ID": tid})

    def remove_favorites(self, track_ids):
        for tid in track_ids:
            self.gw("favorite_song.remove", {"SNG_ID": tid})

    def dislike(self, track_id):
        """Mark a track as disliked (Flow and recommendations stop suggesting it)."""
        self.gw("favorite_dislike.add", {"ID": track_id, "TYPE": "song"})

    def remove_songs(self, playlist_id, track_ids):
        self.gw("playlist.deleteSongs", {"playlist_id": playlist_id, "songs": [[int(t), 0] for t in track_ids]})

    def new_playlist(self, title, track_ids=(), description="", status=STATUS_PRIVATE):
        return self.create_playlist(title, list(track_ids), description=description, status=status)

    def delete_playlist(self, playlist_id):
        self.gw("playlist.delete", {"playlist_id": playlist_id})

    def follow_playlist(self, playlist_id):
        self.gw("playlist.addFavorite", {"parent_playlist_id": int(playlist_id)})

    def unfollow_playlist(self, playlist_id):
        self.gw("playlist.deleteFavorite", {"playlist_id": int(playlist_id)})

    def add_album(self, album_id):
        self.gw("album.addFavorite", {"ALB_ID": album_id})

    def remove_album(self, album_id):
        self.gw("album.deleteFavorite", {"ALB_ID": album_id})

    def follow_artist(self, artist_id):
        self.gw("artist.addFavorite", {"ART_ID": artist_id})

    def unfollow_artist(self, artist_id):
        self.gw("artist.deleteFavorite", {"ART_ID": artist_id})
