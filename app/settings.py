"""
settings.py — FC-FastCapture settings window (Block E · "10XLifeOS").

A dark, brand-styled preferences window where the user can:
  • re-bind the 6 global hotkeys (mode1..mode5 + the floating bar),
  • set the Mode 3 locked capture size (W × H),
  • toggle "remember selection size" and "auto-launch on login",
  • pick the default save folder.

On "Lưu" everything is written back into the shared Config, the macOS
LaunchAgent is enabled/disabled to match the auto-launch toggle, then `saved`
is emitted so main.py can re-register hotkeys.

All brand design (colors / fonts / QSS) comes from `theme`; persistence from the
`config` object passed in. Imports cleanly with no QApplication — every Qt object
is constructed inside methods, never at module top level.

Target: Python 3.9+, PyQt6, macOS.
"""
from __future__ import annotations

import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

import theme
import config

_IS_WIN = sys.platform.startswith("win")


# Cocoa (NSEvent) modifier flag bits — read via event.nativeModifiers() so the
# PHYSICAL key is unambiguous (Qt's event.modifiers() swaps Cmd/Ctrl on macOS,
# which made the recorder store the wrong modifier).
_NSCommand = 0x100000
_NSOption = 0x80000
_NSControl = 0x40000
_NSShift = 0x20000
_NATIVE_MODS = [(_NSCommand, "<cmd>"), (_NSOption, "<alt>"),
                (_NSControl, "<ctrl>"), (_NSShift, "<shift>")]

# macOS virtual key code → character (digits + letters), for the recorded key.
_VK_TO_CHAR = {
    29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7",
    28: "8", 25: "9", 0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g",
    4: "h", 34: "i", 38: "j", 40: "k", 37: "l", 46: "m", 45: "n", 31: "o",
    35: "p", 12: "q", 15: "r", 1: "s", 17: "t", 32: "u", 9: "v", 13: "w",
    7: "x", 16: "y", 6: "z",
}
_LONE_MODS = (Qt.Key.Key_Control, Qt.Key.Key_Meta, Qt.Key.Key_Alt,
              Qt.Key.Key_Shift, Qt.Key.Key_CapsLock)


class HotkeyRecorder(QtWidgets.QPushButton):
    """Click → 'press a combo' → records it. Shows ⌘⌥1-style label; stores the
    pynput string ('<cmd>+<alt>+1'). Supports digits + letters with ≥1 modifier."""

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self._combo = combo or ""
        self._recording = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(150)
        self.setFixedHeight(34)
        self.setFont(theme.number_font(13, 600))
        self.clicked.connect(self._toggle)
        self._refresh()

    def combo(self):
        return self._combo

    def _refresh(self):
        if self._recording:
            self.setText("Nhấn tổ hợp phím…")
        else:
            self.setText(config.pretty_combo(self._combo))
        self.setChecked(self._recording)

    def _toggle(self):
        self._recording = not self._recording
        if self._recording:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._refresh()

    def keyPressEvent(self, event):
        if not self._recording:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._recording = False
            self._refresh()
            return
        if key in _LONE_MODS:
            return  # wait for the real key
        if _IS_WIN:
            # Windows: Qt's cross-platform modifiers are unambiguous (no Cmd/Ctrl
            # swap), so read them directly instead of Cocoa native flags.
            parts = self._win_mods(event)
        else:
            # Physical modifiers from the native Cocoa flags (unambiguous).
            try:
                nm = int(event.nativeModifiers())
            except Exception:
                nm = 0
            parts = [tok for bit, tok in _NATIVE_MODS if nm & bit]
        ch = self._key_char(event)
        if not parts or ch is None:
            # Need at least one modifier + a digit/letter.
            self.setText("Cần Ctrl/Alt/Shift + phím" if _IS_WIN
                         else "Cần ⌘/⌥/⌃/⇧ + phím")
            return
        parts.append(ch)
        self._combo = "+".join(parts)
        self._recording = False
        self._refresh()

    @staticmethod
    def _win_mods(event):
        """Modifier tokens from Qt's cross-platform modifier flags (Windows)."""
        mods = event.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("<ctrl>")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("<alt>")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("<shift>")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("<cmd>")   # the Windows / Super key
        return parts

    @staticmethod
    def _key_char(event):
        # macOS: prefer the native virtual key (layout/Option independent). On
        # Windows the native VK table differs, so fall straight through to the
        # cross-platform Qt key (which equals ASCII for 0-9 / A-Z).
        if not _IS_WIN:
            try:
                vk = int(event.nativeVirtualKey())
                if vk in _VK_TO_CHAR:
                    return _VK_TO_CHAR[vk]
            except Exception:
                pass
        key = event.key()
        if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
            return chr(key)
        if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
            return chr(key).lower()
        return None


