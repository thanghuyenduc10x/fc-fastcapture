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
            # winshot unavailable / PrintWindow failed → live region grab.
            if rect:
                return capture_region(rect[0], rect[1], rect[2], rect[3])
            return Shot(_blank_image(logical_w or 100, logical_h or 100),
                        (0, 0, logical_w or 100, logical_h or 100), 1.0)
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
        # Fall back to a plain region grab of the window's rect.
        if rect:
            return capture_region(rect[0], rect[1], rect[2], rect[3])
        return Shot(_blank_image(logical_w or 100, logical_h or 100),
                    (0, 0, logical_w or 100, logical_h or 100), 1.0)


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
