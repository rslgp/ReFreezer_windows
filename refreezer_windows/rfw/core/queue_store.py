"""The play queue on disk (``%APPDATA%\\refreezer_windows\\queue.json``), so it survives
closing the app. One file, keyed by the Deezer user id: another account never gets it.

Written to a temp file and renamed, so a crash mid-write leaves the previous copy.
"""

import json
import os
from pathlib import Path


def queue_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "refreezer_windows" / "queue.json"


class QueueStore:
    def __init__(self, path=None):
        self.path = Path(path or queue_path())

    def load(self, user_id):
        """The saved snapshot of ``user_id``, or None."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or str(data.get("user_id")) != str(user_id):
            return None
        snap = data.get("snapshot")
        return snap if isinstance(snap, dict) else None

    def save(self, user_id, snapshot):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"user_id": str(user_id), "snapshot": snapshot}), encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
