"""Download UI dialogs and background download task runner for ReFreezer.

Provides:
- DownloadPlaylistDialog: Options dialog (quality, folder, covers, lyrics)
- DownloadProgressDialog: Modeless progress window with real-time status and cancellation
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from ..deezer.api import Playlist, Track
from ..media.downloader import Downloader, default_download_dir
from ..media.downloader import QUALITIES as QUALITY_CHOICES


def center_window(win: tk.Toplevel, width: int, height: int, parent: Optional[tk.Widget] = None) -> None:
    """Center a Toplevel window relative to its parent or the screen."""
    win.update_idletasks()
    if parent:
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        x = max(0, px + (pw - width) // 2)
        y = max(0, py + (ph - height) // 2)
    else:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


class DownloadPlaylistDialog(tk.Toplevel):
    """Configuration dialog for playlist downloads."""

    def __init__(
        self,
        parent: tk.Widget,
        playlist: Playlist,
        downloader: Downloader,
        default_dir: Optional[Path] = None,
        preloaded_tracks: Optional[List[Track]] = None,
        on_start: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.playlist = playlist
        self.downloader = downloader
        self.preloaded_tracks = preloaded_tracks
        self.on_start = on_start

        self.title("Download Playlist")
        self.resizable(False, False)
        self.transient(parent)

        if default_dir is None:
            default_dir = default_download_dir()
        self.dest_var = tk.StringVar(value=str(default_dir))
        self.quality_var = tk.StringVar(value=QUALITY_CHOICES[0][0])
        self.save_cover_var = tk.BooleanVar(value=True)
        self.save_lyrics_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)

        self._build_ui()
        center_window(self, 480, 310, parent)
        self.grab_set()
        self.focus_set()

    def _build_ui(self) -> None:
        pad = 12
        frm = ttk.Frame(self, padding=(pad, pad, pad, pad))
        frm.pack(fill="both", expand=True)

        # Header: Playlist title and tracks info
        hdr_frame = ttk.Frame(frm)
        hdr_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(
            hdr_frame,
            text=f"Download: {self.playlist.title}",
            font=("Segoe UI", 11, "bold"),
            wraplength=440,
        ).pack(anchor="w")

        info_text = f"{self.playlist.tracks} track(s)"
        if self.playlist.owner:
            info_text += f" • by {self.playlist.owner}"
        ttk.Label(
            hdr_frame,
            text=info_text,
            foreground="#666",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        # Audio quality
        q_frame = ttk.Frame(frm)
        q_frame.pack(fill="x", pady=4)
        ttk.Label(q_frame, text="Audio Quality:", width=14, anchor="w").pack(side="left")
        q_box = ttk.Combobox(
            q_frame,
            textvariable=self.quality_var,
            values=[c[0] for c in QUALITY_CHOICES],
            state="readonly",
            width=28,
        )
        q_box.pack(side="left", fill="x", expand=True)

        # Destination folder
        d_frame = ttk.Frame(frm)
        d_frame.pack(fill="x", pady=6)
        ttk.Label(d_frame, text="Save to folder:", width=14, anchor="w").pack(side="left")
        ttk.Entry(d_frame, textvariable=self.dest_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(d_frame, text="Browse...", width=9, command=self._browse_dir).pack(side="right")

        # Options checkboxes
        opts_frame = ttk.LabelFrame(frm, text="Options", padding=(8, 6, 8, 6))
        opts_frame.pack(fill="x", pady=(6, 12))

        ttk.Checkbutton(opts_frame, text="Save album cover art (cover.jpg & embedded)", variable=self.save_cover_var).pack(
            anchor="w", pady=2
        )
        ttk.Checkbutton(opts_frame, text="Save synchronized lyrics (.lrc)", variable=self.save_lyrics_var).pack(
            anchor="w", pady=2
        )
        ttk.Checkbutton(opts_frame, text="Overwrite existing files", variable=self.overwrite_var).pack(
            anchor="w", pady=2
        )

        # Action buttons
        btn_frame = ttk.Frame(frm)
        btn_frame.pack(fill="x", side="bottom")

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.destroy, width=10)
        cancel_btn.pack(side="right", padx=(6, 0))

        dl_btn = ttk.Button(btn_frame, text="Download", command=self._start, width=12)
        dl_btn.pack(side="right")

        self.bind("<Return>", lambda _e: self._start())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _browse_dir(self) -> None:
        init_dir = self.dest_var.get().strip() or str(default_download_dir())
        chosen = filedialog.askdirectory(parent=self, initialdir=init_dir, title="Select Destination Folder")
        if chosen:
            self.dest_var.set(chosen)

    def _start(self) -> None:
        dest_str = self.dest_var.get().strip()
        if not dest_str:
            messagebox.showwarning("Destination Missing", "Please select a download folder.", parent=self)
            return

        dest_dir = Path(dest_str)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not create folder: {e}", parent=self)
            return

        # Map display name back to quality code
        quality_code = "MP3_320"
        for label, code in QUALITY_CHOICES:
            if label == self.quality_var.get():
                quality_code = code
                break

        save_cover = self.save_cover_var.get()
        save_lyrics = self.save_lyrics_var.get()
        overwrite = self.overwrite_var.get()

        self.destroy()

        if self.on_start:
            self.on_start(
                playlist=self.playlist,
                tracks=self.preloaded_tracks,
                dest_root=dest_dir,
                pref_quality=quality_code,
                save_cover=save_cover,
                save_lyrics=save_lyrics,
                overwrite=overwrite,
            )


class DownloadProgressDialog(tk.Toplevel):
    """Modeless real-time download progress window."""

    def __init__(
        self,
        parent: tk.Widget,
        playlist: Playlist,
        dest_root: Path,
        on_cancelled: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.playlist = playlist
        self.dest_root = Path(dest_root)
        self.on_cancelled_cb = on_cancelled

        self.cancel_event = threading.Event()
        self.is_finished = False
        self.target_folder: Optional[Path] = None

        self.title(f"Downloading: {playlist.title}")
        self.minsize(460, 200)
        self.resizable(True, False)

        self.status_var = tk.StringVar(value="Initializing download...")
        self.detail_var = tk.StringVar(value="Waiting for tracks...")
        self.current_track_var = tk.StringVar(value="")

        self._build_ui()
        center_window(self, 500, 210, parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = 12
        frm = ttk.Frame(self, padding=(pad, pad, pad, pad))
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text=f"Downloading: {self.playlist.title}",
            font=("Segoe UI", 10, "bold"),
            wraplength=460,
        ).pack(anchor="w")

        dest_display = f"Save to: {self.dest_root}"
        ttk.Label(
            frm,
            text=dest_display,
            foreground="#666",
            font=("Segoe UI", 8),
            wraplength=460,
        ).pack(anchor="w", pady=(2, 6))

        self.pbar = ttk.Progressbar(frm, mode="determinate")
        self.pbar.pack(fill="x", pady=6)

        ttk.Label(
            frm,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            wraplength=460,
        ).pack(anchor="w")

        ttk.Label(
            frm,
            textvariable=self.detail_var,
            foreground="#555",
            font=("Segoe UI", 8),
            wraplength=460,
        ).pack(anchor="w", pady=(2, 0))

        # Bottom buttons
        self.btn_frame = ttk.Frame(frm)
        self.btn_frame.pack(fill="x", side="bottom", pady=(10, 0))

        self.cancel_btn = ttk.Button(self.btn_frame, text="Cancel", command=self.cancel, width=10)
        self.cancel_btn.pack(side="right")

        self.open_btn = ttk.Button(self.btn_frame, text="Open Folder", command=self._open_folder, width=12)
        # Hidden until complete
        self.close_btn = ttk.Button(self.btn_frame, text="Close", command=self.destroy, width=10)

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        if self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.status_var.set("Cancelling download... please wait.")
        self.cancel_btn.configure(state="disabled")
        if self.on_cancelled_cb:
            try:
                self.on_cancelled_cb()
            except Exception:
                pass

    def update_progress(self, idx: int, total: int, track: Optional[Track], status_msg: str) -> None:
        """Called from worker thread; marshaled to Tk main thread."""
        def _apply():
            if not self.winfo_exists():
                return
            if total > 0 and self.pbar["maximum"] != total:
                self.pbar["maximum"] = total
            self.pbar["value"] = idx
            self.status_var.set(status_msg)
            if total > 0:
                self.detail_var.set(f"{idx} of {total} tracks processed")
        self.after(0, _apply)

    def on_finished(self, result: dict) -> None:
        """Called from worker thread when download finishes."""
        def _apply():
            if not self.winfo_exists():
                return
            self.is_finished = True
            cancelled = result.get("cancelled", False)
            downloaded = result.get("downloaded", 0)
            total = result.get("total", 0)
            errors = result.get("errors", [])
            self.target_folder = result.get("folder")

            if cancelled:
                self.status_var.set(f"Download cancelled ({downloaded} of {total} downloaded).")
                self.detail_var.set("Cancelled by user.")
            elif errors:
                self.status_var.set(f"Completed with {len(errors)} error(s) ({downloaded} of {total} downloaded).")
                self.pbar["value"] = total
                self.detail_var.set(f"{downloaded} file(s) saved to {self.target_folder.name if self.target_folder else ''}")
            else:
                self.status_var.set(f"Download complete! ({downloaded} track(s) saved)")
                self.pbar["value"] = total
                self.detail_var.set(f"All files saved to {self.target_folder.name if self.target_folder else ''}")

            # Reconfigure buttons
            self.cancel_btn.pack_forget()
            if self.target_folder and self.target_folder.exists():
                self.open_btn.pack(side="left")
            self.close_btn.pack(side="right")
        self.after(0, _apply)

    def _open_folder(self) -> None:
        folder = self.target_folder or self.dest_root
        if folder and folder.exists():
            try:
                os.startfile(folder)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {e}", parent=self)

    def _on_close(self) -> None:
        if not self.is_finished and not self.cancel_event.is_set():
            if messagebox.askyesno("Cancel Download", f"Cancel downloading playlist '{self.playlist.title}'?", parent=self):
                self.cancel()
                self.destroy()
        else:
            self.destroy()
