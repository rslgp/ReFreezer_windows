"""Dialogs, status line, clipboard and corner toast for controllers that must not import Tk."""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog


class TkUi:
    def __init__(self, root, set_status):
        self.root, self._set_status = root, set_status
        self._toast = None

    def status(self, text):
        self._set_status(text)

    def error(self, title, text):
        messagebox.showerror(title, text)

    def task_error(self, exc):
        """A background task failed: status line plus a popup."""
        self.status(f"Error: {exc}")
        self.error("Error", str(exc))

    def info(self, title, text):
        messagebox.showinfo(title, text)

    def warning(self, title, text):
        messagebox.showwarning(title, text)

    def confirm(self, title, question):
        return messagebox.askyesno(title, question)

    def ask_string(self, title, prompt):
        return simpledialog.askstring(title, prompt, parent=self.root)

    def ask_directory(self, title, initialdir):
        return filedialog.askdirectory(parent=self.root, title=title, initialdir=initialdir)

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status("Link copied")

    def notify(self, text):
        """Status line plus a short corner toast, seen even when the window is minimized."""
        self.status(text)
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        toast = self._toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        tk.Label(toast, text=text, bg="#222", fg="white", padx=14, pady=8, font=("Segoe UI", 10)).pack()
        toast.update_idletasks()
        x = toast.winfo_screenwidth() - toast.winfo_reqwidth() - 24
        y = toast.winfo_screenheight() - toast.winfo_reqheight() - 72
        toast.geometry(f"+{x}+{y}")
        toast.after(2200, toast.destroy)
