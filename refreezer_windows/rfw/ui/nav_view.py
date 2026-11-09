"""Left pane: library tree (Favorites, Playlists, Albums, Artists, Search)."""

from tkinter import ttk

from ..core.tracklist import HEART
from ..services.browse import SEARCH_KINDS


class NavView:
    def __init__(self, parent, on_open, on_menu):
        """``on_open(iid)`` on selection; ``on_menu(event, iid)`` on right-click (row already selected)."""
        self._on_open, self._on_menu = on_open, on_menu
        self.frame = ttk.Frame(parent)
        self.tree = ttk.Treeview(self.frame, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for iid, text in (("fav", f"{HEART} Favorites"), ("pl", "Playlists"), ("alb", "Albums"),
                          ("art", "Artists"), ("search", "Search")):
            self.tree.insert("", "end", iid=iid, text=text, open=iid == "pl")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Button-3>", self._right_click)

    def _selected(self, _event=None):
        sel = self.tree.selection()
        if sel:
            self._on_open(sel[0])

    def _right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self._on_menu(event, iid)

    def select(self, iid):
        self.tree.selection_set(iid)

    def _fill(self, parent, items, label):
        self.tree.delete(*self.tree.get_children(parent))
        for i, it in enumerate(items):
            self.tree.insert(parent, "end", iid=f"{parent}:{i}", text=label(it))

    def fill_library(self, session):
        self._fill("pl", session.playlists, lambda p: f"{p.title} ({p.tracks})")
        self._fill("alb", session.albums, lambda a: f"{a.title} - {a.artist}")
        self._fill("art", session.artists, lambda a: a.name)

    def show_search(self, query, results):
        self.tree.delete(*self.tree.get_children("search"))
        for kind in SEARCH_KINDS:
            self.tree.insert("search", "end", iid=f"search:{kind}", text=f"{kind.title()} ({len(results[kind])})")
        self.tree.item("search", open=True, text=f"Search: {query}")
        self.tree.selection_set("search:tracks")
