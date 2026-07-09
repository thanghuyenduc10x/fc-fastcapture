"""
platform_backend.py — OS abstraction layer for FC-FastCapture ("10XLifeOS").

One place for every behaviour that must differ across macOS / Windows / Linux:
the log-file location, revealing a folder, the (macOS-only) permission model,
relaunching the app, and pulling it to the foreground so a freshly-shown overlay
can grab the keyboard.

Design rules (same as the rest of the app):
  • Pure stdlib + best-effort ctypes on Windows — no hard third-party deps here.
  • Never raise: every function is wrapped so a missing API degrades gracefully.
  • Imports cleanly on any OS with no QApplication (Qt is touched lazily).

Target: Python 3.9+, macOS + Windows.
"""
from __future__ import annotations

import os
import subprocess
import sys

# Platform flags — read once, used everywhere (cheaper + clearer than repeated
# sys.platform checks, and easy to grep for during the Windows port).
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

# MENU-BAR MODE (macOS): FC runs as an Accessory / menu-bar app (like CleanShot,
# Shottr) so its capture overlay can float over — and its stop button / toast can
# be clicked on — ANOTHER app's native-fullscreen Space. Trade-off (chosen by the
# product owner): no Dock icon (menu-bar icon remains). Always on for macOS; a
# plain windowed app there could not capture a fullscreen app (the v1.0 bug).
# Off-mac (Windows/Linux) there is no Spaces concept → False, code paths no-op.
MENUBAR_MODE = IS_MAC


def set_accessory_policy(on):
    """Switch the app to Accessory (menu-bar, no Dock icon) or Regular policy.

    Called ONCE at startup with on=True. Screenshot tools run as accessory apps
    because on modern macOS that is a precondition for their windows to join
    another app's native-fullscreen Space. NOTE: flipping Regular↔Accessory per
    capture breaks Space-join for windows created after the first flip — so this
    is set once for the whole app lifetime, never toggled. No-op off macOS.
    """
    if not IS_MAC:
        return
    try:
        from AppKit import (NSApp, NSApplicationActivationPolicyAccessory,
                            NSApplicationActivationPolicyRegular)
        NSApp.setActivationPolicy_(
            NSApplicationActivationPolicyAccessory if on
            else NSApplicationActivationPolicyRegular)
    except Exception:
        pass


def activate_app():
    """Explicitly activate the app — Accessory apps don't auto-activate when a
    window shows, so without this the editor/settings/result windows get NO
    keyboard. This intentionally leaves a fullscreen Space: it is only called
    when opening windows the user must TYPE into (edit/settings). No-op off mac.
    """
    if not IS_MAC:
        return
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def pin_over_all_spaces(widget):
    """Pin a small utility window (toast / GIF stop button / recording frame)
    over EVERY Space — incl. another app's fullscreen Space — without
    activating. Without this, showing e.g. the toast on the primary display's
    desktop Space forces macOS to SWITCH there ("chọn xong bị văng về màn hình
    chính"). Same mechanism as the overlay raise. No-op off macOS."""
    raise_window_over_fullscreen(widget)


def raise_window_over_fullscreen(widget):
    """Float a Qt window ABOVE a native-fullscreen app's Space, WITHOUT
    activating our app. Finds the NSWindow by matching NSApp.windows() to the
    widget's on-screen SIZE (overlays are screen-sized) — NOT winId()->NSWindow
    pointer cast, which segfaults (see the gotcha ledger). No-op off macOS."""
    if not IS_MAC:
        return
    try:
        from AppKit import (
            NSApp,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary)
        import Quartz
        gw, gh = int(widget.width()), int(widget.height())
        target = None
        for w in NSApp.windows():
            fr = w.frame()
            if abs(int(fr.size.width) - gw) <= 8 \
                    and abs(int(fr.size.height) - gh) <= 8:
                target = w
                break
        if target is None:
            return
        # Order matters: collection behavior FIRST (so the window may join the
        # active fullscreen Space), then level ABOVE the fullscreen window
        # (shielding level — ScreenSaver level was not enough), then order front.
        target.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary)
        try:
            shield = int(Quartz.CGShieldingWindowLevel())
        except Exception:
            shield = 2000
        target.setLevel_(shield)
        target.orderFrontRegardless()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
