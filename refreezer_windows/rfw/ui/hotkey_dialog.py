"""Settings > Global hotkeys dialog over a HotkeyController (like, dislike, previous,
pause, next)."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..services.hotkey_settings import ACTIONS, LABELS
from ..win.hotkeys import DEFAULT_SETTINGS, HotkeyError


def open_hotkey_dialog(root, hotkeys, status):
    """``hotkeys`` is the HotkeyController; ``status(text)`` the status line."""
    win = tk.Toplevel(root)
    win.title("Global hotkeys")
    win.transient(root)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    enabled = tk.BooleanVar(value=bool(hotkeys.settings["hotkeys_enabled"]))
    ttk.Checkbutton(frm, text="Enable global hotkeys (work while the window is unfocused or minimized)",
                    variable=enabled).grid(row=0, column=0, columnspan=2, sticky="w")
    fields, current = {}, hotkeys.keys()
    for row, name in enumerate(ACTIONS, start=1):
        pad = (8, 2) if row == 1 else (2, 2)
        ttk.Label(frm, text=f"{LABELS[name]}:").grid(row=row, column=0, sticky="w", pady=pad)
        fields[name] = tk.StringVar(value=current[name])
        ttk.Entry(frm, textvariable=fields[name], width=22).grid(row=row, column=1, sticky="w", pady=pad)
    row = len(ACTIONS) + 1
    ttk.Label(frm, text="ctrl / alt / shift / win + one key, e.g. ctrl+alt+L, ctrl+alt+right, ctrl+shift+F9.\n"
                        "Media keys work alone: mediaprev, mediaplaypause, medianext.",
              foreground="#666").grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 2))
    ttk.Label(frm, text=f"Now: {hotkeys.state()}", wraplength=460).grid(
        row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 10))

    def save():
        try:
            errors = hotkeys.save(enabled.get(), {n: v.get() for n, v in fields.items()})
        except HotkeyError as e:
            messagebox.showerror("Global hotkeys", str(e), parent=win)
            return
        if errors:
            messagebox.showwarning("Global hotkeys", "Saved, but not registered:\n" + "\n".join(
                f"{k}: {v}" for k, v in errors.items()), parent=win)
            return
        status("Hotkeys saved")
        win.destroy()

    def defaults():
        for name in ACTIONS:
            fields[name].set(DEFAULT_SETTINGS["hotkey_" + name])

    btns = ttk.Frame(frm)
    btns.grid(row=row + 2, column=0, columnspan=2, sticky="e")
    ttk.Button(btns, text="Defaults", command=defaults).pack(side="left", padx=(0, 12))
    ttk.Button(btns, text="Save", command=save).pack(side="left")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
    win.bind("<Escape>", lambda _e: win.destroy())
    return win