# Hotkey rows in display order: (config name, Vietnamese label).
_HOTKEY_ROWS = [
    ("mode1", "Chụp nhanh"),
    ("mode2", "Chụp + Edit"),
    ("mode3", "Chụp khóa kích thước"),
    ("mode4", "Chụp cửa sổ"),
    ("mode5", "Quay GIF"),
    ("mode6", "Chụp + tự lưu"),
    ("floatingbar", "Thanh nổi"),
]


class SettingsWindow(QtWidgets.QWidget):
    """Brand settings window. `saved` fires after a successful save."""

    saved = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config

        # Widget references populated while building the UI.
        self._hotkey_recorders = {}      # name -> HotkeyRecorder
        self._w_spin = None              # locked width QSpinBox
        self._h_spin = None              # locked height QSpinBox
        self._remember_chk = None        # giữ nguyên vùng chọn lần trước
        self._ask_folder_chk = None      # hỏi vị trí trước khi lưu
        self._autolaunch_chk = None      # auto-launch on login
        self._save_dir = self._cfg.save_dir()
        self._save_dir_lbl = None        # muted QLabel showing current folder
        self._m6_dir = self._cfg.mode6_dir()      # Mode 6 auto-save folder
        self._m6_dir_lbl = None

        self.setWindowTitle("FC-FastCapture — Cài đặt")
        self.setMinimumWidth(580)
        self.setStyleSheet(theme.app_qss())

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────
    def _panel(self):
        """Return a styled #panel QFrame with an empty vertical layout."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("panel")
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(theme.PAD + 2, theme.PAD + 2,
                               theme.PAD + 2, theme.PAD + 2)
        lay.setSpacing(theme.GAP)
        return frame, lay

    def _section_title(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setProperty("role", "subtitle")
        return lbl

    def _divider(self):
        """A thin accent gradient divider line."""
        line = QtWidgets.QFrame()
        line.setFixedHeight(2)
        line.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {theme.ACCENT}, stop:0.7 rgba(201,96,40,0.15),"
            f"stop:1 rgba(201,96,40,0));"
            f"border:none;border-radius:1px;")
        return line

    def _build_ui(self):
        # Scrollable body so the window stays usable on small screens.
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        container = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(container)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(theme.GAP + 6)
        scroll.setWidget(container)

        root.addWidget(self._build_header())

        hotkeys_card = self._build_hotkeys()
        root.addWidget(hotkeys_card)
        # Soft accent glow on the main (largest) card for premium depth.
        theme.apply_glow(hotkeys_card, blur=36, dy=10, alpha=70)

        root.addWidget(self._build_locked_size())
        root.addWidget(self._build_toggles())
        root.addWidget(self._build_save_dir())
        root.addStretch(1)

        # Footer (Lưu / Đóng) is PINNED below the scroll area — never scrolls
        # off, so the primary Save action is always visible.
        footer = QtWidgets.QWidget()
        fl = QtWidgets.QVBoxLayout(footer)
        fl.setContentsMargins(28, 10, 28, 16)
        fl.setSpacing(0)
        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:%s;border:none;" % theme.PANEL_BORDER)
        fl.addWidget(divider)
        fl.addSpacing(10)
        fl.addLayout(self._build_footer())
        outer.addWidget(footer)

    def _build_header(self):
        frame, lay = self._panel()
        lay.setSpacing(theme.PAD_SM)

        title = QtWidgets.QLabel("FC-FastCapture")
        title.setProperty("role", "title")
        try:
            title.setFont(theme.heading_font(26, 800))
            title.setStyleSheet(f"color:{theme.ACCENT};")
        except Exception:
            pass
        lay.addWidget(title)

        sig = QtWidgets.QLabel(theme.SIGNATURE)
        sig.setProperty("role", "signature")
        lay.addWidget(sig)

        lay.addSpacing(theme.PAD_SM - 4)
        lay.addWidget(self._divider())
        return frame

    def _build_hotkeys(self):
        frame, lay = self._panel()
        lay.addWidget(self._section_title("Cài đặt phím tắt"))

        sub = QtWidgets.QLabel(
            "Bấm vào ô rồi nhấn tổ hợp phím (vd %s) để đổi"
            % ("Ctrl+Alt+1" if _IS_WIN else "⌘1"))
        sub.setProperty("role", "muted")
        lay.addWidget(sub)
        lay.addSpacing(2)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(theme.GAP + 2)
        grid.setVerticalSpacing(theme.PAD_SM)
        grid.setColumnStretch(1, 1)

        for row, (name, vi_label) in enumerate(_HOTKEY_ROWS):
            lbl = QtWidgets.QLabel(vi_label)
            lbl.setProperty("role", "secondary")
            try:
                rec = HotkeyRecorder(self._cfg.hotkey(name))
            except Exception:
                rec = HotkeyRecorder("")
            self._hotkey_recorders[name] = rec
            grid.addWidget(lbl, row, 0)
            grid.addWidget(rec, row, 1)

        lay.addLayout(grid)
        return frame

    def _build_locked_size(self):
        frame, lay = self._panel()
        lay.addWidget(self._section_title("Mode 3 — kích thước khoá"))

        sub = QtWidgets.QLabel("Vùng chụp cố định theo W × H (pixel)")
        sub.setProperty("role", "muted")
        lay.addWidget(sub)
        lay.addSpacing(2)

        try:
            lw, lh = self._cfg.locked_size()
        except Exception:
            lw, lh = 1200, 1800

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(theme.GAP)

        w_lbl = QtWidgets.QLabel("Rộng (W)")
        w_lbl.setProperty("role", "secondary")
        self._w_spin = QtWidgets.QSpinBox()
        self._w_spin.setRange(50, 10000)
        self._w_spin.setFont(theme.number_font())
        self._w_spin.setValue(int(lw))
        self._w_spin.setMinimumWidth(110)

        sep = QtWidgets.QLabel("×")
        sep.setProperty("role", "size")

        h_lbl = QtWidgets.QLabel("Cao (H)")
        h_lbl.setProperty("role", "secondary")
        self._h_spin = QtWidgets.QSpinBox()
        self._h_spin.setRange(50, 10000)
        self._h_spin.setFont(theme.number_font())
        self._h_spin.setValue(int(lh))
        self._h_spin.setMinimumWidth(110)

        row.addWidget(w_lbl)
        row.addWidget(self._w_spin)
        row.addSpacing(theme.PAD_SM)
        row.addWidget(sep)
        row.addSpacing(theme.PAD_SM)
        row.addWidget(h_lbl)
        row.addWidget(self._h_spin)
        row.addStretch(1)
        lay.addLayout(row)
        return frame

    def _build_toggles(self):
        frame, lay = self._panel()
        lay.addWidget(self._section_title("Tuỳ chọn"))
        lay.addSpacing(2)

        # 1 · Keep the previous selection size (Block C: remember-size).
        self._remember_chk = QtWidgets.QCheckBox("Giữ nguyên vùng chọn lần trước")
        try:
            self._remember_chk.setChecked(bool(self._cfg.get("remember_size", True)))
        except Exception:
            self._remember_chk.setChecked(True)
        lay.addWidget(self._remember_chk)

        # 2 · Ask for the save folder before each save (inverse of remember_folder).
        self._ask_folder_chk = QtWidgets.QCheckBox("Hỏi vị trí trước khi lưu")
        try:
            self._ask_folder_chk.setChecked(not bool(self._cfg.remember_folder()))
        except Exception:
            self._ask_folder_chk.setChecked(True)
        lay.addWidget(self._ask_folder_chk)

        self._autolaunch_chk = QtWidgets.QCheckBox(
            "Tự mở khi khởi động Windows" if _IS_WIN
            else "Tự mở khi khởi động Mac")
        try:
            self._autolaunch_chk.setChecked(bool(self._cfg.get("auto_launch", True)))
        except Exception:
            self._autolaunch_chk.setChecked(True)
        lay.addWidget(self._autolaunch_chk)
        return frame

    def _build_save_dir(self):
        frame, lay = self._panel()
        lay.addWidget(self._section_title("Lưu file"))

        sub = QtWidgets.QLabel("Thư mục lưu mặc định")
        sub.setProperty("role", "muted")
        lay.addWidget(sub)

        self._save_dir_lbl = QtWidgets.QLabel(self._save_dir or "")
        self._save_dir_lbl.setProperty("role", "secondary")
        self._save_dir_lbl.setWordWrap(True)
        lay.addWidget(self._save_dir_lbl)
        lay.addSpacing(2)

        btn = QtWidgets.QPushButton("Chọn thư mục lưu mặc định...")
        btn.setProperty("variant", "secondary")
        btn.clicked.connect(self._pick_save_dir)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)

        # Mode 6 — the auto-save folder ("Chụp + tự lưu"). Separate from the
        # editor save folder above; first ⌘6 capture asks if still empty.
        lay.addSpacing(8)
        sub6 = QtWidgets.QLabel("Thư mục tự lưu (Chụp + tự lưu)")
        sub6.setProperty("role", "muted")
        lay.addWidget(sub6)
        self._m6_dir_lbl = QtWidgets.QLabel(
            self._m6_dir or "(chưa chọn — lần chụp đầu sẽ hỏi)")
        self._m6_dir_lbl.setProperty("role", "secondary")
        self._m6_dir_lbl.setWordWrap(True)
        lay.addWidget(self._m6_dir_lbl)
        lay.addSpacing(2)
        btn6 = QtWidgets.QPushButton("Chọn thư mục tự lưu...")
        btn6.setProperty("variant", "secondary")
        btn6.clicked.connect(self._pick_m6_dir)
        row6 = QtWidgets.QHBoxLayout()
        row6.addWidget(btn6)
        row6.addStretch(1)
        lay.addLayout(row6)
        return frame

    def _build_footer(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(theme.GAP)
        row.addStretch(1)

        close_btn = QtWidgets.QPushButton("Đóng")
        close_btn.setProperty("variant", "secondary")
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)

        save_btn = QtWidgets.QPushButton("Lưu")
        try:
            save_btn.setStyleSheet(theme.qss_primary_btn())
            save_btn.setMinimumWidth(120)
            theme.apply_glow(save_btn, blur=24, dy=6, alpha=120)
        except Exception:
            pass
        save_btn.clicked.connect(self._on_save)
        row.addWidget(save_btn)
        return row

    # ── actions ──────────────────────────────────────────────────────────
    def _pick_save_dir(self):
        try:
            start = self._save_dir or ""
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Chọn thư mục lưu mặc định", start)
        except Exception:
            chosen = ""
        if chosen:
            self._save_dir = chosen
            if self._save_dir_lbl is not None:
                self._save_dir_lbl.setText(chosen)

    def _pick_m6_dir(self):
        try:
            start = self._m6_dir or self._save_dir or ""
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Chọn thư mục tự lưu (Chụp + tự lưu)", start)
        except Exception:
            chosen = ""
        if chosen:
            self._m6_dir = chosen
            if self._m6_dir_lbl is not None:
                self._m6_dir_lbl.setText(chosen)

    def _on_save(self):
        """Persist every control, sync auto-launch, emit `saved`, close."""
        # Hotkeys — store the recorded pynput strings.
        for name, rec in self._hotkey_recorders.items():
            try:
                combo = rec.combo().strip()
                if combo:
                    self._cfg.set_hotkey(name, combo)
            except Exception:
                pass

        # Mode 3 locked size.
        try:
            self._cfg.set("locked_width", int(self._w_spin.value()))
            self._cfg.set("locked_height", int(self._h_spin.value()))
        except Exception:
            pass

        # Toggles.
        try:
            self._cfg.set("remember_size", bool(self._remember_chk.isChecked()))
        except Exception:
            pass

        # "Hỏi vị trí trước khi lưu" → inverse of remember_folder.
        try:
            ask = bool(self._ask_folder_chk.isChecked())
            self._cfg.set("remember_folder", not ask)
        except Exception:
            pass

        auto_launch = True
        try:
            auto_launch = bool(self._autolaunch_chk.isChecked())
            self._cfg.set("auto_launch", auto_launch)
        except Exception:
            pass

        # Save folder.
        try:
            if self._save_dir:
                self._cfg.set_save_dir(self._save_dir)
        except Exception:
            pass

        # Mode 6 auto-save folder (only when the user actually picked one —
        # empty means "keep asking on first capture").
        try:
            if self._m6_dir:
                self._cfg.set_mode6_dir(self._m6_dir)
        except Exception:
            pass

        # Sync the macOS LaunchAgent to match the toggle — never crash.
        try:
            import autolaunch
            if auto_launch:
                autolaunch.enable()
            else:
                autolaunch.disable()
        except Exception:
            pass

        self.saved.emit()
        self.close()

    # ── presentation ─────────────────────────────────────────────────────
    def show_settings(self):
        """Size to content (capped to screen) so Save is visible, then center."""
        self.show()
        try:
            screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) \
                or QtGui.QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            # Tall enough that most of the content shows without scrolling, but
            # never taller than the screen (the pinned footer stays visible).
            h = 860
            if avail is not None:
                h = min(860, max(520, avail.height() - 80))
            self.resize(620, h)
            if avail is not None:
                geo = self.frameGeometry()
                geo.moveCenter(avail.center())
                self.move(geo.topLeft())
        except Exception:
            pass
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)
