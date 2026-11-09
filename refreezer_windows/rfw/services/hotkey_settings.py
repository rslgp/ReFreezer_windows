"""Global hotkey settings: register like/dislike, report their state, save changes. Tk-free.

The hotkey thread only posts the action (``post``); it runs on the Tk thread.
"""

from ..win.hotkeys import GlobalHotkeys, HotkeyError, load_settings, parse_hotkey, save_settings

ACTIONS = ("like", "dislike")


class HotkeyController:
    def __init__(self, post, actions, status, hotkeys=None, settings=None, save=save_settings):
        """``actions`` maps each name in ACTIONS to its callable; ``status(text)`` is the status line."""
        self._post, self._actions, self._status, self._save = post, actions, status, save
        self.hotkeys = hotkeys or GlobalHotkeys()
        self.settings = load_settings() if settings is None else settings
        self.errors = {}

    def apply(self):
        """(Re)register the hotkeys; returns {name: error} for failures."""
        s = self.settings
        self.hotkeys.stop()
        self.errors = {}
        if not s.get("hotkeys_enabled"):
            return {}

        def posted(fn):
            return lambda: self._post(fn)  # runs on the hotkey thread

        errors = self.hotkeys.start({n: (s["hotkey_" + n], posted(self._actions[n])) for n in ACTIONS})
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
        ok = [f"{n} {s['hotkey_' + n]}" for n in ACTIONS if n not in bad]
        parts = ([f"Active: {', '.join(ok)}"] if ok else []) + [f"NOT active: {n} ({e})" for n, e in bad.items()]
        return "; ".join(parts) if self.hotkeys.running() or bad else "Not started"

    def save(self, enabled, like, dislike):
        """Validate, store and re-register; raises HotkeyError on a bad or repeated key.

        Returns {name: error} for keys that could not be registered.
        """
        if len({parse_hotkey(like), parse_hotkey(dislike)}) < 2:
            raise HotkeyError("Like and dislike need different keys.")
        self.settings.update(hotkeys_enabled=enabled, hotkey_like=like.strip(), hotkey_dislike=dislike.strip())
        self._save(self.settings)
        return self.apply()

    def stop(self):
        self.hotkeys.stop()
