"""
recorder.py — Mode 5: screen record → optimized GIF ("10XLifeOS").

Three pieces wired together by main.py:

  • GifRecorder      — grabs a screen region into PIL frames on a BACKGROUND
                       thread (a fresh ``mss.mss()`` lives inside the worker so
                       there are no cross-thread mss issues), then exports an
                       optimized, size-capped animated GIF via imageio.
  • StopButton       — a small frameless brand panel with a red "● Dừng" button
                       and a live elapsed-seconds counter. It is positioned just
                       OUTSIDE the capture rect so it is never recorded.
  • GifResultWindow  — a brand window that previews the finished GIF with QMovie
                       and offers [Copy GIF] / [Lưu file].

Design rules followed (see CONTRACT.md):
  • Python 3.9 compatible — ``from __future__ import annotations`` at the top,
    no match-statements, no runtime ``X | Y`` unions.
  • All brand colors/fonts/QSS come from ``theme`` — nothing hardcoded.
  • Imports cleanly with NO QApplication and NO display: every Qt object is
    built inside a method, never at module import time.
  • Never crashes — Quartz/mss/imageio/numpy/file IO are all wrapped.
  • The capture thread NEVER touches Qt widgets (it only appends to a list).
"""
from __future__ import annotations

import os
import threading
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer

import theme
import platform_backend

_LOG_FILE = platform_backend.log_path()


def log(msg):
    """Append a diagnostic line to the shared logfile (and print in dev)."""
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass

# Frame / size caps keep the GIF small and memory bounded.
_MAX_FRAMES = 600          # hard cap on captured frames (~40s @ 15fps)
_MAX_LONG_SIDE = 1000      # downscale frames whose longest side exceeds this


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers (geometry normalisation + screen clamping)
# ─────────────────────────────────────────────────────────────────────────────
def _rect_tuple(rect):
    """Accept a QRect OR an (x, y, w, h) tuple → return (x, y, w, h) ints."""
    if isinstance(rect, QRect):
        return rect.x(), rect.y(), rect.width(), rect.height()
    try:
        x, y, w, h = rect
        return int(x), int(y), int(w), int(h)
    except Exception:
        return 0, 0, 0, 0


