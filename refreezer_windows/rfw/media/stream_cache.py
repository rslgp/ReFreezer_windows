"""Full-track stream cache: each track is fetched whole through the shared Downloader.

One fetch future per track id (so two requests never write the same temp file), on a
pool of its own: the GUI task pool waits on these futures and must not run them too.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# MP3 only, since the MCI player cannot open FLAC
STREAM_DIR = Path(tempfile.gettempdir()) / "refreezer_windows_stream"
STREAM_QUALITY = "MP3_128"


class StreamCache:
    def __init__(self, downloader, folder=STREAM_DIR, quality=STREAM_QUALITY, workers=2, executor=None):
        """``downloader()`` returns the session Downloader (it only exists after login)."""
        self._downloader = downloader
        self.folder, self.quality = folder, quality
        self.pool = executor or ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rfw-stream")
        self.futures = {}  # track id -> Future of the decrypted file path

    def fetch(self, track):
        """Future for the full decrypted MP3, one fetch per track (a failed or vanished one is redone)."""
        fut = self.futures.get(track.id)
        stale = fut is not None and fut.done() and (
            fut.cancelled() or fut.exception() is not None or not Path(fut.result()).exists())
        if fut is None or stale:
            fut = self.pool.submit(
                self._downloader().download_track, track, self.folder,
                pref_quality=self.quality, save_cover=False, save_lyrics=False)
            self.futures[track.id] = fut
        return fut

    def prune(self, keep_ids):
        """Drop cached files of tracks that are neither playing nor up next."""
        for tid, fut in list(self.futures.items()):
            if tid in keep_ids or not fut.done():
                continue
            del self.futures[tid]
            if not fut.cancelled() and fut.exception() is None:  # cancelled ones raise on exception()
                try:
                    Path(fut.result()).unlink(missing_ok=True)
                except OSError:
                    pass

    def shutdown(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.prune(set())
