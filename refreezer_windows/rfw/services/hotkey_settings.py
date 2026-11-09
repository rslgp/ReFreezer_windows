"""Global hotkey settings: register like/dislike and the player controls (previous, pause,
next), report their state, save changes. Tk-free.

The hotkey thread only posts the action (``post``); it runs on the Tk thread.
"""

from ..win.hotkeys import GlobalHotkeys, HotkeyError, load_settings, parse_hotkey, save_settings

ACTIONS = ("like", "dislike", "prev", "pause", "next")
LABELS = {"like": "Like playing song", "dislike": "Dislike playing song",
          "prev": "Previous track", "pause": "Pause / resume", "next": "Next track"}


class HotkeyController:
    def __init__(self, post, actions, status, hotkeys=None, settings=None, save=save_settings):
        """``actions`` maps each name in ACTIONS to its callable; ``status(text)`` is the status line."""
        self._post, self._actions, self._status, self._save = post, actions, status, save
        self.hotkeys = hotkeys or GlobalHotkeys()
        self.settings = load_settings() if settings is None else settings
        self.errors = {}

    def keys(self):
        """{action: key as typed}, e.g. {'next': 'ctrl+alt+right', ...}."""
        return {n: self.settings["hotkey_" + n] for n in ACTIONS}

    def apply(self):
        """(Re)register the hotkeys; returns {name: error} for failures."""
        s = self.settings
        self.hotkeys.stop()
        self.errors = {}
        if not s.get("hotkeys_enabled"):
            return {}

        def posted(fn):
            return lambda: self._post(fn)  # runs on the hotkey thread

        errors = self.hotkeys.start({n: (k, posted(self._actions[n])) for n, k in self.keys().items()})
        self.errors = errors
        if errors:
            self._status("Hotkeys: " + "; ".join(f"{k} {v}" for k, v in errors.items()))
        return errors

    def state(self):
        """One line for the settings dialog: what is registered right now."""
        s = self.settings
        if not s.get("hotkeys_enabled"):
            return "Off"
        bad = self.errors
        ok = [f"{n} {k}" for n, k in self.keys().items() if n not in bad]
        parts = ([f"Active: {', '.join(ok)}"] if ok else []) + [f"NOT active: {n} ({e})" for n, e in bad.items()]
        return "; ".join(parts) if self.hotkeys.running() or bad else "Not started"

    def save(self, enabled, keys):
        """Validate {action: key}, store and re-register; raises HotkeyError on a bad or
        repeated key (nothing is stored then). Returns {name: error} for keys that could
        not be registered."""
        parsed = {n: parse_hotkey(keys[n]) for n in ACTIONS}
        if len(set(parsed.values())) < len(ACTIONS):
            raise HotkeyError("Each action needs its own key.")
        self.settings.update(hotkeys_enabled=enabled, **{"hotkey_" + n: keys[n].strip() for n in ACTIONS})
        self._save(self.settings)
        return self.apply()

    def stop(self):
        self.hotkeys.stop()
