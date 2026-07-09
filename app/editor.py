"""
editor.py — in-place annotation editor + premium floating toolbar (modes 2/3/4).

A frameless brand window showing the captured screenshot with on-image annotation
tools: Select, Text, Arrow, Rectangle, Highlighter, Blur (hide sensitive info),
Step badges — plus a color picker, thickness picker, Undo/Redo and Copy / Lưu
file. Annotations default to the brand accent. ``flattened()`` re-paints the base
image + every annotation onto a full-resolution QImage so exports are crisp.

Coordinate model: the user draws in the canvas's LOGICAL points (= the pixmap's
device-independent size). ``flattened()`` scales annotations by ``scale`` (the
capture's devicePixelRatio) up to full pixels.

Target: Python 3.9+, PyQt6, macOS.
"""
from __future__ import annotations

import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal

import theme

# Modifier glyph shown in shortcut tooltips: ⌘ on macOS, "Ctrl+" on Windows.
# (The handler binds to Qt.ControlModifier, which Qt maps to ⌘ on macOS and to
# physical Ctrl on Windows — so the SHORTCUT is correct either way; only the
# label needs to match the platform.)
_MOD = "Ctrl+" if sys.platform.startswith("win") else "⌘"


# ─────────────────────────────────────────────────────────────────────────────
# Annotation items — each stores its own color/width so the color & thickness
# pickers work per-annotation. All geometry is in LOGICAL canvas points.
# ─────────────────────────────────────────────────────────────────────────────
class _Item:
    def paint(self, painter, scale):  # pragma: no cover - overridden
        raise NotImplementedError


class _ArrowItem(_Item):
    """A line from p1→p2 with a filled triangular head at p2."""

    def __init__(self, p1, p2, color=None, width=4):
        self.p1 = QPoint(p1)
        self.p2 = QPoint(p2)
        self.color = color or theme.ANNOTATION
        self.width = width

    def paint(self, painter, scale):
        import math
        a = QtCore.QPointF(self.p1.x() * scale, self.p1.y() * scale)
        b = QtCore.QPointF(self.p2.x() * scale, self.p2.y() * scale)
        color = theme.qcolor(self.color)
        pen = QtGui.QPen(color)
        pen.setWidthF(max(1.0, self.width * scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        ux, uy = dx / length, dy / length
        head_len = max(10.0, (self.width + 8) * scale)
        head_w = max(6.0, (self.width + 4) * scale)
        base = QtCore.QPointF(b.x() - ux * head_len, b.y() - uy * head_len)
        painter.drawLine(a, base)
        nx, ny = -uy, ux
        left = QtCore.QPointF(base.x() + nx * head_w, base.y() + ny * head_w)
        right = QtCore.QPointF(base.x() - nx * head_w, base.y() - ny * head_w)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QtGui.QPolygonF([b, left, right]))


class _RectItem(_Item):
    """An OUTLINE-only rectangle."""

    def __init__(self, rect, color=None, width=4):
        self.rect = QRect(rect).normalized()
        self.color = color or theme.ANNOTATION
        self.width = width

    def paint(self, painter, scale):
        r = QtCore.QRectF(self.rect.x() * scale, self.rect.y() * scale,
                          self.rect.width() * scale, self.rect.height() * scale)
        pen = QtGui.QPen(theme.qcolor(self.color))
        pen.setWidthF(max(1.0, self.width * scale))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)


