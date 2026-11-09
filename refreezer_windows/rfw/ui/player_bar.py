"""Bottom of the window: player controls, then the now-playing / status line."""

import tkinter as tk
from tkinter import ttk

from ..core.playqueue import new_seed
from ..deezer.api import FLOW_TYPES

# Like button text by "playing song is in Favorites"
LIKE_TEXT = {False: "♡ Like", True: "♥ Liked"}


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

    def show_liked(self, liked):
        """Mirror "playing song is in Favorites" on the Like button."""
        text = LIKE_TEXT[liked]
        if self.like_btn.cget("text") != text:
            self.like_btn.configure(text=text)