# ─────────────────────────────────────────────────────────────────────────────
# GifRecorder — background frame grabber + GIF exporter
# ─────────────────────────────────────────────────────────────────────────────
class GifRecorder(QtCore.QObject):
    """Capture a logical-point screen region into PIL RGB frames, then export.

    The grab loop runs on a plain ``threading.Thread`` (NOT a QThread) so it can
    own a fresh ``mss.mss()`` instance — mss screenshot objects are not safe to
    share across threads. The worker only appends to ``self._frames``; it never
    touches Qt. ``stop()`` flips a flag and joins the thread.
    """

    def __init__(self, x, y, w, h, fps=15, parent=None):
        super().__init__(parent)
        self.x = int(x)
        self.y = int(y)
        self.w = max(1, int(w))
        self.h = max(1, int(h))
        # Clamp fps to a sane GIF range (<=15fps keeps files small).
        try:
            self.fps = max(1, min(15, int(fps)))
        except Exception:
            self.fps = 15

        self._frames = []                 # list[PIL.Image.Image] (RGB)
        self._frames_lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread = None               # type: ignore[assignment]

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        """Begin capturing frames on a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, name="GifRecorderWorker", daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the worker to stop and wait for it to finish."""
        self._stop_evt.set()
        t = self._thread
        if t is not None and t.is_alive():
            try:
                t.join(timeout=3.0)
            except Exception:
                pass
            if t.is_alive():
                # Worker didn't terminate in time — don't pretend it stopped.
                log("⚠ recorder thread chưa dừng kịp (vẫn còn chạy nền)")
        self._thread = None

    def capped(self):
        """True once the frame cap was hit (recording effectively stopped)."""
        return self.frame_count() >= _MAX_FRAMES

    def frame_count(self):
        """Number of frames captured so far (thread-safe)."""
        with self._frames_lock:
            return len(self._frames)

    # ── worker thread ────────────────────────────────────────────────────
    def _run(self):
        """Grab the region at ~1/fps into PIL RGB frames. Never touches Qt."""
        # Import inside the thread and guard — mss/Pillow may be missing.
        try:
            import mss  # type: ignore
        except Exception:
            return
        try:
            from PIL import Image  # type: ignore
        except Exception:
            return

        region = {"left": self.x, "top": self.y,
                  "width": self.w, "height": self.h}
        interval = 1.0 / float(self.fps)

        # A FRESH mss.mss() owned entirely by this thread.
        try:
            sct = mss.mss()
        except Exception:
            return

        try:
            while not self._stop_evt.is_set():
                tick = time.time()
                try:
                    raw = sct.grab(region)
                    # Build a PIL RGB frame from the BGRA buffer.
                    frame = Image.frombytes(
                        "RGB", raw.size, raw.bgra, "raw", "BGRX")
                except Exception:
                    # Skip a bad frame but keep recording.
                    frame = None

                if frame is not None:
                    with self._frames_lock:
                        if len(self._frames) >= _MAX_FRAMES:
                            break  # memory cap reached → stop on its own
                        self._frames.append(frame)

                # Sleep the remainder of the frame interval (in small slices so
                # stop() is responsive), accounting for grab time.
                remaining = interval - (time.time() - tick)
                while remaining > 0 and not self._stop_evt.is_set():
                    nap = min(0.05, remaining)
                    time.sleep(nap)
                    remaining -= nap
        finally:
            try:
                sct.close()
            except Exception:
                pass

    # ── export ───────────────────────────────────────────────────────────
    def export_gif(self, path):
        """Write an optimized GIF to ``path``; return path (or '' if no frames).

        Frames are converted to numpy arrays, large frames are downscaled so the
        longest side is <= ~1000px, then written with imageio (v3 first, then a
        mimsave fallback). Everything is guarded so this never raises.
        """
        # Snapshot the frame list so a late worker append can't race us.
        with self._frames_lock:
            frames = list(self._frames)
        if not frames:
            return ""

        # Ensure the destination directory exists.
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
        except OSError:
            pass

        # Downscale factor (first frame, applied uniformly) — computed up front so
        # BOTH the imageio path and the Pillow fallback below can use it.
        scale = self._downscale_factor(frames[0])

        # ── Preferred path: imageio (needs numpy). BEST-EFFORT: if numpy/imageio
        #    are missing or fail, fall THROUGH to the Pillow writer below instead
        #    of returning "" — that early give-up was the "no GIF file" bug in the
        #    packaged .app (imageio's GIF plugin wasn't always bundled). ──
        try:
            import numpy as np  # type: ignore
            import imageio  # type: ignore
            arrays = []
            for pil_frame in frames:
                arr = self._frame_to_array(pil_frame, scale, np)
                if arr is not None:
                    arrays.append(arr)
            if arrays:
                duration_ms = 1000.0 / float(self.fps)
                try:
                    import imageio.v3 as iio  # type: ignore
                    iio.imwrite(path, arrays, duration=duration_ms, loop=0)
                    if os.path.exists(path):
                        return path
                except Exception:
                    pass
                try:
                    imageio.mimsave(path, arrays,
                                    duration=1.0 / float(self.fps), loop=0)
                    if os.path.exists(path):
                        return path
                except Exception:
                    pass
                try:
                    imageio.mimsave(path, arrays, duration=1.0 / float(self.fps))
                    if os.path.exists(path):
                        return path
                except Exception:
                    pass
        except Exception:
            pass

        # Bulletproof fallback: write the GIF with Pillow DIRECTLY — no imageio /
        # numpy needed. Survives a PyInstaller bundle that's missing imageio's GIF
        # plugin (the likely cause of "no GIF file" in the packaged .app).
        try:
            from PIL import Image  # type: ignore
            pil_frames = []
            for f in frames:
                im = f
                if scale < 1.0:
                    try:
                        im = im.resize(
                            (max(1, int(im.size[0] * scale)),
                             max(1, int(im.size[1] * scale))), Image.LANCZOS)
                    except Exception:
                        im = f
                if im.mode != "RGB":
                    try:
                        im = im.convert("RGB")
                    except Exception:
                        pass
                pil_frames.append(im)
            if pil_frames:
                pil_frames[0].save(
                    path, save_all=True, append_images=pil_frames[1:],
                    format="GIF", duration=int(1000.0 / float(self.fps)),
                    loop=0, optimize=True, disposal=2)
                if os.path.exists(path):
                    return path
        except Exception as e:
            log("✕ PIL GIF fallback lỗi: %s" % e)

        return ""

    def _downscale_factor(self, pil_frame):
        """Return a scale factor <=1.0 capping the longest side at _MAX_LONG_SIDE."""
        try:
            w, h = pil_frame.size
        except Exception:
            return 1.0
        longest = max(w, h)
        if longest > _MAX_LONG_SIDE:
            return float(_MAX_LONG_SIDE) / float(longest)
        return 1.0

    def _frame_to_array(self, pil_frame, scale, np):
        """Convert a PIL frame (optionally downscaled) to an RGB numpy array."""
        try:
            img = pil_frame
            if scale < 1.0:
                try:
                    from PIL import Image  # type: ignore
                    new_w = max(1, int(img.size[0] * scale))
                    new_h = max(1, int(img.size[1] * scale))
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                except Exception:
                    img = pil_frame  # if resize fails, keep original
            if img.mode != "RGB":
                img = img.convert("RGB")
            return np.asarray(img)
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# StopButton — floating "● Dừng" + elapsed timer, placed OUTSIDE the capture rect
# ─────────────────────────────────────────────────────────────────────────────
class StopButton(QtWidgets.QWidget):
    """Small always-on-top brand panel to end a recording.

    Shows a red "● Dừng" primary button plus a live elapsed-seconds label.
    It is positioned just outside the capture rectangle (below-right, clamped
    on-screen) so it never appears in the recorded GIF. Clicking emits
    ``stopped``.
    """

    stopped = pyqtSignal()

    def __init__(self, near_rect, parent=None):
        super().__init__(parent)
        self._near = _rect_tuple(near_rect)
        self._elapsed = 0
        self._timer = None  # type: ignore[assignment]

        # Frameless, translucent, always-on-top. NO Qt.WindowType.Tool — Tool
        # windows auto-hide when the app isn't frontmost, but the Stop button
        # must stay visible while the user records over OTHER apps.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._build_ui()
        self.place_near(self._near)

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Root brand panel (theme.qss_panel) so it reads as part of the app.
        self._panel = QtWidgets.QFrame(self)
        self._panel.setObjectName("panel")
        self._panel.setStyleSheet(theme.qss_panel())

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        row = QtWidgets.QHBoxLayout(self._panel)
        row.setContentsMargins(theme.PAD, theme.PAD_SM, theme.PAD, theme.PAD_SM)
        row.setSpacing(theme.GAP)

        # Elapsed-seconds label in the Inter (number) font.
        self._time_lbl = QtWidgets.QLabel("0,0s")
        self._time_lbl.setFont(theme.number_font(14, 600))
        self._time_lbl.setStyleSheet("color:%s;background:transparent;"
                                     % theme.TEXT_PRIMARY)
        row.addWidget(self._time_lbl)

        # Red primary "● Dừng" button.
        self._btn = QtWidgets.QPushButton("● Dừng")
        self._btn.setFont(theme.body_font(13, 600))
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Use the brand accent primary look but force a clear "stop red" so the
        # action reads unmistakably (still brand-consistent radius/padding).
        self._btn.setStyleSheet(
            "QPushButton{background:#E04545;color:%s;border:none;"
            "border-radius:%dpx;padding:8px 18px;font-weight:600;}"
            "QPushButton:hover{background:#F05555;}"
            "QPushButton:pressed{background:#C03A3A;}"
            % (theme.TEXT_PRIMARY, theme.RADIUS_BUTTON))
        self._btn.clicked.connect(self._on_click)
        row.addWidget(self._btn)

        self.adjustSize()

    # ── elapsed timer ────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        # Menu-bar mode: keep the Stop button visible/clickable over a
        # native-fullscreen Space (it lives outside the recorded region).
        try:
            import platform_backend
            if platform_backend.MENUBAR_MODE:
                platform_backend.pin_over_all_spaces(self)
        except Exception:
            pass
        if self._timer is None:
            self._start = time.time()
            self._timer = QTimer(self)
            self._timer.setInterval(100)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def _tick(self):
        secs = time.time() - getattr(self, "_start", time.time())
        # Vietnamese decimal comma to match the brand locale.
        self._time_lbl.setText(("%.1fs" % secs).replace(".", ","))

    def _on_click(self):
        self._stop_timer()
        self.stopped.emit()

    def _stop_timer(self):
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    def closeEvent(self, event):
        self._stop_timer()
        super().closeEvent(event)

    # ── placement (outside the capture rect, clamped on-screen) ──────────
    def place_near(self, rect):
        """Position the panel just below-right of the capture rect, on-screen."""
        x, y, w, h = _rect_tuple(rect)
        self._near = (x, y, w, h)
        self.adjustSize()
        size = self.sizeHint() if not self.size().isValid() else self.size()
        bw = max(size.width(), self.width())
        bh = max(size.height(), self.height())

        # Default: just below the rect, right-aligned to its right edge.
        gap = theme.GAP
        px = x + w - bw
        py = y + h + gap

        # Determine the available screen area to clamp against.
        avail = self._available_geometry_for(x + w // 2, y + h // 2)
        if avail is not None:
            ax, ay, aw, ah = avail
            # If there's no room below, place ABOVE the rect instead.
            if py + bh > ay + ah:
                py = y - bh - gap
                # If still off the top, tuck it inside the bottom of the screen.
                if py < ay:
                    py = ay + ah - bh - gap
            # Horizontal clamp.
            if px + bw > ax + aw:
                px = ax + aw - bw - gap
            if px < ax:
                px = ax + gap

            # Final guard: the button must NEVER overlap the capture rect (it
            # would be recorded into the GIF). If it does, slide it beside the
            # rect; as a last resort park it in a screen corner clear of it.
            cap = QRect(x, y, w, h)
            if QRect(int(px), int(py), int(bw), int(bh)).intersects(cap):
                if x + w + gap + bw <= ax + aw:          # right of the rect
                    px, py = x + w + gap, max(ay, min(y, ay + ah - bh))
                elif x - gap - bw >= ax:                  # left of the rect
                    px, py = x - gap - bw, max(ay, min(y, ay + ah - bh))
                else:                                     # corner clear of rect
                    px = ax + gap
                    py = ay + gap if (y > ay + bh + gap) else (ay + ah - bh - gap)

        self.move(int(px), int(py))

    def _available_geometry_for(self, gx, gy):
        """Return (x, y, w, h) of the screen containing point (gx, gy), or None."""
        try:
            screen = QtGui.QGuiApplication.screenAt(QtCore.QPoint(int(gx), int(gy)))
            if screen is None:
                screen = QtGui.QGuiApplication.primaryScreen()
            if screen is None:
                return None
            g = screen.availableGeometry()
            return g.x(), g.y(), g.width(), g.height()
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# RecordingFrame — a persistent accent border around the area being recorded so
# the user can keep track of it. The border is drawn in a small margin OUTSIDE
# the captured region, so it never appears in the GIF. Click-through.
# ─────────────────────────────────────────────────────────────────────────────
_FRAME_PAD = 4   # border thickness / margin (logical px), drawn outside region


class RecordingFrame(QtWidgets.QWidget):
    def __init__(self, rect, parent=None):
        super().__init__(parent)
        self._rect = _rect_tuple(rect)   # (x, y, w, h) = the captured region
        # No Qt.WindowType.Tool (would auto-hide when another app is frontmost).
        # WindowTransparentForInput = the WHOLE frame window is click-through
        # (Qt sets NSWindow.ignoresMouseEvents=YES) so the user can keep clicking
        # the app being recorded WHILE the GIF records. WA_TransparentForMouseEvents
        # alone is unreliable for a top-level window on macOS.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        x, y, w, h = self._rect
        p = _FRAME_PAD
        try:
            self.setGeometry(int(x - p), int(y - p), int(w + 2 * p),
                             int(h + 2 * p))
        except Exception:
            pass

    def paintEvent(self, event):
        try:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            pen = QtGui.QPen(theme.qcolor(theme.ACCENT))
            pen.setWidth(_FRAME_PAD)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            half = _FRAME_PAD / 2.0
            # Border centerline sits half a pad in → the stroke fills exactly the
            # margin [edge, edge+pad], i.e. OUTSIDE the recorded region.
            painter.drawRect(QtCore.QRectF(
                half, half, self.width() - _FRAME_PAD,
                self.height() - _FRAME_PAD))
            painter.end()
        except Exception:
            pass

    def show_frame(self):
        try:
            self.show()
            self.raise_()
            import platform_backend
            if platform_backend.MENUBAR_MODE:
                platform_backend.pin_over_all_spaces(self)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# GifResultWindow — brand preview of the finished GIF + Copy / Save actions
# ─────────────────────────────────────────────────────────────────────────────
class GifResultWindow(QtWidgets.QWidget):
    """Preview the exported GIF with QMovie and offer Copy / Save.

    ``on_copy(gif_path)`` is called for [Copy GIF].
    ``on_save(gif_path) -> bool`` is called for [Lưu file]; if it returns True
    the window closes.
    """

    def __init__(self, gif_path, on_copy=None, on_save=None, parent=None):
        super().__init__(parent)
        self._gif_path = gif_path
        self._on_copy = on_copy
        self._on_save = on_save
        self._movie = None  # type: ignore[assignment]

        self.setWindowTitle("FC-FastCapture — GIF")
        self.setStyleSheet(theme.app_qss())
        self.setMinimumWidth(360)

        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        root.setSpacing(theme.GAP)

        # Header + signature.
        title = QtWidgets.QLabel("Ảnh GIF đã sẵn sàng")
        title.setProperty("role", "subtitle")
        root.addWidget(title)

        sig = QtWidgets.QLabel(theme.SIGNATURE)
        sig.setProperty("role", "signature")
        root.addWidget(sig)

        # GIF preview inside a brand panel.
        panel = QtWidgets.QFrame()
        panel.setObjectName("panel")
        pl = QtWidgets.QVBoxLayout(panel)
        pl.setContentsMargins(theme.PAD_SM, theme.PAD_SM, theme.PAD_SM, theme.PAD_SM)

        self._preview = QtWidgets.QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(320, 200)
        pl.addWidget(self._preview)
        root.addWidget(panel)

        self._setup_movie()

        # Action buttons — both primary accent (Copy + Save).
        btns = QtWidgets.QHBoxLayout()
        btns.setSpacing(theme.GAP)
        btns.addStretch(1)

        self._copy_btn = QtWidgets.QPushButton("Copy GIF")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._do_copy)
        btns.addWidget(self._copy_btn)

        self._save_btn = QtWidgets.QPushButton("Lưu file")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._do_save)
        btns.addWidget(self._save_btn)

        root.addLayout(btns)

    def _setup_movie(self):
        """Load the GIF into a QMovie and play it inside the preview label."""
        path = self._gif_path
        if not path or not os.path.exists(path):
            self._preview.setText("Không tải được GIF")
            self._preview.setProperty("role", "muted")
            return
        try:
            movie = QtGui.QMovie(path)
            if not movie.isValid():
                self._preview.setText("Không tải được GIF")
                return
            # Cap the preview so a big recording doesn't blow up the window.
            try:
                movie.jumpToFrame(0)
                fsize = movie.currentImage().size()
                if fsize.width() > 640 or fsize.height() > 480:
                    fsize.scale(640, 480, Qt.AspectRatioMode.KeepAspectRatio)
                    movie.setScaledSize(fsize)
            except Exception:
                pass
            self._movie = movie
            self._preview.setMovie(movie)
            movie.start()
        except Exception:
            self._preview.setText("Không tải được GIF")

    # ── actions ──────────────────────────────────────────────────────────
    def _do_copy(self):
        if callable(self._on_copy):
            try:
                self._on_copy(self._gif_path)
            except Exception:
                pass
        # Auto-close after copying (button or ⌘C).
        self.close()

    def keyPressEvent(self, event):
        try:
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                return
            if event.key() == Qt.Key.Key_C and ctrl:
                self._do_copy()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def _do_save(self):
        if callable(self._on_save):
            ok = False
            try:
                ok = bool(self._on_save(self._gif_path))
            except Exception:
                ok = False
            if ok:
                self.close()

    # ── show / cleanup ───────────────────────────────────────────────────
    def show_result(self):
        """Show the window, centered on the primary screen, and bring it front."""
        self.show()
        try:
            screen = QtGui.QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                fr = self.frameGeometry()
                fr.moveCenter(geo.center())
                self.move(fr.topLeft())
        except Exception:
            pass
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self._movie is not None:
            try:
                self._movie.stop()
            except Exception:
                pass
        super().closeEvent(event)
