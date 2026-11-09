"""System-wide hotkeys through Win32 RegisterHotKey (works while the window is unfocused
or minimized), plus the small JSON settings file that stores them.

RegisterHotKey with no window posts WM_HOTKEY to the registering thread, so a dedicated
thread registers the keys and runs a GetMessage loop. Callbacks run on that thread: hand
them to the Tk thread (the GUI puts them on its queue).
"""

import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
NAMED_KEYS = {
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE,
}
# Keyboard media keys: made for this, so they may be used without a modifier
MEDIA_KEYS = {"medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplaypause": 0xB3}

DEFAULT_SETTINGS = {
    "hotkeys_enabled": True,
    "hotkey_like": "ctrl+alt+L",
    "hotkey_dislike": "ctrl+alt+D",
    # Player controls; a global key is taken from every program, hence the modifiers
    "hotkey_prev": "ctrl+alt+left",
    "hotkey_pause": "ctrl+alt+down",
    "hotkey_next": "ctrl+alt+right",
}


class HotkeyError(ValueError):
    pass


def parse_hotkey(text):
    """'ctrl+alt+L' -> (modifier flags, virtual-key code). Needs a modifier and one key;
    media keys (medianext, mediaprev, mediaplaypause, mediastop) may stand alone."""
    parts = [p.strip().lower() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    mods, keys = 0, []
    for p in parts:
        if p in MODIFIERS:
            mods |= MODIFIERS[p]
        else:
            keys.append(p)
    if len(keys) != 1:
        raise HotkeyError(f"'{text}': use modifiers plus exactly one key, e.g. ctrl+alt+L")
    key = keys[0]
    if key in MEDIA_KEYS:
        return mods, MEDIA_KEYS[key]
    if not mods:
        raise HotkeyError(f"'{text}': add at least one of ctrl, alt, shift, win "
                          "(a global key is taken from every program)")
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        raise HotkeyError(f"'{text}': unknown key '{key}'")
    return mods, vk


def settings_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "refreezer_windows" / "settings.json"


def load_settings(path=None):
    path = Path(path or settings_path())
    data = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return data


def save_settings(data, path=None):
    path = Path(path or settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


def claim_single_instance(name="Local\\ReFreezerWindows", window_title="ReFreezer for Windows"):
    """Mutex handle if this is the only running app (keep it alive); else None, after
    bringing the running window forward. Global hotkeys belong to one process, so a second
    copy would silently miss them while the first answered "Nothing is playing"."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return handle
    kernel32.CloseHandle(handle)
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, window_title)
    if hwnd:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    return None


class GlobalHotkeys:
    """Registers {name: (hotkey text, callback)} on a background thread."""

    def __init__(self, user32=None):
        self._user32 = user32
        self._thread = None
        self._thread_id = None

    def start(self, bindings):
        """Register the bindings; returns {name: error text} for the ones that failed."""
        self.stop()
        parsed, errors = {}, {}
        for name, (text, cb) in bindings.items():
            try:
                parsed[name] = (parse_hotkey(text), cb)
            except HotkeyError as e:
                errors[name] = str(e)
        if not parsed:
            return errors
        ready = threading.Event()
        result = {}
        self._thread = threading.Thread(target=self._run, args=(parsed, ready, result), daemon=True,
                                        name="global-hotkeys")
        self._thread.start()
        ready.wait(5)
        errors.update(result)
        return errors

    def _run(self, parsed, ready, result):
        user32 = self._user32 or ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        callbacks = {}
        for i, (name, ((mods, vk), cb)) in enumerate(parsed.items(), start=1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                callbacks[i] = cb
            else:
                result[name] = "already used by another program (or invalid)"
        ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in callbacks:
                    try:
                        callbacks[msg.wParam]()
                    except Exception:
                        pass
        finally:
            for i in callbacks:
                user32.UnregisterHotKey(None, i)

    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        if self._thread is not None and self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None
        self._thread_id = None
