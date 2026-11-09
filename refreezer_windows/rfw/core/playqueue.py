"""Play queue for full-track playlist streaming, with seeded shuffle.

Shuffle order is ``random.Random(seed)`` over the track positions, so the same seed and
list always give the same order; ``reroll`` draws a new seed. The track playing when the
order changes moves to the front, so playback never jumps.

``order`` positions are what the queue panel shows; ``version`` changes on every edit or
move, so a view can redraw only when something changed. Removed tracks stay out even
after a reshuffle.
"""

import random
from dataclasses import asdict, fields

from ..deezer.api import Track

# Track fields worth keeping on disk; the stream token expires, so it is fetched again
_TRACK_FIELDS = {f.name for f in fields(Track)} - {"track_token"}


def new_seed():
    return random.SystemRandom().randrange(1, 1_000_000)


class PlayQueue:
    def __init__(self, tracks, start=None, shuffle=False, seed=None):
        """``start`` is a track index to play first; None starts at the top of the order."""
        self.tracks = list(tracks)
        if not self.tracks:
            raise ValueError("Nothing to play")
        self.shuffle = shuffle
        self.seed = new_seed() if seed is None else int(seed)
        self.version = 0
        self._removed = set()  # track indexes taken out of the queue
        if start is not None:
            start = min(max(start, 0), len(self.tracks) - 1)
        self._arrange(start)

    def _arrange(self, first):
        """Rebuild the order; track index ``first`` (if given) becomes the one at ``pos``."""
        order = [i for i in range(len(self.tracks)) if i not in self._removed]
        if self.shuffle:
            random.Random(self.seed).shuffle(order)
            if first is not None:
                order.remove(first)
                order.insert(0, first)
            self.order, self.pos = order, 0
        else:
            self.order, self.pos = order, order.index(first) if first is not None else 0
        self.version += 1

    @property
    def current(self):
        return self.tracks[self.order[self.pos]]

    def peek_next(self):
        return self.tracks[self.order[self.pos + 1]] if self.pos + 1 < len(self.order) else None

    def next(self):
        """Advance; None at the end of the queue."""
        if self.pos + 1 >= len(self.order):
            return None
        self.pos += 1
        self.version += 1
        return self.current

    def prev(self):
        if self.pos > 0:
            self.pos -= 1
            self.version += 1
        return self.current

    def entries(self):
        """(order position, track) for every queued track, played ones included."""
        return [(p, self.tracks[i]) for p, i in enumerate(self.order)]

    def jump(self, order_pos):
        """Make the track at ``order_pos`` the current one."""
        self.pos = min(max(order_pos, 0), len(self.order) - 1)
        self.version += 1
        return self.current

    def play_next(self, order_pos):
        """Move the track at ``order_pos`` right after the current one."""
        if order_pos == self.pos or not 0 <= order_pos < len(self.order):
            return
        idx = self.order.pop(order_pos)
        if order_pos < self.pos:
            self.pos -= 1
        self.order.insert(self.pos + 1, idx)
        self.version += 1

    def remove(self, order_pos):
        """Take a track that is not playing out of the queue; False for the current one."""
        if order_pos == self.pos or not 0 <= order_pos < len(self.order):
            return False
        self._removed.add(self.order.pop(order_pos))
        if order_pos < self.pos:
            self.pos -= 1
        self.version += 1
        return True

    def extend(self, tracks):
        """Append tracks after the current order (Flow refills); duplicates are dropped."""
        known = {t.id for t in self.tracks}
        for t in tracks:
            if t.id not in known:
                known.add(t.id)
                self.tracks.append(t)
                self.order.append(len(self.tracks) - 1)
                self.version += 1

    def remaining(self):
        return len(self.order) - self.pos - 1

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self._arrange(self.order[self.pos])

    def reroll(self, seed=None):
        """New shuffle order from a new (or given) seed; turns shuffle on."""
        self.seed = new_seed() if seed is None else int(seed)
        self.shuffle = True
        self._arrange(self.order[self.pos])
        return self.seed

    def position_label(self):
        return f"{self.pos + 1}/{len(self.order)}"

    # ---- saved queue (resume after closing the app) ------------------------------

    def to_dict(self):
        """Plain data for JSON: the tracks, the order, where it is and the shuffle state."""
        return {"tracks": [{k: v for k, v in asdict(t).items() if k in _TRACK_FIELDS} for t in self.tracks],
                "order": list(self.order), "pos": self.pos, "shuffle": self.shuffle, "seed": self.seed,
                "removed": sorted(self._removed)}

    @classmethod
    def from_dict(cls, data):
        """Inverse of ``to_dict``; raises ValueError on data that does not fit."""
        try:
            tracks = [Track(**{k: v for k, v in t.items() if k in _TRACK_FIELDS}) for t in data["tracks"]]
            q = cls(tracks, shuffle=bool(data.get("shuffle")), seed=data.get("seed"))
            order = [int(i) for i in data["order"]]
            pos = int(data["pos"])
        except (KeyError, TypeError) as e:
            raise ValueError(f"bad saved queue: {e}") from e
        if not order or any(not 0 <= i < len(tracks) for i in order) or not 0 <= pos < len(order):
            raise ValueError("bad saved queue: order out of range")
        q.order, q.pos = order, pos
        q._removed = {int(i) for i in data.get("removed", ()) if 0 <= int(i) < len(tracks)}
        q.version += 1
        return q
