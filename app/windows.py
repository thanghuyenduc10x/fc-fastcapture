"""
windows.py — macOS on-screen window detection via Quartz (CoreGraphics).

Enumerates the currently visible application windows so Mode 4 ("Chụp cửa sổ")
can offer them as click-to-capture targets. Everything is reported in **logical
screen points, GLOBAL** (top-left origin of the primary display; secondary
monitors may be negative) — exactly what Quartz's CGWindowBounds already gives
us and what the rest of the app (Qt global coords, overlay, capture) expects.

This module has NO Qt dependency and constructs no objects at import time, so it
imports cleanly even with no QApplication / no display. Every Quartz call is
wrapped so a missing framework or a permission failure degrades to an empty list
rather than crashing the app.

Target: Python 3.9+, macOS (Apple Silicon).
"""
from __future__ import annotations

# Our own app's owner names — windows belonging to these are skipped so the
# floating bar / toolbars / dev terminal never appear as capture targets.
_SELF_OWNERS = ("FC-FastCapture", "Python")

# Minimum logical size (points) for a window to be considered real / pickable.
_MIN_W = 40
_MIN_H = 40


def list_windows():
    """Return on-screen windows, front-most first (front-to-back z-order).

    Each item is a dict:
        {"id": int, "title": str, "owner": str,
         "x": int, "y": int, "w": int, "h": int}
    Coordinates are logical global points.

    Filtering rules:
        • only normal windows (kCGWindowLayer == 0)
        • only on-screen, non-desktop elements (via the list options below)
        • width > 40 and height > 40
        • windows owned by our own app ("FC-FastCapture", "Python") are skipped

    Never raises: returns [] if Quartz is unavailable or anything goes wrong.
    """
    # Windows: enumerate via the Win32 backend (returns the same dict shape,
    # with `id` = HWND). Falls through to [] if that backend is unavailable.
    try:
        import platform_backend
        if platform_backend.IS_WIN:
            try:
                import winshot
                return winshot.list_windows()
            except Exception:
                return []
    except Exception:
        pass
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
            kCGWindowLayer,
            kCGWindowBounds,
            kCGWindowOwnerName,
            kCGWindowName,
            kCGWindowNumber,
        )
    except Exception:
        # Quartz / pyobjc not installed or import failed — degrade gracefully.
        return []

    try:
        options = (kCGWindowListOptionOnScreenOnly
                   | kCGWindowListExcludeDesktopElements)
        info_list = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
    except Exception:
        return []

    if not info_list:
        return []

    results = []
    # The list comes back already in front-to-back z-order; preserve it.
    for info in info_list:
        try:
            # Keep only layer-0 (normal application) windows.
            layer = info.get(kCGWindowLayer, None)
            if layer is None or int(layer) != 0:
                continue

            owner = info.get(kCGWindowOwnerName, None)
            owner = str(owner) if owner is not None else ""
            # Skip our own UI / interpreter windows.
            if owner in _SELF_OWNERS:
                continue

            bounds = info.get(kCGWindowBounds, None)
            if not bounds:
                continue
            # kCGWindowBounds is a CFDictionary {X, Y, Width, Height} in points.
            x = int(round(float(bounds.get("X", 0))))
            y = int(round(float(bounds.get("Y", 0))))
            w = int(round(float(bounds.get("Width", 0))))
            h = int(round(float(bounds.get("Height", 0))))

            # Reject tiny / degenerate windows (menus, shadows, helpers).
            if w <= _MIN_W or h <= _MIN_H:
                continue

            # kCGWindowName may be missing (no Screen Recording permission, or
            # the window simply has no title) — fall back to an empty string.
            title = info.get(kCGWindowName, None)
            title = str(title) if title is not None else ""

            wid = info.get(kCGWindowNumber, 0)
            try:
                wid = int(wid)
            except Exception:
                wid = 0

            results.append({
                "id": wid,
                "title": title,
                "owner": owner,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
            })
        except Exception:
            # One malformed entry must never abort the whole enumeration.
            continue

    return results
