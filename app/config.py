"""
config.py — read / write ~/.fc_fastcapture.json

Holds all persisted settings: hotkeys, locked size (Mode 3), remembered
selection size (Block C), auto-launch flag, save folder + remember-folder flag.

Pure stdlib, no Qt — safe to import anywhere. Use `load_config()` for a shared
singleton or `Config()` for an isolated instance.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".fc_fastcapture.json")
DEFAULT_SAVE_DIR = os.path.join(HOME, "Desktop", "FC-FastCapture")

_IS_WIN = sys.platform.startswith("win")

# Global-hotkey defaults are platform-specific (pynput-style canonical strings;
# Settings can re-record them). macOS uses fast 2-key ⌘+number combos. Windows
# uses Ctrl+Alt+number because Win+number is reserved by the taskbar.
if _IS_WIN:
    _DEFAULT_HOTKEYS = {
        "mode1": "<ctrl>+<alt>+1",   # Quick capture → clipboard only
        "mode2": "<ctrl>+<alt>+2",   # Capture + edit
        "mode3": "<ctrl>+<alt>+3",   # Locked size + edit
        "mode4": "<ctrl>+<alt>+4",   # Window capture + edit
        "mode5": "<ctrl>+<alt>+5",   # Record → GIF
        "mode6": "<ctrl>+<alt>+6",   # Capture → auto-save to fixed folder (v1.3)
        "mode7": "<ctrl>+<alt>+7",   # Capture → OCR (extract text) (v1.5)
        "floatingbar": "<ctrl>+<alt>+0",
    }
else:
    _DEFAULT_HOTKEYS = {
        "mode1": "<cmd>+1",   # Quick capture → clipboard only
        "mode2": "<cmd>+2",   # Capture + edit
        "mode3": "<cmd>+3",   # Locked size + edit
        "mode4": "<cmd>+4",   # Window capture + edit
        "mode5": "<cmd>+5",   # Record → GIF
        "mode6": "<cmd>+6",   # Capture → auto-save to fixed folder (v1.3)
        "mode7": "<cmd>+7",   # Capture → OCR (extract text) (v1.5)
        "floatingbar": "<cmd>+0",
    }

DEFAULTS = {
    "hotkeys": _DEFAULT_HOTKEYS,
    # Mode 3 locked rectangle (screen-safe default: 1800 was taller than any
    # Mac screen → got clamped, breaking the "exact size" promise).
    "locked_width": 1200,
    "locked_height": 800,
    # Block C — remember selection size (Mode 1 ↔ 2)
    "remember_size": True,
    "remembered_width": 1200,
    "remembered_height": 800,
    # Auto-launch on login
    "auto_launch": True,
    # Block B — save behavior
    "save_dir": DEFAULT_SAVE_DIR,
    "remember_folder": False,
    # Mode 6 — capture → auto-save (v1.3). Empty = not chosen yet → the FIRST
    # mode-6 capture shows the folder picker, then saves silently ever after.
    "mode6_dir": "",
    # Mode 7 — capture → OCR via OpenRouter (v1.5). Key entered by the user in
    # Settings (stored locally; NEVER committed/logged). Empty key → Mode 7
    # shows a hint to add it.
    "openrouter_api_key": "",
    "openrouter_model": "google/gemini-2.5-flash-lite",
    # GIF
    "gif_fps": 15,
}

# Human-friendly hotkey labels for the menu / settings (display only).
if _IS_WIN:
    HOTKEY_LABELS = {
        "mode1": "Ctrl+Alt+1", "mode2": "Ctrl+Alt+2", "mode3": "Ctrl+Alt+3",
        "mode4": "Ctrl+Alt+4", "mode5": "Ctrl+Alt+5", "mode6": "Ctrl+Alt+6",
        "floatingbar": "Ctrl+Alt+0",
    }
else:
    HOTKEY_LABELS = {
        "mode1": "⌘1", "mode2": "⌘2", "mode3": "⌘3",
        "mode4": "⌘4", "mode5": "⌘5", "mode6": "⌘6", "floatingbar": "⌘0",
    }

_PRETTY_SYM = {
    "cmd": "⌘", "command": "⌘", "meta": "⌘", "super": "⌘", "win": "⌘",
    "ctrl": "⌃", "control": "⌃", "alt": "⌥", "option": "⌥", "opt": "⌥",
    "shift": "⇧",
}
_PRETTY_ORDER = {"⌘": 0, "⌃": 1, "⌥": 2, "⇧": 3}


_WIN_NAMES = {
    "cmd": "Win", "command": "Win", "meta": "Win", "super": "Win", "win": "Win",
    "ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "option": "Alt",
    "opt": "Alt", "shift": "Shift",
}
_WIN_ORDER = {"Ctrl": 0, "Alt": 1, "Shift": 2, "Win": 3}


def pretty_combo(combo):
    """'<cmd>+<alt>+1' → '⌘⌥1' on macOS / 'Ctrl+Alt+1' on Windows. '—' if empty."""
    if not combo:
        return "—"
    if _IS_WIN:
        mods = []
        key = ""
        for part in str(combo).split("+"):
            tok = part.strip().strip("<>")
            low = tok.lower()
            if low in _WIN_NAMES:
                mods.append(_WIN_NAMES[low])
            elif tok:
                key = tok.upper()
        mods = sorted(dict.fromkeys(mods), key=lambda m: _WIN_ORDER.get(m, 9))
        return "+".join(mods + ([key] if key else []))
    mods = []
    key = ""
    for part in str(combo).split("+"):
        tok = part.strip().strip("<>")
        low = tok.lower()
        if low in _PRETTY_SYM:
            mods.append(_PRETTY_SYM[low])
        elif tok:
            key = tok.upper()
    mods = sorted(set(mods), key=lambda m: _PRETTY_ORDER.get(m, 9))
    return "".join(mods) + key


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Loads on construction; every set()/save() writes atomically to disk."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    # ── persistence ──────────────────────────────────────────────────────
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                disk = json.load(f)
            self.data = _deep_merge(DEFAULTS, disk)
        except (FileNotFoundError, ValueError, OSError):
            self.data = copy.deepcopy(DEFAULTS)
        return self.data

    def save(self):
        try:
            d = os.path.dirname(self.path) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".fc_tmp_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ── generic access ───────────────────────────────────────────────────
    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            self.save()

    def update(self, mapping, save=True):
        self.data.update(mapping)
        if save:
            self.save()

    # ── hotkeys ──────────────────────────────────────────────────────────
    def hotkeys(self):
        return dict(self.data.get("hotkeys", {}))

    def hotkey(self, name):
        return self.data.get("hotkeys", {}).get(name, DEFAULTS["hotkeys"].get(name))

    def set_hotkey(self, name, value, save=True):
        self.data.setdefault("hotkeys", {})[name] = value
        if save:
            self.save()

    # ── Block C: remembered selection size ───────────────────────────────
    def remembered_size(self):
        return (int(self.data.get("remembered_width", 1200)),
                int(self.data.get("remembered_height", 800)))

    def set_remembered_size(self, w, h):
        self.data["remembered_width"] = int(w)
        self.data["remembered_height"] = int(h)
        self.save()

    def remember_size_enabled(self):
        return bool(self.data.get("remember_size", True))

    # ── Mode 3 locked size ───────────────────────────────────────────────
    def locked_size(self):
        return (int(self.data.get("locked_width", 1200)),
                int(self.data.get("locked_height", 1800)))

    # ── Block B: save folder ─────────────────────────────────────────────
    def save_dir(self):
        return self.data.get("save_dir", DEFAULT_SAVE_DIR)

    def set_save_dir(self, path, remember=None):
        self.data["save_dir"] = path
        if remember is not None:
            self.data["remember_folder"] = bool(remember)
        self.save()

    def remember_folder(self):
        return bool(self.data.get("remember_folder", False))

    def ensure_save_dir(self):
        """Create the configured save directory if missing; return its path."""
        path = self.save_dir()
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            path = DEFAULT_SAVE_DIR
            os.makedirs(path, exist_ok=True)
            self.set_save_dir(path)
        return path

    # ── Mode 6: capture → auto-save folder (v1.3) ────────────────────────
    def mode6_dir(self):
        """The fixed auto-save folder; "" = not chosen yet (first run asks)."""
        return self.data.get("mode6_dir", "")

    def set_mode6_dir(self, path):
        # normpath strips trailing separators so equality checks stay sane.
        self.data["mode6_dir"] = os.path.normpath(path) if path else ""
        self.save()

    def ensure_mode6_dir(self):
        """Create the mode-6 folder if missing; return its path or "" on
        failure. NO silent fallback to another location — the caller re-asks
        the user instead (saving somewhere unexpected is worse than asking)."""
        path = self.mode6_dir()
        if not path:
            return ""
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            return ""

    # ── Mode 7: OCR via OpenRouter (v1.5) ────────────────────────────────
    def openrouter_api_key(self):
        return self.data.get("openrouter_api_key", "") or ""

    def set_openrouter_api_key(self, key):
        self.data["openrouter_api_key"] = (key or "").strip()
        self.save()

    def openrouter_model(self):
        return (self.data.get("openrouter_model")
                or "google/gemini-2.5-flash-lite")

    def set_openrouter_model(self, model):
        self.data["openrouter_model"] = (model or "").strip() \
            or "google/gemini-2.5-flash-lite"
        self.save()


_SINGLETON = None


def load_config():
    """Shared process-wide Config singleton."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Config()
    return _SINGLETON
