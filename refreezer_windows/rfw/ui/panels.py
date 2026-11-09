"""Collapsible panes: each panel gets a small button in its header; collapsing swaps the
panel for a thin strip (a button plus its name written top to bottom) in the same slot,
and clicking the strip brings the panel back where it was."""

from tkinter import ttk


class PanelDock:
    def __init__(self, pane, on_layout=None):
        """``pane`` is a horizontal ttk.Panedwindow; ``on_layout()`` runs after every toggle
        (the composition root re-places the dividers when everything is shown again)."""
        self.pane, self._on_layout = pane, on_layout
        self._panels = []  # dicts: name, frame, strip, weight, collapsed

    def add(self, name, frame, header, weight, edge="left"):
        """Add ``frame`` as the next pane. Its collapse button goes into ``header``; ``edge``
        is the window side it folds toward (decides the arrows)."""
        fold, unfold = ("‹", "›") if edge == "left" else ("›", "‹")
        panel = {"name": name, "frame": frame, "weight": weight, "collapsed": False}
        btn = ttk.Button(header, text=fold, width=2, command=lambda: self.collapse(name))
        first = header.pack_slaves()[:1]
        if edge == "left":  # in front of the title
            btn.pack(side="left", padx=(0, 6), **({"before": first[0]} if first else {}))
        else:
            btn.pack(side="right", padx=(6, 0))
        strip = ttk.Frame(self.pane, width=26)
        ttk.Button(strip, text=unfold, width=2, command=lambda: self.expand(name)).pack(pady=(0, 6))
        ttk.Label(strip, text="\n".join(name), justify="center").pack()
        panel["strip"], panel["button"] = strip, btn
        self._panels.append(panel)
        self.pane.add(frame, weight=weight)

    def _panel(self, name):
        return next(p for p in self._panels if p["name"] == name)

    def is_collapsed(self, name):
        return self._panel(name)["collapsed"]

    def all_expanded(self):
        return not any(p["collapsed"] for p in self._panels)

    def _swap(self, panel, collapsed):
        if panel["collapsed"] == collapsed:
            return
        old, new = (panel["frame"], panel["strip"]) if collapsed else (panel["strip"], panel["frame"])
        index = [str(w) for w in self.pane.panes()].index(str(old))
        self.pane.forget(old)
        self.pane.insert(index, new, weight=0 if collapsed else panel["weight"])
        panel["collapsed"] = collapsed
        if self._on_layout:
            self._on_layout()

    def collapse(self, name):
        self._swap(self._panel(name), True)

    def expand(self, name):
        self._swap(self._panel(name), False)

    def toggle(self, name):
        p = self._panel(name)
        self._swap(p, not p["collapsed"])
