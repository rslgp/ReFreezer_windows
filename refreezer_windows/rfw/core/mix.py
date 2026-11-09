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

# Settings > Mix: settings.json key -> default. Numbers are clamped to MIX_LIMITS.
MIX_DEFAULTS = {
    "mix_seeds_per_batch": MIX_SEEDS_PER_BATCH,  # seed songs asked per refill
    "mix_tracks_per_seed": MIX_TRACKS_PER_SEED,  # recommendations kept per seed song
    "mix_refill_at": 2,  # Flow and mixes refill when this many songs or fewer are left
    "mix_shuffle_seeds": True,  # seed songs in Seed-box order; off = playlist order
    "mix_skip_playlist_songs": True,  # never queue a song that is in the playlist
    "mix_interleave": True,  # one song per seed in turn; off = each seed's songs together
}
MIX_LIMITS = {"mix_seeds_per_batch": (1, 20), "mix_tracks_per_seed": (1, 80), "mix_refill_at": (0, 20)}


def mix_options(settings):
    """The MIX_DEFAULTS keys of ``settings``, defaults for missing ones, numbers clamped."""
    out = {}
    for key, default in MIX_DEFAULTS.items():
        value = settings.get(key, default)
        if key in MIX_LIMITS:
            lo, hi = MIX_LIMITS[key]
            try:
                value = min(max(int(value), lo), hi)
            except (TypeError, ValueError):
                value = default
        else:
            value = bool(value)
        out[key] = value
    return out


class PlaylistMix:
    def __init__(self, tracks, seed, seeds_per_batch=MIX_SEEDS_PER_BATCH, per_seed=MIX_TRACKS_PER_SEED,
                 shuffle_seeds=True, skip_playlist_songs=True, interleave=True):
        self.seed = seed
        self.seeds_per_batch, self.per_seed = seeds_per_batch, per_seed
        self.interleave = interleave
        # Playlist songs are never recommended back (unless the setting allows them)
        self._seen = {t.id for t in tracks} if skip_playlist_songs else set()
        self._seeds = list(tracks)
        if shuffle_seeds:
            random.Random(seed).shuffle(self._seeds)

    @classmethod
    def from_settings(cls, tracks, seed, settings):
        """A mix tuned by Settings > Mix (``settings`` holds the MIX_DEFAULTS keys)."""
        o = mix_options(settings)
        return cls(tracks, seed, o["mix_seeds_per_batch"], o["mix_tracks_per_seed"], o["mix_shuffle_seeds"],
                   o["mix_skip_playlist_songs"], o["mix_interleave"])

    def tune(self, settings):
        """Apply Settings > Mix counts and order to the next batches (the seed order and the
        playlist-song rule are fixed when the mix starts)."""
        o = mix_options(settings)
        self.seeds_per_batch, self.per_seed = o["mix_seeds_per_batch"], o["mix_tracks_per_seed"]
        self.interleave = o["mix_interleave"]

    def exclude(self, ids):
        """Never recommend these (songs already queued, e.g. from a resumed queue)."""
        self._seen.update(ids)

    def remaining_seeds(self):
        return len(self._seeds)

    def next_seeds(self):
        batch, self._seeds = self._seeds[:self.seeds_per_batch], self._seeds[self.seeds_per_batch:]
        return batch

    def merge(self, mixes):
        """Round-robin over the per-seed mixes (or one after another when ``interleave`` is
        off), keeping only songs not seen before."""
        # per_seed counts songs that can still be queued (the seed song itself is usually first)
        lists = [[t for t in m if t.id not in self._seen][:self.per_seed] for m in mixes]
        if self.interleave:
            ordered = [m[i] for i in range(max((len(m) for m in lists), default=0)) for m in lists if i < len(m)]
        else:
            ordered = [t for m in lists for t in m]
        out = []
        for t in ordered:
            if t.id not in self._seen:
                self._seen.add(t.id)
                out.append(t)
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
