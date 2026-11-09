"""Login, library loading and account writes (favorites, playlists, follows). Tk-free.

``nav`` is the library tree: ``fill_library(session)`` and ``select(iid)``.
"""

from gpm.arl import save_arl

from ..core.session import need_login
from ..core.tasks import gather
from ..deezer.api import Album, Artist, Library, Playlist
from ..media.downloader import Downloader

# Library save/remove per item type: (add method, remove method) on api.Library
LIBRARY_WRITES = {
    Playlist: ("follow_playlist", "unfollow_playlist"),
    Album: ("add_album", "remove_album"),
    Artist: ("follow_artist", "unfollow_artist"),
}


class AccountController:
    def __init__(self, session, tasks, ui, tracklist, nav, on_login, library_factory=Library,
                 remember_arl=save_arl):
        self.session, self.tasks, self.ui = session, tasks, ui
        self.tracklist, self.nav, self._on_login = tracklist, nav, on_login
        self._library_factory, self._remember_arl = library_factory, remember_arl

    # ---- login / library ----------------------------------------------------

    def login(self, arl, remember=False):
        arl = arl.strip()
        if not arl:
            self.ui.warning("ARL missing", "Paste your Deezer 'arl' cookie value first.")
            return
        if remember:
            self._remember_arl(arl)
        api = self._library_factory(arl)

        def work():
            api.login()
            return api

        def done(api):
            self.session.api = api
            self.session.downloader = Downloader(api)
            self._on_login(api.user_name)
            self.refresh_library(open_favorites=True)

        self.tasks.run(work, done, "Logging in...")

    def refresh_library(self, open_favorites=False):
        if need_login(self.session, self.ui):
            return
        api = self.session.api

        def work():  # four independent reads: side by side, not one after another
            return gather(api.playlists, api.albums, api.artists, api.favorite_ids)

        def done(res):
            s = self.session
            s.playlists, s.albums, s.artists, s.favorite_ids = res
            self.nav.fill_library(s)
            self.ui.status(f"{len(s.favorite_ids)} favorites, {len(s.playlists)} playlists, "
                           f"{len(s.albums)} albums, {len(s.artists)} artists")
            if open_favorites:
                self.nav.select("fav")
            elif self.tracklist.kind == "tracks":
                self.tracklist.changed()

        self.tasks.run(work, done, "Loading library...")

    # ---- account changes ------------------------------------------------------

    def write(self, fn, then=None):
        """Run an account change, then refresh the library lists."""
        def done(_):
            if then:
                then()
            self.refresh_library()
        self.tasks.run(fn, done, "Saving...")

    def set_favorite(self, ids, add):
        api = self.session.api
        fn = (lambda: api.add_favorites(ids)) if add else (lambda: api.remove_favorites(ids))

        def then():
            if add:
                self.session.favorite_ids.update(ids)
                self.tracklist.changed()
            else:
                self.session.favorite_ids.difference_update(ids)
                if self.tracklist.source[0] == "favorites":
                    self.tracklist.drop_ids(ids)
                else:
                    self.tracklist.changed()

        self.write(fn, then)

    def save_to_library(self, item, add):
        """Follow/save (or unfollow/remove) a playlist, album or artist."""
        api = self.session.api
        method = getattr(api, LIBRARY_WRITES[type(item)][0 if add else 1])
        self.write(lambda: method(item.id))

    def delete_playlist(self, playlist):
        api = self.session.api
        if self.ui.confirm("Confirm", f"Delete playlist '{playlist.title}'? This cannot be undone."):
            self.write(lambda: api.delete_playlist(playlist.id))

    def add_to_playlist(self, playlist, ids):
        api = self.session.api
        self.write(lambda: api.add_songs(playlist.id, ids),
                   lambda: self.ui.status(f"Added {len(ids)} to '{playlist.title}'"))

    def remove_from_playlist(self, playlist, ids):
        if not self.ui.confirm("Confirm", f"Remove {len(ids)} track(s) from '{playlist.title}'?"):
            return
        api = self.session.api
        self.write(lambda: api.remove_songs(playlist.id, ids), lambda: self.tracklist.drop_ids(ids))

    def new_playlist(self, ids=()):
        if need_login(self.session, self.ui):
            return
        title = self.ui.ask_string("New playlist", "Playlist title:")
        if not title or not title.strip():
            return
        title = title.strip()
        status = 0 if self.ui.confirm("New playlist", "Make it public?\n(No = private)") else 1
        api = self.session.api
        self.write(lambda: api.new_playlist(title, ids, status=status),
                   lambda: self.ui.status(f"Created '{title}'"))
