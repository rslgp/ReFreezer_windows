"""Settings > Global hotkeys dialog over a HotkeyController."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..win.hotkeys import HotkeyError


def open_hotkey_dialog(root, hotkeys, status):
    """``hotkeys`` is the HotkeyController; ``status(text)`` the status line."""
    win = tk.Toplevel(root)
    win.title("Global hotkeys")
    win.transient(root)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    s = hotkeys.settings
    enabled = tk.BooleanVar(value=bool(s["hotkeys_enabled"]))
    like = tk.StringVar(value=s["hotkey_like"])
    dislike = tk.StringVar(value=s["hotkey_dislike"])
    ttk.Checkbutton(frm, text="Enable global hotkeys (work while the window is unfocused or minimized)",
                    variable=enabled).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(frm, text="Like playing song:").grid(row=1, column=0, sticky="w", pady=(8, 2))
    ttk.Entry(frm, textvariable=like, width=22).grid(row=1, column=1, sticky="w", pady=(8, 2))
    ttk.Label(frm, text="Dislike playing song:").grid(row=2, column=0, sticky="w", pady=2)
    ttk.Entry(frm, textvariable=dislike, width=22).grid(row=2, column=1, sticky="w", pady=2)
    ttk.Label(frm, text="ctrl / alt / shift / win + one key, e.g. ctrl+alt+L, ctrl+shift+F9",
              foreground="#666").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 2))
    ttk.Label(frm, text=f"Now: {hotkeys.state()}", wraplength=430).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(0, 10))

    def save():
        try:
            errors = hotkeys.save(enabled.get(), like.get(), dislike.get())
        except HotkeyError as e:
            messagebox.showerror("Global hotkeys", str(e), parent=win)
            return
        if errors:
            messagebox.showwarning("Global hotkeys", "Saved, but not registered:\n" + "\n".join(
                f"{k}: {v}" for k, v in errors.items()), parent=win)
            return
        status("Hotkeys saved")
        win.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=2, sticky="e")
    ttk.Button(btns, text="Save", command=save).pack(side="left")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
