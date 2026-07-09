"""
capture.py — screenshots via mss + Pillow, RETINA-AWARE ("10XLifeOS").

This module owns ALL retina/HiDPI handling for FC-FastCapture. Every other
module speaks in *logical screen points* (Qt global coordinates, top-left of the
primary display is the origin; secondary monitors may be negative). Here we grab
the underlying full-resolution (backing-store) pixels through `mss`, wrap them in
a PIL image, and remember the scale factor so the editor / clipboard can render
crisp images at the correct device-pixel-ratio.

Design rules honoured here:
  • NO Qt windows are created in this module.
  • Imports must succeed even before a QApplication exists — every Qt / mss /
    Pillow touch happens INSIDE a function, never at module import time.
  • NEVER crash: all Quartz / mss / Pillow / file IO is wrapped in try/except,
    degrading gracefully (e.g. a 1x1 black image) instead of raising.
  • mss is created fresh inside a `with` block per call, which is the
    thread-safe way to use it (each capture mode / recorder thread gets its own).

Target: Python 3.9+, PyQt6, macOS first.
"""
from __future__ import annotations

import io
import os

# Heavy / optional third-party deps are imported lazily inside functions so this
# module always imports cleanly even if a dependency is missing on disk.


# ─────────────────────────────────────────────────────────────────────────────
# Shot — the value object returned by every capture call
# ─────────────────────────────────────────────────────────────────────────────
class Shot:
    """A single captured frame.

    Attributes
    ----------
    image : PIL.Image.Image
        Full-resolution (retina) RGB image of the grabbed region.
    rect : tuple
        (x, y, w, h) — the *logical* global integers that were requested.
    scale : float
        image pixel width / requested logical width (>= 1.0). On a 2x retina
        display this is ~2.0; on a 1x display ~1.0.
    """

    __slots__ = ("image", "rect", "scale")

    def __init__(self, image, rect, scale):
        self.image = image
        # Normalise rect to a plain tuple of ints.
        try:
            x, y, w, h = rect
            self.rect = (int(x), int(y), int(w), int(h))
        except Exception:
            self.rect = (0, 0, 0, 0)
        try:
            self.scale = float(scale) if scale and scale >= 1.0 else 1.0
        except Exception:
            self.scale = 1.0

    def __repr__(self):
        return "Shot(rect=%r, scale=%.3f, image=%r)" % (
            self.rect, self.scale, self.image)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def _blank_image(w, h):
    """Return a small safe black RGB PIL image (used when capture fails)."""
    try:
        from PIL import Image
        return Image.new("RGB", (max(1, int(w)), max(1, int(h))), (0, 0, 0))
    except Exception:
        # Pillow itself unavailable — return None; callers tolerate this.
        return None


def _frame_to_pil(frame):
    """Convert an mss screenshot frame to a full-resolution RGB PIL image.

    mss returns BGRA pixels; the contract specifies building the PIL image via
    ``Image.frombytes("RGB", frame.size, frame.bgra, "raw", "BGRX")`` which both
    drops the alpha channel and swaps B/R for us in one fast C call.
    """
    from PIL import Image
    return Image.frombytes("RGB", frame.size, frame.bgra, "raw", "BGRX")


# ─────────────────────────────────────────────────────────────────────────────
# Capture
# ─────────────────────────────────────────────────────────────────────────────
def capture_region(x, y, w, h):
    """Grab a logical-point region of the screen → Shot (retina full-res).

    `x, y, w, h` are logical global points. On a retina display the returned
    frame is physically larger than requested; THAT larger frame IS the
    full-resolution image we want. scale = frame.width / requested logical width.
    """
    x, y, w, h = int(x), int(y), int(w), int(h)
    w = max(1, w)
    h = max(1, h)
    region = {"left": x, "top": y, "width": w, "height": h}

    try:
        import mss
        # Fresh mss per call inside a `with` block → thread-safe.
        with mss.mss() as sct:
            frame = sct.grab(region)
            img = _frame_to_pil(frame)
            # Physical pixel width / requested logical width (>= 1.0).
            scale = float(frame.width) / float(max(1, w))
            if scale < 1.0:
                scale = 1.0
            return Shot(img, (x, y, w, h), scale)
    except Exception:
        # mss missing / capture denied / region off-screen → never crash.
        return Shot(_blank_image(w, h), (x, y, w, h), 1.0)


