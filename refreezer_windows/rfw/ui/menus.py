"""Right-click menus of the track list, the library tree and the play queue."""

import tkinter as tk

from ..deezer.api import Album, Artist, Playlist, Track
from ..media.downloader import QUALITIES
from ..win.desktop import open_in_deezer


class ContextMenus:
    def __init__(self, root, session, tracklist, ui, account, browser, list_actions, downloads, nav,
                 playback=None):
        """``nav`` is the library tree view (it selects the right-clicked node); ``playback``
        runs the queue entries."""
        self.root, self.session, self.tracklist, self.ui = root, session, tracklist, ui
        self.account, self.browser, self.actions, self.downloads = account, browser, list_actions, downloads
        self.nav, self.playback = nav, playback

    def track_menu(self, event, sel):
        """Menu for the selected rows of the track list."""
        if not sel:
            return
        m = tk.Menu(self.root, tearoff=False)
        if isinstance(sel[0], Track):
            self._track_entries(m, [it for it in sel if isinstance(it, Track)])
        else:
            item = sel[0]
            m.add_command(label="Open", command=lambda: self.browser.open_item(item))
            m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(item.url))
            m.add_separator()
            self.library_entries(m, item)
        m.tk_popup(event.x_root, event.y_root)

    def queue_menu(self, event, order_pos, track):
        """Menu for one song of the play queue panel."""
        m = tk.Menu(self.root, tearoff=False)
        self.queue_entries(m, order_pos, track)
        m.tk_popup(event.x_root, event.y_root)

    def queue_entries(self, m, order_pos, track):
        pb = self.playback
        playing = pb.playq is not None and order_pos == pb.playq.pos
        if not playing:
            m.add_command(label="Play now", command=lambda: pb.jump_to(order_pos))
            m.add_command(label="Play next", command=lambda: pb.play_next(order_pos))
        m.add_command(label="Remove from queue", command=lambda: pb.remove_from_queue(order_pos))
        m.add_separator()
        self._track_entries(m, [track], in_list=False)

    def _track_entries(self, m, tracks, in_list=True):
        """Entries for ``tracks``; ``in_list`` adds those that act on the shown track list."""
        s, account, actions = self.session, self.account, self.actions
        ids = [t.id for t in tracks]
        m.add_command(label="Play preview", command=lambda: actions.preview(tracks[0]))
        if in_list:
            m.add_command(label="Play from here", command=lambda: actions.play_from(tracks[0], False))
            m.add_command(label="Play shuffled", command=lambda: actions.play_from(tracks[0], True))
        m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(tracks[0].url))
        m.add_command(label="Copy link", command=lambda: self.ui.copy(tracks[0].url))
        m.add_separator()
        if any(i not in s.favorite_ids for i in ids):
            m.add_command(label=f"Add to favorites ({len(ids)})", command=lambda: account.set_favorite(ids, True))
        if any(i in s.favorite_ids for i in ids):
            m.add_command(label=f"Remove from favorites ({len(ids)})", command=lambda: account.set_favorite(ids, False))
        sub = tk.Menu(m, tearoff=False)
        sub.add_command(label="New playlist...", command=lambda: account.new_playlist(ids))
        own = [p for p in s.playlists if s.is_own(p)]
        if own:
            sub.add_separator()
        for p in own:
            sub.add_command(label=p.title, command=lambda p=p: account.add_to_playlist(p, ids))
        m.add_cascade(label="Add to playlist", menu=sub)
        src = self.tracklist.source
        if in_list and src[0] == "playlist":
            m.add_separator()
            self.download_entries(m, src[1])
            if s.is_own(src[1]):
                m.add_command(label="Remove from this playlist", command=lambda: account.remove_from_playlist(src[1], ids))
        m.add_separator()
        label = f"Download track ('{tracks[0].title}')" if len(tracks) == 1 else f"Download selected ({len(tracks)} tracks)"
        sub_tr = tk.Menu(m, tearoff=False)
        for q_label, quality in QUALITIES:
            sub_tr.add_command(label=q_label, command=lambda q=quality: self.downloads.download_selected_tracks(tracks, q))
        m.add_cascade(label=label, menu=sub_tr)

    def nav_menu(self, event, iid):
        """Menu for a library tree node."""
        if self.session.api is None:
            return
        self.nav.select(iid)
        m = tk.Menu(self.root, tearoff=False)
        if iid in ("pl", "fav"):
            m.add_command(label="New playlist...", command=self.account.new_playlist)
        if iid == "fav":
            fav_pl = self.session.favorites_playlist()
            self.play_entries(m, fav_pl)
            self.download_entries(m, fav_pl)
        item = self.browser.item_at(iid)
        if item is not None:
            m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(item.url))
            self.library_entries(m, item)
        m.add_command(label="Refresh library", command=self.account.refresh_library)
        m.tk_popup(event.x_root, event.y_root)

    def play_entries(self, m, playlist):
        m.add_command(label="Play", command=lambda: self.actions.play_playlist(playlist))
        m.add_command(label="Play shuffled", command=lambda: self.actions.play_playlist(playlist, shuffle=True))
        m.add_command(label="Play mix (recommendations)", command=lambda: self.actions.play_playlist_mix(playlist))

    def download_entries(self, m, playlist):
        dl = self.downloads
        if dl.cancel is not None:
            m.add_command(label="Cancel download", command=dl.cancel.set)
            return
        sub = tk.Menu(m, tearoff=False)
        for label, quality in QUALITIES:
            sub.add_command(label=label, command=lambda q=quality: dl.download_playlist(playlist, pref_quality=q))
        sub.add_separator()
        sub.add_command(label="Options...", command=lambda: dl.download_playlist_dialog(playlist))
        m.add_cascade(label="Download playlist", menu=sub)

    def library_entries(self, m, item):
        """Play/download/save/follow entries for a playlist, album or artist."""
        s, account = self.session, self.account
        saved = s.in_library(item)
        if isinstance(item, Playlist):
            self.play_entries(m, item)
            self.download_entries(m, item)
            if s.is_own(item):
                m.add_command(label="Delete playlist", command=lambda: account.delete_playlist(item))
            else:
                m.add_command(label="Remove from library" if saved else "Add to library",
                              command=lambda: account.save_to_library(item, not saved))
        elif isinstance(item, Album):
            m.add_command(label="Remove from library" if saved else "Add to library",
                          command=lambda: account.save_to_library(item, not saved))
        elif isinstance(item, Artist):
            m.add_command(label="Unfollow" if saved else "Follow",
                          command=lambda: account.save_to_library(item, not saved))
        m.add_separator()
