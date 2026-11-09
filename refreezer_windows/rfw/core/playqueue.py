"""Play queue for full-track playlist streaming, with seeded shuffle.

Shuffle order is ``random.Random(seed)`` over the track positions, so the same seed and
list always give the same order; ``reroll`` draws a new seed. The track playing when the
order changes moves to the front, so playback never jumps.
"""

import random


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
        if start is not None:
            start = min(max(start, 0), len(self.tracks) - 1)
        self._arrange(start)

    def _arrange(self, first):
        """Rebuild the order; track index ``first`` (if given) becomes the one at ``pos``."""
        order = list(range(len(self.tracks)))
        if self.shuffle:
            random.Random(self.seed).shuffle(order)
            if first is not None:
                order.remove(first)
                order.insert(0, first)
            self.order, self.pos = order, 0
        else:
            self.order, self.pos = order, first or 0

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
        return self.current

    def prev(self):
        if self.pos > 0:
            self.pos -= 1
        return self.current

    def extend(self, tracks):
        """Append tracks after the current order (Flow refills); duplicates are dropped."""
        known = {t.id for t in self.tracks}
        for t in tracks:
            if t.id not in known:
                known.add(t.id)
                self.tracks.append(t)
                self.order.append(len(self.tracks) - 1)

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
