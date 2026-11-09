"""Right pane: title, live filter and the list of tracks/albums/artists/playlists."""

import tkinter as tk
from tkinter import ttk

from ..core.tracklist import HEADINGS, HEART


class TrackView:
    def __init__(self, parent, tracklist, on_activate, on_menu):
        """Renders ``tracklist``; ``on_activate()`` on double-click/Enter, ``on_menu(event, items)``
        on right-click (the clicked row is selected first)."""
        self.tracklist, self._on_activate, self._on_menu = tracklist, on_activate, on_menu
        self.frame = ttk.Frame(parent)
        filt = ttk.Frame(self.frame)
        filt.pack(fill="x", pady=(0, 4))
        self.title_var = tk.StringVar(value="")
        ttk.Label(filt, textvariable=self.title_var, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.render())
        ttk.Entry(filt, textvariable=self.filter_var, width=24).pack(side="right")
        ttk.Label(filt, text="Filter:").pack(side="right", padx=4)

        table = ttk.Frame(self.frame)
        table.pack(fill="both", expand=True)
        cols = ("fav", "c1", "c2", "c3", "c4")
        self.list = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for c, w, stretch in (("fav", 28, False), ("c1", 300, True), ("c2", 200, True),
                              ("c3", 220, True), ("c4", 60, False)):
            self.list.column(c, width=w, stretch=stretch, anchor="center" if c in ("fav", "c4") else "w")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.list.bind("<Double-1>", lambda _e: self._on_activate())
        self.list.bind("<Return>", lambda _e: self._on_activate())
        self.list.bind("<Button-3>", self._right_click)
        tracklist.subscribe(self._shown, self.render)

    def _shown(self):
        tl = self.tracklist
        self.title_var.set(f"{tl.title}  ({len(tl.items)})")
        for col, text in zip(("c1", "c2", "c3", "c4"), HEADINGS[tl.kind]):
            self.list.heading(col, text=text)
        self.list.heading("fav", text=HEART if tl.kind == "tracks" else "")
        self.render()

    def render(self):
        self.list.delete(*self.list.get_children())
        for i, row in self.tracklist.rows(self.filter_var.get()):
            self.list.insert("", "end", iid=str(i), values=row)

    def selected(self):
        return [self.tracklist.items[int(i)] for i in self.list.selection()]

    def _right_click(self, event):
        row = self.list.identify_row(event.y)
        if not row:
            return
        if row not in self.list.selection():
            self.list.selection_set(row)
        self._on_menu(event, self.selected())
