"""Settings > Mix: how playlist mixes (and the Flow refill) behave. Tk-free.

Values live in the shared settings dict under core.mix.MIX_DEFAULTS keys; the next mix
(and the next refill of the playing one) uses them.
"""

from ..core.mix import MIX_DEFAULTS, MIX_LIMITS, mix_options
from ..win.hotkeys import save_settings

LABELS = {
    "mix_seeds_per_batch": "Seed songs per refill",
    "mix_tracks_per_seed": "Recommendations kept per seed song",
    "mix_refill_at": "Refill when this many songs are left (Flow too)",
    "mix_shuffle_seeds": "Pick seed songs in Seed-box order (off: playlist order)",
    "mix_skip_playlist_songs": "Leave out songs already in the playlist",
    "mix_interleave": "Alternate between seed songs (off: one seed's songs together)",
}


class MixSettingsController:
    def __init__(self, settings, save=save_settings):
        self.settings, self._save = settings, save

    def values(self):
        return mix_options(self.settings)

    def save(self, values):
        """Validate and store {key: value}; raises ValueError naming the bad field."""
        clean = {}
        for key, default in MIX_DEFAULTS.items():
            value = values.get(key, default)
            if key in MIX_LIMITS:
                lo, hi = MIX_LIMITS[key]
                try:
                    value = int(str(value).strip())
                except ValueError:
                    raise ValueError(f"{LABELS[key]}: type a whole number") from None
                if not lo <= value <= hi:
                    raise ValueError(f"{LABELS[key]}: between {lo} and {hi}")
            clean[key] = value if key in MIX_LIMITS else bool(value)
        self.settings.update(clean)
        self._save(self.settings)
