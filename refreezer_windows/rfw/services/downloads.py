"""Playlist / track downloads: options dialog, one running download, progress, cancel. Tk-free.

The dialogs are injected: ``options_dialog(playlist=, downloader=, default_dir=,
preloaded_tracks=, on_start=)`` and ``progress_dialog(playlist, dest_root)`` (which has
``cancel_event``, ``update_progress`` and ``on_finished``).
"""

from pathlib import Path

from ..core.session import need_login
from ..deezer.api import Playlist
from ..media.downloader import default_download_dir
from ..win.desktop import open_folder


class DownloadsController:
    def __init__(self, session, tasks, ui, tracklist, options_dialog, progress_dialog):
        self.session, self.tasks, self.ui, self.tracklist = session, tasks, ui, tracklist
        self.options_dialog, self.progress_dialog = options_dialog, progress_dialog
        self.download_dir = default_download_dir()
        # Set while a playlist download runs; setting it asks the workers to stop
        self.cancel = None

    def _dir(self):
        return Path(self.download_dir) if self.download_dir else default_download_dir()

    def open_downloads_folder(self):
        try:
            open_folder(self._dir())
        except Exception as e:
            self.ui.error("Error", f"Could not open downloads folder: {e}")

    def download_playlist_dialog(self, playlist, preloaded_tracks=None):
        if need_login(self.session, self.ui):
            return
        if self.cancel is not None:
            self.ui.info("Download in progress",
                         "A download is already running. Please cancel or wait for it to finish.")
            return
        if preloaded_tracks is None:
            preloaded_tracks = self.tracklist.tracks_of(playlist)
        self.options_dialog(
            playlist=playlist,
            downloader=self.session.downloader,
            default_dir=self._dir(),
            preloaded_tracks=preloaded_tracks,
            on_start=self.download_playlist,
        )

    def download_playlist(self, playlist, pref_quality="MP3_320", dest_root=None, tracks=None,
                          save_cover=True, save_lyrics=True, overwrite=False):
        """Download a whole playlist into <folder>/<playlist title> (DOWNLOAD_WORKERS at a time)."""
        if need_login(self.session, self.ui) or self.cancel is not None:
            return
        if dest_root is None:
            folder = self.ui.ask_directory("Download to folder", str(self._dir()))
            if not folder:
                return
            dest_root = folder
        dest_root = Path(dest_root)

        self.download_dir = dest_root
        dlg = self.progress_dialog(playlist, dest_root)
        cancel = self.cancel = dlg.cancel_event
        dl, tasks = self.session.downloader, self.tasks

        def progress(idx, total, track, msg):  # worker thread: hand it to the Tk thread
            tasks.post_status(msg)
            tasks.post(lambda: dlg.update_progress(idx, total, track, msg))

        def work():
            try:
                return dl.download_playlist(
                    playlist=playlist,
                    tracks=tracks,
                    dest_root=dest_root,
                    pref_quality=pref_quality,
                    save_cover=save_cover,
                    save_lyrics=save_lyrics,
                    overwrite=overwrite,
                    progress_cb=progress,
                    is_cancelled=cancel.is_set,
                )
            finally:
                self.cancel = None  # also on error, so the next download can start

        def done(res):
            dlg.on_finished(res)
            head = "Cancelled" if res["cancelled"] else "Finished"
            self.ui.status(f"{head}: {res['downloaded']}/{res['total']} track(s) in {res['folder']}")

        self.tasks.run(work, done, f"Downloading '{playlist.title}'...")

    def download_selected_tracks(self, tracks, quality):
        if need_login(self.session, self.ui) or not tracks:
            return
        title = tracks[0].title if len(tracks) == 1 else f"Selected Tracks ({len(tracks)})"
        self.download_playlist(Playlist(id="adhoc", title=title, tracks=len(tracks)),
                               pref_quality=quality, tracks=tracks)

    def shutdown(self):
        if self.cancel is not None:
            self.cancel.set()
