"""
winshot.py — Windows window enumeration + single-window capture (Win32).

The Windows backend for Mode 4 ("capture one window"), mirroring the macOS
Quartz code in windows.py / capture.py:

  • list_windows()          → same dict shape as windows.py:
                              {id, title, owner, x, y, w, h}
                              where `id` is the HWND (int) and x/y/w/h are in
                              LOGICAL points (physical pixels ÷ per-window DPI),
                              front-to-back z-order, tiny/tool/cloaked windows
                              filtered out.
  • capture_window(hwnd, …) → a capture.Shot via PrintWindow into a top-down
                              32-bit DIB. PW_RENDERFULLCONTENT captures modern
                              GPU-composited windows (Chrome/Edge/Electron).

Pure ctypes (user32/gdi32/dwmapi) — no pywin32. Never raises; callers fall back
to a plain region grab. On non-Windows the module still imports (windll is
absent → the backend simply reports "unavailable").

KNOWN RISK (needs testing on real Windows): multi-monitor + fractional DPI
coordinate reconciliation, and windows that refuse PrintWindow (return black) —
both degrade to the region-grab fallback in capture.py rather than crashing.

Target: Python 3.9+, Windows.
"""
from __future__ import annotations

import ctypes

# ── Win32 handles (absent on non-Windows → backend disabled) ─────────────────
_OK = False
try:
    from ctypes import wintypes
    _user32 = ctypes.windll.user32          # type: ignore[attr-defined]
    _gdi32 = ctypes.windll.gdi32            # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32      # type: ignore[attr-defined]
    try:
        _dwmapi = ctypes.windll.dwmapi      # type: ignore[attr-defined]
    except Exception:
        _dwmapi = None
    _OK = True
except Exception:
    _OK = False


def available():
    """True if the Win32 backend can be used on this platform."""
    return bool(_OK)


# ── constants ────────────────────────────────────────────────────────────────
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_GW_OWNER = 4
_DWMWA_CLOAKED = 14
_PW_RENDERFULLCONTENT = 0x00000002
_DIB_RGB_COLORS = 0
_MIN_W = 40
_MIN_H = 40


def _win_long(hwnd, idx):
    try:
        # GetWindowLongPtrW on 64-bit; GetWindowLongW is fine for GWL_EXSTYLE.
        fn = getattr(_user32, "GetWindowLongPtrW", None) or _user32.GetWindowLongW
        fn.restype = ctypes.c_ssize_t
        return int(fn(wintypes.HWND(hwnd), idx))
    except Exception:
        return 0


def _dpi_scale(hwnd):
    """Per-window DPI scale (1.0 = 96 dpi). Falls back to 1.0."""
    try:
        getdpi = getattr(_user32, "GetDpiForWindow", None)
        if getdpi is not None:
            getdpi.restype = ctypes.c_uint
            dpi = int(getdpi(wintypes.HWND(hwnd)))
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _is_cloaked(hwnd):
    if _dwmapi is None:
        return False
    try:
        val = ctypes.c_int(0)
        res = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), _DWMWA_CLOAKED,
            ctypes.byref(val), ctypes.sizeof(val))
        return res == 0 and val.value != 0
    except Exception:
        return False


def _owner_name(hwnd):
    """Process image basename that owns hwnd, and its PID."""
    try:
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        pid_val = int(pid.value)
        if pid_val == 0:
            return "", 0
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  pid_val)
        if not h:
            return "", pid_val
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            ok = _kernel32.QueryFullProcessImageNameW(
                h, 0, buf, ctypes.byref(size))
            if ok:
                import os as _os
                return _os.path.basename(buf.value), pid_val
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        pass
    return "", 0