def log_path():
    """Absolute path to the app log file for this OS (dir created best-effort).

    macOS   : ~/Library/Logs/FC-FastCapture.log
    Windows : %LOCALAPPDATA%\\FC-FastCapture\\Logs\\FC-FastCapture.log
    Linux   : $XDG_STATE_HOME (or ~/.local/state)/FC-FastCapture/FC-FastCapture.log
    """
    try:
        if IS_WIN:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "FC-FastCapture", "Logs")
        elif IS_MAC:
            d = os.path.expanduser("~/Library/Logs")
        else:
            base = os.environ.get("XDG_STATE_HOME",
                                  os.path.expanduser("~/.local/state"))
            d = os.path.join(base, "FC-FastCapture")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "FC-FastCapture.log")
    except Exception:
        # Last-resort fallback — the home directory always exists.
        return os.path.join(os.path.expanduser("~"), "FC-FastCapture.log")


# ─────────────────────────────────────────────────────────────────────────────
# File manager
# ─────────────────────────────────────────────────────────────────────────────
def open_folder(path):
    """Reveal a folder in the OS file manager. Never raises."""
    try:
        if IS_WIN:
            os.startfile(path)  # type: ignore[attr-defined]  (Windows only)
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Permissions (macOS only — Windows / Linux have no such gate)
# ─────────────────────────────────────────────────────────────────────────────
def open_permission_settings(anchor):
    """Open a specific macOS System Settings > Privacy pane. No-op elsewhere."""
    if not IS_MAC:
        return
    try:
        url = "x-apple.systempreferences:com.apple.preference.security?" + anchor
        subprocess.Popen(["open", url])
    except Exception:
        pass


def check_permissions():
    """Return (screen_recording_ok, accessibility_ok). Never raises.

    Only macOS gates screen capture + global input behind privacy permissions;
    Windows and Linux grant both implicitly, so we return (True, True) there.
    """
    if not IS_MAC:
        return True, True
    screen_ok = True
    access_ok = True
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        screen_ok = bool(CGPreflightScreenCaptureAccess())
    except Exception:
        screen_ok = True
    for mod in ("ApplicationServices", "HIServices", "Quartz"):
        try:
            m = __import__(mod, fromlist=["AXIsProcessTrusted"])
            if hasattr(m, "AXIsProcessTrusted"):
                access_ok = bool(m.AXIsProcessTrusted())
                break
        except Exception:
            continue
    return screen_ok, access_ok


def request_screen_access():
    """Trigger the macOS screen-capture permission prompt. No-op elsewhere."""
    if not IS_MAC:
        return
    try:
        from Quartz import CGRequestScreenCaptureAccess
        CGRequestScreenCaptureAccess()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Relaunch
# ─────────────────────────────────────────────────────────────────────────────
def relaunch(cmd):
    """Spawn a fresh copy of the app after a short delay, per-OS. `cmd` is the
    argv from autolaunch.current_launch_command(). Never raises. The caller is
    expected to quit the Qt app right after."""
    try:
        if not cmd:
            return
        if IS_WIN:
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) \
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            # A brief delay lets THIS process exit first (single-instance lock),
            # then the new copy starts. cmd.exe timeout avoids a python dep.
            joined = " ".join('"%s"' % c for c in cmd)
            subprocess.Popen("timeout /t 1 >nul & " + joined,
                             shell=True, creationflags=flags, close_fds=True)
        elif IS_MAC:
            if cmd[0] == "open":
                target = cmd[-1]
                subprocess.Popen(["/bin/sh", "-c", "sleep 1; open %r" % target])
            else:
                quoted = " ".join("%r" % c for c in cmd)
                subprocess.Popen(["/bin/sh", "-c", "sleep 1; %s &" % quoted])
        else:
            quoted = " ".join("%r" % c for c in cmd)
            subprocess.Popen(["/bin/sh", "-c", "sleep 1; %s &" % quoted])
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Foreground activation (so a just-shown overlay can grab the keyboard)
# ─────────────────────────────────────────────────────────────────────────────
def pull_to_foreground(widget=None):
    """Best-effort bring the app to the front so a freshly-shown overlay becomes
    the key window and receives ESC / Enter. The hotkey fires while ANOTHER app
    is frontmost, so this is what makes keyboard capture work. Never raises.

    macOS  : AppKit activateIgnoringOtherApps.
    Windows: relax the foreground lock (AllowSetForegroundWindow) so the
             subsequent Qt activateWindow() succeeds; if a widget is given and
             already has a native handle, foreground it directly.
    """
    if IS_MAC:
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
    elif IS_WIN:
        try:
            import ctypes
            ASFW_ANY = -1  # any process may set the foreground window
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
            if widget is not None:
                try:
                    hwnd = int(widget.winId())
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    ctypes.windll.user32.BringWindowToTop(hwnd)
                except Exception:
                    pass
        except Exception:
            pass
