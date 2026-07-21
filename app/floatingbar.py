"""
floatingbar.py — Block D · the always-on-top floating launcher bar.

A tiny horizontal brand bar that floats over every other window. It shows the
"FC" logo mark plus five ghost mode buttons (1..5) and a small "—" hide button.
Clicking a number emits ``modeTriggered(n)``; clicking "—" emits
``hideRequested``. The whole bar can be dragged anywhere on screen by pressing
on any empty area (not on a button).

The brand design (panel colors, ghost-button QSS, accent, heading font) comes
entirely from ``theme``. Position persistence is handled locally so the bar
re-appears where the user last left it.

Target: Python 3.9+, PyQt6, macOS. Imports cleanly with no QApplication (all Qt
objects are constructed inside the class, never at module top level).
"""
from __future__ import annotations

import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal, QPoint

import theme

_IS_WIN = sys.platform.startswith("win")


# Tooltips for the 5 mode buttons (Vietnamese, exact brand strings) ────────────
_MODE_TOOLTIPS = {
    1: "Chụp nhanh",
    2: "Chụp + Edit",
    3: "Chụp khóa kích thước",
    4: "Chụp cửa sổ",
    5: "Quay GIF",
    6: "Chụp + tự lưu",
    7: "Quét lấy chữ (OCR)",
}