def capture_window(window_id, logical_w=None, logical_h=None,
                   rect=None):
    """Capture ONE window by its CGWindowID (Mode 4).

    Uses Quartz `CGWindowListCreateImage`, which grabs the WINDOW'S OWN content
    regardless of where it sits (any monitor, even if partially occluded) — far
    more reliable than grabbing a screen region (which on multi-monitor setups
    could come back as just the desktop wallpaper). Falls back to a region grab
    if anything goes wrong.
    """
    # Windows: window_id is an HWND — use the Win32 PrintWindow backend.
    try:
        import platform_backend
        if platform_backend.IS_WIN:
            try:
                import winshot
                shot = winshot.capture_window(window_id, logical_w,
                                              logical_h, rect)
                if shot is not None:
                    return shot
            except Exception:
                pass
            # winshot unavailable / PrintWindow failed → signal failure so the
            # CALLER's fallback chain runs (frozen crop first — DPI-proof —
            # then a properly delayed, DPI-mapped live grab). An internal live
            # capture_region here would feed mss a LOGICAL rect (offset ~25%
            # on 125%-scaled Windows) and mask the caller's better fallbacks.
            return None
    except Exception:
        pass
    try:
        import Quartz
        from PIL import Image
        cg = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            int(window_id),
            Quartz.kCGWindowImageBoundsIgnoreFraming)
        if cg is None:
            raise ValueError("no window image")
        pw = int(Quartz.CGImageGetWidth(cg))
        ph = int(Quartz.CGImageGetHeight(cg))
        if pw < 1 or ph < 1:
            raise ValueError("empty window image")
        bpr = int(Quartz.CGImageGetBytesPerRow(cg))
        provider = Quartz.CGImageGetDataProvider(cg)
        data = Quartz.CGDataProviderCopyData(provider)
        buf = bytes(data)
        # CGImage is premultiplied BGRA; read with the real stride (bpr).
        img = Image.frombuffer("RGBA", (pw, ph), buf, "raw", "BGRA", bpr, 1)
        img = img.convert("RGB")
        lw = int(logical_w) if logical_w else pw
        lh = int(logical_h) if logical_h else ph
        scale = float(pw) / float(max(1, lw))
        if scale < 1.0:
            scale = 1.0
        rx, ry = (rect[0], rect[1]) if rect else (0, 0)
        return Shot(img, (rx, ry, lw, lh), scale)
    except Exception:
        # Quartz failed → return None; the caller owns the fallback chain
        # (frozen crop → delayed live grab), which avoids grabbing the live
        # screen zero milliseconds after the overlay closed.
        return None


def capture_full():
    """Capture the entire virtual desktop (union of all monitors)."""
    x, y, w, h = virtual_geometry()
    return capture_region(x, y, w, h)


def virtual_geometry():
    """Return (x, y, w, h) of the whole virtual desktop in logical points.

    Prefer mss's monitor[0] (its "all monitors" bounding box). Fall back to the
    union of QGuiApplication screen geometries, then to a sane default. Never
    raises.
    """
    # 1) mss virtual monitor (index 0 is the union of every physical monitor).
    try:
        import mss
        with mss.mss() as sct:
            mons = sct.monitors
            if mons:
                m = mons[0]
                w = int(m.get("width", 0))
                h = int(m.get("height", 0))
                if w > 0 and h > 0:
                    return (int(m.get("left", 0)), int(m.get("top", 0)), w, h)
    except Exception:
        pass

    # 2) Qt union of all screen geometries (logical points).
    try:
        from PyQt6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        if screens:
            union = None
            for s in screens:
                g = s.geometry()
                union = g if union is None else union.united(g)
            if union is not None and union.width() > 0 and union.height() > 0:
                return (int(union.x()), int(union.y()),
                        int(union.width()), int(union.height()))
    except Exception:
        pass

    # 3) Last-resort default.
    return (0, 0, 1440, 900)


def primary_scale():
    """Backing scale (device pixel ratio) of the primary display, >= 1.0.

    Tries Qt's primaryScreen().devicePixelRatio(); falls back to 1.0.
    """
    try:
        from PyQt6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            dpr = float(scr.devicePixelRatio())
            if dpr >= 1.0:
                return dpr
    except Exception:
        pass
    return 1.0


# ─────────────────────────────────────────────────────────────────────────────
# PIL ↔ Qt conversions
# ─────────────────────────────────────────────────────────────────────────────
def pil_to_qimage(pil_img):
    """Convert a PIL image to a QtGui.QImage (RGBA8888, owns its own buffer).

    Returns a 1x1 transparent QImage on any failure rather than raising.
    """
    from PyQt6 import QtGui
    try:
        img = pil_img.convert("RGBA")
        w, h = img.size
        data = img.tobytes("raw", "RGBA")
        qimg = QtGui.QImage(
            data, w, h, w * 4, QtGui.QImage.Format.Format_RGBA8888)
        # The bytes buffer is owned by Python; copy() detaches QImage from it so
        # the pixels stay valid after `data` is garbage-collected.
        return qimg.copy()
    except Exception:
        return QtGui.QImage(1, 1, QtGui.QImage.Format.Format_RGBA8888)


