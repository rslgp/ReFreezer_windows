"""Keeps the play queue on disk while the app runs and brings it back after login. Tk-free.

``tick`` (poll loop, Tk thread) saves when the queue changes (new track, reorder, refill)
and every SAVE_EVERY_S seconds while it plays, so the time in the song is kept too, even
after a crash. Nothing is saved or cleared before ``restore`` ran for the logged-in user,
so starting the app never wipes the saved queue.
"""

import time

SAVE_EVERY_S = 10


class QueuePersistence:
    def __init__(self, playback, store, status, clock=time.monotonic):
        self.playback, self.store, self._status, self._clock = playback, store, status, clock
        self.user_id = None  # set by restore: saving is on from then
        self._last_key = None
        self._last_save = 0.0

    def _key(self):
        pq = self.playback.playq
        return None if pq is None else (id(pq), pq.version, pq.pos)

    def restore(self, user_id):
        """After login: load ``user_id``'s saved queue (paused at the saved time). True if loaded."""
        self.user_id = user_id
        snap = self.store.load(user_id)
        loaded = snap is not None and self.playback.restore(snap)
        if loaded:
            pq = self.playback.playq
            self._status(f"Queue restored: {pq.current.title} [{pq.position_label()}], press ⏯ to continue")
        self._last_key, self._last_save = self._key(), self._clock()
        return loaded

    def tick(self):
        if self.user_id is None:
            return
        key = self._key()
        changed = key != self._last_key
        if not changed and (key is None or self._clock() - self._last_save < SAVE_EVERY_S):
            return
        self.save_now()

    def save_now(self):
        """Write the queue now (or delete the file when the queue was stopped)."""
        if self.user_id is None:
            return
        snap = self.playback.snapshot()
        try:
            if snap is None:
                self.store.clear()
            else:
                self.store.save(self.user_id, snap)
        except OSError as e:
            self._status(f"Could not save the queue: {e}")
        self._last_key, self._last_save = self._key(), self._clock()
