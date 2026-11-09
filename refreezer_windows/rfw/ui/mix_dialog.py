"""Settings > Mix dialog over a MixSettingsController."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..core.mix import MIX_DEFAULTS, MIX_LIMITS
from ..services.mix_settings import LABELS


def open_mix_dialog(root, mix_settings, status):
    """``mix_settings`` is the MixSettingsController; ``status(text)`` the status line."""
    win = tk.Toplevel(root)
    win.title("Mix settings")
    win.transient(root)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    current, fields = mix_settings.values(), {}
    row = 0
    for key in MIX_DEFAULTS:
        if key in MIX_LIMITS:
            lo, hi = MIX_LIMITS[key]
            ttk.Label(frm, text=f"{LABELS[key]}:").grid(row=row, column=0, sticky="w", pady=2)
            fields[key] = tk.StringVar(value=str(current[key]))
            ttk.Spinbox(frm, from_=lo, to=hi, textvariable=fields[key], width=6).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=2)
        else:
            fields[key] = tk.BooleanVar(value=current[key])
            ttk.Checkbutton(frm, text=LABELS[key], variable=fields[key]).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1
    ttk.Label(frm, text="Seed order and the playlist rule apply to the next mix; the rest also to "
                        "the next refill of the playing mix or Flow.",
              foreground="#666", wraplength=420).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 10))

    def save():
        try:
            mix_settings.save({k: v.get() for k, v in fields.items()})
        except ValueError as e:
            messagebox.showerror("Mix settings", str(e), parent=win)
            return
        status("Mix settings saved")
        win.destroy()

    def defaults():
        for key, value in MIX_DEFAULTS.items():
            fields[key].set(str(value) if key in MIX_LIMITS else value)

    btns = ttk.Frame(frm)
    btns.grid(row=row + 1, column=0, columnspan=2, sticky="e")
    ttk.Button(btns, text="Defaults", command=defaults).pack(side="left", padx=(0, 12))
    ttk.Button(btns, text="Save", command=save).pack(side="left")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
    win.bind("<Escape>", lambda _e: win.destroy())
    return win
