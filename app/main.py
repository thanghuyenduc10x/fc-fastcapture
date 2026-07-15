"""
main.py — FC-FastCapture launcher & controller ("10XLifeOS").

Runs in the background as a macOS menu-bar (tray) app:
  • global hotkeys (Quartz CGEventTap)  • menu bar (QSystemTrayIcon)  • 5 modes
  • floating bar  • settings  • auto-launch  • permission guidance (never crash)

The brand design lives in theme.py; persistence in config.py. This file wires
overlay/capture/editor/recorder/floatingbar/settings/notify together.

Target: Python 3.9+, PyQt6, macOS first (modular for a future Windows port).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

import theme
import config
import platform_backend
import capture
import windows
import autolaunch
# MultiScreenOverlay spans every display (3-monitor support) but exposes the
# same selected/cancelled/start/close interface as SelectionOverlay.
from overlay import MultiScreenOverlay as SelectionOverlay
from editor import EditorWindow
from recorder import GifRecorder, StopButton, GifResultWindow, RecordingFrame
from floatingbar import FloatingBar
from settings import SettingsWindow
from notify import show_toast


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────
_LOG_FILE = platform_backend.log_path()


def log(msg):
    """Status line — printed (dev/run.sh) AND appended to a logfile so the
    packaged .app (launched via Finder, no console) is still diagnosable."""
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


def _timestamp():
    return time.strftime("FC_%Y-%m-%d_%H%M%S")


_LOCK_PATH = os.path.expanduser("~/.fc_fastcapture.lock")


def acquire_single_instance():
    """Return True if we are the only running FC instance (and claim the lock).
    Prevents a second menu-bar icon when the app is launched twice."""
    try:
        if os.path.exists(_LOCK_PATH):
            with open(_LOCK_PATH, "r") as f:
                pid = int((f.read() or "0").strip() or "0")
            if pid > 0:
                try:
                    os.kill(pid, 0)   # signal 0 = existence check, doesn't kill
                    return False      # another instance is alive
                except OSError:
                    pass              # stale lock (process gone) → reclaim
        with open(_LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True   # never block startup on lock errors


def release_single_instance():
    try:
        if os.path.exists(_LOCK_PATH):
            with open(_LOCK_PATH, "r") as f:
                if (f.read() or "").strip() == str(os.getpid()):
                    os.remove(_LOCK_PATH)
    except Exception:
        pass


def open_settings_pane(anchor):
    """Open a specific System Settings > Privacy pane (macOS; no-op elsewhere)."""
    platform_backend.open_permission_settings(anchor)


def check_permissions():
    """Return (screen_recording_ok, accessibility_ok). Never raises.
    Windows/Linux have no such gate → always (True, True)."""
    return platform_backend.check_permissions()


def request_screen_access():
    platform_backend.request_screen_access()


def restart_app():
    """Quit and relaunch the app so newly-granted permissions take effect.

    Screen Recording (and to be safe, Accessibility) only apply on a fresh
    launch — this relaunches the same bundle/dev command after a short delay.
    On Windows this simply restarts the app (no permission model).
    """
    try:
        cmd = autolaunch.current_launch_command()
    except Exception:
        cmd = None
    platform_backend.relaunch(cmd)
    QtWidgets.QApplication.quit()


def make_tray_icon():
    """Menu-bar icon — the SAME FC brand mark as the app icon + floating bar
    (accent squircle, white 'FC'), so all three are consistent."""
    try:
        return QtGui.QIcon(theme.fc_mark(18, margin_ratio=0.04))
    except Exception:
        # Fallback: plain accent 'FC' text.
        pm = QtGui.QPixmap(36, 36)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setFont(theme.heading_font(15, 800))
        p.setPen(theme.qcolor(theme.ACCENT))
        p.drawText(QtCore.QRectF(0, 0, 36, 36),
                   int(Qt.AlignmentFlag.AlignCenter), "FC")
        p.end()
        return QtGui.QIcon(pm)


def place_window_on_screen(win, x, y):
    """Move `win` to (x, y) but keep it FULLY inside the screen it lands on
    (so an editor opened near a screen edge never has its toolbar off-screen)."""
    try:
        pt = QtCore.QPoint(int(x), int(y))
        scr = QtGui.QGuiApplication.screenAt(pt) or \
            QtGui.QGuiApplication.primaryScreen()
        avail = scr.availableGeometry()
        fw = win.frameGeometry().width() or win.width()
        fh = win.frameGeometry().height() or win.height()
        nx = max(avail.left(), min(int(x), avail.right() - fw))
        ny = max(avail.top(), min(int(y), avail.bottom() - fh))
        win.move(nx, ny)
    except Exception:
        try:
            win.move(max(0, int(x)), max(0, int(y)))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Folder picker (Block B) — brand styled, with "Nhớ thư mục này" checkbox
# ─────────────────────────────────────────────────────────────────────────────
class FolderPickDialog(QtWidgets.QDialog):
    def __init__(self, current, parent=None, show_remember=True, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or "Chọn thư mục lưu")
        self.setMinimumWidth(440)
        self._path = current
        self._show_remember = bool(show_remember)
        self.setStyleSheet(theme.app_qss())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        root.setSpacing(theme.GAP)

        title = QtWidgets.QLabel("Lưu file vào thư mục")
        title.setProperty("role", "subtitle")
        root.addWidget(title)

        row = QtWidgets.QHBoxLayout()
        self.path_lbl = QtWidgets.QLabel(current)
        self.path_lbl.setProperty("role", "secondary")
        self.path_lbl.setWordWrap(True)
        browse = QtWidgets.QPushButton("Chọn…")
        browse.setProperty("variant", "secondary")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_lbl, 1)
        row.addWidget(browse, 0)
        root.addLayout(row)

        self.remember = QtWidgets.QCheckBox("Nhớ thư mục này (không hỏi lại)")
        if self._show_remember:
            root.addWidget(self.remember)
        else:
            # Mode 6 ALWAYS remembers — showing the checkbox would only
            # confuse ("what happens if I untick it?").
            self.remember.setChecked(True)
            self.remember.hide()

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("Hủy")
        cancel.setProperty("variant", "secondary")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Lưu vào đây")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu", self._path or os.path.expanduser("~"))
        if d:
            self._path = d
            self.path_lbl.setText(d)

    def get(self):
        """Return (folder, remember) or None if cancelled."""
        if self.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                os.makedirs(self._path, exist_ok=True)
            except OSError:
                return None
            return self._path, self.remember.isChecked()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Size input (Mode 3) — type the EXACT W × H, then place the fixed frame
# ─────────────────────────────────────────────────────────────────────────────
class SizeInputDialog(QtWidgets.QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FC-FastCapture — Kích thước chụp")
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(theme.app_qss())
        self.setMinimumWidth(360)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        root.setSpacing(theme.GAP)

        title = QtWidgets.QLabel("MODE 3 — nhập kích thước chính xác")
        title.setProperty("role", "subtitle")
        root.addWidget(title)
        hint = QtWidgets.QLabel("Khung sẽ tạo đúng W × H bạn nhập (chỉ di chuyển).")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(theme.GAP)
        self._w = QtWidgets.QSpinBox()
        self._h = QtWidgets.QSpinBox()
        for sp, val in ((self._w, w), (self._h, h)):
            sp.setRange(50, 20000)
            sp.setValue(int(val))
            sp.setFont(theme.number_font(15, 600))
            sp.setFixedHeight(38)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlab = QtWidgets.QLabel("W")
        wlab.setProperty("role", "size")
        xlab = QtWidgets.QLabel("×")
        xlab.setProperty("role", "size")
        hlab = QtWidgets.QLabel("H")
        hlab.setProperty("role", "size")
        row.addWidget(wlab)
        row.addWidget(self._w, 1)
        row.addWidget(xlab)
        row.addWidget(hlab)
        row.addWidget(self._h, 1)
        root.addLayout(row)

        btns = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton("Huỷ")
        cancel.setProperty("variant", "secondary")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Chụp →")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        btns.addWidget(cancel)
        btns.addStretch(1)
        btns.addWidget(ok)
        root.addLayout(btns)

    def get_size(self):
        """Return (w, h) ints or None if cancelled."""
        if self.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            return (int(self._w.value()), int(self._h.value()))
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Permission window (brand) — shown when Screen Recording / Accessibility missing
# ─────────────────────────────────────────────────────────────────────────────
class PermissionWindow(QtWidgets.QWidget):
    def __init__(self, screen_ok, access_ok, on_continue):
        super().__init__()
        self._on_continue = on_continue
        self._badges = {}   # key -> (status QLabel)
        self.setWindowTitle("FC-FastCapture — Cấp quyền")
        self.setMinimumWidth(540)
        # Stay on top so it's never buried behind the browser while the user
        # toggles permissions in System Settings and comes back.
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(theme.app_qss())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(theme.GAP)

        title = QtWidgets.QLabel("Cần cấp quyền để FC-FastCapture hoạt động")
        title.setProperty("role", "title")
        root.addWidget(title)

        sig = QtWidgets.QLabel(theme.SIGNATURE)
        sig.setProperty("role", "signature")
        root.addWidget(sig)

        self._intro = QtWidgets.QLabel(
            "Bật 2 quyền bên dưới. Cửa sổ này tự cập nhật khi bạn bật xong.")
        self._intro.setProperty("role", "secondary")
        self._intro.setWordWrap(True)
        root.addWidget(self._intro)

        root.addWidget(self._perm_card(
            "screen",
            "1 · Quay màn hình (Screen Recording)",
            "Bắt buộc để chụp & quay màn hình.",
            screen_ok,
            "Mở cài đặt Screen Recording",
            lambda: open_settings_pane("Privacy_ScreenCapture"),
            extra=("Yêu cầu quyền ngay", request_screen_access)))

        root.addWidget(self._perm_card(
            "access",
            "2 · Trợ năng (Accessibility)",
            "Bắt buộc để dùng phím tắt toàn cục (⌘1…⌘5).",
            access_ok,
            "Mở cài đặt Accessibility",
            lambda: open_settings_pane("Privacy_Accessibility")))

        note = QtWidgets.QLabel(
            "Lưu ý: quyền Quay màn hình chỉ có hiệu lực sau khi KHỞI ĐỘNG LẠI "
            "app (cơ chế bảo mật của macOS). Bật xong → bấm “Khởi động lại app”.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        root.addWidget(note)

        btns = QtWidgets.QHBoxLayout()
        cont = QtWidgets.QPushButton("Tiếp tục (chạy nền)")
        cont.setProperty("variant", "secondary")
        cont.clicked.connect(self._continue)
        btns.addWidget(cont)
        btns.addStretch(1)
        restart = QtWidgets.QPushButton("🔄  Khởi động lại app")
        restart.clicked.connect(restart_app)
        btns.addWidget(restart)
        root.addLayout(btns)

        # Live re-check so badges flip to green the moment a permission is granted.
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1200)

    def _perm_card(self, key, title, desc, ok, btn_text, btn_cb, extra=None):
        card = QtWidgets.QFrame()
        card.setObjectName("panel")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        head = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel(title)
        t.setProperty("role", "subtitle")
        status = QtWidgets.QLabel()
        head.addWidget(t, 1)
        head.addWidget(status, 0)
        lay.addLayout(head)
        self._badges[key] = status
        self._set_badge(status, ok)
        d = QtWidgets.QLabel(desc)
        d.setProperty("role", "secondary")
        d.setWordWrap(True)
        lay.addWidget(d)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(btn_text)
        b.setProperty("variant", "secondary")
        b.clicked.connect(btn_cb)
        row.addWidget(b)
        if extra:
            eb = QtWidgets.QPushButton(extra[0])
            eb.clicked.connect(extra[1])
            row.addWidget(eb)
        row.addStretch(1)
        lay.addLayout(row)
        return card

    def _set_badge(self, label, ok):
        label.setText("✓ Đã bật" if ok else "✕ Chưa bật")
        label.setStyleSheet("color:%s;font-weight:700;"
                            % (theme.SUCCESS if ok else theme.ACCENT))

    def _refresh(self):
        screen_ok, access_ok = check_permissions()
        if "screen" in self._badges:
            self._set_badge(self._badges["screen"], screen_ok)
        if "access" in self._badges:
            self._set_badge(self._badges["access"], access_ok)
        if screen_ok and access_ok:
            self._intro.setText("✓ Đã đủ quyền! Bấm “Khởi động lại app” để áp dụng.")
            self._intro.setStyleSheet("color:%s;font-weight:700;" % theme.SUCCESS)

    def _continue(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        self.hide()
        if self._on_continue:
            self._on_continue()

    def closeEvent(self, event):
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Controller — owns config, tray, hotkeys and every mode flow
# ─────────────────────────────────────────────────────────────────────────────
class Controller(QtCore.QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cfg = config.load_config()
        self.cfg.ensure_save_dir()

        # live windows / widgets (kept as attrs so they aren't GC'd)
        self.overlay = None
        self.editor = None
        self.recorder = None
        self.stopbtn = None
        self.gifresult = None
        self.recframe = None
        self.bar = None
        self.settings = None
        self.perm_win = None

        self._bar_was_visible = False
        self._in_capture = False   # _begin/_end_capture idempotency
        self._frozen = None        # freeze-first: per-screen frozen pixmaps
        self._freezing = False     # freeze in-flight (overlay not built yet)
        self._combos = {}          # name -> (frozenset(mods), keycode)
        self._tap = None           # Quartz CGEventTap (global hotkeys)
        self._tap_src = None
        self._tap_cb = None        # strong ref to the tap callback

        self._build_tray()
        self._register_hotkeys()

    # ── menu bar ─────────────────────────────────────────────────────────
    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(make_tray_icon(), self.app)
        self.tray.setToolTip("FC-FastCapture v%s · 10XLifeOS" % theme.APP_VERSION)
        menu = QtWidgets.QMenu()
        menu.setStyleSheet(theme.app_qss())
        # Version header (disabled) so users can see which build they're on.
        _hdr = menu.addAction("FC-FastCapture  v%s" % theme.APP_VERSION)
        _hdr.setEnabled(False)
        menu.addSeparator()

        # Map QAction → hotkey config-name so labels can be refreshed live
        # (e.g. right after the user changes a hotkey in Settings).
        self._hk_actions = {}

        def add(label, key_name, cb):
            key = config.pretty_combo(self.cfg.hotkey(key_name)) if key_name else ""
            text = label if not key else (label + "\t" + key)
            act = menu.addAction(text)
            act.triggered.connect(cb)
            if key_name:
                self._hk_actions[act] = (label, key_name)
            return act

        add("Chụp nhanh", "mode1", self.mode1)
        add("Chụp + Edit", "mode2", self.mode2)
        add("Chụp khóa kích thước", "mode3", self.mode3)
        add("Chụp cửa sổ", "mode4", self.mode4)
        add("Quay GIF", "mode5", self.mode5)
        add("Chụp + tự lưu", "mode6", self.mode6)
        menu.addSeparator()
        add("Mở thanh nổi", "floatingbar", self.open_bar)
        add("Settings", "", self.open_settings)
        add("Mở thư mục lưu", "", self.open_save_folder)
        add("Chọn lại thư mục lưu…", "", self.choose_save_folder)
        menu.addSeparator()
        add("Thoát FC-FastCapture", "", self.quit)

        # Keep a strong ref to the menu (and thus its QActions + their slot
        # connections) — without this, Python GC can collect the local `menu`,
        # leaving a dead native menu whose items do nothing when clicked.
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.show()

    # ── global hotkeys ───────────────────────────────────────────────────
    # macOS virtual key codes for the digit row (layout-independent). We match
    # on these + the live modifier set instead of pynput.GlobalHotKeys, because
    # GlobalHotKeys fails when Option (⌥) transforms the character (⌥1 ≠ "1").
    _VK_DIGITS = {"0": 29, "1": 18, "2": 19, "3": 20, "4": 21,
                  "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
                  # ANSI letter virtual key codes (so letter hotkeys also work)
                  "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5,
                  "h": 4, "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45,
                  "o": 31, "p": 35, "q": 12, "r": 15, "s": 1, "t": 17, "u": 32,
                  "v": 9, "w": 13, "x": 7, "y": 16, "z": 6}

    @classmethod
    def _parse_combo(cls, combo):
        """'<cmd>+<alt>+1' → (frozenset({'cmd','alt'}), vk) or None."""
        if not combo:
            return None
        mods = set()
        vk = None
        for raw in combo.replace(" ", "").split("+"):
            tok = raw.strip("<>").lower()
            if tok in ("cmd", "command", "win", "super", "meta"):
                mods.add("cmd")
            elif tok in ("alt", "option", "opt"):
                mods.add("alt")
            elif tok in ("ctrl", "control"):
                mods.add("ctrl")
            elif tok == "shift":
                mods.add("shift")
            elif tok in cls._VK_DIGITS:
                vk = cls._VK_DIGITS[tok]
        if vk is None or not mods:
            return None
        return (frozenset(mods), vk)

    def _rebuild_combos(self):
        names = ["mode1", "mode2", "mode3", "mode4", "mode5", "mode6",
                 "floatingbar"]
        self._combos = {}
        for name in names:
            parsed = self._parse_combo(self.cfg.hotkey(name))
            if parsed:
                self._combos[name] = parsed

    def _register_hotkeys(self):
        """Global hotkeys via a Quartz CGEventTap on the MAIN thread.

        We deliberately do NOT use pynput's keyboard Listener: on macOS 26 its
        background thread calls Text-Input-Source APIs off the main thread, which
        triggers a dispatch_assert_queue crash (SIGTRAP) — that was the "app
        quits on Save" bug. A CGEventTap added to the main run loop reads raw
        keycodes + modifier flags (no TIS, no off-main work), so it's both crash-
        free and reliable. Re-registering only updates self._combos — the tap
        callback reads it live, so there's no listener teardown/rebuild.
        """
        self._rebuild_combos()
        if platform_backend.IS_WIN:
            # Windows: Win32 RegisterHotKey backend (re-registers on reload).
            if getattr(self, "_winhk", None) is None:
                try:
                    from hotkeys_win import WinHotkeyManager
                    self._winhk = WinHotkeyManager(self)
                    self._winhk.install()
                    log("✓ Phím tắt toàn cục đã bật (Win32 RegisterHotKey).")
                except Exception as e:
                    self._winhk = None
                    log("⚠ Không đăng ký được phím tắt Windows: %s" % e)
            else:
                self._winhk.reload()
            return
        if getattr(self, "_tap", None) is None:
            self._install_event_tap()

    def _install_event_tap(self):
        try:
            import Quartz
        except Exception:
            log("⚠ Quartz thiếu — phím tắt tắt (vẫn dùng menu/thanh nổi).")
            return

        FLAG = {
            "cmd": Quartz.kCGEventFlagMaskCommand,
            "alt": Quartz.kCGEventFlagMaskAlternate,
            "ctrl": Quartz.kCGEventFlagMaskControl,
            "shift": Quartz.kCGEventFlagMaskShift,
        }

        def _callback(proxy, etype, event, refcon):
            try:
                # Re-enable if the system disabled the tap (timeout/user input).
                if etype in (Quartz.kCGEventTapDisabledByTimeout,
                             Quartz.kCGEventTapDisabledByUserInput):
                    Quartz.CGEventTapEnable(self._tap, True)
                    return event
                if etype != Quartz.kCGEventKeyDown:
                    return event
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                flags = Quartz.CGEventGetFlags(event)
                mods = set()
                for tok, mask in FLAG.items():
                    if flags & mask:
                        mods.add(tok)
                # MENU-BAR MODE: an Accessory app's overlay/editor can't be
                # the key window, so keyPressEvent(ESC/Enter) never fires.
                # Forward them through the tap instead (no key window needed).
                if platform_backend.MENUBAR_MODE and not mods:
                    if self.overlay is not None:
                        if keycode == 53:      # ESC → cancel selection
                            QTimer.singleShot(0, self._overlay_cancel_fs)
                            return None
                        if keycode == 36:      # Return → confirm selection
                            QTimer.singleShot(0, self._overlay_confirm_fs)
                            return None
                    elif keycode == 53 and self._editor_should_take_esc():
                        # ESC closes the editor — UNLESS an inline text field is
                        # open (then ESC belongs to that field, handled by Qt).
                        QTimer.singleShot(0, self._editor_cancel_fs)
                        return None
                for nm, (need, vk) in self._combos.items():
                    if keycode == vk and need == mods:
                        # Defer the actual work to the event loop; keep the tap
                        # callback instant so macOS never disables it.
                        QTimer.singleShot(0, lambda n=nm: self.dispatch(n))
                        return None   # consume the keystroke
            except Exception:
                pass
            return event

        try:
            self._tap_cb = _callback   # keep a strong ref (GC-safety)
            mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault, mask, self._tap_cb, None)
            if not self._tap:
                self._tap = None
                log("⚠ Không tạo được CGEventTap (cần quyền Accessibility).")
                return
            self._tap_src = Quartz.CFMachPortCreateRunLoopSource(
                None, self._tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(), self._tap_src,
                Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            log("✓ Phím tắt toàn cục đã bật (CGEventTap).")
        except Exception as e:
            self._tap = None
            log("⚠ Không đăng ký được phím tắt: %s" % e)

    def _stop_event_tap(self):
        try:
            import Quartz
            if getattr(self, "_tap", None) is not None:
                Quartz.CGEventTapEnable(self._tap, False)
        except Exception:
            pass

    def _suspend_tap(self):
        """Temporarily disable global hotkeys (e.g. while recording a new one in
        Settings) so the keystrokes reach the recorder instead of being consumed
        and triggering a capture. REFCOUNTED: nested suspenders (Settings open
        + Mode 3's size dialog) don't re-enable each other's suspension."""
        self._tap_susp = getattr(self, "_tap_susp", 0) + 1
        if self._tap_susp > 1:
            return   # already suspended by an outer caller
        if platform_backend.IS_WIN:
            if getattr(self, "_winhk", None) is not None:
                self._winhk.suspend()
            return
        self._stop_event_tap()

    def _resume_tap(self):
        self._tap_susp = max(0, getattr(self, "_tap_susp", 0) - 1)
        if self._tap_susp > 0:
            return   # an outer suspender is still active
        if platform_backend.IS_WIN:
            if getattr(self, "_winhk", None) is not None:
                self._winhk.resume()
            return
        try:
            import Quartz
            if getattr(self, "_tap", None) is not None:
                Quartz.CGEventTapEnable(self._tap, True)
        except Exception:
            pass

    def dispatch(self, name):
        {
            "mode1": self.mode1, "mode2": self.mode2, "mode3": self.mode3,
            "mode4": self.mode4, "mode5": self.mode5, "mode6": self.mode6,
            "floatingbar": self.toggle_bar,
        }.get(name, lambda: None)()

    # ── MENU-BAR MODE: tap-forwarded overlay ESC/Enter (no key window) ──
    def _overlay_cancel_fs(self):
        ov = self.overlay
        if ov is None:
            return
        try:
            ov.cancel()
        except Exception:
            self._cancel()

    def _overlay_confirm_fs(self):
        ov = self.overlay
        if ov is None:
            return
        try:
            ov.confirm()
        except Exception:
            pass

    def _editor_should_take_esc(self):
        """True when a menu-bar-mode ESC should close the editor: editor visible
        AND no inline text field is being typed into (that field owns ESC)."""
        ed = getattr(self, "editor", None)
        if ed is None or not ed.isVisible():
            return False
        try:
            return getattr(ed.canvas, "_editing", None) is None
        except Exception:
            return True

    def _editor_cancel_fs(self):
        ed = getattr(self, "editor", None)
        if ed is not None and ed.isVisible():
            try:
                ed.close()
            except Exception:
                pass

    # ── capture lifecycle (auto-hide our own UI) ─────────────────────────
    def _capture_busy(self):
        """True if a capture/recording/edit is already in flight — used to block
        re-entry (a 2nd hotkey while recording would orphan the recorder thread
        + StopButton/RecordingFrame, leaving the screen being recorded forever)."""
        if self.overlay is not None:
            return True
        if getattr(self, "_freezing", False):
            # A freeze-first capture is mid-flight (overlay not built yet).
            return True
        if getattr(self, "_in_capture", False):
            # Covers the whole begin→end window — incl. Mode 3's nested size
            # dialog, where overlay is None but a capture IS in progress (the
            # tray menu stays clickable during the dialog's event loop).
            return True
        if self.recorder is not None or self.stopbtn is not None:
            return True
        if self.editor is not None and self.editor.isVisible():
            return True
        gr = getattr(self, "gifresult", None)
        if gr is not None and gr.isVisible():
            return True
        return False

    def _begin_capture(self):
        # Idempotent — mode 3 calls this before its size dialog AND again via
        # the freeze helper; only the FIRST call may sample bar visibility, or
        # the restore flag would be clobbered to False.
        if getattr(self, "_in_capture", False):
            return
        self._in_capture = True
        self._bar_was_visible = bool(self.bar and self.bar.isVisible())
        if self.bar:
            self.bar.hide()

    def _end_capture(self):
        self._in_capture = False
        if self._bar_was_visible and self.bar:
            self.bar.show_bar()

    def _cancel(self):
        self.overlay = None
        self._frozen = None       # release the frozen screen pixmaps
        self._freezing = False
        self._end_capture()

    # ── FREEZE-FIRST (v1.1) ──────────────────────────────────────────────
    # Hotkey → our UI hides → every screen is snapshotted THAT instant → the
    # overlay opens showing the FROZEN image → the user selects at leisure →
    # the shot is CROPPED from the frozen pixels (instant, no re-grab).
    # Fixes both the "missed the moment while dragging" UX and the Windows
    # DPI offset bug (crop is per-screen local + explicit scale; the legacy
    # global-logical-rect → mss path was wrong under 125-150% scaling).
    def _start_frozen_overlay(self, build_overlay, delay_ms=60):
        """build_overlay(frozen_list) must return a started-ready overlay with
        .selected already connected. Freeze failure → live overlay (legacy).

        delay_ms: how long to wait before grabbing the freeze. 60ms is enough
        for the floating bar to hide; a MODAL DIALOG that just closed (mode 3's
        size input) needs ~300ms or its window is still on screen when we grab
        — it then gets burned into the frozen backdrop AND the final capture
        (reported on both Windows VM and Mac)."""
        self._begin_capture()
        self._freezing = True
        def go():
            self._freezing = False
            try:
                self._frozen = capture.freeze_screens()
            except Exception:
                self._frozen = None
            if not self._frozen:
                log("⚠ Freeze thất bại — overlay chạy chế độ live (fallback).")
            try:
                self.overlay = build_overlay(self._frozen)
            except Exception as e:
                log("✕ Không mở được overlay: %s" % e)
                self._cancel()
                return
            # (Menu-bar mode: app runs Accessory for its whole lifetime — set once at
            # startup. Flipping Regular↔Accessory per capture broke Space-join
            # for windows created after the first cycle: run 1 visible, run 2+
            # invisible. CleanShot-class tools never flip either.)
            self.overlay.cancelled.connect(self._cancel)
            self.overlay.start()
        # One breath (60ms) so the floating bar/dialog is truly gone from the
        # screen before we freeze — imperceptible, keeps our UI out of the shot.
        QTimer.singleShot(max(0, int(delay_ms)), go)

    def _grab(self, rect, handler):
        # Freeze-first: crop from the frozen snapshot — instant, DPI-proof.
        frozen = getattr(self, "_frozen", None)
        if frozen:
            shot = None
            try:
                shot = capture.crop_from_frozen(frozen, rect)
            except Exception:
                shot = None
            self._frozen = None   # release pixmaps immediately
            if shot is not None:
                if self.overlay:
                    self.overlay.close()
                if shot.rect[2] < 4 or shot.rect[3] < 4:
                    self._cancel()
                    return
                handler(shot)
                return
            log("⚠ Crop từ ảnh freeze thất bại — chụp live (fallback).")
        if self.overlay:
            self.overlay.close()
        # legacy live path: let the overlay fully disappear before grabbing
        QTimer.singleShot(140, lambda: self._do_grab(rect, handler))

    def _do_grab(self, rect, handler):
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        if w < 4 or h < 4:
            self._cancel()
            return
        try:
            # DPI-mapped live grab (Windows: logical→physical; macOS: as-is) —
            # without it this fallback would reintroduce the 125% offset bug.
            shot = capture.capture_region_dpi(x, y, w, h)
        except Exception as e:
            log("✕ Lỗi chụp: %s" % e)
            self._cancel()   # clears self.overlay too — else busy-guard sticks
            return
        handler(shot)

    # ── MODE 1 — quick → clipboard only, NEVER save ──────────────────────
    def mode1(self):
        if self._capture_busy():
            return
        def build(frozen):
            ov = SelectionOverlay(mode="free", frozen=frozen)
            ov.selected.connect(lambda r: self._grab(r, self._after_mode1))
            return ov
        self._start_frozen_overlay(build)

    def _after_mode1(self, shot):
        try:
            capture.copy_pil_to_clipboard(shot.image)
        except Exception as e:
            log("✕ Lỗi copy: %s" % e)
        # Block C: always remember the selection size
        self.cfg.set_remembered_size(shot.rect[2], shot.rect[3])
        show_toast("Đã copy vào clipboard")
        log("✓ MODE 1 · Đã copy clipboard · KHÔNG lưu file")
        self.overlay = None
        self._end_capture()

    # ── MODE 6 — capture → AUTO-SAVE to a fixed folder (v1.3) ────────────
    # First use asks for the folder ONCE (FolderPickDialog, remember hidden);
    # every later capture saves silently. Clipboard is also filled so the
    # shot can be pasted immediately. The folder is changeable in Settings.
    def mode6(self):
        if self._capture_busy():
            return
        def build(frozen):
            ov = SelectionOverlay(mode="free", frozen=frozen)
            ov.selected.connect(lambda r: self._grab(r, self._after_mode6))
            return ov
        self._start_frozen_overlay(build)

    def _ask_mode6_dir(self):
        """First-run (or folder-lost) picker. Returns the folder or None.

        Runs a NESTED exec() loop → suspend the tap so a second hotkey can't
        dispatch into it (mode3's defensive pattern). As an Accessory app we
        must activate explicitly or the dialog gets no keyboard/focus.
        """
        self._suspend_tap()
        try:
            platform_backend.activate_app()
            dlg = FolderPickDialog(
                self.cfg.mode6_dir() or self.cfg.save_dir(),
                show_remember=False,
                title="Chụp + tự lưu — chọn thư mục (hỏi một lần)")
            res = dlg.get()
        finally:
            self._resume_tap()
        if res is None:
            return None
        folder = res[0]
        self.cfg.set_mode6_dir(folder)
        return folder

    def _after_mode6(self, shot):
        # 1) Clipboard first — it must survive ANY save failure below.
        try:
            capture.copy_pil_to_clipboard(shot.image)
        except Exception as e:
            log("✕ Lỗi copy: %s" % e)
        self.cfg.set_remembered_size(shot.rect[2], shot.rect[3])

        # 2) Resolve the auto-save folder: configured & creatable, else ask
        #    (first run — or the remembered folder vanished, e.g. Drive
        #    unmounted/renamed; asking beats silently saving elsewhere).
        folder = self.cfg.ensure_mode6_dir()
        if not folder:
            folder = self._ask_mode6_dir()

        # 3) Save (never prompts → collision suffix -1/-2 for same-second shots).
        saved_name = ""
        if folder:
            try:
                path = capture.unique_path(folder, _timestamp(), ".png")
                if capture.save_pil(shot.image, path):
                    saved_name = os.path.basename(path)
            except Exception as e:
                log("✕ MODE 6 · Tự lưu lỗi: %s" % e)

        if saved_name:
            show_toast("Đã lưu %s (+ clipboard)" % saved_name)
            log("✓ MODE 6 · Đã tự lưu %s · Đã copy clipboard" % saved_name)
        elif folder:
            show_toast("Đã copy · Tự lưu file thất bại", ok=False)
            log("✕ MODE 6 · Tự lưu thất bại (thư mục: %s) · clipboard OK" % folder)
        else:
            show_toast("Đã copy · chưa lưu (chưa chọn thư mục)", ok=False)
            log("• MODE 6 · Người dùng chưa chọn thư mục · clipboard OK")
        # EVERY exit path must release the busy-guard or all captures lock up.
        self.overlay = None
        self._end_capture()

    # ── MODE 2 / 3 / 4 — capture then edit in place ──────────────────────
    def mode2(self):
        if self._capture_busy():
            return
        def build(frozen):
            if self.cfg.remember_size_enabled():
                w, h = self.cfg.remembered_size()
                ov = SelectionOverlay(mode="preset", initial_size=(w, h),
                                      frozen=frozen)
            else:
                ov = SelectionOverlay(mode="free", frozen=frozen)
            ov.selected.connect(
                lambda r: self._grab(r, lambda s: self._edit(s, "MODE 2",
                                                             "MODE 2")))
            return ov
        self._start_frozen_overlay(build)

    def mode3(self):
        if self._capture_busy():
            return
        self._begin_capture()
        w, h = self.cfg.locked_size()
        # Ask for the EXACT W × H first (pre-filled with the last size), then show
        # a fixed-size frame of exactly that size to position and capture.
        # SizeInputDialog.exec() runs a NESTED event loop in which self.overlay is
        # still None, so a second mode hotkey (the tap dispatches via singleShot,
        # which fires inside that loop) would pass the busy-guard and start a
        # parallel capture. Suspend the global tap for the dialog's lifetime.
        self._suspend_tap()
        try:
            dlg = SizeInputDialog(w, h)
            res = dlg.get_size()
            # Force the dialog OFF-SCREEN before we freeze: hide + flush the
            # event loop so the window server actually removes it. exec()
            # returning does NOT mean the window is gone from the compositor.
            try:
                dlg.hide()
                dlg.deleteLater()
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass
        finally:
            self._resume_tap()
        if res is None:
            self._end_capture()
            return
        w, h = res
        self.cfg.data["locked_width"] = w
        self.cfg.data["locked_height"] = h
        self.cfg.save()
        ctx = "MODE 3 · %dx%d" % (w, h)
        def build(frozen):
            ov = SelectionOverlay(mode="preset", initial_size=(w, h),
                                  fixed_size=True, frozen=frozen)
            ov.selected.connect(
                lambda r: self._grab(r, lambda s: self._edit(s, "MODE 3", ctx)))
            return ov
        # Freeze well AFTER the size dialog closed — 60ms was NOT enough for a
        # modal dialog's teardown (it got captured into the frozen backdrop on
        # both Windows and Mac); 300ms + the explicit hide/flush above is.
        self._start_frozen_overlay(build, delay_ms=300)

    def mode4(self):
        if self._capture_busy():
            return
        wins = []
        try:
            wins = windows.list_windows()
        except Exception:
            wins = []
        def build(frozen):
            ov = SelectionOverlay(mode="window", windows=wins, frozen=frozen)
            ov.selected.connect(self._grab_window)
            return ov
        self._start_frozen_overlay(build)

    def _grab_window(self, rect):
        # Read the picked window (has the CGWindow id) BEFORE closing the overlay.
        win = getattr(self.overlay, "picked_window", None) if self.overlay else None
        frozen = getattr(self, "_frozen", None)
        self._frozen = None
        if self.overlay:
            self.overlay.close()
        if frozen:
            # Freeze-first: no need to wait for the overlay to vanish — the
            # fallback crop reads the snapshot, not the live screen.
            self._do_grab_window(rect, win, frozen)
        else:
            QTimer.singleShot(140,
                              lambda: self._do_grab_window(rect, win, None))

    def _do_grab_window(self, rect, win, frozen=None):
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        if w < 4 or h < 4:
            self._cancel()
            return
        wid = None
        try:
            wid = int(win.get("id")) if win else None
        except Exception:
            wid = None
        shot = None
        if wid:
            # Capture the window's own content (reliable on every monitor).
            try:
                shot = capture.capture_window(wid, w, h, (x, y, w, h))
            except Exception:
                shot = None
        if (shot is None or shot.image is None) and frozen:
            # Fallback #2: crop the window's rect from the frozen snapshot —
            # DPI-proof on Windows (the live region grab below is not).
            try:
                shot = capture.crop_from_frozen(frozen, rect)
            except Exception:
                shot = None
        if shot is None or shot.image is None:
            # Final fallback: DPI-mapped LIVE grab. On the frozen path we got
            # here ~0ms after the overlay closed — wait for the compositor to
            # actually remove it or the overlay ends up in the shot.
            def _live():
                try:
                    s2 = capture.capture_region_dpi(x, y, w, h)
                except Exception as e:
                    log("✕ Lỗi chụp: %s" % e)
                    self._cancel()
                    return
                self._edit(s2, "MODE 4", "MODE 4 · Chụp cửa sổ")
            QTimer.singleShot(140 if frozen else 0, _live)
            return
        self._edit(shot, "MODE 4", "MODE 4 · Chụp cửa sổ")

    def _edit(self, shot, mode_label, log_ctx):
        # Block C: remember size after mode 2 as well
        if mode_label == "MODE 2":
            self.cfg.set_remembered_size(shot.rect[2], shot.rect[3])
        self.overlay = None
        pm = capture.pil_to_qpixmap(shot.image, dpr=shot.scale)
        self.editor = EditorWindow(
            pm, mode_label=mode_label, scale=shot.scale,
            on_copy=lambda qimg: self._on_copy(qimg, log_ctx),
            on_save=lambda qimg: self._on_save(qimg, log_ctx))
        self.editor.show_editor()
        if platform_backend.MENUBAR_MODE:
            # Accessory apps don't auto-activate when a window shows — without
            # this the editor gets NO keyboard (ESC/⌘Z/typing dead; user had to
            # click buttons). Activating leaves a fullscreen Space — accepted:
            # the user is switching to editing anyway.
            platform_backend.activate_app()
        # Put the editor's CANVAS exactly over the region the user just selected,
        # so it feels like editing happens in place (select → annotate, one step).
        self.editor.place_canvas_over(shot.rect[0], shot.rect[1])
        self._end_capture()

    def _on_copy(self, qimage, log_ctx):
        try:
            capture.copy_qimage_to_clipboard(qimage)
        except Exception as e:
            log("✕ Lỗi copy: %s" % e)
            show_toast("Copy thất bại — hãy thử Lưu file", ok=False)
            return False
        show_toast("Đã copy ảnh đã chỉnh")
        log("✓ %s · Copied" % log_ctx)
        return True

    def _on_save(self, qimage, log_ctx):
        path = self._save_qimage(qimage, ".png")
        if path:
            show_toast(os.path.basename(path))
            log("✓ %s · Saved → %s" % (log_ctx, path))
            return True
        return False

    # ── MODE 5 — record → GIF ────────────────────────────────────────────
    def mode5(self):
        if self._capture_busy():
            return
        self._begin_capture()
        self.overlay = SelectionOverlay(mode="free")
        self.overlay.selected.connect(self._start_record)
        self.overlay.cancelled.connect(self._cancel)
        self.overlay.start()

    def _start_record(self, rect):
        if self.overlay:
            self.overlay.close()
        self.overlay = None
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        if w < 8 or h < 8:
            self._cancel()
            return
        log("● Đang quay...")
        # Windows DPI fix: the recorder feeds mss, which speaks PHYSICAL pixels
        # there — convert the logical selection once, on the main thread. On
        # macOS this is an identity mapping (mss speaks logical points).
        try:
            gx, gy, gw, gh, _dpr = capture.logical_rect_to_physical(x, y, w, h)
        except Exception:
            gx, gy, gw, gh = x, y, w, h
        try:
            self.recorder = GifRecorder(gx, gy, gw, gh,
                                        fps=self.cfg.get("gif_fps", 15))
        except Exception as e:
            log("✕ Không khởi tạo được recorder: %s" % e)
            self._end_capture()
            return
        # Persistent accent frame around the recording area (drawn OUTSIDE the
        # region so it's not in the GIF) — keeps the selection visible.
        self.recframe = RecordingFrame((x, y, w, h))
        self.recframe.show_frame()
        self.stopbtn = StopButton((x, y, w, h))
        self.stopbtn.stopped.connect(self._stop_record)
        self.stopbtn.show()
        # start after the overlay/stop-button have settled (stop btn + frame are
        # outside the region; small delay keeps frame 1 clean)
        QTimer.singleShot(180, self.recorder.start)
        # Auto-stop when the frame cap is hit, else recording silently freezes
        # while the Stop button stays up (worker can't touch Qt → poll here).
        self._rec_poll = QTimer(self.app)
        self._rec_poll.timeout.connect(self._check_record_cap)
        self._rec_poll.start(1000)

    def _check_record_cap(self):
        rec = self.recorder
        if rec is not None and rec.capped():
            show_toast("Đã đạt giới hạn ~40s — tự dừng quay")
            self._stop_record()

    def _stop_record(self):
        if getattr(self, "_rec_poll", None) is not None:
            self._rec_poll.stop()
            self._rec_poll = None
        rec = self.recorder
        if rec is None:
            return
        try:
            rec.stop()
        except Exception:
            pass
        # Clear refs NOW so the busy-guard releases and the stop button can't be
        # double-clicked into a second export.
        self.recorder = None
        if self.stopbtn:
            self.stopbtn.close()
            self.stopbtn = None
        if getattr(self, "recframe", None):
            self.recframe.close()
            self.recframe = None
        nframes = 0
        try:
            nframes = rec.frame_count()
        except Exception:
            pass
        log("● MODE 5 · dừng quay · frames=%d" % nframes)
        tmp = os.path.join(tempfile.gettempdir(), _timestamp() + ".gif")
        try:
            path = rec.export_gif(tmp)
        except Exception as e:
            log("✕ Lỗi xuất GIF: %s" % e)
            self._end_capture()
            return
        if not path or not os.path.exists(path):
            log("✕ GIF rỗng (không có frame).")
            self._end_capture()
            return
        self.gifresult = GifResultWindow(
            path, on_copy=self._on_gif_copy, on_save=self._on_gif_save)
        self.gifresult.show_result()
        if platform_backend.MENUBAR_MODE:
            platform_backend.activate_app()   # keyboard/clicks for the result
        self._end_capture()

    def _on_gif_copy(self, path):
        ok = False
        try:
            ok = capture.copy_gif_to_clipboard(path)
        except Exception:
            ok = False
        show_toast("Đã copy GIF" if ok else "Copy GIF không hỗ trợ — hãy Lưu file",
                   ok=ok)
        log("✓ MODE 5 · GIF · Copied")

    def _on_gif_save(self, path):
        saved = self._save_blob(path, ".gif")
        if saved:
            show_toast(os.path.basename(saved))
            log("✓ MODE 5 · GIF · Saved → %s" % saved)
            return True
        return False

    # ── Block B: save resolution ─────────────────────────────────────────
    def _resolve_save_target(self, ext):
        """Return the full file path to write to.

        - "Hỏi vị trí trước khi lưu" ON  (remember_folder == False) → show the
          native macOS Save panel so the user can pick the folder AND rename
          the file.
        - OFF (remember_folder == True) → auto path FC_<timestamp> in the saved
          folder, no prompt.
        """
        folder = self.cfg.ensure_save_dir()
        default_name = _timestamp() + ext
        if self.cfg.remember_folder():
            return os.path.join(folder, default_name)
        flt = "Ảnh PNG (*.png)" if ext == ".png" else (
            "Ảnh GIF (*.gif)" if ext == ".gif" else "Tệp (*%s)" % ext)
        try:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                None, "Lưu file", os.path.join(folder, default_name), flt)
        except Exception:
            path = ""
        if not path:
            return None
        if not path.lower().endswith(ext):
            path += ext
        return path

    def _save_qimage(self, qimage, ext):
        path = self._resolve_save_target(ext)
        if not path:
            return None
        try:
            ok = qimage.save(path, "PNG")
        except Exception:
            ok = False
        return path if ok else None

    def _save_blob(self, src, ext):
        path = self._resolve_save_target(ext)
        if not path:
            return None
        try:
            shutil.copyfile(src, path)
        except OSError:
            return None
        return path

    def choose_save_folder(self):
        """Menu → re-pick the default save folder (with the 'remember' tick).
        Lets the user restore the folder-picker prompt after they'd chosen to
        always remember a folder."""
        res = FolderPickDialog(self.cfg.save_dir()).get()
        if res is None:
            return
        folder, remember = res
        self.cfg.set_save_dir(folder, remember=remember)
        if remember:
            show_toast("Đã nhớ thư mục lưu")
        else:
            show_toast("Sẽ hỏi thư mục mỗi lần lưu")

    # ── floating bar ─────────────────────────────────────────────────────
    def open_bar(self):
        if self.bar is None:
            self.bar = FloatingBar()
            self.bar.modeTriggered.connect(self._bar_mode)
            self.bar.hideRequested.connect(self.bar.hide)
        self.bar.show_bar()

    def toggle_bar(self):
        if self.bar and self.bar.isVisible():
            self.bar.hide()
        else:
            self.open_bar()

    def _bar_mode(self, n):
        [None, self.mode1, self.mode2, self.mode3, self.mode4, self.mode5][n]()

    # ── settings / misc ──────────────────────────────────────────────────
    def open_settings(self):
        self.settings = SettingsWindow(self.cfg)
        self.settings.saved.connect(self._after_settings)
        self.settings.closed.connect(self._resume_tap)
        # Suspend global hotkeys while Settings is open so recording a new combo
        # isn't swallowed by the tap (which would fire a capture instead).
        self._suspend_tap()
        self.settings.show_settings()
        if platform_backend.MENUBAR_MODE:
            platform_backend.activate_app()   # hotkey recorder needs keyboard

    def _after_settings(self):
        # Guarantee the tap is re-enabled even if re-registering/labels raise —
        # otherwise global hotkeys would stay permanently dead after saving.
        try:
            self._register_hotkeys()
            self._refresh_menu_labels()
        finally:
            self._resume_tap()
        show_toast("Đã lưu cài đặt")

    def _refresh_menu_labels(self):
        """Update tray-menu hotkey labels to match the current config."""
        for act, (label, name) in getattr(self, "_hk_actions", {}).items():
            key = config.pretty_combo(self.cfg.hotkey(name))
            act.setText(label if not key else (label + "\t" + key))

    def open_save_folder(self):
        folder = self.cfg.ensure_save_dir()
        platform_backend.open_folder(folder)

    def show_permissions(self, screen_ok, access_ok):
        self.perm_win = PermissionWindow(screen_ok, access_ok, on_continue=None)
        self.perm_win.show()
        self.perm_win.raise_()
        self.perm_win.activateWindow()
        if platform_backend.MENUBAR_MODE:
            # Accessory app doesn't auto-activate → the first-run permission
            # window would open UNFOCUSED behind other apps. Force it forward
            # so the team actually sees the setup guidance on first launch.
            platform_backend.activate_app()
            self.perm_win.raise_()

    def quit(self):
        self._stop_event_tap()
        try:
            self.tray.hide()
        except Exception:
            pass
        release_single_instance()
        self.app.quit()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    QtWidgets.QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app = QtWidgets.QApplication(sys.argv)
    if platform_backend.MENUBAR_MODE:
        # Accessory for the app's WHOLE lifetime (like CleanShot). Flipping
        # Regular↔Accessory per capture broke fullscreen-Space joining for
        # windows created after the first cycle (run 1 visible, run 2+ not).
        # Trade-off (product decision): no Dock icon — menu-bar icon remains.
        platform_backend.set_accessory_policy(True)
        log("✓ Chế độ menu-bar (Accessory) — hỗ trợ chụp/quay khi fullscreen")
    app.setApplicationName(theme.APP_NAME)
    app.setApplicationDisplayName(theme.APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    theme.load_fonts()
    app.setStyleSheet(theme.app_qss())
    # NOTE: v1.2 runs as a menu-bar (Accessory) app — see set_accessory_policy
    # above + LSUIElement in build.sh. We traded the Dock icon (a v1.1 choice
    # for discoverability) for the ability to capture over another app's native-
    # fullscreen Space, which a normal windowed app cannot do. The menu-bar "FC"
    # icon is the entry point; first-run guidance points the user to it.
    app.setApplicationName(theme.APP_NAME)

    # Single instance — if FC is already running, don't add a 2nd menu-bar icon.
    if not acquire_single_instance():
        log("⚠ FC-FastCapture đã chạy rồi — không mở thêm bản thứ 2.")
        sys.exit(0)

    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        log("⚠ Không có menu bar (system tray).")

    controller = Controller(app)

    # First-launch permission guidance — never blocks, never crashes.
    screen_ok, access_ok = check_permissions()
    if not (screen_ok and access_ok):
        controller.show_permissions(screen_ok, access_ok)
        log("⚠ Thiếu quyền: Screen=%s Accessibility=%s" % (screen_ok, access_ok))

    # Show the floating bar on launch → immediate, visible proof the app is
    # running (plus a quick toast). The bar is draggable + hideable.
    controller.open_bar()
    show_toast("FC-FastCapture đang chạy")

    log("✓ FC-FastCapture đang chạy · biểu tượng 'FC' trên menu bar (thanh trên cùng).")
    log("  Phím tắt: ⌘1 Quick · ⌘2 Edit · ⌘3 Khóa · ⌘4 Cửa sổ · "
        "⌘5 GIF · ⌘0 Thanh nổi")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
