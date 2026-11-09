"""Library browsing: tree node / item -> list shown on the right, and search. Tk-free.

Library tree ids: "fav", "pl", "alb", "art", "search", "pl:<i>", "alb:<i>", "art:<i>",
"search:<kind>".
"""

from ..core.session import need_login
from ..deezer.api import Album, Artist, Playlist

SEARCH_KINDS = ("tracks", "albums", "artists", "playlists")


class Browser:
    def __init__(self, session, tasks, ui, tracklist, on_search):
        """``on_search(query, results)`` shows the result counts in the library tree."""
        self.session, self.tasks, self.ui, self.tracklist = session, tasks, ui, tracklist
        self._on_search = on_search

    def open_node(self, iid):
        s = self.session
        if s.api is None:
            return
        if iid == "fav":
            self.load_tracks("Favorites", lambda: s.api.favorites(self.tasks.progress), ("favorites",))
        elif iid == "pl":
            self.tracklist.show("playlists", "Playlists", s.playlists)
        elif iid == "alb":
            self.tracklist.show("albums", "Albums", s.albums)
        elif iid == "art":
            self.tracklist.show("artists", "Artists", s.artists)
        elif iid.startswith("search:"):
            kind = iid[7:]
            self.tracklist.show(kind, f"Search: {kind}", s.search_results.get(kind, []), ("search",))
        else:
            item = self.item_at(iid)
            if item is not None:
                self.open_item(item)

    def item_at(self, iid):
        """The playlist/album/artist behind a "pl:<i>" / "alb:<i>" / "art:<i>" node, else None."""
        prefix, _, idx = iid.partition(":")
        lists = {"pl": self.session.playlists, "alb": self.session.albums, "art": self.session.artists}
        if not idx or prefix not in lists:
            return None
        return lists[prefix][int(idx)]

    def open_item(self, item):
        api = self.session.api
        if isinstance(item, Playlist):
            self.load_tracks(item.title, lambda: api.playlist_tracks(item.id, self.tasks.progress), ("playlist", item))
        elif isinstance(item, Album):
            self.load_tracks(f"{item.title} - {item.artist}", lambda: api.album_tracks(item.id), ("album", item))
        elif isinstance(item, Artist):
            self.load_tracks(f"{item.name} - top tracks", lambda: api.artist_top(item.id), ("artist", item))

    def load_tracks(self, title, fetch, source):
        self.tasks.run(fetch, lambda tracks: self.tracklist.show("tracks", title, tracks, source),
                       f"Loading {title}...")

    def search(self, query):
        query = query.strip()
        if not query or need_login(self.session, self.ui):
            return
        api = self.session.api

        def done(res):
            self.session.search_results = res
            self._on_search(query, res)

        self.tasks.run(lambda: api.search(query), done, f"Searching '{query}'...")
