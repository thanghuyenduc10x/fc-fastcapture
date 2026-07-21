"""
ocr_popup.py — Mode 7 result UI (v1.5).

A worker thread runs the OpenRouter call (1-3s network) OFF the UI thread so the
app never freezes, then a small brand-styled popup shows the recognised text:
editable, pre-selected, ⌘↵ / Ctrl+↵ copies (the selection if any, else all) and
closes, ESC closes. Selecting part of the text and copying grabs only that part
— the "chọn lại đoạn text" the user asked for.
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal

import theme
import ocr


class OcrWorker(QtCore.QThread):
    """Runs ocr.extract_text off the UI thread. Emits exactly one of the
    signals. The image + key live only for the thread's lifetime."""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, pil_image, api_key, model, parent=None):
        super().__init__(parent)
        self._img = pil_image
        self._key = api_key
        self._model = model

    def run(self):
        try:
            text = ocr.extract_text(self._img, self._key, self._model)
            self.done.emit(text)
        except ocr.OcrError as e:
            self.failed.emit(str(e))
        except Exception as e:                       # never crash the thread
            self.failed.emit("Lỗi không mong đợi: %s" % e)


class OcrResultPopup(QtWidgets.QDialog):
    """Spinner → editable text. ⌘↵ copy+close · ESC close."""

    def __init__(self, pil_image, api_key, model, parent=None):
        super().__init__(parent)
        self._img = pil_image
        self._key = api_key
        self._model = model
        self._worker = None
        self.setWindowTitle("Quét lấy chữ (OCR)")
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.app_qss())
        # Destroy on close so the closed window can't linger (see the toast
        # zombie bug in the gotcha ledger).
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(theme.PAD, theme.PAD, theme.PAD, theme.PAD)
        root.setSpacing(theme.GAP)

        title = QtWidgets.QLabel("Văn bản nhận được")
        title.setProperty("role", "subtitle")
        root.addWidget(title)

        # Status line (spinner / error). Shown while loading, hidden on success.
        self.status = QtWidgets.QLabel("⏳ Đang đọc chữ trong ảnh…")
        self.status.setProperty("role", "secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.edit = QtWidgets.QTextEdit()
        self.edit.setAcceptRichText(False)
        self.edit.setMinimumHeight(200)
        self.edit.setStyleSheet(
            "QTextEdit{background:%s;color:%s;border:1px solid %s;"
            "border-radius:%dpx;padding:8px;}"
            % (theme.CONTROL, theme.TEXT_PRIMARY, theme.SECONDARY_BORDER,
               theme.RADIUS_BUTTON))
        self.edit.setVisible(False)
        root.addWidget(self.edit)

        hint = QtWidgets.QLabel("⌘↵ Sao chép & đóng  ·  bôi chọn để lấy một "
                                "phần  ·  Esc đóng")
        hint.setProperty("role", "muted")
        root.addWidget(hint)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.retry_btn = QtWidgets.QPushButton("Thử lại")
        self.retry_btn.setProperty("variant", "secondary")
        self.retry_btn.setStyleSheet(theme.qss_secondary_btn())
        self.retry_btn.clicked.connect(self._start)
        self.retry_btn.setVisible(False)
        close_btn = QtWidgets.QPushButton("Đóng")
        close_btn.setProperty("variant", "secondary")
        close_btn.setStyleSheet(theme.qss_secondary_btn())
        close_btn.clicked.connect(self.close)
        self.copy_btn = QtWidgets.QPushButton("Sao chép & đóng")
        self.copy_btn.setStyleSheet(theme.qss_primary_btn())
        self.copy_btn.clicked.connect(self._copy_and_close)
        self.copy_btn.setEnabled(False)
        btns.addWidget(self.retry_btn)
        btns.addWidget(close_btn)
        btns.addWidget(self.copy_btn)
        root.addLayout(btns)

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        """Show the popup and kick off the OCR call."""
        self.show()
        self.raise_()
        self.activateWindow()
        # Accessory (menu-bar) app doesn't auto-activate → no keyboard without
        # this (same reason the editor/settings do it).
        try:
            import platform_backend
            if getattr(platform_backend, "MENUBAR_MODE", False):
                platform_backend.activate_app()
                self.raise_()
        except Exception:
            pass
        self._start()

    def _start(self):
        self.retry_btn.setVisible(False)
        self.copy_btn.setEnabled(False)
        self.edit.setVisible(False)
        self.status.setVisible(True)
        self.status.setStyleSheet("")
        self.status.setText("⏳ Đang đọc chữ trong ảnh…")
        self._worker = OcrWorker(self._img, self._key, self._model, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, text):
        if not text:
            self.status.setText("Không thấy chữ nào trong ảnh.")
            self.retry_btn.setVisible(True)
            return
        self.status.setVisible(False)
        self.edit.setVisible(True)
        self.edit.setPlainText(text)
        self.edit.selectAll()
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.copy_btn.setEnabled(True)
        self.adjustSize()

    def _on_failed(self, msg):
        self.status.setVisible(True)
        self.status.setText("✕ " + msg)
        self.status.setStyleSheet("color:%s;" % theme.ACCENT)
        self.retry_btn.setVisible(True)

    def _copy_and_close(self):
        cur = self.edit.textCursor()
        if cur.hasSelection():
            # Qt selectedText() encodes line breaks as U+2029 (paragraph sep)
            # — restore real newlines or the clipboard gets one run-on line.
            text = cur.selectedText().replace("\u2029", "\n")
        else:
            text = self.edit.toPlainText()
        text = text.strip("\n")
        if text:
            try:
                QtWidgets.QApplication.clipboard().setText(text)
            except Exception:
                pass
            try:
                from notify import show_toast
                show_toast("Đã copy chữ vào clipboard")
            except Exception:
                pass
        self.close()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl_or_cmd = bool(mods & (Qt.KeyboardModifier.ControlModifier
                                   | Qt.KeyboardModifier.MetaModifier))
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ctrl_or_cmd \
                and self.copy_btn.isEnabled():
            self._copy_and_close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # Stop the worker if the user bailed mid-call (best-effort).
        try:
            if self._worker is not None and self._worker.isRunning():
                self._worker.requestInterruption()
        except Exception:
            pass
        super().closeEvent(event)
