"""Side pane: the stream play queue, the playing track highlighted, played ones greyed."""

import tkinter as tk
from tkinter import ttk


class QueueView:
    def __init__(self, parent, on_jump, on_menu):
        """``on_jump(order_pos)`` on double-click/Enter, ``on_menu(event, order_pos, track)``
        on right-click (the clicked row is selected first)."""
        self._on_jump, self._on_menu = on_jump, on_menu
        self._key = None  # (queue identity, version) last drawn
        self._tracks = {}
        self.frame = ttk.Frame(parent)
        # Title row; the panel dock adds its collapse button here
        self.header = ttk.Frame(self.frame)
        self.header.pack(fill="x", pady=(0, 4))
        self.title_var = tk.StringVar(value="Queue")
        ttk.Label(self.header, textvariable=self.title_var, font=("Segoe UI", 11, "bold")).pack(side="left")
        table = ttk.Frame(self.frame)
        table.pack(fill="both", expand=True)
        self.list = ttk.Treeview(table, columns=("n", "title", "artist"), show="headings", selectmode="browse")
        for col, text, w, stretch in (("n", "#", 36, False), ("title", "Title", 170, True),
                                      ("artist", "Artist", 120, True)):
            self.list.heading(col, text=text)
            self.list.column(col, width=w, stretch=stretch, anchor="e" if col == "n" else "w")
        self.list.tag_configure("current", background="#dbeafe", font=("Segoe UI", 9, "bold"))
        self.list.tag_configure("played", foreground="#999")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.list.bind("<Double-1>", lambda _e: self._jump_selected())
        self.list.bind("<Return>", lambda _e: self._jump_selected())
        self.list.bind("<Button-3>", self._right_click)

    def refresh(self, playq):
        """Redraw only when the queue or its version changed (cheap to call every poll)."""
        key = (id(playq), playq.version) if playq is not None else None
        if key == self._key:
            return
        self._key = key
        self.list.delete(*self.list.get_children())
        self._tracks = {}
        if playq is None:
            self.title_var.set("Queue")
            return
        self.title_var.set(f"Queue  ({playq.position_label()})")
        for pos, track in playq.entries():
            tag = "current" if pos == playq.pos else "played" if pos < playq.pos else ""
            mark = "▶" if pos == playq.pos else str(pos + 1)
            self.list.insert("", "end", iid=str(pos), values=(mark, track.title, track.artist), tags=(tag,))
            self._tracks[pos] = track
        self.list.see(str(playq.pos))

    def _jump_selected(self):
        sel = self.list.selection()
        if sel:
            self._on_jump(int(sel[0]))

    def _right_click(self, event):
        row = self.list.identify_row(event.y)
        if not row:
            return
        self.list.selection_set(row)
        self._on_menu(event, int(row), self._tracks[int(row)])