def pil_to_qpixmap(pil_img, dpr=1.0):
    """Convert a PIL image to a QPixmap and tag it with a device pixel ratio.

    `dpr` is the retina scale (typically Shot.scale). Setting the pixmap's
    device pixel ratio makes Qt draw the full-res pixels at the correct LOGICAL
    size, so a 2400px-wide retina grab displays as 1200 logical points crisply.
    """
    from PyQt6 import QtGui
    try:
        qimg = pil_to_qimage(pil_img)
        pm = QtGui.QPixmap.fromImage(qimg)
        try:
            d = float(dpr) if dpr and dpr >= 1.0 else 1.0
        except Exception:
            d = 1.0
        pm.setDevicePixelRatio(d)  # REQUIRED by contract.
        return pm
    except Exception:
        pm = QtGui.QPixmap(1, 1)
        try:
            pm.setDevicePixelRatio(1.0)
        except Exception:
            pass
        return pm


# ─────────────────────────────────────────────────────────────────────────────
# Clipboard
# ─────────────────────────────────────────────────────────────────────────────
def copy_qimage_to_clipboard(qimage):
    """Place a QImage on the system clipboard. Never raises."""
    try:
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setImage(qimage)
    except Exception:
        pass


def copy_pil_to_clipboard(pil_img):
    """Place a PIL image on the system clipboard (via QImage). Never raises."""
    try:
        copy_qimage_to_clipboard(pil_to_qimage(pil_img))
    except Exception:
        pass


def copy_gif_to_clipboard(path):
    """Put an animated GIF file on the clipboard. Returns True on success.

    Builds a QMimeData carrying BOTH:
      • a file:// QUrl list (so Finder / file-aware apps can paste the file), and
      • the raw 'image/gif' bytes (so apps that accept animated image data get
        the animation).
    Many macOS apps will only accept the first (static) frame of a pasted GIF,
    so callers should also offer a "save file" path — but we provide the richest
    payload we can.
    """
    try:
        if not path or not os.path.exists(path):
            return False
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtWidgets import QApplication

        mime = QMimeData()
        # 1) file URL list
        try:
            mime.setUrls([QUrl.fromLocalFile(os.path.abspath(path))])
        except Exception:
            pass
        # 2) raw image/gif bytes
        try:
            with open(path, "rb") as f:
                blob = f.read()
            mime.setData("image/gif", blob)
        except Exception:
            pass

        cb = QApplication.clipboard()
        if cb is None:
            return False
        cb.setMimeData(mime)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Saving
# ─────────────────────────────────────────────────────────────────────────────
def save_pil(pil_img, path):
    """Save a PIL image as PNG to `path`; return the path (or "" on failure)."""
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        img = pil_img
        # PNG keeps an alpha channel; ensure a sane mode for both RGB & RGBA.
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(path, "PNG")
        return path
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# FREEZE-FIRST capture (v1.1) — the screen is snapshotted the INSTANT the
# hotkey fires; the user then selects a region ON the frozen image and we CROP
# from it. Two wins:
#   1. Timing — fleeting moments (a face in a Zoom call) can't be missed while
#      dragging a selection: the pixels are already frozen.
#   2. Correctness — cropping happens in per-screen LOCAL coordinates with an
#      explicit per-screen scale, which sidesteps the Windows DPI bug where a
#      LOGICAL global rect was fed to mss (which speaks PHYSICAL pixels on
#      Windows → the captured region was offset/scaled versus the selection).
# Every function degrades gracefully: callers fall back to the legacy live
# capture path when anything here returns None/{}.
# ─────────────────────────────────────────────────────────────────────────────
def qimage_to_pil(qimg):
    """QImage → PIL RGB image (stride-safe). Returns None on failure."""
    try:
        from PyQt6 import QtGui
        from PIL import Image
        img = qimg.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        w, h = img.width(), img.height()
        if w < 1 or h < 1:
            return None
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        return Image.frombuffer("RGBA", (w, h), bytes(ptr), "raw", "RGBA",
                                img.bytesPerLine(), 1).convert("RGB")
    except Exception:
        return None


