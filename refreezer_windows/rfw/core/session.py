"""Logged-in account state shared by the controllers (Tk thread only)."""

from ..deezer.api import Album, Artist, Playlist


class Session:
    def __init__(self):
        self.api = None  # api.Library once logged in
        # One Downloader per session: every download/stream path reuses it (and its license token)
        self.downloader = None
        self.favorite_ids = set()
        self.playlists, self.albums, self.artists = [], [], []
        self.search_results = {}

    def is_own(self, playlist):
        return self.api is not None and self.api.is_own(playlist)

    def in_library(self, item):
        """Whether a playlist/album/artist is already saved/followed in the account."""
        lists = {Playlist: self.playlists, Album: self.albums, Artist: self.artists}
        return any(x.id == item.id for x in lists.get(type(item), ()))

    def favorites_playlist(self):
        """Favorites as a Playlist, for the play/download menus."""
        return Playlist(id=getattr(self.api, "loved_tracks_id", "favorites") or "favorites",
                        title="Favorites", tracks=len(self.favorite_ids))


def need_login(session, ui):
    """True (after telling the user) when there is no logged-in session yet."""
    if session.api is None:
        ui.info("Not logged in", "Log in with your ARL first.")
        return True
    return False
