"""Tkinter GUI for Windows. Network work runs in a worker thread; the UI thread
polls a queue, so Tk is only touched from the main thread."""

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import core
from .arl import find_arl, save_arl
from .deezer_client import STATUS_PRIVATE, STATUS_PUBLIC, DeezerClient
from .lastfm import LastfmClient, find_api_key, save_api_key


class App:
    def __init__(self, root):
        self.root = root
        root.title("Deezer Genre Playlist Maker (Last.fm)")
        root.minsize(560, 480)
        self.q = queue.Queue()
        self.client = None
        self.tracks = []
        self.genres_by_track = {}
        self.genres = []  # (name, count) in listbox order
        self.last_url = None
        self._auto_title = ""

        frm = ttk.Frame(root, padding=10)
        frm.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)

        head = ttk.Frame(frm)
        head.grid(row=0, column=0, columnspan=4, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="ARL cookie:").grid(row=0, column=0, sticky="w")
        self.arl_var = tk.StringVar(value=find_arl() or "")
        ttk.Entry(head, textvariable=self.arl_var, show="*").grid(row=0, column=1, sticky="ew", padx=4)
        self.remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(head, text="Remember", variable=self.remember_var).grid(row=0, column=2)
        self.load_btn = ttk.Button(head, text="Load favorites", command=self.load)
        self.load_btn.grid(row=0, column=3, rowspan=2, padx=(4, 0), sticky="ns")

        ttk.Label(head, text="Last.fm API key:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.key_var = tk.StringVar(value=find_api_key() or "")
        ttk.Entry(head, textvariable=self.key_var, show="*").grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        self.source_var = tk.StringVar(value="lastfm")
        ttk.Combobox(head, textvariable=self.source_var, values=core.SOURCES, state="readonly",
                     width=8).grid(row=1, column=2, pady=(4, 0))

        self.status_var = tk.StringVar(value="Paste your ARL and click Load favorites.")
        ttk.Label(frm, textvariable=self.status_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=4)

        box = ttk.Frame(frm)
        box.grid(row=3, column=0, columnspan=4, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(box, selectmode="extended", exportselection=False, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        ttk.Label(frm, text="Playlist title:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.title_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.title_var).grid(row=4, column=1, sticky="ew", padx=4, pady=(8, 0))
        self.private_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Private", variable=self.private_var).grid(row=4, column=2, pady=(8, 0))
        self.create_btn = ttk.Button(frm, text="Create playlist", command=self.create, state="disabled")
        self.create_btn.grid(row=4, column=3, padx=(4, 0), pady=(8, 0))

        self.sel_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.sel_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.continue_btn = ttk.Button(frm, text="Continue Last.fm fetch", command=self.resume, state="disabled")
        self.continue_btn.grid(row=5, column=2, sticky="e", pady=(6, 0))
        self.open_btn = ttk.Button(frm, text="Open playlist", command=self.open_url, state="disabled")
        self.open_btn.grid(row=5, column=3, sticky="e", pady=(6, 0))

        # (client, tracks, source, key) once favorites are loaded: lets Continue
        # redo only the genre step, without reloading favorites from Deezer
        self._fetched = None
        self._pending = 0

        root.after(100, self.poll)

    # ---- worker plumbing -------------------------------------------------

    def run_bg(self, fn):
        def wrapper():
            try:
                self.q.put(("done", fn()))
            except Exception as e:  # surfaced to the user in the UI thread
                self.q.put(("error", e))
        self.set_busy(True)
        threading.Thread(target=wrapper, daemon=True).start()

    def progress(self, done, total, label):
        self.q.put(("progress", (done, total, label)))

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "progress":
                    done, total, label = payload
                    self.bar.configure(maximum=max(total, 1), value=done)
                    self.status_var.set(f"{label}: {done}/{total}")
                elif kind == "error":
                    self.set_busy(False)
                    hint = " Click 'Continue Last.fm fetch' to resume." if self._fetched else ""
                    self.status_var.set(f"Error: {payload}.{hint}")
                    messagebox.showerror("Error", f"{payload}\n\nFinished lookups are cached.{hint}")
                elif kind == "done":
                    self.set_busy(False)
                    callback = payload
                    if callable(callback):
                        callback()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_busy(self, busy):
        self.load_btn.configure(state="disabled" if busy else "normal")
        can_create = not busy and bool(self.listbox.curselection())
        self.create_btn.configure(state="normal" if can_create else "disabled")
        # Continue is offered after a failed run or when some lookups are still pending
        can_resume = not busy and self._fetched is not None and (self._pending > 0 or self.tracks is not self._fetched[1])
        self.continue_btn.configure(state="normal" if can_resume else "disabled")
        self.root.configure(cursor="watch" if busy else "")

    # ---- actions ---------------------------------------------------------

    def load(self):
        arl = self.arl_var.get().strip()
        if not arl:
            messagebox.showwarning("ARL missing", "Paste your Deezer 'arl' cookie value first.")
            return
        source = self.source_var.get()
        key = self.key_var.get().strip()
        if source == "lastfm" and not key:
            messagebox.showwarning("Last.fm key missing", "Paste your Last.fm API key, or pick the 'deezer' source.")
            return
        if self.remember_var.get():
            save_arl(arl)
            if key:
                save_api_key(key)

        self._fetched, self._pending = None, 0

        def work():
            client = DeezerClient(arl).login()
            self.q.put(("progress", (0, 1, f"Logged in as {client.user_name}")))
            tracks = core.fetch_favorites(client, progress=self.progress)
            # Plain attribute swap from the worker; Tk itself is only touched in poll()
            self._fetched = (client, tracks, source, key)
            return self._genre_step()

        self.run_bg(work)

    def _genre_step(self):
        """Worker-side: resolve genres for the already-fetched favorites (cache-aware)."""
        client, tracks, source, key = self._fetched
        lf = LastfmClient(key) if source == "lastfm" else None
        genres_by_track, pending = core.build_genre_map(client, tracks, source=source, lastfm_client=lf,
                                                        progress=self.progress)
        return lambda: self.loaded(client, tracks, genres_by_track, pending)

    def resume(self):
        if self._fetched:
            self.run_bg(self._genre_step)

    def loaded(self, client, tracks, genres_by_track, pending=0):
        self.client, self.tracks, self.genres_by_track = client, tracks, genres_by_track
        self._pending = pending
        groups = core.group_by_genre(tracks, genres_by_track)
        self.genres = [(g, len(items)) for g, items in groups.items()]
        self.listbox.delete(0, "end")
        for g, n in self.genres:
            self.listbox.insert("end", f"{g}  ({n})")
        msg = f"{client.user_name}: {len(tracks)} favorites in {len(self.genres)} genres. "
        if pending:
            msg += f"{pending} Last.fm lookups failed: click 'Continue Last.fm fetch' to retry them."
        else:
            msg += "Select one or more genres (Ctrl/Shift+click)."
        self.status_var.set(msg)
        self.on_select()
        self.set_busy(False)

    def selected_genres(self):
        return [self.genres[i][0] for i in self.listbox.curselection()]

    def on_select(self, _event=None):
        genres = self.selected_genres()
        n = len(core.select_tracks(self.tracks, self.genres_by_track, genres)) if genres else 0
        self.sel_var.set(f"{n} tracks selected" if genres else "")
        # Keep the title in sync until the user types their own
        if self.title_var.get() in ("", self._auto_title):
            self._auto_title = core.default_title(genres) if genres else ""
            self.title_var.set(self._auto_title)
        self.create_btn.configure(state="normal" if genres else "disabled")

    def create(self):
        genres = self.selected_genres()
        tracks = core.select_tracks(self.tracks, self.genres_by_track, genres)
        title = self.title_var.get().strip() or core.default_title(genres)
        if not tracks:
            messagebox.showinfo("Nothing to add", "No favorites match the selected genres.")
            return
        if not messagebox.askyesno("Create playlist", f"Create '{title}' with {len(tracks)} tracks?"):
            return
        status = STATUS_PRIVATE if self.private_var.get() else STATUS_PUBLIC
        client = self.client

        def work():
            pid = core.create_genre_playlist(
                client, title, tracks,
                description=f"Generated from Favorites by genre: {', '.join(genres)}",
                status=status, progress=self.progress,
            )
            return lambda: self.created(pid, title, len(tracks))

        self.run_bg(work)

    def created(self, pid, title, n):
        self.last_url = core.playlist_url(pid)
        self.status_var.set(f"Created '{title}' ({n} tracks): {self.last_url}")
        self.open_btn.configure(state="normal")

    def open_url(self):
        if self.last_url:
            webbrowser.open(self.last_url)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
