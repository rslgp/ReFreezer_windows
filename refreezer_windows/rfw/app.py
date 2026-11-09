"""ReFreezer for Windows - Tk GUI.

Left: library tree (Favorites, Playlists, Albums, Artists, Search results).
Right: the selected list. Bottom: 30 s preview player.
Network calls run on a small thread pool; results come back through a queue that
the Tk main thread polls, so widgets are only touched from the main thread.
"""

import os
import queue
import threading
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from gpm.arl import find_arl, save_arl

from .api import Album, Artist, Library, Playlist, Track
from .downloader import QUALITIES, Downloader, default_download_dir
from .downloader_ui import DownloadPlaylistDialog, DownloadProgressDialog
from .player import PlayerError, PreviewPlayer

HEART = "♥"

# Download menu: (label, refreezer quality name)


def fmt_duration(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def open_in_deezer(url):
    """Desktop app via the deezer:// protocol when installed, else the browser."""
    try:
        os.startfile(url.replace("https://", "deezer://"))
    except OSError:
        webbrowser.open(url)


# Column headings per list kind: (col1, col2, col3, col4)
HEADINGS = {
    "tracks": ("Title", "Artist", "Album", "Time"),
    "albums": ("Album", "Artist", "Tracks", ""),
    "artists": ("Artist", "Fans", "", ""),
    "playlists": ("Playlist", "Owner", "Tracks", ""),
}


class MainWindow:
    def __init__(self, root):
        self.root = root
        root.title("ReFreezer for Windows")
        root.geometry("1100x680")
        root.minsize(800, 480)

        self.api = None
        self.downloader = None
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.player = PreviewPlayer()
        self.busy = 0
        self.favorite_ids = set()
        self.playlists, self.albums, self.artists = [], [], []
        self.search_results = {}
        self.download_dir = default_download_dir()
        # Set while a playlist download runs; setting it asks the worker to stop
        self.download_cancel = None
        # Current right-hand list: kind in HEADINGS, items, source describes where tracks came from
        self.kind, self.items, self.source = "tracks", [], ("none",)

        self._build_menu()
        self._build_top()
        self._build_body()
        self._build_player()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self.poll)

    # ---- layout ----------------------------------------------------------

    def _build_menu(self):
        bar = tk.Menu(self.root)
        f = tk.Menu(bar, tearoff=False)
        f.add_command(label="Login", command=self.login)
        f.add_command(label="Refresh library", command=self.refresh_library)
        f.add_separator()
        f.add_command(label="Quit", command=self.quit)
        bar.add_cascade(label="File", menu=f)
        t = tk.Menu(bar, tearoff=False)
        t.add_command(label="New playlist...", command=self.new_playlist)
        t.add_command(label="Genre playlist maker...", command=self.open_genre_maker)
        t.add_separator()
        t.add_command(label="Open downloads folder", command=self.open_downloads_folder)
        bar.add_cascade(label="Tools", menu=t)
        self.root.config(menu=bar)

    def _build_top(self):
        top = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        ttk.Label(top, text="ARL:").pack(side="left")
        self.arl_var = tk.StringVar(value=find_arl() or "")
        e = ttk.Entry(top, textvariable=self.arl_var, show="*", width=28)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda _e: self.login())
        self.remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Remember", variable=self.remember_var).pack(side="left")
        self.login_btn = ttk.Button(top, text="Login", command=self.login)
        self.login_btn.pack(side="left", padx=4)
        self.user_var = tk.StringVar(value="Not logged in")
        ttk.Label(top, textvariable=self.user_var).pack(side="left", padx=8)

        self.search_btn = ttk.Button(top, text="Search", command=self.search, state="disabled")
        self.search_btn.pack(side="right")
        self.search_var = tk.StringVar()
        s = ttk.Entry(top, textvariable=self.search_var, width=32)
        s.pack(side="right", padx=4)
        s.bind("<Return>", lambda _e: self.search())

    def _build_body(self):
        pane = ttk.Panedwindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8)

        left = ttk.Frame(pane)
        self.nav = ttk.Treeview(left, show="tree", selectmode="browse")
        nsb = ttk.Scrollbar(left, orient="vertical", command=self.nav.yview)
        self.nav.configure(yscrollcommand=nsb.set)
        self.nav.pack(side="left", fill="both", expand=True)
        nsb.pack(side="right", fill="y")
        for iid, text in (("fav", f"{HEART} Favorites"), ("pl", "Playlists"), ("alb", "Albums"),
                          ("art", "Artists"), ("search", "Search")):
            self.nav.insert("", "end", iid=iid, text=text, open=iid == "pl")
        self.nav.bind("<<TreeviewSelect>>", self.on_nav)
        self.nav.bind("<Button-3>", self.nav_menu)
        pane.add(left, weight=1)

        right = ttk.Frame(pane)
        filt = ttk.Frame(right)
        filt.pack(fill="x", pady=(0, 4))
        self.title_var = tk.StringVar(value="")
        ttk.Label(filt, textvariable=self.title_var, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.render())
        ttk.Entry(filt, textvariable=self.filter_var, width=24).pack(side="right")
        ttk.Label(filt, text="Filter:").pack(side="right", padx=4)

        table = ttk.Frame(right)
        table.pack(fill="both", expand=True)
        cols = ("fav", "c1", "c2", "c3", "c4")
        self.list = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for c, w, stretch in (("fav", 28, False), ("c1", 300, True), ("c2", 200, True),
                              ("c3", 220, True), ("c4", 60, False)):
            self.list.column(c, width=w, stretch=stretch, anchor="center" if c in ("fav", "c4") else "w")
        lsb = ttk.Scrollbar(table, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=lsb.set)
        self.list.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.list.bind("<Double-1>", self.on_activate)
        self.list.bind("<Return>", self.on_activate)
        self.list.bind("<Button-3>", self.list_menu)
        pane.add(right, weight=4)

    def _build_player(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        self.play_btn = ttk.Button(bar, text="▶ Preview", command=self.play_selected)
        self.play_btn.pack(side="left")
        ttk.Button(bar, text="■ Stop", command=self.stop).pack(side="left", padx=4)
        ttk.Button(bar, text="Open in Deezer", command=self.open_selected).pack(side="left")
        self.now_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.now_var).pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Paste your ARL and click Login.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#666").pack(side="right")
        self.bar = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.bar.pack(side="right", padx=8)

    # ---- background work -------------------------------------------------

    def bg(self, fn, on_ok=None, status=None):
        """Run ``fn`` on the pool; ``on_ok(result)`` later runs on the Tk thread."""
        if status:
            self.status_var.set(status)
        self.busy += 1
        self.bar.start(12)

        def task():
            try:
                self.q.put(("ok", on_ok, fn()))
            except Exception as e:  # shown in the UI thread
                self.q.put(("err", None, e))

        self.pool.submit(task)

    def progress(self, done, total, label):
        self.q.put(("status", None, f"{label}: {done}/{total}"))

    def poll(self):
        try:
            while True:
                kind, cb, payload = self.q.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                    continue
                self.busy -= 1
                if self.busy <= 0:
                    self.busy = 0
                    self.bar.stop()
                if kind == "err":
                    self.status_var.set(f"Error: {payload}")
                    messagebox.showerror("Error", str(payload))
                elif cb:
                    cb(payload)
        except queue.Empty:
            pass
        if self.player.current is not None and self.player.state() != "playing":
            self.player.stop()
            self.now_var.set("")
        self.root.after(150, self.poll)

    def need_login(self):
        if self.api is None:
            messagebox.showinfo("Not logged in", "Log in with your ARL first.")
            return True
        return False

    # ---- login / library -------------------------------------------------

    def login(self):
        arl = self.arl_var.get().strip()
        if not arl:
            messagebox.showwarning("ARL missing", "Paste your Deezer 'arl' cookie value first.")
            return
        if self.remember_var.get():
            save_arl(arl)
        api = Library(arl)

        def work():
            api.login()
            return api

        def done(api):
            self.api = api
            # One Downloader per session: every download path reuses it (and its license token)
            self.downloader = Downloader(api)
            self.user_var.set(f"Logged in as {api.user_name}")
            self.search_btn.configure(state="normal")
            self.refresh_library(open_favorites=True)

        self.bg(work, done, "Logging in...")

    def refresh_library(self, open_favorites=False):
        if self.need_login():
            return
        api = self.api

        def work():
            return api.playlists(), api.albums(), api.artists(), api.favorite_ids()

        def done(res):
            self.playlists, self.albums, self.artists, self.favorite_ids = res
            self._fill_nav("pl", "pl", self.playlists, lambda p: f"{p.title} ({p.tracks})")
            self._fill_nav("alb", "alb", self.albums, lambda a: f"{a.title} - {a.artist}")
            self._fill_nav("art", "art", self.artists, lambda a: a.name)
            self.status_var.set(f"{len(self.favorite_ids)} favorites, {len(self.playlists)} playlists, "
                                f"{len(self.albums)} albums, {len(self.artists)} artists")
            if open_favorites:
                self.nav.selection_set("fav")
            elif self.kind == "tracks":
                self.render()

        self.bg(work, done, "Loading library...")

    def _fill_nav(self, parent, prefix, items, label):
        self.nav.delete(*self.nav.get_children(parent))
        for i, it in enumerate(items):
            self.nav.insert(parent, "end", iid=f"{prefix}:{i}", text=label(it))

    # ---- navigation ------------------------------------------------------

    def on_nav(self, _event=None):
        sel = self.nav.selection()
        if not sel or self.api is None:
            return
        iid = sel[0]
        if iid == "fav":
            self.load_tracks("Favorites", lambda: self.api.favorites(self.progress), ("favorites",))
        elif iid == "pl":
            self.show("playlists", "Playlists", self.playlists)
        elif iid == "alb":
            self.show("albums", "Albums", self.albums)
        elif iid == "art":
            self.show("artists", "Artists", self.artists)
        elif iid.startswith("pl:"):
            self.open_item(self.playlists[int(iid[3:])])
        elif iid.startswith("alb:"):
            self.open_item(self.albums[int(iid[4:])])
        elif iid.startswith("art:"):
            self.open_item(self.artists[int(iid[4:])])
        elif iid.startswith("search:"):
            kind = iid[7:]
            self.show(kind, f"Search: {kind}", self.search_results.get(kind, []), ("search",))

    def open_item(self, item):
        api = self.api
        if isinstance(item, Playlist):
            self.load_tracks(item.title, lambda: api.playlist_tracks(item.id, self.progress), ("playlist", item))
        elif isinstance(item, Album):
            self.load_tracks(f"{item.title} - {item.artist}", lambda: api.album_tracks(item.id), ("album", item))
        elif isinstance(item, Artist):
            self.load_tracks(f"{item.name} - top tracks", lambda: api.artist_top(item.id), ("artist", item))

    def load_tracks(self, title, fetch, source):
        self.bg(fetch, lambda tracks: self.show("tracks", title, tracks, source), f"Loading {title}...")

    def show(self, kind, title, items, source=("none",)):
        self.kind, self.items, self.source = kind, list(items), source
        self.title_var.set(f"{title}  ({len(self.items)})")
        for col, text in zip(("c1", "c2", "c3", "c4"), HEADINGS[kind]):
            self.list.heading(col, text=text)
        self.list.heading("fav", text=HEART if kind == "tracks" else "")
        self.render()

    def _row(self, it):
        if isinstance(it, Track):
            fav = HEART if it.id in self.favorite_ids else ""
            title = f"{it.title}  [E]" if it.explicit else it.title
            return (fav, title, it.artist, it.album, fmt_duration(it.duration))
        if isinstance(it, Album):
            return ("", it.title, it.artist, it.tracks or "", "")
        if isinstance(it, Artist):
            return ("", it.name, f"{it.fans:,}" if it.fans else "", "", "")
        return ("", it.title, it.owner, it.tracks or "", "")

    def render(self):
        self.list.delete(*self.list.get_children())
        needle = self.filter_var.get().strip().casefold()
        for i, it in enumerate(self.items):
            row = self._row(it)
            if needle and not any(needle in str(v).casefold() for v in row[1:4]):
                continue
            self.list.insert("", "end", iid=str(i), values=row)

    def selected(self):
        return [self.items[int(i)] for i in self.list.selection()]

    def selected_tracks(self):
        return [it for it in self.selected() if isinstance(it, Track)]

    def on_activate(self, _event=None):
        sel = self.selected()
        if not sel:
            return
        if isinstance(sel[0], Track):
            self.play(sel[0])
        else:
            self.open_item(sel[0])

    # ---- preview player --------------------------------------------------

    def play_selected(self):
        tracks = self.selected_tracks()
        if tracks:
            self.play(tracks[0])

    def play(self, track):
        api, player = self.api, self.player

        def work():
            return player.fetch(api.preview_url(track), track.id)

        def done(path):
            try:
                player.play(path, track)
                self.now_var.set(f"♪ {track.artist} - {track.title} (30 s preview)")
                self.status_var.set("")
            except PlayerError as e:
                messagebox.showerror("Playback error", str(e))

        self.bg(work, done, f"Loading preview: {track.title}")

    def stop(self):
        self.player.stop()
        self.now_var.set("")

    def open_selected(self):
        sel = self.selected()
        if sel:
            open_in_deezer(sel[0].url)

    # ---- context menus ---------------------------------------------------

    def list_menu(self, event):
        row = self.list.identify_row(event.y)
        if not row:
            return
        if row not in self.list.selection():
            self.list.selection_set(row)
        sel = self.selected()
        m = tk.Menu(self.root, tearoff=False)
        if isinstance(sel[0], Track):
            tracks = self.selected_tracks()
            ids = [t.id for t in tracks]
            m.add_command(label="Play preview", command=lambda: self.play(tracks[0]))
            m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(tracks[0].url))
            m.add_command(label="Copy link", command=lambda: self.copy(tracks[0].url))
            m.add_separator()
            if any(i not in self.favorite_ids for i in ids):
                m.add_command(label=f"Add to favorites ({len(ids)})", command=lambda: self.set_favorite(ids, True))
            if any(i in self.favorite_ids for i in ids):
                m.add_command(label=f"Remove from favorites ({len(ids)})", command=lambda: self.set_favorite(ids, False))
            sub = tk.Menu(m, tearoff=False)
            sub.add_command(label="New playlist...", command=lambda: self.new_playlist(ids))
            own = [p for p in self.playlists if self.api.is_own(p)]
            if own:
                sub.add_separator()
            for p in own:
                sub.add_command(label=p.title, command=lambda p=p: self.add_to_playlist(p, ids))
            m.add_cascade(label="Add to playlist", menu=sub)
            src = self.source
            if src[0] == "playlist":
                m.add_separator()
                self._download_entries(m, src[1])
                if self.api.is_own(src[1]):
                    m.add_command(label="Remove from this playlist", command=lambda: self.remove_from_playlist(src[1], ids))
            m.add_separator()
            track_label = f"Download track ('{tracks[0].title}')" if len(tracks) == 1 else f"Download selected ({len(tracks)} tracks)"
            sub_tr = tk.Menu(m, tearoff=False)
            for label, quality in QUALITIES:
                sub_tr.add_command(label=label, command=lambda q=quality, t=tracks: self.download_selected_tracks(t, q))
            m.add_cascade(label=track_label, menu=sub_tr)
        else:
            item = sel[0]
            m.add_command(label="Open", command=lambda: self.open_item(item))
            m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(item.url))
            m.add_separator()
            self._library_entries(m, item)
        m.tk_popup(event.x_root, event.y_root)

    def nav_menu(self, event):
        iid = self.nav.identify_row(event.y)
        if not iid or self.api is None:
            return
        self.nav.selection_set(iid)
        m = tk.Menu(self.root, tearoff=False)
        if iid in ("pl", "fav"):
            m.add_command(label="New playlist...", command=self.new_playlist)
        if iid == "fav":
            fav_pl = Playlist(
                id=getattr(self.api, "loved_tracks_id", "favorites") or "favorites",
                title="Favorites",
                tracks=len(self.favorite_ids),
            )
            self._download_entries(m, fav_pl)
        prefix, _, idx = iid.partition(":")
        if idx:
            item = {"pl": self.playlists, "alb": self.albums, "art": self.artists}[prefix][int(idx)]
            m.add_command(label="Open in Deezer", command=lambda: open_in_deezer(item.url))
            self._library_entries(m, item)
        m.add_command(label="Refresh library", command=self.refresh_library)
        m.tk_popup(event.x_root, event.y_root)

    def _download_entries(self, m, playlist):
        if self.download_cancel is not None:
            m.add_command(label="Cancel download", command=self.download_cancel.set)
            return
        sub = tk.Menu(m, tearoff=False)
        for label, quality in QUALITIES:
            sub.add_command(label=label, command=lambda q=quality: self.download_playlist(playlist, pref_quality=q))
        sub.add_separator()
        sub.add_command(label="Options...", command=lambda: self.download_playlist_dialog(playlist))
        m.add_cascade(label="Download playlist", menu=sub)

    def _library_entries(self, m, item):
        api = self.api
        if isinstance(item, Playlist):
            self._download_entries(m, item)
            if api.is_own(item):
                m.add_command(label="Delete playlist", command=lambda: self.confirm_write(
                    f"Delete playlist '{item.title}'? This cannot be undone.", lambda: api.delete_playlist(item.id)))
            elif any(p.id == item.id for p in self.playlists):
                m.add_command(label="Remove from library", command=lambda: self.write(lambda: api.unfollow_playlist(item.id)))
            else:
                m.add_command(label="Add to library", command=lambda: self.write(lambda: api.follow_playlist(item.id)))
        elif isinstance(item, Album):
            if any(a.id == item.id for a in self.albums):
                m.add_command(label="Remove from library", command=lambda: self.write(lambda: api.remove_album(item.id)))
            else:
                m.add_command(label="Add to library", command=lambda: self.write(lambda: api.add_album(item.id)))
        elif isinstance(item, Artist):
            if any(a.id == item.id for a in self.artists):
                m.add_command(label="Unfollow", command=lambda: self.write(lambda: api.unfollow_artist(item.id)))
            else:
                m.add_command(label="Follow", command=lambda: self.write(lambda: api.follow_artist(item.id)))
        m.add_separator()

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Link copied")

    # ---- account changes -------------------------------------------------

    def write(self, fn, then=None):
        """Run an account change, then refresh the library lists."""
        def done(_):
            if then:
                then()
            self.refresh_library()
        self.bg(fn, done, "Saving...")

    def confirm_write(self, question, fn):
        if messagebox.askyesno("Confirm", question):
            self.write(fn)

    def set_favorite(self, ids, add):
        api = self.api
        fn = (lambda: api.add_favorites(ids)) if add else (lambda: api.remove_favorites(ids))

        def then():
            if add:
                self.favorite_ids.update(ids)
            else:
                self.favorite_ids.difference_update(ids)
                if self.source[0] == "favorites":
                    self.items = [t for t in self.items if t.id not in ids]
            self.render()

        self.write(fn, then)

    def add_to_playlist(self, playlist, ids):
        self.write(lambda: self.api.add_songs(playlist.id, ids),
                   lambda: self.status_var.set(f"Added {len(ids)} to '{playlist.title}'"))

    def remove_from_playlist(self, playlist, ids):
        if not messagebox.askyesno("Confirm", f"Remove {len(ids)} track(s) from '{playlist.title}'?"):
            return

        def then():
            self.items = [t for t in self.items if t.id not in ids]
            self.render()

        self.write(lambda: self.api.remove_songs(playlist.id, ids), then)

    def new_playlist(self, ids=()):
        if self.need_login():
            return
        title = simpledialog.askstring("New playlist", "Playlist title:", parent=self.root)
        if not title or not title.strip():
            return
        public = messagebox.askyesno("New playlist", "Make it public?\n(No = private)")
        status = 0 if public else 1
        self.write(lambda: self.api.new_playlist(title.strip(), ids, status=status),
                   lambda: self.status_var.set(f"Created '{title.strip()}'"))

    # ---- downloads -------------------------------------------------------

    def open_downloads_folder(self):
        folder = Path(self.download_dir) if self.download_dir else default_download_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open downloads folder: {e}")

    def download_playlist_dialog(self, playlist, preloaded_tracks=None):
        if self.need_login():
            return
        if self.download_cancel is not None:
            messagebox.showinfo("Download in progress", "A download is already running. Please cancel or wait for it to finish.")
            return

        if preloaded_tracks is None and self.source[0] == "playlist" and self.source[1].id == playlist.id:
            preloaded_tracks = self.items

        DownloadPlaylistDialog(
            parent=self.root,
            playlist=playlist,
            downloader=self.downloader,
            default_dir=Path(self.download_dir) if self.download_dir else default_download_dir(),
            preloaded_tracks=preloaded_tracks,
            on_start=self.download_playlist,
        )

    def download_playlist(
        self,
        playlist,
        pref_quality="MP3_320",
        dest_root=None,
        tracks=None,
        save_cover=True,
        save_lyrics=True,
        overwrite=False,
    ):
        """Download a whole playlist into <folder>/<playlist title>, one at a time."""
        if self.need_login() or self.download_cancel is not None:
            return
        if dest_root is None:
            folder = filedialog.askdirectory(parent=self.root, title="Download to folder",
                                             initialdir=str(self.download_dir or default_download_dir()))
            if not folder:
                return
            dest_root = Path(folder)
        else:
            dest_root = Path(dest_root)

        self.download_dir = dest_root
        progress_dlg = DownloadProgressDialog(self.root, playlist, dest_root)
        cancel = self.download_cancel = progress_dlg.cancel_event
        dl = self.downloader

        def progress(idx, total, _track, msg):
            self.q.put(("status", None, msg))
            progress_dlg.update_progress(idx, total, _track, msg)

        def work():
            try:
                return dl.download_playlist(
                    playlist=playlist,
                    tracks=tracks,
                    dest_root=dest_root,
                    pref_quality=pref_quality,
                    save_cover=save_cover,
                    save_lyrics=save_lyrics,
                    overwrite=overwrite,
                    progress_cb=progress,
                    is_cancelled=cancel.is_set,
                )
            finally:
                self.download_cancel = None

        def done(res):
            progress_dlg.on_finished(res)
            errors = res["errors"]
            head = "Cancelled" if res["cancelled"] else "Finished"
            summary = f"{head}: {res['downloaded']}/{res['total']} track(s) in {res['folder']}"
            self.status_var.set(summary)

        self.bg(work, done, f"Downloading '{playlist.title}'...")

    def download_selected_tracks(self, tracks, quality):
        if self.need_login() or not tracks:
            return
        title = tracks[0].title if len(tracks) == 1 else f"Selected Tracks ({len(tracks)})"
        adhoc = Playlist(id="adhoc", title=title, tracks=len(tracks))
        self.download_playlist(adhoc, pref_quality=quality, tracks=tracks)

    # ---- search / tools --------------------------------------------------

    def search(self):
        query = self.search_var.get().strip()
        if not query or self.need_login():
            return

        def done(res):
            self.search_results = res
            self.nav.delete(*self.nav.get_children("search"))
            for kind in ("tracks", "albums", "artists", "playlists"):
                self.nav.insert("search", "end", iid=f"search:{kind}", text=f"{kind.title()} ({len(res[kind])})")
            self.nav.item("search", open=True, text=f"Search: {query}")
            self.nav.selection_set("search:tracks")

        self.bg(lambda: self.api.search(query), done, f"Searching '{query}'...")

    def open_genre_maker(self):
        from gpm.gui import App as GenreApp
        win = tk.Toplevel(self.root)
        app = GenreApp(win)
        if self.arl_var.get().strip():
            app.arl_var.set(self.arl_var.get().strip())

    def quit(self):
        if self.download_cancel is not None:
            self.download_cancel.set()
        self.player.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