def freeze_screens():
    """Snapshot EVERY screen right now → list of per-screen frozen entries.

    Each entry is a dict:
        {"screen": QScreen, "pixmap": QPixmap (physical px, DPR set),
         "geo": QRect (logical global), "scale": float (physical/logical)}
    The pixmap's devicePixelRatio is set so drawing it at (0,0) in a widget
    that covers the screen paints it at exactly logical size (crisp on retina).
    Returns [] if nothing could be captured (caller falls back to live grabs).
    """
    frozen = []
    # macOS: without Screen Recording permission, grabWindow silently returns
    # wallpaper-only pixmaps (NOT null) — the freeze would "work" but show an
    # empty desktop. Bail to the live path, where the permission flow guides.
    try:
        import platform_backend
        if platform_backend.IS_MAC:
            screen_ok, _ = platform_backend.check_permissions()
            if not screen_ok:
                return []
    except Exception:
        pass
    try:
        from PyQt6 import QtGui
        screens = list(QtGui.QGuiApplication.screens())
    except Exception:
        return []
    for sc in screens:
        try:
            geo = sc.geometry()  # logical global
            if geo.width() < 1 or geo.height() < 1:
                continue
            pm = sc.grabWindow(0)  # this screen's content, physical pixels
            if pm is None or pm.isNull() or pm.width() < 1:
                continue
            scale = float(pm.width()) / float(geo.width())
            if scale < 1.0:
                scale = 1.0
            try:
                pm.setDevicePixelRatio(scale)
            except Exception:
                pass
            frozen.append({"screen": sc, "pixmap": pm, "geo": geo,
                           "scale": scale})
        except Exception:
            continue
    return frozen


def crop_from_frozen(frozen, qrect):
    """Crop a GLOBAL logical QRect out of the frozen snapshot → Shot or None.

    Finds the frozen screen containing the selection (selections are per-screen
    — each overlay clamps to its own display), converts to screen-LOCAL logical
    coords, scales by that screen's ratio and crops PHYSICAL pixels. No global
    coordinate system ever touches the OS capture APIs → DPI-proof.
    """
    try:
        if not frozen or qrect is None or qrect.width() < 1:
            return None
        cx, cy = qrect.center().x(), qrect.center().y()
        entry = None
        for f in frozen:
            if f["geo"].contains(cx, cy):
                entry = f
                break
        if entry is None:  # center off every screen → best overlap
            best, area = None, -1
            for f in frozen:
                inter = f["geo"].intersected(qrect)
                a = max(0, inter.width()) * max(0, inter.height())
                if a > area:
                    best, area = f, a
            entry = best
        if entry is None:
            return None
        geo, pm, scale = entry["geo"], entry["pixmap"], entry["scale"]
        clamped = qrect.intersected(geo)
        if clamped.width() < 1 or clamped.height() < 1:
            return None
        lx = clamped.x() - geo.x()
        ly = clamped.y() - geo.y()
        px = int(round(lx * scale))
        py = int(round(ly * scale))
        pw = int(round(clamped.width() * scale))
        ph = int(round(clamped.height() * scale))
        # Clamp to the pixmap's physical bounds.
        px = max(0, min(px, pm.width() - 1))
        py = max(0, min(py, pm.height() - 1))
        pw = max(1, min(pw, pm.width() - px))
        ph = max(1, min(ph, pm.height() - py))
        from PyQt6.QtCore import QRect as _QRect
        sub = pm.copy(_QRect(px, py, pw, ph))
        img = qimage_to_pil(sub.toImage())
        if img is None:
            return None
        return Shot(img, (clamped.x(), clamped.y(),
                          clamped.width(), clamped.height()), scale)
    except Exception:
        return None


def capture_region_dpi(x, y, w, h):
    """capture_region with the Windows DPI mapping applied.

    Takes a LOGICAL global rect, grabs the matching PHYSICAL pixels, and
    returns a Shot whose .rect stays LOGICAL with .scale carrying the DPR —
    exactly what the editor expects. On macOS this is capture_region verbatim.
    Used by the LIVE fallback paths (freeze failed / frozen crop failed).
    """
    try:
        px, py, pw, ph, dpr = logical_rect_to_physical(x, y, w, h)
    except Exception:
        px, py, pw, ph, dpr = x, y, w, h, 1.0
    shot = capture_region(px, py, pw, ph)
    if dpr and dpr > 1.0:
        try:
            return Shot(shot.image, (int(x), int(y), int(w), int(h)),
                        max(shot.scale, float(dpr)))
        except Exception:
            pass
    return shot


