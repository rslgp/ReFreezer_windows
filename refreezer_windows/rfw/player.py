"""30 s preview player using the Windows MCI API (winmm.dll), so no extra packages.

``fetch`` (network) may run in a worker thread; ``play``/``stop``/``state`` must be
called from the Tk main thread, since MCI devices belong to the thread that opened them.
"""

import ctypes
import tempfile
import urllib.request
from pathlib import Path

ALIAS = "rfwpreview"


class PlayerError(Exception):
    pass


def _mci(command):
    winmm = ctypes.windll.winmm
    buf = ctypes.create_unicode_buffer(256)
    err = winmm.mciSendStringW(command, buf, 255, 0)
    if err:
        msg = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(err, msg, 255)
        raise PlayerError(msg.value or f"MCI error {err}")
    return buf.value


class PreviewPlayer:
    def __init__(self, cache_dir=None, mci=_mci):
        self.dir = Path(cache_dir or Path(tempfile.gettempdir()) / "refreezer_windows_previews")
        self._mci = mci
        self._open = False
        self.current = None

    def fetch(self, url, track_id):
        """Download the preview once; later plays reuse the file."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{int(track_id)}.mp3"
        if not path.exists() or path.stat().st_size == 0:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            tmp = path.with_suffix(".part")
            with urllib.request.urlopen(req, timeout=30) as res, open(tmp, "wb") as f:
                f.write(res.read())
            tmp.replace(path)
        return path

    def play(self, path, track=None):
        self.stop()
        self._mci(f'open "{path}" type mpegvideo alias {ALIAS}')
        self._open = True
        self._mci(f"play {ALIAS}")
        self.current = track

    def stop(self):
        if self._open:
            try:
                self._mci(f"close {ALIAS}")
            except PlayerError:
                pass
        self._open = False
        self.current = None

    def state(self):
        """'playing', 'stopped' (finished) or '' when nothing is open."""
        if not self._open:
            return ""
        try:
            return self._mci(f"status {ALIAS} mode")
        except PlayerError:
            return ""
