"""
overlay.py — FC-FastCapture selection overlay ("10XLifeOS").

The heart of the capture UX. `SelectionOverlay` is a frameless, translucent,
always-on-top widget that dims the screen and lets the user pick the region to
capture in one of four modes:

  • "free"   — press-drag-release to define an arbitrary rectangle.
  • "preset" — a remembered-size rectangle starts centered; drag the body to
               move and the 8 handles to resize; ENTER / double-click confirms.
  • "locked" — a fixed-size rectangle follows the cursor (cursor = center);
               single click places it.
  • "window" — hovering highlights the front-most window under the cursor;
               click captures that window's rectangle.

All geometry emitted via the `selected` signal is in GLOBAL logical points
(top-left origin of the primary display), matching Qt global coords and Quartz
window bounds (see CONTRACT.md). Robustness choice: the overlay covers the
SINGLE screen under the cursor; local coordinates are translated to global by
adding the overlay's top-left.

The overlay never crashes (risky Qt/geometry calls are guarded) and always hides
itself BEFORE emitting `selected`, so it can never appear in the screenshot.

Target: Python 3.9+, PyQt6, macOS first.
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QPointF, QRectF

import theme

# Minimum drag distance (logical px) to count a "free" drag as a real selection.
_MIN_DRAG = 8
# Size of the square resize handles drawn in "preset" mode (logical px).
_HANDLE = 9
# Hit-test slack around a handle so it's easy to grab (logical px).
_HANDLE_HIT = 11


class SelectionOverlay(QtWidgets.QWidget):
    """Fullscreen selection overlay. Emits a GLOBAL logical QRect on confirm."""

    selected = pyqtSignal(QRect)   # GLOBAL logical rect chosen by the user
    cancelled = pyqtSignal()       # user pressed ESC / aborted

    def __init__(self, mode="free", locked_size=None, initial_size=None,
                 windows=None, parent=None, screen=None, fixed_size=False):
        super().__init__(parent)
        # Which screen this overlay covers (None → the screen under the cursor).
        self._screen = screen
        # fixed_size: preset frame that can only be MOVED, never resized — used by
        # Mode 3 so the capture is always EXACTLY the configured W×H.
        self._fixed_size = bool(fixed_size)
        # Only the overlay on the cursor's screen grabs the keyboard (Qt allows
        # one grab); MultiScreenOverlay sets this per-display.
        self._active = True
        self._mode = mode if mode in ("free", "preset", "locked", "window") \
            else "free"
        self._locked_size = self._coerce_size(locked_size, (1200, 1800))
        self._initial_size = self._coerce_size(initial_size, (1200, 800))
        # windows: list of dicts {"x","y","w","h",...} in GLOBAL logical pts.
        self._windows = list(windows) if windows else []

        # --- per-mode mutable state (all in LOCAL widget coords) -------------
        # "free": rubber-band rect being dragged.
        self._origin = None          # QPoint where the drag started
        self._free_rect = QRect()    # current rubber-band rect

        # "preset": the editable rect + active drag operation.
        self._preset_rect = QRect()  # set on start() once geometry is known
        self._drag_mode = None       # None | "move" | one of the handle keys
        self._drag_start = None      # QPoint mouse pos at grab time
        self._drag_rect0 = None      # QRect snapshot at grab time

        # "locked": last cursor position (rect center follows it).
        self._cursor = None          # QPoint local cursor pos

        # "window": currently highlighted window rect in LOCAL coords (or None).
        self._hover_rect = None
        self._hover_window = None     # the highlighted window dict (has id)
        self.picked_window = None     # set when a window is chosen (Mode 4)

        self._emitted = False        # guard so we emit at most once

        # Window chrome: frameless, always-on-top. NOT Tool — a Tool window can't
        # become the key window on macOS, so it never receives keyPressEvent
        # (ESC/Enter) even with grabKeyboard(). Plain frameless windows CAN be key.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(QtGui.QCursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _coerce_size(value, fallback):
        """Return a safe (w, h) int tuple, falling back on bad input."""
        try:
            w, h = int(value[0]), int(value[1])
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
        return fallback

    def _to_global(self, local_rect):
        """Translate a LOCAL widget rect to a GLOBAL logical QRect."""
        try:
            tl = self.geometry().topLeft()
            return QRect(local_rect.x() + tl.x(), local_rect.y() + tl.y(),
                         local_rect.width(), local_rect.height())
        except Exception:
            return QRect(local_rect)

    def _current_rect(self):
        """The selection rect to paint, in LOCAL widget coords (may be empty).

        One helper consulted by both paintEvent and the size label so the
        on-screen geometry and the emitted rect always agree.
        """
        if self._mode == "free":
            return QRect(self._free_rect)
        if self._mode == "preset":
            return QRect(self._preset_rect)
        if self._mode == "locked":
            return self._locked_rect_at(self._cursor)
        if self._mode == "window":
            return QRect(self._hover_rect) if self._hover_rect else QRect()
        return QRect()

    def _locked_rect_at(self, center):
        """Fixed-size rect centered on `center`, clamped inside the widget."""
        if center is None:
            return QRect()
        w, h = self._locked_size
        x = center.x() - w // 2
        y = center.y() - h // 2
        return self._clamp(QRect(x, y, w, h))

    def _clamp(self, rect):
        """Clamp a rect so it stays fully inside the overlay widget."""
        bounds = self.rect()
        r = QRect(rect)
        if r.width() > bounds.width():
            r.setWidth(bounds.width())
        if r.height() > bounds.height():
            r.setHeight(bounds.height())
        if r.left() < bounds.left():
            r.moveLeft(bounds.left())
        if r.top() < bounds.top():
            r.moveTop(bounds.top())
        if r.right() > bounds.right():
            r.moveRight(bounds.right())
        if r.bottom() > bounds.bottom():
            r.moveBottom(bounds.bottom())
        return r

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self):
        """Cover the screen under the cursor, show on top, grab the keyboard."""
        try:
            screen = self._screen \
                or QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) \
                or QtGui.QGuiApplication.primaryScreen()
            geo = screen.geometry() if screen is not None else QRect(0, 0, 800, 600)
        except Exception:
            geo = QRect(0, 0, 800, 600)

        try:
            self.setGeometry(geo)
        except Exception:
            pass

        # Seed per-mode state now that the widget geometry (and thus size) is
        # known. All state is kept in LOCAL coords.
        self._init_mode_state()

        try:
            self.show()
            self.setGeometry(geo)            # re-assert after show (macOS quirk)
            self.raise_()
            self.activateWindow()
            if self._active:
                self.setFocus(Qt.FocusReason.OtherFocusReason)
                self.grabKeyboard()           # only the cursor's-screen overlay
        except Exception:
            pass
        self._ensure_action_box()
        self.update()

    def _ensure_action_box(self):
        """Build the floating action box ([✓ Chụp] for preset + [✕ Huỷ]) that
        sits RIGHT NEXT TO the selection so the controls are always at hand."""
        try:
            # Preset boxes live only on the active (cursor) screen — don't put a
            # confirm box on secondary monitors that have no editable rect.
            if self._mode == "preset" and not self._active:
                return
            if getattr(self, "_action_box", None) is not None:
                return
            box = QtWidgets.QWidget(self)
            lay = QtWidgets.QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)

            # A visible Confirm button matters for "preset" mode (resize/move) —
            # otherwise users don't know it confirms with Enter/double-click.
            if self._mode == "preset":
                ok = QtWidgets.QPushButton("✓  Chụp", box)
                ok.setCursor(Qt.CursorShape.PointingHandCursor)
                ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                ok.setStyleSheet(theme.qss_primary_btn())
                ok.clicked.connect(self._confirm_current)
                lay.addWidget(ok)

            cancel = QtWidgets.QPushButton("✕  Huỷ", box)
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            cancel.setStyleSheet(
                "QPushButton{background:rgba(18,18,58,0.94);color:%s;"
                "border:1px solid %s;border-radius:6px;padding:9px 16px;"
                "font-weight:700;}"
                "QPushButton:hover{background:%s;color:#FFFFFF;"
                "border:1px solid %s;}"
                % (theme.TEXT_PRIMARY, theme.SECONDARY_BORDER,
                   theme.ACCENT, theme.ACCENT))
            cancel.clicked.connect(self._abort)
            lay.addWidget(cancel)

            box.adjustSize()
            self._action_box = box
            box.show()
            self._position_action_box()
        except Exception:
            pass

    def _confirm_current(self):
        """Confirm the current selection (used by the [✓ Chụp] button)."""
        try:
            self._finish(self._current_rect())
        except Exception:
            pass

    def _position_action_box(self):
        """Keep the action box pinned just below-right of the selection (or above
        if there's no room); fall back to top-center when there's no selection."""
        box = getattr(self, "_action_box", None)
        if box is None:
            return
        try:
            box.adjustSize()
            bw, bh = box.width(), box.height()
            r = self._current_rect()
            gap = 12
            if r is None or r.isNull() or r.width() < 2:
                x = (self.width() - bw) // 2
                y = 28
            else:
                x = r.right() - bw
                y = r.bottom() + gap
                if y + bh > self.height() - 6:      # no room below → above
                    y = r.top() - bh - gap
                if y < 6:                           # still off → inside top
                    y = r.top() + gap
                x = max(6, min(x, self.width() - bw - 6))
            box.move(int(x), int(y))
            box.raise_()
        except Exception:
            pass

    def _init_mode_state(self):
        """Initialise mode-specific state once geometry is available."""
        if self._mode == "preset":
            # On multi-monitor, ONLY the cursor's-screen overlay shows the editable
            # box + "✓ Chụp"; the others are plain dimmers (else every screen shows
            # its own box and confirming the wrong one captures the wrong region).
            if not self._active:
                self._preset_rect = QRect()
                return
            w, h = self._initial_size
            # Don't let the preset exceed the screen.
            w = min(w, max(20, self.width()))
            h = min(h, max(20, self.height()))
            cx, cy = self.width() // 2, self.height() // 2
            self._preset_rect = self._clamp(QRect(cx - w // 2, cy - h // 2, w, h))
        elif self._mode == "locked":
            # Start centered on the current cursor (mapped into the widget).
            try:
                gp = QtGui.QCursor.pos()
                self._cursor = self.mapFromGlobal(gp)
            except Exception:
                self._cursor = QPoint(self.width() // 2, self.height() // 2)
        elif self._mode == "window":
            try:
                gp = QtGui.QCursor.pos()
                self._update_hover(self.mapFromGlobal(gp))
            except Exception:
                self._hover_rect = None

    def _finish(self, local_rect):
        """Hide first, then emit `selected` with the GLOBAL rect (once)."""
        if self._emitted:
            return
        # Window rects come from Quartz already valid (possibly spanning past
        # this overlay's screen) — don't clamp them or Mode 4 would truncate a
        # window on multi-monitor setups. Other modes clamp to the screen.
        rect = local_rect if self._mode == "window" else self._clamp(local_rect)
        if rect.width() < _MIN_DRAG or rect.height() < _MIN_DRAG:
            return
        self._emitted = True
        global_rect = self._to_global(rect)
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        # Hide BEFORE emitting so the overlay never lands in the screenshot.
        self.close()
        self.selected.emit(global_rect)

    def _abort(self):
        """ESC / cancel path — release, close, emit cancelled (once)."""
        if self._emitted:
            return
        self._emitted = True
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.close()
        self.cancelled.emit()

    # ── keyboard ──────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._abort()
            return
        if self._mode == "preset" and key in (Qt.Key.Key_Return,
                                               Qt.Key.Key_Enter):
            self._finish(self._preset_rect)
            return
        super().keyPressEvent(event)

    # ── mouse ─────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        if self._mode == "free":
            self._origin = pos
            self._free_rect = QRect(pos, pos)
            self.update()

        elif self._mode == "preset":
            self._begin_preset_drag(pos)
            # Pressing empty space (not the rect/handles) starts a BRAND-NEW
            # selection by dragging — so users can re-pick a size instead of
            # tediously dragging the 4 edges. (Disabled for Mode 3 fixed-size.)
            if self._drag_mode is None and not self._fixed_size:
                self._drag_mode = "new"
                self._drag_start = pos
                self._preset_backup = QRect(self._preset_rect)   # restore on click
                self._preset_rect = QRect(pos, pos)
                self.setCursor(QtGui.QCursor(Qt.CursorShape.CrossCursor))
                self.update()

        elif self._mode == "locked":
            # Single click places the fixed rect → confirm.
            self._cursor = pos
            self._finish(self._locked_rect_at(pos))

        elif self._mode == "window":
            self._update_hover(pos)
            if self._hover_rect:
                self.picked_window = self._hover_window
                self._finish(self._hover_rect)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self._mode == "free":
            if self._origin is not None:
                self._free_rect = QRect(self._origin, pos).normalized()
                self.update()

        elif self._mode == "preset":
            if self._drag_mode is not None:
                self._update_preset_drag(pos)
            else:
                # Hover feedback: pick the cursor that matches the hot zone.
                self.setCursor(QtGui.QCursor(self._cursor_for(pos)))

        elif self._mode == "locked":
            self._cursor = pos
            self.update()

        elif self._mode == "window":
            self._update_hover(pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._mode == "free":
            if self._origin is not None:
                pos = event.position().toPoint()
                rect = QRect(self._origin, pos).normalized()
                self._origin = None
                # Ignore accidental micro-drags.
                if rect.width() >= _MIN_DRAG and rect.height() >= _MIN_DRAG:
                    self._finish(rect)
                else:
                    self._free_rect = QRect()
                    self.update()

        elif self._mode == "preset":
            dragmode = self._drag_mode
            # Releasing after POSITIONING the box ("move" the whole rect, or draw
            # a brand-"new" one) jumps STRAIGHT to edit — no separate "✓ Chụp"
            # click. Resizing via a handle does NOT auto-confirm, so the user can
            # fine-tune the size first, then move + release to capture.
            confirm = dragmode in ("move", "new")
            # A brand-new empty-space drag that's only a click (too small) → keep
            # the previous rect and don't treat it as a positioning gesture.
            if dragmode == "new":
                r = self._preset_rect
                if (r.width() < _MIN_DRAG or r.height() < _MIN_DRAG) and \
                        getattr(self, "_preset_backup", None) is not None:
                    self._preset_rect = QRect(self._preset_backup)
                    confirm = False
            self._drag_mode = None
            self._drag_start = None
            self._drag_rect0 = None
            r = self._preset_rect
            if confirm and r.width() >= _MIN_DRAG and r.height() >= _MIN_DRAG:
                self._finish(r)
                return
            self.update()
            self.setCursor(QtGui.QCursor(
                self._cursor_for(event.position().toPoint())))

    def mouseDoubleClickEvent(self, event):
        # Double-click confirms the preset rectangle.
        if self._mode == "preset" and event.button() == Qt.MouseButton.LeftButton:
            self._finish(self._preset_rect)

    # ── "preset" mode: handles, move & resize ─────────────────────────────
    def _handle_points(self, rect):
        """Return {key: center QPoint} for the 8 resize handles of `rect`."""
        l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
        cx = rect.center().x()
        cy = rect.center().y()
        return {
            "tl": QPoint(l, t), "tr": QPoint(r, t),
            "bl": QPoint(l, b), "br": QPoint(r, b),
            "t": QPoint(cx, t), "b": QPoint(cx, b),
            "l": QPoint(l, cy), "r": QPoint(r, cy),
        }

    def _hit_handle(self, pos):
        """Return the handle key under `pos`, or None."""
        if self._fixed_size:
            return None   # no resize handles → frame stays the exact W×H
        for key, pt in self._handle_points(self._preset_rect).items():
            if abs(pos.x() - pt.x()) <= _HANDLE_HIT and \
                    abs(pos.y() - pt.y()) <= _HANDLE_HIT:
                return key
        return None

    def _cursor_for(self, pos):
        """Pick the right cursor shape for a position in preset mode."""
        key = self._hit_handle(pos)
        shapes = {
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
        }
        if key:
            return shapes.get(key, Qt.CursorShape.SizeAllCursor)
        if self._preset_rect.contains(pos):
            return Qt.CursorShape.SizeAllCursor   # body → move
        return Qt.CursorShape.CrossCursor

    def _begin_preset_drag(self, pos):
        """Start a move/resize operation in preset mode."""
        key = self._hit_handle(pos)
        if key:
            self._drag_mode = key
        elif self._preset_rect.contains(pos):
            self._drag_mode = "move"
        else:
            self._drag_mode = None
            return
        self._drag_start = pos
        self._drag_rect0 = QRect(self._preset_rect)

    def _update_preset_drag(self, pos):
        """Apply an in-progress move/resize/new-draw to the preset rect."""
        # Brand-new rubber-band selection (drag from empty space).
        if self._drag_mode == "new" and self._drag_start is not None:
            self._preset_rect = QRect(self._drag_start, pos).normalized()
            self.update()
            return
        if self._drag_rect0 is None or self._drag_start is None:
            return
        dx = pos.x() - self._drag_start.x()
        dy = pos.y() - self._drag_start.y()
        r0 = self._drag_rect0
        mode = self._drag_mode

        if mode == "move":
            moved = QRect(r0)
            moved.translate(dx, dy)
            self._preset_rect = self._clamp(moved)
            self.update()
            return

        # Resize: adjust the affected edges, keep a minimum size, clamp.
        left, top = r0.left(), r0.top()
        right, bottom = r0.right(), r0.bottom()
        if "l" in mode:
            left = r0.left() + dx
        if "r" in mode:
            right = r0.right() + dx
        if "t" in mode:
            top = r0.top() + dy
        if "b" in mode:
            bottom = r0.bottom() + dy

        # Enforce a sane minimum so the rect can't invert or vanish.
        if right - left < _MIN_DRAG:
            if "l" in mode:
                left = right - _MIN_DRAG
            else:
                right = left + _MIN_DRAG
        if bottom - top < _MIN_DRAG:
            if "t" in mode:
                top = bottom - _MIN_DRAG
            else:
                bottom = top + _MIN_DRAG

        new = QRect(QPoint(left, top), QPoint(right, bottom)).normalized()
        self._preset_rect = self._clamp(new)
        self.update()

    # ── "window" mode: front-most window under the cursor ─────────────────
    def _update_hover(self, local_pos):
        """Find the front-most window whose GLOBAL rect contains the cursor."""
        try:
            tl = self.geometry().topLeft()
        except Exception:
            tl = QPoint(0, 0)
        gx = local_pos.x() + tl.x()
        gy = local_pos.y() + tl.y()

        found = None
        found_win = None
        # `windows` is front-to-back z-order → first match is the front-most.
        for win in self._windows:
            try:
                wx, wy = int(win["x"]), int(win["y"])
                ww, wh = int(win["w"]), int(win["h"])
            except (KeyError, TypeError, ValueError):
                continue
            if wx <= gx < wx + ww and wy <= gy < wy + wh:
                # Convert back to LOCAL coords for painting / emit.
                found = QRect(wx - tl.x(), wy - tl.y(), ww, wh)
                found_win = win
                break

        self._hover_window = found_win   # the dict (has the CGWindow id)
        if found != self._hover_rect:
            self._hover_rect = found
            self.update()

    # ── painting ──────────────────────────────────────────────────────────
    def paintEvent(self, event):
        try:
            self._paint(event)
        except Exception:
            # Painting must never crash the overlay.
            pass
        # Keep the [✓ Chụp]/[✕ Huỷ] box pinned next to the (possibly moved)
        # selection on every repaint.
        self._position_action_box()

    def _paint(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        full = self.rect()
        dim = theme.qcolor(theme.OVERLAY_DIM)

        sel = self._current_rect()
        has_sel = sel.width() > 0 and sel.height() > 0

        if not has_sel:
            # Nothing selected yet → veil the whole screen.
            painter.fillRect(full, dim)
            painter.end()
            return

        # Dim everything EXCEPT the selection by filling the four surrounding
        # bands. (Drawing bands keeps the hole crisp without composition modes.)
        self._fill_around(painter, full, sel, dim)

        # 2px accent border around the selection.
        pen = QtGui.QPen(theme.qcolor(theme.ACCENT))
        pen.setWidth(2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inset by 1px so the 2px stroke sits on the selection edge.
        painter.drawRect(QRectF(sel.x() + 0.5, sel.y() + 0.5,
                                sel.width() - 1, sel.height() - 1))

        # Resize handles (preset mode only; hidden when the size is fixed).
        if self._mode == "preset" and not self._fixed_size:
            self._draw_handles(painter, sel)

        # Live size chip: "W: 1200  H: 800".
        self._draw_size_label(painter, sel)

        painter.end()

    def _fill_around(self, painter, full, sel, color):
        """Fill the dim veil everywhere except the selection rectangle."""
        s = sel.intersected(full)
        # Top band.
        painter.fillRect(QRect(full.left(), full.top(),
                               full.width(), s.top() - full.top()), color)
        # Bottom band.
        painter.fillRect(QRect(full.left(), s.bottom() + 1,
                               full.width(), full.bottom() - s.bottom()), color)
        # Left band (between top and bottom of selection).
        painter.fillRect(QRect(full.left(), s.top(),
                               s.left() - full.left(), s.height()), color)
        # Right band.
        painter.fillRect(QRect(s.right() + 1, s.top(),
                               full.right() - s.right(), s.height()), color)

    def _draw_handles(self, painter, sel):
        """Draw the 8 resize handles as small accent squares."""
        painter.setPen(QtGui.QPen(theme.qcolor(theme.ACCENT), 1))
        painter.setBrush(theme.qcolor(theme.ACCENT))
        half = _HANDLE / 2.0
        for pt in self._handle_points(sel).values():
            painter.drawRect(QRectF(pt.x() - half, pt.y() - half,
                                    _HANDLE, _HANDLE))

    def _draw_size_label(self, painter, sel):
        """Draw a dark rounded chip with 'W: %d  H: %d' near the selection."""
        text = "W: %d  H: %d" % (sel.width(), sel.height())
        font = theme.number_font(13, 600)
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()

        pad_x, pad_y = 10, 6
        chip_w = tw + pad_x * 2
        chip_h = th + pad_y * 2

        # Prefer just above the selection's top-left; if there's no room, drop
        # the chip just inside the top-left corner instead.
        x = sel.left()
        y = sel.top() - chip_h - 6
        if y < self.rect().top():
            y = sel.top() + 6
            x = sel.left() + 6
        # Keep the chip on screen horizontally.
        x = max(self.rect().left() + 2,
                min(x, self.rect().right() - chip_w - 2))

        chip = QRectF(x, y, chip_w, chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        # Dark, slightly translucent background for legibility.
        bg = theme.qcolor(theme.PANEL)
        bg.setAlpha(235)
        painter.setBrush(bg)
        painter.drawRoundedRect(chip, theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)

        painter.setPen(theme.qcolor(theme.ACCENT))
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)

    # ── safety net ────────────────────────────────────────────────────────
    def closeEvent(self, event):
        # Always release the keyboard grab on any close path.
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# MultiScreenOverlay — one SelectionOverlay per display so the user can select
# on ANY monitor (Mode 4 windows on other screens, free/preset/locked anywhere).
# Drop-in replacement for SelectionOverlay: same selected/cancelled signals +
# start() + close(); confirming/cancelling on any screen tears down the rest.
# ─────────────────────────────────────────────────────────────────────────────
class MultiScreenOverlay(QtCore.QObject):
    selected = pyqtSignal(QRect)   # GLOBAL logical rect
    cancelled = pyqtSignal()

    def __init__(self, mode="free", locked_size=None, initial_size=None,
                 windows=None, parent=None, fixed_size=False):
        super().__init__(parent)
        self._overlays = []
        self._done = False
        self.picked_window = None     # set on selection in Mode 4
        try:
            screens = list(QtGui.QGuiApplication.screens())
        except Exception:
            screens = []
        if not screens:
            screens = [None]   # fall back to a single cursor-screen overlay
        for sc in screens:
            try:
                ov = SelectionOverlay(mode=mode, locked_size=locked_size,
                                      initial_size=initial_size, windows=windows,
                                      screen=sc, fixed_size=fixed_size)
                ov.selected.connect(
                    lambda r, o=ov: self._on_selected(r, o))
                ov.cancelled.connect(self._on_cancelled)
                self._overlays.append(ov)
            except Exception:
                pass

    def start(self):
        # Pull FC to the front so the active overlay can become the key window and
        # receive ESC/Enter — the hotkey fires while another app is frontmost.
        # macOS: AppKit activate; Windows: relax the foreground lock.
        try:
            import platform_backend
            platform_backend.pull_to_foreground()
        except Exception:
            pass
        # Only the overlay on the cursor's screen grabs the keyboard (ESC/Enter);
        # the others still render + accept mouse (cancel button, window pick).
        try:
            cur = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        except Exception:
            cur = None
        any_active = False
        for ov in self._overlays:
            ov._active = (cur is not None and ov._screen is cur)
            any_active = any_active or ov._active
        if not any_active and self._overlays:
            self._overlays[0]._active = True
        for ov in self._overlays:
            try:
                ov.start()
            except Exception:
                pass

    def _on_selected(self, rect, overlay=None):
        if self._done:
            return
        self._done = True
        # Forward the picked window dict (Mode 4) from the originating overlay.
        try:
            self.picked_window = overlay.picked_window if overlay else None
        except Exception:
            self.picked_window = None
        self._close_all()
        self.selected.emit(rect)

    def _on_cancelled(self):
        if self._done:
            return
        self._done = True
        self._close_all()
        self.cancelled.emit()

    def _close_all(self):
        for ov in self._overlays:
            try:
                ov.close()
            except Exception:
                pass

    def close(self):
        self._close_all()
