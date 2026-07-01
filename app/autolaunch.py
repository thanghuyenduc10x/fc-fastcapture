"""
autolaunch.py — macOS LaunchAgent integration for FC-FastCapture ("10XLifeOS").

Provides a tiny, dependency-free helper to start the app automatically when the
user logs into macOS, by writing a per-user LaunchAgent plist into
``~/Library/LaunchAgents`` and (un)loading it via ``launchctl``.

No Qt here — this is pure stdlib. Every public function is wrapped in
``try/except`` and returns a bool; it must NEVER raise, even if ``launchctl`` is
unavailable or the filesystem is read-only.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys

# Reverse-DNS label identifying our LaunchAgent job.
LABEL = "com.10xlifeos.fcfastcapture"

# Per-user LaunchAgents directory and the plist path for this job.
LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
PLIST_PATH = os.path.join(LAUNCH_AGENTS_DIR, LABEL + ".plist")

_IS_WIN = sys.platform.startswith("win")

# Windows "run at login" uses the per-user Run registry key instead of a
# LaunchAgent plist. Value name shown in Task Manager > Startup.
_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_WIN_RUN_VALUE = "FC-FastCapture"


def _win_run_command():
    """The command string stored in the Run key (quoted exe / python main.py)."""
    cmd = current_launch_command()
    return " ".join('"%s"' % c for c in cmd)


def _app_bundle_path():
    """
    If we are running from inside a packaged ``.app`` bundle, return the
    absolute path to that ``.app`` directory; otherwise return None.

    Detection looks for the ``.app/Contents`` marker in either the Python
    executable path or argv[0] (PyInstaller/py2app both place the binary under
    ``<App>.app/Contents/MacOS/...``).
    """
    candidates = []
    try:
        candidates.append(os.path.abspath(sys.executable))
    except Exception:
        pass
    try:
        if sys.argv and sys.argv[0]:
            candidates.append(os.path.abspath(sys.argv[0]))
    except Exception:
        pass

    for path in candidates:
        if not path:
            continue
        marker = ".app/Contents"
        idx = path.find(marker)
        if idx != -1:
            # Trim back to and including ".app" → the bundle root.
            return path[: idx + len(".app")]
    return None


def current_launch_command():
    """
    Return the argv list used to relaunch this app.

    - Packaged (.app bundle): ``["open", "-a", "<AppBundlePath>"]`` so macOS
      launches it the normal way.
    - Dev mode: ``[<python>, <abs path to main.py next to this file>]``.
    """
    try:
        if _IS_WIN:
            # Frozen (.exe): launch the executable directly. Dev: python main.py.
            if getattr(sys, "frozen", False):
                return [os.path.abspath(sys.executable)]
            here = os.path.dirname(os.path.abspath(__file__))
            return [os.path.abspath(sys.executable),
                    os.path.join(here, "main.py")]

        bundle = _app_bundle_path()
        if bundle:
            return ["open", "-a", bundle]

        # Dev mode: run main.py sitting alongside this module.
        here = os.path.dirname(os.path.abspath(__file__))
        main_py = os.path.join(here, "main.py")
        return [os.path.abspath(sys.executable), main_py]
    except Exception:
        # Last-resort fallback — should be reachable only on bizarre setups.
        return [sys.executable, "main.py"]


def is_enabled():
    """Return True if auto-launch is currently configured."""
    if _IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as k:
                winreg.QueryValueEx(k, _WIN_RUN_VALUE)
            return True
        except Exception:
            return False
    try:
        return os.path.isfile(PLIST_PATH)
    except Exception:
        return False


def _launchctl(*args):
    """Run ``launchctl <args>`` quietly; never raise."""
    try:
        subprocess.run(
            ["launchctl"] + list(args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        # launchctl missing / sandboxed — ignore, this is best-effort.
        pass


def enable(program_args=None):
    """
    Install the LaunchAgent plist (RunAtLoad=True) so the app starts at the next
    macOS login. ``program_args`` overrides the relaunch argv; defaults to
    :func:`current_launch_command`. Returns True on success, False on any error.

    IMPORTANT: we deliberately do NOT ``launchctl load -w`` here. Loading a
    RunAtLoad job launches it immediately — and since enabling auto-launch
    happens while the app is already running, that would spawn a DUPLICATE
    instance (and, when run head-less by launchd from a non-GUI context, can
    crash the second copy). Writing the plist is enough: launchd loads every
    agent in ~/Library/LaunchAgents automatically at the next login, which is
    exactly the desired "open on Mac startup" behavior.
    """
    try:
        if _IS_WIN:
            import winreg
            if program_args:
                cmd = " ".join('"%s"' % c for c in program_args)
            else:
                cmd = _win_run_command()
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as k:
                winreg.SetValueEx(k, _WIN_RUN_VALUE, 0, winreg.REG_SZ, cmd)
            return True

        args = program_args or current_launch_command()

        plist = {
            "Label": LABEL,
            "ProgramArguments": list(args),
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
        }

        os.makedirs(LAUNCH_AGENTS_DIR, exist_ok=True)
        with open(PLIST_PATH, "wb") as fh:
            plistlib.dump(plist, fh)
        # No launchctl load here — takes effect at next login (see docstring).
        return True
    except Exception:
        return False


def disable():
    """
    Unload the LaunchAgent and remove its plist file. Returns True on success
    (including the case where nothing was installed), False on any error.
    """
    try:
        if _IS_WIN:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, _WIN_RUN_VALUE)
            except FileNotFoundError:
                pass
            return True

        # Unload first so the job stops being scheduled (ignore errors).
        _launchctl("unload", "-w", PLIST_PATH)

        if os.path.isfile(PLIST_PATH):
            os.remove(PLIST_PATH)
        return True
    except Exception:
        return False