class _HighlightItem(_Item):
    """A translucent freehand stroke (highlighter marker)."""

    def __init__(self, points, color=None, width=14):
        self.points = [QPoint(p) for p in points]
        self.color = color or theme.HIGHLIGHT
        self.width = width

    def add(self, p):
        self.points.append(QPoint(p))

    def paint(self, painter, scale):
        if len(self.points) < 1:
            return
        c = theme.qcolor(self.color)
        c.setAlpha(110)
        pen = QtGui.QPen(c)
        pen.setWidthF(max(2.0, self.width * scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QtGui.QPainterPath()
        path.moveTo(self.points[0].x() * scale, self.points[0].y() * scale)
        for pt in self.points[1:]:
            path.lineTo(pt.x() * scale, pt.y() * scale)
        if len(self.points) == 1:
            painter.drawPoint(QtCore.QPointF(self.points[0].x() * scale,
                                             self.points[0].y() * scale))
        else:
            painter.drawPath(path)


class _PenItem(_Item):
    """An OPAQUE freehand stroke (pen / "Vẽ tay") — the highlighter's sibling.

    Differences vs _HighlightItem: full alpha, normal thickness (no ×3), and
    midpoint-quadratic smoothing applied ONLY in paint() (the stored data stays
    a raw point list, so live preview / undo / redo work identically)."""

    def __init__(self, points, color=None, width=4):
        self.points = [QPoint(p) for p in points]
        self.color = color or theme.ANNOTATION
        self.width = width

    def add(self, p):
        # Point-thinning: skip points closer than 2 logical px to the last one
        # (bounds list growth during slow, dense drags on retina mice).
        if self.points and (p - self.points[-1]).manhattanLength() < 2:
            return
        self.points.append(QPoint(p))

    def paint(self, painter, scale):
        if len(self.points) < 1:
            return
        pen = QtGui.QPen(theme.qcolor(self.color))   # opaque — no setAlpha
        pen.setWidthF(max(1.0, self.width * scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pts = [QtCore.QPointF(p.x() * scale, p.y() * scale)
               for p in self.points]
        if len(pts) == 1:
            painter.drawPoint(pts[0])   # single click → round dot (RoundCap)
            return
        # Midpoint smoothing: curve through each point toward the next midpoint
        # — an opaque thin stroke shows polyline corners far more than the fat
        # translucent highlighter, so this is worth the few extra lines.
        path = QtGui.QPainterPath()
        path.moveTo(pts[0])
        for i in range(1, len(pts) - 1):
            mid = QtCore.QPointF((pts[i].x() + pts[i + 1].x()) / 2.0,
                                 (pts[i].y() + pts[i + 1].y()) / 2.0)
            path.quadTo(pts[i], mid)
        path.lineTo(pts[-1])
        painter.drawPath(path)


class _BlurItem(_Item):
    """Pixelates a rectangular region of the base image (hide sensitive info)."""

    def __init__(self, rect, source):
        self.rect = QRect(rect).normalized()
        self.source = source   # full-res QPixmap of the screenshot

    def paint(self, painter, scale):
        r = self.rect
        if r.width() < 2 or r.height() < 2 or self.source is None:
            return
        sd = self.source.devicePixelRatio() or 1.0
        sx, sy = int(r.x() * sd), int(r.y() * sd)
        sw, sh = max(1, int(r.width() * sd)), max(1, int(r.height() * sd))
        sub = self.source.copy(sx, sy, sw, sh)
        sub.setDevicePixelRatio(1.0)
        pw, ph = max(1, sub.width() // 14), max(1, sub.height() // 14)
        small = sub.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        pix = small.scaled(sub.width(), sub.height(),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        pix.setDevicePixelRatio(1.0)
        target = QtCore.QRectF(r.x() * scale, r.y() * scale,
                               r.width() * scale, r.height() * scale)
        painter.drawPixmap(target, pix, QtCore.QRectF(0, 0, pix.width(),
                                                      pix.height()))


class _StepItem(_Item):
    """A numbered circular badge (1, 2, 3 …) for step-by-step callouts."""

    def __init__(self, pos, number, color=None):
        self.pos = QPoint(pos)        # CENTER of the badge
        self.number = number
        self.color = color or theme.ANNOTATION

    def paint(self, painter, scale):
        r = max(11.0, 13.0 * scale)
        cx, cy = self.pos.x() * scale, self.pos.y() * scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(self.color))
        painter.drawEllipse(QtCore.QPointF(cx, cy), r, r)
        painter.setPen(theme.qcolor("#FFFFFF"))
        f = theme.number_font(max(8, int(r * 1.0)), 800)
        painter.setFont(f)
        painter.drawText(QtCore.QRectF(cx - r, cy - r, r * 2, r * 2),
                         int(Qt.AlignmentFlag.AlignCenter), str(self.number))


class _TextItem(_Item):
    """A committed text label anchored at top-left ``pos`` (logical points)."""

    def __init__(self, pos, text, size=18, color=None):
        self.pos = QPoint(pos)
        self.text = text
        self.size = size
        self.color = color or theme.ANNOTATION

    def paint(self, painter, scale):
        font = theme.number_font(max(1, int(round(self.size * scale))), 700)
        painter.setFont(font)
        painter.setPen(theme.qcolor(self.color))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        metrics = QtGui.QFontMetrics(font)
        x = self.pos.x() * scale
        y = self.pos.y() * scale + metrics.ascent()
        painter.drawText(int(round(x)), int(round(y)), self.text)


# ─────────────────────────────────────────────────────────────────────────────
# Image canvas — paints base pixmap + annotations and handles tool input
# ─────────────────────────────────────────────────────────────────────────────
class _Canvas(QtWidgets.QWidget):
    def __init__(self, editor, pixmap):
        super().__init__(editor)
        self._editor = editor
        self._pixmap = pixmap
        dpr = pixmap.devicePixelRatio() or 1.0
        self._logical_w = int(round(pixmap.width() / dpr))
        self._logical_h = int(round(pixmap.height() / dpr))
        self.setFixedSize(self._logical_w, self._logical_h)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._tool = "arrow"
        self._drag_start = None
        self._drag_cur = None
        self._live = None        # in-progress item (highlight) being drawn
        self._editing = None     # active inline QLineEdit
        self._editing_pos = None

    def set_tool(self, tool):
        self._commit_text()
        self._tool = tool
        if tool == "text":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif tool in ("arrow", "rect", "highlight", "pen", "blur", "step"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def logical_size(self):
        return (self._logical_w, self._logical_h)

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        try:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(QtCore.QRectF(0, 0, self._logical_w,
                                             self._logical_h),
                               self._pixmap, QtCore.QRectF(self._pixmap.rect()))
            for item in self._editor.items:
                painter.save()
                try:
                    item.paint(painter, 1.0)
                except Exception:
                    pass
                painter.restore()
            # live preview
            prev = self._preview_item()
            if prev is not None:
                painter.save()
                try:
                    prev.paint(painter, 1.0)
                except Exception:
                    pass
                painter.restore()
            painter.end()
        except Exception:
            pass

    def _preview_item(self):
        if self._tool in ("highlight", "pen") and self._live is not None:
            return self._live
        if self._drag_start is None or self._drag_cur is None:
            return None
        col, w = self._editor.current_color(), self._editor.current_width()
        if self._tool == "arrow":
            return _ArrowItem(self._drag_start, self._drag_cur, col, w)
        if self._tool == "rect":
            return _RectItem(QRect(self._drag_start, self._drag_cur), col, w)
        if self._tool == "blur":
            return _BlurItem(QRect(self._drag_start, self._drag_cur),
                             self._pixmap)
        return None

    # ── mouse / tool interaction ─────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._tool == "text":
            self._begin_text(pos)
        elif self._tool == "step":
            n = 1 + sum(1 for it in self._editor.items
                        if isinstance(it, _StepItem))
            self._editor.add_item(_StepItem(pos, n, self._editor.current_color()))
        elif self._tool == "highlight":
            self._live = _HighlightItem([pos], self._editor.current_color(),
                                        self._editor.current_width() * 3)
            self.update()
        elif self._tool == "pen":
            self._live = _PenItem([pos], self._editor.current_color(),
                                  self._editor.current_width())   # no ×3
            self.update()
        elif self._tool in ("arrow", "rect", "blur"):
            self._drag_start = pos
            self._drag_cur = pos
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._tool in ("highlight", "pen") and self._live is not None:
            self._live.add(pos)
            self.update()
        elif self._drag_start is not None:
            self._drag_cur = pos
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._tool in ("highlight", "pen") and self._live is not None:
            # Highlight needs a real stroke (≥2 points); pen commits even a
            # single click — an opaque round dot is useful for marking points.
            min_pts = 1 if self._tool == "pen" else 2
            if len(self._live.points) >= min_pts:
                self._editor.add_item(self._live)
            self._live = None
            self.update()
            return
        if self._drag_start is None:
            return
        end = event.position().toPoint()
        start = self._drag_start
        self._drag_start = None
        self._drag_cur = None
        col, w = self._editor.current_color(), self._editor.current_width()
        if self._tool == "arrow":
            if (abs(end.x() - start.x()) + abs(end.y() - start.y())) >= 6:
                self._editor.add_item(_ArrowItem(start, end, col, w))
        elif self._tool == "rect":
            r = QRect(start, end).normalized()
            if r.width() >= 4 and r.height() >= 4:
                self._editor.add_item(_RectItem(r, col, w))
        elif self._tool == "blur":
            r = QRect(start, end).normalized()
            if r.width() >= 6 and r.height() >= 6:
                self._editor.add_item(_BlurItem(r, self._pixmap))
        self.update()

    # ── inline text editing ──────────────────────────────────────────────
    def _begin_text(self, pos):
        self._commit_text()
        edit = QtWidgets.QLineEdit(self)
        font = theme.number_font(18, 700)
        edit.setFont(font)
        fm = QtGui.QFontMetrics(font)
        edit.setStyleSheet(
            "QLineEdit{background:rgba(20,20,26,0.92);border:1px solid %s;"
            "border-radius:5px;color:%s;padding:1px 5px;}"
            % (theme.ACCENT, self._editor.current_color()))
        edit.setFixedHeight(fm.height() + 10)
        edit.resize(140, fm.height() + 10)
        edit.move(pos)

        def _grow(text):
            try:
                w = QtGui.QFontMetrics(edit.font()).horizontalAdvance(text) + 26
                edit.resize(max(140, w), edit.height())
            except Exception:
                pass
        edit.textChanged.connect(_grow)
        edit.show()
        self._editing = edit
        self._editing_pos = QPoint(pos)
        # Commit on Enter only. We intentionally do NOT connect editingFinished:
        # it can fire spuriously while the window is activating and discard the
        # field before the user types a single character. Pending text is instead
        # committed when the tool changes, a new text is started, or on Copy/Save.
        edit.returnPressed.connect(self._commit_text)
        try:
            self.window().activateWindow()
            self.window().raise_()
        except Exception:
            pass
        edit.setFocus()
        QtCore.QTimer.singleShot(0, edit.setFocus)

    def _commit_text(self):
        edit = self._editing
        if edit is None:
            return
        self._editing = None
        text = ""
        pos = self._editing_pos
        try:
            text = edit.text().strip()
            fm = QtGui.QFontMetrics(edit.font())
            cr = edit.contentsRect()
            tl = edit.mapTo(self, cr.topLeft())
            top = tl.y() + max(0, (cr.height() - fm.height()) // 2)
            pos = QPoint(tl.x(), top)
        except Exception:
            pass
        try:
            edit.deleteLater()
        except Exception:
            pass
        if text and pos is not None:
            self._editor.add_item(
                _TextItem(pos, text, size=18, color=self._editor.current_color()))
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Draggable toolbar row (dragging an empty area moves the whole window)
# ─────────────────────────────────────────────────────────────────────────────
class _ToolbarFrame(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._press = None
        self._origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.window().frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None:
            delta = event.globalPosition().toPoint() - self._press
            self.window().move(self._origin + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        self._origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# The editor window
# ─────────────────────────────────────────────────────────────────────────────
class EditorWindow(QtWidgets.QWidget):
    closed = pyqtSignal()

    def __init__(self, pixmap, mode_label="", scale=1.0,
                 on_copy=None, on_save=None, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._scale = float(scale) if scale else 1.0
        self._mode_label = mode_label or ""
        self._on_copy = on_copy
        self._on_save = on_save

        self.items = []          # live annotations (paint order)
        self._redo = []          # redo stack

        self._color = theme.SWATCHES[0]
        self._width = theme.THICKNESSES[1][1]   # "Vừa"
        self._tool_buttons = {}
        self._swatch_buttons = []
        self._thick_buttons = []

        # NOTE: no Qt.WindowType.Tool — Tool windows can't become key on macOS
        # so the inline text field would receive no keystrokes.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._build_ui()

    # ── current style accessors (used by the canvas) ─────────────────────
    def current_color(self):
        return self._color

    def current_width(self):
        return self._width

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)   # room for the glow
        outer.setSpacing(0)

        panel = QtWidgets.QFrame(self)
        panel.setObjectName("panel")
        # Bright accent border + accent glow so the editor stands out from the
        # frozen screenshot behind it (esp. over a fullscreen app, where a
        # subtle panel border blended into the background — "lẫn với màn hình").
        panel.setStyleSheet(
            "QFrame#panel{background-color:%s;border:2px solid %s;"
            "border-radius:%dpx;}" % (theme.PANEL, theme.ACCENT,
                                      theme.RADIUS_PANEL))
        theme.apply_glow(panel, color=theme.ACCENT, blur=44, dy=0, alpha=210)
        outer.addWidget(panel)

        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(theme.PAD_SM, theme.PAD_SM,
                               theme.PAD_SM, theme.PAD_SM)
        col.setSpacing(theme.GAP)

        col.addWidget(self._build_toolbar())

        # Canvas inside a scroll area so captures BIGGER than the screen can be
        # scrolled/annotated fully (the window is capped to the screen below).
        self.canvas = _Canvas(self, self._pixmap)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidget(self.canvas)
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        col.addWidget(self._scroll)

        self._select_tool("arrow")
        self._refresh_swatches()
        self._refresh_thickness()

    def _tool_btn_qss(self):
        return (
            "QPushButton{background:transparent;border:1px solid transparent;"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(201,96,40,0.16);"
            "border:1px solid rgba(201,96,40,0.45);}"
            "QPushButton:checked{background:%s;border:1px solid %s;}"
            % (theme.ACCENT, theme.ACCENT))

    def _icon_button(self, name, tip, checkable):
        btn = QtWidgets.QPushButton()
        btn.setCheckable(checkable)
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(44, 42)
        btn.setStyleSheet(self._tool_btn_qss())
        btn.setIcon(QtGui.QIcon(theme.tool_icon(name, 26, theme.TEXT_SECONDARY)))
        btn.setIconSize(QSize(26, 26))
        return btn

    def _build_toolbar(self):
        bar = _ToolbarFrame(self)
        bar.setObjectName("toolbar")
        bar.setStyleSheet("QFrame#toolbar{background:transparent;}")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(5)

        if self._mode_label:
            chip = QtWidgets.QLabel(self._mode_label)
            chip.setStyleSheet(
                "QLabel{color:%s;background:rgba(201,96,40,0.15);"
                "border:1px solid rgba(201,96,40,0.50);border-radius:7px;"
                "padding:4px 10px;font-family:'%s';font-weight:700;font-size:11px;}"
                % (theme.ACCENT, theme.family("number")))
            row.addWidget(chip)
            row.addSpacing(2)

        # Tools (checkable, exclusive)
        self._tool_group = QtWidgets.QButtonGroup(self)
        self._tool_group.setExclusive(True)
        # No "select" tool — it confused users (it did nothing). Tools all draw;
        # clicks without a drag are harmless (arrow/rect need a drag, text needs
        # a deliberate click). Move the whole editor via the toolbar drag.
        tools = [
            ("text", "Chữ (gõ trên ảnh)"),
            ("arrow", "Mũi tên"), ("rect", "Khung chữ nhật"),
            ("pen", "Vẽ tay"),
            ("highlight", "Bút dạ quang"), ("blur", "Làm mờ (che thông tin)"),
            ("step", "Đánh số bước"),
        ]
        for name, tip in tools:
            btn = self._icon_button(name, tip, True)
            btn.clicked.connect(lambda _=False, n=name: self._select_tool(n))
            self._tool_group.addButton(btn)
            self._tool_buttons[name] = btn
            row.addWidget(btn)

        row.addWidget(self._sep())

        # Color swatches
        for cidx, cval in enumerate(theme.SWATCHES):
            sw = QtWidgets.QPushButton()
            sw.setFixedSize(24, 24)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip("Màu")
            sw.clicked.connect(lambda _=False, c=cval: self._set_color(c))
            self._swatch_buttons.append((sw, cval))
            row.addWidget(sw)

        row.addWidget(self._sep())

        # Thickness presets
        for label, w in theme.THICKNESSES:
            tb = QtWidgets.QPushButton()
            tb.setCheckable(True)
            tb.setFixedSize(40, 42)
            tb.setToolTip("Độ dày: %s" % label)
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            tb.setStyleSheet(self._tool_btn_qss())
            tb.setIcon(QtGui.QIcon(self._dot_icon(w)))
            tb.setIconSize(QSize(26, 26))
            tb.clicked.connect(lambda _=False, ww=w: self._set_width(ww))
            self._thick_buttons.append((tb, w))
            row.addWidget(tb)

        row.addWidget(self._sep())

        undo = self._icon_button("undo", "Hoàn tác (%sZ)" % _MOD, False)
        undo.clicked.connect(self.undo)
        row.addWidget(undo)
        redo = self._icon_button("redo", "Làm lại (%s⇧Z)" % _MOD, False)
        redo.clicked.connect(self.redo)
        row.addWidget(redo)

        row.addStretch(1)

        cancel_btn = QtWidgets.QPushButton("✕ Huỷ")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(theme.qss_secondary_btn())
        cancel_btn.setFixedHeight(40)
        cancel_btn.setToolTip("Huỷ & chụp lại (ESC)")
        cancel_btn.clicked.connect(self.close)
        row.addWidget(cancel_btn)

        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(theme.qss_secondary_btn())
        copy_btn.setFixedHeight(40)
        copy_btn.clicked.connect(self._do_copy)
        row.addWidget(copy_btn)

        save_btn = QtWidgets.QPushButton("Lưu file")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(theme.qss_primary_btn())
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._do_save)
        row.addWidget(save_btn)
        return bar

    def _sep(self):
        line = QtWidgets.QFrame(self)
        line.setFixedSize(1, 26)
        line.setStyleSheet("background:%s;border:none;" % theme.SECONDARY_BORDER)
        return line

    def _dot_icon(self, w):
        """A filled dot whose size reflects the pen thickness."""
        pm = QtGui.QPixmap(52, 52)
        pm.setDevicePixelRatio(2.0)
        pm.fill(theme.qcolor("rgba(0,0,0,0)"))
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.qcolor(theme.TEXT_SECONDARY))
        r = 4 + w
        p.drawEllipse(QtCore.QPointF(13, 13), r / 2.0, r / 2.0)
        p.end()
        return pm

    # ── tool / style selection ───────────────────────────────────────────
    def _select_tool(self, name):
        for n, btn in self._tool_buttons.items():
            btn.setChecked(n == name)
            col = theme.TEXT_PRIMARY if n == name else theme.TEXT_SECONDARY
            btn.setIcon(QtGui.QIcon(theme.tool_icon(n, 26, col)))
        try:
            self.canvas.set_tool(name)
        except Exception:
            pass

    def _set_color(self, c):
        self._color = c
        self._refresh_swatches()

    def _refresh_swatches(self):
        for sw, cval in self._swatch_buttons:
            sel = (cval == self._color)
            border = theme.TEXT_PRIMARY if sel else theme.SECONDARY_BORDER
            sw.setStyleSheet(
                "QPushButton{background:%s;border:2px solid %s;border-radius:12px;}"
                % (cval, border))

    def _set_width(self, w):
        self._width = w
        self._refresh_thickness()

    def _refresh_thickness(self):
        for tb, w in self._thick_buttons:
            tb.setChecked(w == self._width)

    # ── annotation model + undo/redo ─────────────────────────────────────
    def add_item(self, item):
        self.items.append(item)
        self._redo.clear()
        try:
            self.canvas.update()
        except Exception:
            pass

    def undo(self):
        if not self.items:
            return
        self._redo.append(self.items.pop())
        try:
            self.canvas.update()
        except Exception:
            pass

    def redo(self):
        if not self._redo:
            return
        self.items.append(self._redo.pop())
        try:
            self.canvas.update()
        except Exception:
            pass

    # ── flatten to full-resolution QImage ────────────────────────────────
    def flattened(self):
        size = self._pixmap.size()
        image = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32)
        try:
            image.fill(Qt.GlobalColor.transparent)
        except Exception:
            pass
        try:
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(QtCore.QRect(0, 0, size.width(), size.height()),
                               self._pixmap)
            for item in self.items:
                painter.save()
                try:
                    item.paint(painter, self._scale)
                except Exception:
                    pass
                painter.restore()
            painter.end()
        except Exception:
            pass
        return image

    # ── Copy / Save ──────────────────────────────────────────────────────
    def _commit_pending(self):
        try:
            self.canvas._commit_text()
        except Exception:
            pass

    def _do_copy(self):
        if self._on_copy is None:
            return
        self._commit_pending()
        ok = True
        try:
            ok = self._on_copy(self.flattened())
        except Exception:
            ok = False
        # Close only if the copy didn't fail — never destroy the user's only copy
        # of the annotated image on an error (ok is None = legacy success).
        if ok is not False:
            self.close()

    def _do_save(self):
        if self._on_save is None:
            return
        self._commit_pending()
        ok = False
        try:
            ok = bool(self._on_save(self.flattened()))
        except Exception:
            ok = False
        if ok:
            self.close()

    # ── show + placement ─────────────────────────────────────────────────
    def _cap_scroll_to_screen(self):
        """Cap the canvas viewport to the screen so a capture larger than the
        display scrolls instead of growing the window off-screen."""
        try:
            screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) \
                or QtGui.QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            cw, ch = self.canvas.logical_size()
            max_w = min(cw, avail.width() - 60)
            max_h = min(ch, avail.height() - 150)   # room for toolbar + margins
            self._scroll.setMaximumSize(max(120, max_w), max(120, max_h))
            self._scroll.setMinimumSize(min(cw, max_w), min(ch, max_h))
        except Exception:
            pass

    def show_editor(self):
        self._cap_scroll_to_screen()
        self.adjustSize()
        self._clamp_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()

    def place_canvas_over(self, gx, gy):
        """Position the window so the CANVAS (frozen screenshot) lands exactly on
        the just-selected region at global (gx, gy) — so annotation feels like it
        happens 'in place' on the selection, not in a separate window. The toolbar
        floats just above; the whole window is clamped to stay on-screen."""
        try:
            self.adjustSize()
            # Offset of the canvas's top-left within the window chrome.
            off = self.canvas.mapTo(self, QtCore.QPoint(0, 0))
            x = int(gx) - off.x()
            y = int(gy) - off.y()
            scr = QtGui.QGuiApplication.screenAt(
                QtCore.QPoint(int(gx), int(gy))) \
                or QtGui.QGuiApplication.primaryScreen()
            w, h = self.width(), self.height()
            if scr is not None:
                avail = scr.availableGeometry()
                m = 6
                x = max(avail.left() + m,
                        min(x, avail.right() - w - m))
                y = max(avail.top() + m,
                        min(y, avail.bottom() - h - m))
            self.move(int(x), int(y))
        except Exception:
            # Fall back to the plain top-left placement.
            try:
                self.move(int(gx), int(gy))
            except Exception:
                pass

    def _clamp_on_screen(self):
        try:
            self.adjustSize()
            geo = self.frameGeometry()
            screen = QtGui.QGuiApplication.screenAt(geo.center()) \
                or QtGui.QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            w, h = geo.width(), geo.height()
            margin = 8
            x = min(max(avail.left() + margin, self.x()),
                    max(avail.left() + margin, avail.right() - w - margin))
            y = min(max(avail.top() + margin, self.y()),
                    max(avail.top() + margin, avail.bottom() - h - margin))
            self.move(int(x), int(y))
        except Exception:
            pass

    # ── keyboard ─────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key == Qt.Key.Key_Z and ctrl:
            self.redo() if shift else self.undo()
            return
        # ⌘C copies the annotated image then closes (skip while typing text —
        # the inline QLineEdit handles ⌘C itself and won't reach here).
        if key == Qt.Key.Key_C and ctrl and self.canvas._editing is None:
            self._do_copy()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)