def list_windows():
    """Return on-screen top-level application windows, front-to-back z-order.

    Same contract as windows.list_windows(): a list of dicts
    {id(HWND), title, owner, x, y, w, h} with x/y/w/h in logical points. Returns
    [] on any failure so Mode 4 simply offers no targets instead of crashing.
    """
    if not _OK:
        return []
    try:
        self_pid = int(_kernel32.GetCurrentProcessId())
    except Exception:
        self_pid = -1

    results = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            # Skip windows owned by another window (dialogs/tool palettes).
            if _user32.GetWindow(hwnd, _GW_OWNER):
                return True
            ex = _win_long(hwnd, _GWL_EXSTYLE)
            if ex & _WS_EX_TOOLWINDOW and not (ex & _WS_EX_APPWINDOW):
                return True
            if _is_cloaked(hwnd):
                return True

            # Title (Windows needs no permission for this, unlike macOS).
            n = int(_user32.GetWindowTextLengthW(hwnd))
            title = ""
            if n > 0:
                tbuf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, tbuf, n + 1)
                title = tbuf.value or ""

            rect = wintypes.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            pw = rect.right - rect.left
            ph = rect.bottom - rect.top
            if pw <= 0 or ph <= 0:
                return True

            owner, pid = _owner_name(hwnd)
            if pid == self_pid:
                return True  # never list our own windows

            scale = _dpi_scale(hwnd)
            lx = int(round(rect.left / scale))
            ly = int(round(rect.top / scale))
            lw = int(round(pw / scale))
            lh = int(round(ph / scale))
            if lw <= _MIN_W or lh <= _MIN_H:
                return True

            # Windows with no title and not app-flagged are usually chrome —
            # keep titled windows and explicit app windows only.
            if not title and not (ex & _WS_EX_APPWINDOW):
                return True

            results.append({
                "id": int(hwnd),
                "title": title,
                "owner": owner,
                "x": lx,
                "y": ly,
                "w": lw,
                "h": lh,
            })
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        return []
    return results


# ── single-window capture via PrintWindow ────────────────────────────────────
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def capture_window(hwnd, logical_w=None, logical_h=None, rect=None):
    """Capture ONE window by HWND → a capture.Shot, or None on failure.

    Renders the window's OWN pixels (even if occluded) via PrintWindow with
    PW_RENDERFULLCONTENT. Returns None so capture.py can fall back to a region
    grab if PrintWindow is unavailable / returns an empty image.
    """
    if not _OK:
        return None
    hwnd = int(hwnd)
    hdc_win = hdc_mem = hbmp = None
    try:
        from PIL import Image
        r = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        pw = r.right - r.left
        ph = r.bottom - r.top
        if pw < 1 or ph < 1:
            return None

        hdc_win = _user32.GetWindowDC(hwnd)
        if not hdc_win:
            return None
        hdc_mem = _gdi32.CreateCompatibleDC(hdc_win)
        hbmp = _gdi32.CreateCompatibleBitmap(hdc_win, pw, ph)
        if not hdc_mem or not hbmp:
            return None
        old = _gdi32.SelectObject(hdc_mem, hbmp)

        ok = _user32.PrintWindow(hwnd, hdc_mem, _PW_RENDERFULLCONTENT)
        if not ok:
            # Older path: full-window print without the "full content" flag.
            _user32.PrintWindow(hwnd, hdc_mem, 0)

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = pw
        bmi.biHeight = -ph          # negative → top-down rows
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0        # BI_RGB

        buf = ctypes.create_string_buffer(pw * ph * 4)
        got = _gdi32.GetDIBits(hdc_mem, hbmp, 0, ph, buf,
                               ctypes.byref(bmi), _DIB_RGB_COLORS)
        _gdi32.SelectObject(hdc_mem, old)
        if not got:
            return None

        img = Image.frombuffer("RGBA", (pw, ph), buf.raw,
                               "raw", "BGRA", 0, 1).convert("RGB")
        # Detect an all-black PrintWindow failure (some protected windows) so the
        # caller can fall back to a live region grab of the same rect.
        try:
            extrema = img.convert("L").getextrema()
            if extrema == (0, 0):
                return None
        except Exception:
            pass

        lw = int(logical_w) if logical_w else pw
        lh = int(logical_h) if logical_h else ph
        scale = float(pw) / float(max(1, lw))
        if scale < 1.0:
            scale = 1.0
        rx, ry = (rect[0], rect[1]) if rect else (0, 0)

        import capture
        return capture.Shot(img, (rx, ry, lw, lh), scale)
    except Exception:
        return None
    finally:
        try:
            if hbmp:
                _gdi32.DeleteObject(hbmp)
            if hdc_mem:
                _gdi32.DeleteDC(hdc_mem)
            if hdc_win:
                _user32.ReleaseDC(hwnd, hdc_win)
        except Exception:
            pass
