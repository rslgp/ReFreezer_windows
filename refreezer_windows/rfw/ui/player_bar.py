"""Bottom of the window: player controls, then the now-playing / status line."""

import tkinter as tk
from tkinter import ttk

from ..core.playqueue import new_seed
from ..deezer.api import FLOW_TYPES

# Like button text by "playing song is in Favorites"
LIKE_TEXT = {False: "♡ Like", True: "♥ Liked"}
# Resolution of the seek bar (its value runs 0..SEEK_STEPS)
SEEK_STEPS = 1000


def fmt_time(ms):
    """m:ss (h:mm:ss from an hour on)."""
    s = max(int(ms), 0) // 1000
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


class PlayerBar:
    """Also the view of PlaybackController (now line, Shuffle, Seed)."""

    def __init__(self, root, playback, likes, list_actions):
        ctl = ttk.Frame(root, padding=(8, 8, 8, 0))
        ctl.pack(fill="x")
        ttk.Button(ctl, text="▶ Preview", command=list_actions.play_selected).pack(side="left")
        ttk.Button(ctl, text="▶ Play", command=list_actions.play_selected_full).pack(side="left", padx=(4, 0))
        ttk.Button(ctl, text="⏮", width=3, command=playback.queue_prev).pack(side="left", padx=(8, 0))
        ttk.Button(ctl, text="⏯", width=3, command=playback.toggle_pause).pack(side="left")
        ttk.Button(ctl, text="⏭", width=3, command=playback.queue_next).pack(side="left")
        ttk.Button(ctl, text="■ Stop", command=playback.stop).pack(side="left", padx=4)
        flow_btn = ttk.Menubutton(ctl, text="🌊 Flow")
        flow_menu = tk.Menu(flow_btn, tearoff=False)
        for label, flow_type in FLOW_TYPES:
            flow_menu.add_command(label=label, command=lambda t=flow_type: playback.play_flow(t))
        flow_btn["menu"] = flow_menu
        flow_btn.pack(side="left", padx=(8, 0))
        self.like_btn = ttk.Button(ctl, text=LIKE_TEXT[False], width=9, command=likes.like_current)
        self.like_btn.pack(side="left", padx=(4, 0))
        ttk.Button(ctl, text="👎 Dislike", command=likes.dislike_current).pack(side="left", padx=(4, 0))
        self.shuffle_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Shuffle", variable=self.shuffle_var,
                        command=playback.on_shuffle_toggle).pack(side="left", padx=(8, 0))
        ttk.Button(ctl, text="🎲 Reroll", command=playback.reroll).pack(side="left", padx=4)
        ttk.Label(ctl, text="Seed:").pack(side="left")
        self.seed_var = tk.StringVar(value=str(new_seed()))
        seed_entry = ttk.Entry(ctl, textvariable=self.seed_var, width=9)
        seed_entry.pack(side="left", padx=4)
        seed_entry.bind("<Return>", lambda _e: playback.apply_seed())
        ttk.Button(ctl, text="Open in Deezer", command=list_actions.open_selected).pack(side="right")

        # Seek bar: click or drag anywhere on it to jump in the playing song
        seek_row = ttk.Frame(root, padding=(8, 6, 8, 0))
        seek_row.pack(fill="x")
        self.time_var = tk.StringVar(value=fmt_time(0))
        ttk.Label(seek_row, textvariable=self.time_var, width=6, anchor="e").pack(side="left")
        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_scale = ttk.Scale(seek_row, from_=0.0, to=SEEK_STEPS, variable=self.seek_var)
        self.seek_scale.pack(side="left", fill="x", expand=True, padx=6)
        self.length_var = tk.StringVar(value=fmt_time(0))
        ttk.Label(seek_row, textvariable=self.length_var, width=6).pack(side="left")
        self._dragging = False
        self._on_seek = playback.seek
        self.seek_scale.bind("<ButtonPress-1>", self._seek_press)
        self.seek_scale.bind("<B1-Motion>", self._seek_drag)
        self.seek_scale.bind("<ButtonRelease-1>", self._seek_release)

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        self.now_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.now_var).pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Paste your ARL and click Login.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#666").pack(side="right")
        self.bar = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.bar.pack(side="right", padx=8)

    # ---- PlaybackController view -------------------------------------------

    def set_now(self, text):
        self.now_var.set(text)

    def get_shuffle(self):
        return self.shuffle_var.get()

    def set_shuffle(self, on):
        self.shuffle_var.set(on)

    def get_seed(self):
        return self.seed_var.get()

    def set_seed(self, text):
        self.seed_var.set(text)

    # ---- status line ------------------------------------------------------------

    def set_status(self, text):
        self.status_var.set(text)

    def set_busy(self, busy):
        if busy:
            self.bar.start(12)
        else:
            self.bar.stop()

    # ---- seek bar -----------------------------------------------------------------

    def _fraction_at(self, x):
        width = max(self.seek_scale.winfo_width(), 1)
        return min(max(x / width, 0.0), 1.0)

    def _seek_press(self, event):
        """Jump straight to the clicked spot (ttk's default only steps toward it)."""
        self._dragging = True
        self.seek_var.set(self._fraction_at(event.x) * SEEK_STEPS)
        return "break"

    def _seek_drag(self, event):
        if self._dragging:
            self.seek_var.set(self._fraction_at(event.x) * SEEK_STEPS)
        return "break"

    def _seek_release(self, event):
        if self._dragging:
            self._dragging = False
            self._on_seek(self._fraction_at(event.x))
        return "break"

    def show_progress(self, progress):
        """``progress`` is (position ms, length ms) or None when idle; ignored mid-drag."""
        pos, length = progress if progress else (0, 0)
        if self._dragging:
            pos = self.seek_var.get() / SEEK_STEPS * length
        else:
            self.seek_var.set(pos / length * SEEK_STEPS if length else 0.0)
        self.time_var.set(fmt_time(pos))
        self.length_var.set(fmt_time(length))

    def show_liked(self, liked):
        """Mirror "playing song is in Favorites" on the Like button."""
        text = LIKE_TEXT[liked]
        if self.like_btn.cget("text") != text:
            self.like_btn.configure(text=text)
