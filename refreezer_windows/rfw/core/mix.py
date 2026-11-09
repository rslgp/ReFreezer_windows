"""Playlist mix: an endless recommendation queue seeded by a playlist's own songs.

Each batch takes the next few seed songs (playlist order shuffled by the Seed box, so the
same seed gives the same mix), asks Deezer for a track mix per seed in parallel (refreezer's
``playMix``), then interleaves them round-robin. Songs already in the playlist or already
queued are dropped, so the queue only holds new recommendations.
"""

import random

from .tasks import gather

# Seed songs per batch and recommendations kept per seed song
MIX_SEEDS_PER_BATCH = 3
MIX_TRACKS_PER_SEED = 12
# Batches tried in a row when every seed of a batch brought nothing new
MIX_MAX_EMPTY_BATCHES = 3


class PlaylistMix:
    def __init__(self, tracks, seed, seeds_per_batch=MIX_SEEDS_PER_BATCH, per_seed=MIX_TRACKS_PER_SEED):
        self.seed = seed
        self.seeds_per_batch, self.per_seed = seeds_per_batch, per_seed
        self._seen = {t.id for t in tracks}  # playlist songs are never recommended back
        self._seeds = list(tracks)
        random.Random(seed).shuffle(self._seeds)

    def remaining_seeds(self):
        return len(self._seeds)

    def next_seeds(self):
        batch, self._seeds = self._seeds[:self.seeds_per_batch], self._seeds[self.seeds_per_batch:]
        return batch

    def merge(self, mixes):
        """Round-robin over the per-seed mixes, keeping only songs not seen before."""
        lists = [m[:self.per_seed] for m in mixes]
        out = []
        for i in range(max((len(m) for m in lists), default=0)):
            for m in lists:
                if i < len(m) and m[i].id not in self._seen:
                    self._seen.add(m[i].id)
                    out.append(m[i])
        return out

    def next_batch(self, fetch):
        """Next recommendations; ``fetch(track_id)`` returns a mix. [] once seeds run out.

        Blocking: call from a worker thread. A failing seed just contributes nothing.
        """
        def safe(track_id):
            try:
                return fetch(track_id)
            except Exception:
                return []

        for _ in range(MIX_MAX_EMPTY_BATCHES):
            seeds = self.next_seeds()
            if not seeds:
                return []
            batch = self.merge(gather(*(lambda tid=s.id: safe(tid) for s in seeds)))
            if batch:
                return batch
        return []
