"""Top bar: ARL entry, Remember, Login, user name, search box."""

import tkinter as tk
from tkinter import ttk

from gpm.arl import find_arl


class TopBar:
    def __init__(self, root, on_login, on_search):
        """``on_login(arl, remember)``, ``on_search(query)``."""
        self._on_login, self._on_search = on_login, on_search
        top = ttk.Frame(root, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        ttk.Label(top, text="ARL:").pack(side="left")
        self.arl_var = tk.StringVar(value=find_arl() or "")
        e = ttk.Entry(top, textvariable=self.arl_var, show="*", width=28)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda _e: self.login())
        self.remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Remember", variable=self.remember_var).pack(side="left")
        self.login_btn = ttk.Button(top, text="Login", command=self.login)
        self.login_btn.pack(side="left", padx=4)
        self.user_var = tk.StringVar(value="Not logged in")
        ttk.Label(top, textvariable=self.user_var).pack(side="left", padx=8)

        self.search_btn = ttk.Button(top, text="Search", command=self.search, state="disabled")
        self.search_btn.pack(side="right")
        self.search_var = tk.StringVar()
        s = ttk.Entry(top, textvariable=self.search_var, width=32)
        s.pack(side="right", padx=4)
        s.bind("<Return>", lambda _e: self.search())

    @property
    def arl(self):
        return self.arl_var.get().strip()

    def login(self):
        self._on_login(self.arl_var.get(), self.remember_var.get())

    def search(self):
        self._on_search(self.search_var.get())

    def logged_in(self, user_name):
        self.user_var.set(f"Logged in as {user_name}")
        self.search_btn.configure(state="normal")
