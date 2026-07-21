"""
hotkeys_win.py — global hotkeys on Windows via Win32 RegisterHotKey.

The Windows counterpart to the macOS CGEventTap subsystem in main.py. It reads
the SAME hotkey strings from the shared Config ("<ctrl>+<alt>+1", …), registers
each with the OS, and calls ``controller.dispatch(name)`` on the Qt main thread
when a combo fires.

Mechanism (no polling, no background thread, no pywin32):
  • A hidden native QWidget owns the hotkeys; its HWND receives ``WM_HOTKEY``.
  • ``RegisterHotKey`` binds each combo to that window with ``MOD_NOREPEAT``.
  • A ``QAbstractNativeEventFilter`` catches ``WM_HOTKEY`` in the Qt event loop
    and dispatches the mapped mode via ``QTimer.singleShot(0, …)`` — so the
    actual work runs on the event loop, never inside the message pump.

Every Win32 call is guarded; nothing here raises. On non-Windows this module is
simply never imported (main.py branches on ``platform_backend.IS_WIN``).

Target: Python 3.9+, PyQt6, Windows.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QWidget

# Win32 modifier masks for RegisterHotKey.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# The six bindable actions, in the same order the rest of the app uses.
_HOTKEY_NAMES = ["mode1", "mode2", "mode3", "mode4", "mode5", "mode6", "mode7", "floatingbar"]


def _vk_for_char(ch):
    """Digit/letter → Win32 virtual-key code. VK codes equal the ASCII code of
    the character for '0'-'9' (0x30-0x39) and the UPPERCASE letter (0x41-0x5A)."""
    if not ch or len(ch) != 1:
        return None
    ch = ch.lower()
    if "0" <= ch <= "9":
        return ord(ch)
    if "a" <= ch <= "z":
        return ord(ch.upper())
    return None


def parse_combo(combo):
    """'<ctrl>+<alt>+1' → (mods_mask_with_NOREPEAT, vk) or None.

    Accepts the same pynput-style tokens the config stores. The 'cmd' token maps
    to the Windows/Super key (MOD_WIN) for round-trip compatibility, though the
    Windows DEFAULTS use ctrl+alt to avoid clashing with taskbar Win+number.
    """
    if not combo:
        return None
    mods = 0
    vk = None
    for raw in str(combo).replace(" ", "").split("+"):
        tok = raw.strip("<>").lower()
        if tok in ("cmd", "command", "win", "super", "meta"):
            mods |= MOD_WIN
        elif tok in ("alt", "option", "opt"):
            mods |= MOD_ALT
        elif tok in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif tok == "shift":
            mods |= MOD_SHIFT
        else:
            v = _vk_for_char(tok)
            if v is not None:
                vk = v
    if vk is None or mods == 0:
        return None
    return (mods | MOD_NOREPEAT, vk)


class WinHotkeyManager(QAbstractNativeEventFilter):
    """Owns the OS-level global hotkeys on Windows.

    controller must expose ``.cfg`` (a Config) and ``.dispatch(name)``.
    """

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._win = None          # hidden native QWidget (HWND owner)
        self._hwnd = None
        self._id_to_name = {}      # hotkey id -> action name
        self._registered = []      # list of hotkey ids currently registered
        self._next_id = 1
        self._suspended = False
        self._installed = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def install(self):
        """Create the owner window, install the event filter, register combos."""
        try:
            app = QApplication.instance()
            if app is None:
                return
            # A hidden, never-shown top-level widget whose native HWND owns the
            # hotkeys. winId() forces the native handle to be created eagerly.
            self._win = QWidget()
            self._win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            self._hwnd = int(self._win.winId())
            app.installNativeEventFilter(self)
            self._installed = True
            self.reload()
        except Exception:
            pass

    def reload(self):
        """Re-read the combos from config and (re)register them with the OS."""
        if not self._installed or self._suspended:
            return
        self._unregister_all()
        try:
            for name in _HOTKEY_NAMES:
                try:
                    combo = self._controller.cfg.hotkey(name)
                except Exception:
                    combo = None
                parsed = parse_combo(combo)
                if not parsed:
                    continue
                mods, vk = parsed
                hid = self._next_id
                self._next_id += 1
                ok = ctypes.windll.user32.RegisterHotKey(
                    wintypes.HWND(self._hwnd), hid, mods, vk)
                if ok:
                    self._id_to_name[hid] = name
                    self._registered.append(hid)
        except Exception:
            pass

    def _unregister_all(self):
        for hid in list(self._registered):
            try:
                ctypes.windll.user32.UnregisterHotKey(
                    wintypes.HWND(self._hwnd), hid)
            except Exception:
                pass
        self._registered = []
        self._id_to_name = {}

    # ── suspend / resume (e.g. while recording a new combo in Settings) ──
    def suspend(self):
        if not self._suspended:
            self._unregister_all()
            self._suspended = True

    def resume(self):
        if self._suspended:
            self._suspended = False
            self.reload()

    def stop(self):
        try:
            self._unregister_all()
            app = QApplication.instance()
            if app is not None and self._installed:
                app.removeNativeEventFilter(self)
        except Exception:
            pass
        self._installed = False

    # ── the WM_HOTKEY pump ───────────────────────────────────────────────
    def nativeEventFilter(self, eventType, message):
        try:
            et = eventType
            if isinstance(et, (bytes, bytearray)):
                et = bytes(et)
            if et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    name = self._id_to_name.get(int(msg.wParam))
                    if name:
                        # Defer to the event loop — keep the pump instant.
                        QTimer.singleShot(
                            0, lambda n=name: self._controller.dispatch(n))
                        return True, 0
        except Exception:
            pass
        return False, 0