def map_logical_to_physical(rect, screens, monitors):
    """PURE core of the DPI mapping — no Qt, no mss, no OS calls, so it is unit-
    testable on any platform (see test_dpi.py). Reproduces the Asus-Vivobook
    class of bug deterministically.

        rect     : (x, y, w, h) LOGICAL global rect.
        screens  : list of {"x","y","w","h","dpr"} — Qt screens (logical geo+DPR).
                   Put the center/primary screen FIRST (parity with Qt.screenAt).
        monitors : list of {"left","top","width","height"} — mss PHYSICAL monitors
                   (already EXCLUDING mss.monitors[0], the union box).

    Returns (px, py, pw, ph, scale) in PHYSICAL pixels, or None when matching is
    ambiguous (caller then falls back to identity). Uses object identity in
    `screens` for the multi-identical-monitor tiebreak.
    """
    rx, ry, rw, rh = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    cx, cy = rx + rw / 2.0, ry + rh / 2.0
    sc = None
    for s in screens:
        if s["x"] <= cx < s["x"] + s["w"] and s["y"] <= cy < s["y"] + s["h"]:
            sc = s
            break
    if sc is None:
        sc = screens[0] if screens else None
    if sc is None:
        return None
    dpr = float(sc.get("dpr") or 1.0)
    pw = int(round(sc["w"] * dpr))
    ph = int(round(sc["h"] * dpr))
    matches = [m for m in monitors
               if abs(m["width"] - pw) <= 2 and abs(m["height"] - ph) <= 2]
    if len(matches) == 1:
        mon = matches[0]
    elif len(monitors) == 1:
        # Single monitor (the Vivobook case) — trivially unambiguous.
        mon = monitors[0]
    elif len(matches) > 1:
        # Two+ identical monitors: same physical size ⇒ same DPR ⇒ matching Qt
        # screens share logical size too. Left-to-right / top-to-bottom ORDER is
        # preserved between Qt screens and mss monitors, so rank our screen among
        # its same-size Qt siblings and pick the same rank among the mss ones.
        qt_same = [s for s in screens
                   if abs(int(round(s["w"] * float(s.get("dpr") or 1))) - pw) <= 2
                   and abs(int(round(s["h"] * float(s.get("dpr") or 1))) - ph) <= 2]
        qt_same.sort(key=lambda s: (s["x"], s["y"]))
        matches.sort(key=lambda m: (m["left"], m["top"]))
        idx = next((i for i, s in enumerate(qt_same) if s is sc), None)
        if idx is None or idx >= len(matches):
            return None
        mon = matches[idx]
    else:
        return None
    lx = rx - sc["x"]
    ly = ry - sc["y"]
    return (int(mon["left"] + round(lx * dpr)),
            int(mon["top"] + round(ly * dpr)),
            max(1, int(round(rw * dpr))),
            max(1, int(round(rh * dpr))),
            dpr)


def logical_rect_to_physical(x, y, w, h):
    """Map a LOGICAL global rect to the PHYSICAL-pixel rect mss expects.

    macOS: identity — mss speaks logical points there (current behaviour).
    Windows: Qt speaks logical (scaled) coordinates while mss speaks physical
    pixels, so a 125%-scaled laptop (the Asus Vivobook case) offsets every grab
    by 25%. The real Qt/mss data is GATHERED here; the math lives in the pure,
    unit-tested map_logical_to_physical(). Falls back to identity (scale 1.0) on
    any error or ambiguity. Returns (x, y, w, h, scale).
    """
    try:
        import platform_backend
        if not platform_backend.IS_WIN:
            return (int(x), int(y), int(w), int(h), 1.0)
    except Exception:
        return (int(x), int(y), int(w), int(h), 1.0)
    try:
        from PyQt6 import QtGui
        from PyQt6.QtCore import QRect as _QRect
        import mss
        # ONE dict per Qt screen (identity matters for the tiebreak).
        by_screen = {}
        for s in QtGui.QGuiApplication.screens():
            g = s.geometry()
            by_screen[s] = {"x": g.x(), "y": g.y(), "w": g.width(),
                            "h": g.height(),
                            "dpr": float(s.devicePixelRatio() or 1.0)}
        rc = QtGui.QGuiApplication.screenAt(
            _QRect(int(x), int(y), int(w), int(h)).center()) \
            or QtGui.QGuiApplication.primaryScreen()
        sel = by_screen.get(rc)
        # Center/primary screen first → parity with Qt.screenAt semantics.
        screens = ([sel] if sel is not None else []) + \
                  [d for s, d in by_screen.items() if d is not sel]
        with mss.mss() as sct:
            mons = [dict(m) for m in sct.monitors[1:]]  # [0] is the union
        res = map_logical_to_physical((x, y, w, h), screens, mons)
        if res is None:
            return (int(x), int(y), int(w), int(h), 1.0)
        return res
    except Exception:
        return (int(x), int(y), int(w), int(h), 1.0)
