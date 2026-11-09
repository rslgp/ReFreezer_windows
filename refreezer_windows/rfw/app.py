"""ReFreezer for Windows - Tk GUI.

Left: library tree (Favorites, Playlists, Albums, Artists, Search results).
Right: the selected list. Bottom: player (30 s previews, or full tracks streamed as a
queue with seeded shuffle).

``MainWindow`` is only the composition root: it builds the Tk-free controllers (rfw.*)
and the views (rfw.ui.*), wires them, and runs the poll loop that brings background
results back to the Tk thread, so widgets and MCI are only touched from that thread.
"""

import tkinter as tk
from functools import partial
from tkinter import messagebox, ttk

from .core.session import Session
from .core.tasks import TaskRunner
from .core.tracklist import TrackList
from .services.account import AccountController
from .services.browse import Browser
from .services.downloads import DownloadsController
from .services.hotkey_settings import HotkeyController
from .services.likes import LikeService
from .services.list_actions import ListActions
from .services.playback import PlaybackController
from .ui.download_dialogs import DownloadPlaylistDialog, DownloadProgressDialog
from .ui.hotkey_dialog import open_hotkey_dialog
from .ui.menus import ContextMenus
from .ui.nav_view import NavView
from .ui.player_bar import PlayerBar
from .ui.tk_ui import TkUi
from .ui.top_bar import TopBar
from .ui.track_view import TrackView
from .win.hotkeys import claim_single_instance

POLL_MS = 150


class MainWindow:
    def __init__(self, root):
        self.root = root
        root.title("ReFreezer for Windows")
        root.geometry("1100x680")
        root.minsize(800, 480)

        # Controllers (Tk-free). Lambdas below are late-bound where a view and its
        # controller need each other; every one is resolved before the first event.
        self.session = Session()
        self.tracklist = TrackList(self.session)
        self.ui = TkUi(root, lambda text: self.player_bar.set_status(text))
        self.tasks = TaskRunner(on_status=self.ui.status, on_error=self.ui.task_error,
                                on_busy=lambda busy: self.player_bar.set_busy(busy))
        self.playback = PlaybackController(self.session, self.tasks, self.ui)
        self.likes = LikeService(self.session, self.tasks, self.ui, self.playback, self.tracklist)
        self.browser = Browser(self.session, self.tasks, self.ui, self.tracklist,
                               on_search=lambda query, res: self.nav_view.show_search(query, res))
        self.list_actions = ListActions(self.tracklist, lambda: self.track_view.selected(),
                                        self.playback, self.browser)
        self.downloads = DownloadsController(
            self.session, self.tasks, self.ui, self.tracklist,
            options_dialog=partial(DownloadPlaylistDialog, parent=root),
            progress_dialog=partial(DownloadProgressDialog, root))
        self.hotkeys = HotkeyController(
            post=self.tasks.post, status=self.ui.status,
            actions={"like": self.likes.like_current, "dislike": self.likes.dislike_current})

        # Views, packed top to bottom
        self.top_bar = TopBar(root, on_login=lambda arl, remember: self.account.login(arl, remember),
                              on_search=self.browser.search)
        pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8)
        self.nav_view = NavView(pane, on_open=self.browser.open_node,
                                on_menu=lambda event, iid: self.menus.nav_menu(event, iid))
        pane.add(self.nav_view.frame, weight=1)
        self.track_view = TrackView(pane, self.tracklist, on_activate=self.list_actions.activate,
                                    on_menu=lambda event, sel: self.menus.track_menu(event, sel))
        pane.add(self.track_view.frame, weight=4)
        self.player_bar = PlayerBar(root, self.playback, self.likes, self.list_actions)
        self.playback.view = self.player_bar

        self.account = AccountController(self.session, self.tasks, self.ui, self.tracklist,
                                         nav=self.nav_view, on_login=self.top_bar.logged_in)
        self.menus = ContextMenus(root, self.session, self.tracklist, self.ui, self.account, self.browser,
                                  self.list_actions, self.downloads, self.nav_view)
        self._build_menu()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self.poll)

    def _build_menu(self):
        bar = tk.Menu(self.root)
        f = tk.Menu(bar, tearoff=False)
        f.add_command(label="Login", command=self.top_bar.login)
        f.add_command(label="Refresh library", command=self.account.refresh_library)
        f.add_separator()
        f.add_command(label="Quit", command=self.quit)
        bar.add_cascade(label="File", menu=f)
        t = tk.Menu(bar, tearoff=False)
        t.add_command(label="New playlist...", command=self.account.new_playlist)
        t.add_command(label="Genre playlist maker...", command=self.open_genre_maker)
        t.add_separator()
        t.add_command(label="Open downloads folder", command=self.downloads.open_downloads_folder)
        bar.add_cascade(label="Tools", menu=t)
        s = tk.Menu(bar, tearoff=False)
        s.add_command(label="Global hotkeys...",
                      command=lambda: open_hotkey_dialog(self.root, self.hotkeys, self.ui.status))
        bar.add_cascade(label="Settings", menu=s)
        self.root.config(menu=bar)

    def poll(self):
        """Tk thread, every POLL_MS: apply background results, auto-advance, mirror the Like state."""
        try:
            self.tasks.drain()
            self.playback.tick()
            self.player_bar.show_liked(self.likes.current_liked())
        finally:  # one failing callback must not stop the loop
            self.root.after(POLL_MS, self.poll)

    def open_genre_maker(self):
        from gpm.gui import App as GenreApp
        app = GenreApp(tk.Toplevel(self.root))
        if self.top_bar.arl:
            app.arl_var.set(self.top_bar.arl)

    def quit(self):
        self.downloads.shutdown()
        self.playback.shutdown()
        self.hotkeys.stop()
        self.tasks.shutdown()
        self.root.destroy()


def main():
    instance = claim_single_instance()
    if instance is None:
        return  # already running: that window was brought to the front
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    win = MainWindow(root)
    errors = win.hotkeys.apply()
    if errors:
        root.after(300, lambda: messagebox.showwarning(
            "Global hotkeys", "These hotkeys are not active:\n" + "\n".join(
                f"{k}: {v}" for k, v in errors.items()) + "\n\nChange them in Settings > Global hotkeys."))
    root.mainloop()


if __name__ == "__main__":
    main()
