"""
notify.py — FC-FastCapture brand toast (Block G · "10XLifeOS").

A small frameless, translucent toast that appears at the bottom-right corner of
the primary screen, auto-dismissing after 2 seconds. It is used by main.py for
quick non-blocking feedback ("Đã copy vào clipboard", a saved filename, errors…).

Public API:
    show_toast(message, ok=True, parent=None) -> Toast
    class Toast(QtWidgets.QWidget)

All brand colors/fonts/QSS come from `theme` — nothing is hardcoded. Qt objects
are only constructed inside class/function bodies, so this module imports cleanly
with no QApplication and no display. Every risky call is guarded.

Target: Python 3.9+, PyQt6, macOS first.
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer

import theme

# Module-level strong references to live toasts so the garbage collector does not
# destroy them while they are still on screen. Appended on show, removed on close.
_active = []  # type: list

# Visual constants (local layout tuning only — brand values come from theme).
_MARGIN = 24          # gap from the screen's bottom-right corner (logical px)
_AUTO_CLOSE_MS = 2000  # auto-dismiss after 2 seconds
_FADE_MS = 180         # gentle fade-in duration


class Toast(QtWidgets.QWidget):
    """A single brand toast widget.

    Frameless + translucent top-level. The visible surface is an inner panel
    styled with theme.qss_bar() (premium dark gradient, rounded 12) carrying a
    soft accent glow. Inside: a slim accent edge bar + a colored status dot, an
    accent badge ("FC ✓" success / "FC ✕" error) followed by the white message
    label in the Inter (number) font. Self-closes after 2000ms.
    """

    def __init__(self, message, ok=True, parent=None):
        super().__init__(parent)
        self._message = "" if message is None else str(message)
        self._ok = bool(ok)
        self._fade = None  # keep a strong ref to the running animation

        # Frameless, always-on-top toast that never steals focus. No
        # Qt.WindowType.Tool — Tool windows auto-hide when the app isn't
        # frontmost, so the toast would never be seen over other apps.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._build_ui()

        # Auto-close timer — single-shot, fires once 2s after the toast is shown.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_AUTO_CLOSE_MS)
        self._timer.timeout.connect(self.close)

    # ── construction ─────────────────────────────────────────────────────
    def _build_ui(self):
        """Build the panel + row (badge + message). Wrapped so a styling error
        never bubbles up to main."""
        try:
            # Status color drives the accent dot / edge bar / badge.
            # Always brand orange (consistent) — ✓ / ✕ glyph shows success/error.
            status = theme.ACCENT

            # Outer transparent margin lets the drop shadow / glow breathe.
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(18, 16, 18, 18)
            outer.setSpacing(0)

            # Inner brand panel — the actual visible surface (premium gradient).
            panel = QtWidgets.QFrame(self)
            panel.setObjectName("panel")
            panel.setStyleSheet("QFrame#panel{%s}" % theme.qss_bar())
            outer.addWidget(panel)

            row = QtWidgets.QHBoxLayout(panel)
            row.setContentsMargins(theme.PAD_SM, theme.PAD_SM, theme.PAD,
                                   theme.PAD_SM)
            row.setSpacing(theme.GAP)

            # Slim accent edge bar (left) for a premium floating-card feel.
            edge = QtWidgets.QFrame(panel)
            edge.setFixedWidth(3)
            edge.setMinimumHeight(20)
            edge.setStyleSheet(
                "background:%s;border-radius:1px;" % status)
            edge.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            row.addWidget(edge, 0)

            # Colored status dot before the badge.
            dot = QtWidgets.QLabel("●", panel)
            dot.setFont(theme.number_font(11, 700))
            dot.setStyleSheet(
                "color:%s;background:transparent;" % status)
            dot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            row.addWidget(dot, 0)

            # Accent badge: success → "FC ✓" (SUCCESS), error → "FC ✕" (ACCENT).
            badge = QtWidgets.QLabel("FC ✓" if self._ok else "FC ✕", panel)
            badge.setFont(theme.number_font(13, 700))
            badge.setStyleSheet(
                "color:%s;font-weight:700;background:transparent;" % status)
            badge.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            row.addWidget(badge, 0)

            # White message label in the Inter (number) font.
            msg = QtWidgets.QLabel(self._message, panel)
            msg.setFont(theme.number_font(13, 500))
            msg.setStyleSheet(
                "color:%s;background:transparent;" % theme.TEXT_PRIMARY)
            msg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            row.addWidget(msg, 1)

            # Premium accent glow on the panel for a floating, lifted feel.
            try:
                theme.apply_glow(panel, color=status, blur=34, dy=8, alpha=160)
            except Exception:
                pass

            self.adjustSize()
        except Exception:
            # Never let a styling/layout failure crash the caller.
            pass

    # ── positioning ──────────────────────────────────────────────────────
    def _move_to_corner(self):
        """Place the toast at the bottom-right of the primary screen's available
        geometry, leaving a ~24px margin. Falls back silently on any error."""
        try:
            screen = QtWidgets.QApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            size = self.sizeHint()
            x = geo.right() - size.width() - _MARGIN
            y = geo.bottom() - size.height() - _MARGIN
            self.move(int(x), int(y))
        except Exception:
            pass

    # ── lifecycle ────────────────────────────────────────────────────────
    def show_toast(self):
        """Show the toast, register it in _active, position it and start the
        auto-close timer."""
        try:
            if self not in _active:
                _active.append(self)
            self.adjustSize()
            self._move_to_corner()
            self.show()
            self.raise_()
            self._move_to_corner()  # re-place after the final size is known
            self._start_fade_in()
            self._timer.start()
        except Exception:
            # If showing fails, make sure we are not leaking a dead ref.
            try:
                if self in _active:
                    _active.remove(self)
            except Exception:
                pass

    def _start_fade_in(self):
        """Gentle fade-in on window opacity. Best-effort; never affects the 2s
        lifetime (the auto-close timer runs independently)."""
        try:
            self.setWindowOpacity(0.0)
            anim = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(_FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self._fade = anim
            anim.start()
        except Exception:
            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

    def closeEvent(self, event):
        """Remove our strong reference so the widget can be GC'd after close."""
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        try:
            if self in _active:
                _active.remove(self)
        except Exception:
            pass
        super().closeEvent(event)


def show_toast(message, ok=True, parent=None):
    """Create, show and return a brand Toast at the bottom-right corner.

    message : text shown next to the accent badge.
    ok      : True → success badge "FC ✓" (SUCCESS); False → "FC ✕" (ACCENT).
    parent  : optional parent QWidget (toast still floats as a top-level Tool).

    Returns the Toast (or None if construction failed). Never raises.
    """
    try:
        toast = Toast(message, ok=ok, parent=parent)
        toast.show_toast()
        return toast
    except Exception:
        return None