class FloatingBar(QtWidgets.QWidget):
    """Frameless, translucent, always-on-top launcher bar.

    Signals
    -------
    modeTriggered(int) : emitted with the mode number (1..5) when a button is
                         clicked.
    hideRequested()    : emitted when the small "—" button is clicked.
    """

    modeTriggered = pyqtSignal(int)
    hideRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Frameless, translucent, always-on-top utility window. Using the Tool
        # FramelessWindowHint removes the title bar; WindowStaysOnTopHint keeps
        # it above other apps. IMPORTANT: do NOT use Qt.WindowType.Tool — on
        # macOS a Tool/utility window AUTO-HIDES whenever the app is not the
        # frontmost one, so the bar would vanish the moment you click another
        # app. A plain frameless always-on-top window stays visible everywhere.
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint)
        if _IS_WIN:
            # On Windows a Tool window does NOT auto-hide (that macOS quirk is why
            # it's avoided above); it just keeps this always-on-top launcher bar
            # off the taskbar, which is what we want here.
            flags |= Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Drag state — None when not dragging; otherwise the offset from the
        # window top-left to the press point (global).
        self._drag_offset = None
        # Remembers whether show_bar() has positioned the bar at least once.
        self._positioned = False
        # Last known top-left position (restored on subsequent show_bar calls).
        self._last_pos = None

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        """Build the root panel + logo + 5 mode buttons + hide button."""
        # Outer layout holds only the rounded panel; margins give the drop
        # shadow / accent glow room to render without being clipped.
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)

        # Root rounded panel — premium dark gradient via theme.qss_bar().
        self._panel = QtWidgets.QFrame(self)
        self._panel.setObjectName("fcFloatingPanel")
        self._panel.setStyleSheet(
            "QFrame#fcFloatingPanel{" + theme.qss_bar() + "}"
        )
        outer.addWidget(self._panel)

        # Soft accent glow under the panel for a floating, premium feel.
        # Best-effort — graphics effects must never break the bar.
        try:
            theme.apply_glow(self._panel, blur=26, dy=8, alpha=90)
        except Exception:
            pass

        row = QtWidgets.QHBoxLayout(self._panel)
        row.setContentsMargins(theme.PAD, 8, theme.PAD, 8)
        row.setSpacing(5)

        # Left: tiny "FC" logo mark in ACCENT using the bold heading font.
        logo = QtWidgets.QLabel("FC", self._panel)
        logo.setFont(theme.heading_font(14, 800))
        logo.setStyleSheet(
            "QLabel{color:#FFFFFF;padding:5px 9px;border-radius:8px;"
            "background:%s;}" % theme.ACCENT
        )
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(logo)

        # Thin vertical separator after the logo mark.
        sep = QtWidgets.QFrame(self._panel)
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(
            "background:%s;border:none;margin:5px 4px;" % theme.SECONDARY_BORDER
        )
        sep.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(sep)
        row.addSpacing(2)

        # Seven ghost mode buttons with vector icons + Vietnamese tooltips.
        tool_qss = theme.qss_tool_btn()
        for n in range(1, 8):
            btn = QtWidgets.QPushButton(self._panel)
            btn.setToolTip(_MODE_TOOLTIPS[n])
            btn.setStyleSheet(tool_qss)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(44, 38)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # Crisp vector icon for each capture mode (premium, no plain text).
            try:
                pm = theme.mode_icon(n, 24)
                btn.setIcon(QtGui.QIcon(pm))
                btn.setIconSize(QtCore.QSize(24, 24))
            except Exception:
                # Fall back to the original numeric label if icons fail.
                btn.setText(str(n))
                btn.setFont(theme.number_font(13, 600))
            # Bind n per-iteration via default arg to avoid late-binding bug.
            btn.clicked.connect(lambda _checked=False, m=n: self.modeTriggered.emit(m))
            row.addWidget(btn)

        # Right: small "—" hide button → emits hideRequested.
        row.addSpacing(2)
        sep2 = QtWidgets.QFrame(self._panel)
        sep2.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep2.setFixedWidth(1)
        sep2.setStyleSheet(
            "background:%s;border:none;margin:5px 4px;" % theme.SECONDARY_BORDER
        )
        sep2.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(sep2)

        hide_btn = QtWidgets.QPushButton("—", self._panel)
        hide_btn.setToolTip("Ẩn thanh nổi")
        hide_btn.setStyleSheet(tool_qss)
        hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        hide_btn.setFixedSize(36, 36)
        hide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hide_btn.setFont(theme.number_font(15, 700))
        # clicked emits a bool; hideRequested takes 0 args → drop it via lambda.
        hide_btn.clicked.connect(lambda _checked=False: self.hideRequested.emit())
        row.addSpacing(2)
        row.addWidget(hide_btn)

    # ──────────────────────────────────────────────────────────────────────
    # Show / positioning
    # ──────────────────────────────────────────────────────────────────────
    def show_bar(self):
        """Show the bar top-most, positioning it near top-center the first
        time and restoring the last position on subsequent calls."""
        # Make sure the widget has a valid sizeHint before we position it.
        self.adjustSize()

        if not self._positioned:
            self._position_top_center()
            self._positioned = True
        elif self._last_pos is not None:
            # Restore the remembered position (e.g. after a hide/show cycle).
            self.move(self._last_pos)

        self.show()
        self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass
        self._pin_all_spaces()
        self._clear_hover()

    def _clear_hover(self):
        """Clear any stuck :hover highlight on the buttons.

        When a mode button is clicked, the bar hides for the capture WHILE the
        cursor is still over the button, so Qt never delivers the Leave event —
        the accent hover border then 'sticks' when the bar reappears. We send a
        synthetic Leave + clear the under-mouse flag to reset each button.
        """
        try:
            for btn in self._panel.findChildren(QtWidgets.QPushButton):
                btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                QtWidgets.QApplication.sendEvent(
                    btn, QtCore.QEvent(QtCore.QEvent.Type.Leave))
                btn.update()
        except Exception:
            pass

    def _pin_all_spaces(self):
        """Safe no-op hook. The bar stays above ordinary windows via
        Qt.WindowType.WindowStaysOnTopHint. (Bridging winId()→NSWindow to pin it
        to every Space could SEGFAULT — an uncatchable C-level crash — so we keep
        this a no-op for stability.)"""
        return

    def _position_top_center(self):
        """Place the bar near the top-center of the primary screen."""
        try:
            screen = QtGui.QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            bar = self.frameGeometry()
            x = geo.x() + (geo.width() - bar.width()) // 2
            # A little gap below the top edge so it doesn't hug the menu bar.
            y = geo.y() + 24
            self.move(int(x), int(y))
            self._last_pos = self.pos()
        except Exception:
            # If anything about screen geometry fails, just show at origin-ish.
            self.move(120, 80)
            self._last_pos = self.pos()

    # ──────────────────────────────────────────────────────────────────────
    # Dragging — press on empty area, then move the whole window
    # ──────────────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        """Begin dragging when the press is on an empty area (not a button)."""
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            # Only start a drag if we did NOT press on an interactive button.
            if not isinstance(child, QtWidgets.QPushButton):
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Move the window while dragging."""
        if self._drag_offset is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            self._last_pos = self.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End the drag and persist the final position."""
        if self._drag_offset is not None:
            self._drag_offset = None
            self._last_pos = self.pos()
            event.accept()
            return
        super().mouseReleaseEvent(event)
