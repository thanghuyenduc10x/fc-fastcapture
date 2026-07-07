#!/usr/bin/env bash
# FC-FastCapture — smoke-test each block. Clear PASS/FAIL per check.
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
if [ -d "$VENV" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

# Run UI tests headless so no windows actually appear.
export QT_QPA_PLATFORM=offscreen

python - <<'PYEOF'
import importlib, os, sys, traceback

PASS, FAIL = 0, 0
def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        print("  \033[92m✓ PASS\033[0m  %s" % name)
        PASS += 1
    except Exception as e:
        print("  \033[91m✕ FAIL\033[0m  %s  →  %s" % (name, e))
        traceback.print_exc()
        FAIL += 1

# Construct the QApplication FIRST so any QFontDatabase / QSS / widget call is
# safe (accessing QFontDatabase before a QGuiApplication is an uncatchable
# qFatal/SIGABRT). One app instance is shared by every block below.
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

print("\n══ BLOCK 1 · theme + config + import ══")

def t_compile():
    import py_compile, glob
    for f in sorted(glob.glob("*.py")):
        py_compile.compile(f, doraise=True)
check("Tất cả .py biên dịch (py_compile)", t_compile)

def t_theme():
    import theme
    assert theme.ACCENT == "#C96028"                 # brand accent (fixed)
    assert theme.BG.startswith("#") and len(theme.BG) == 7
    assert theme.PANEL.startswith("#") and len(theme.PANEL) == 7
    assert "LifeOS" in theme.SIGNATURE and "Thắng Huyền Đức" in theme.SIGNATURE
    assert isinstance(theme.app_qss(), str) and len(theme.app_qss()) > 100
check("theme: hằng số brand + QSS", t_theme)

def t_config():
    import importlib, config
    importlib.reload(config)
    c = config.Config(path="/tmp/_fc_test_cfg.json")
    c.set("locked_width", 1234)
    c.set_remembered_size(640, 480)
    c.set_save_dir("/tmp/fc_save_test", remember=True)
    d = config.Config(path="/tmp/_fc_test_cfg.json")
    assert d.get("locked_width") == 1234
    assert d.remembered_size() == (640, 480)
    assert d.remember_folder() is True
    os.remove("/tmp/_fc_test_cfg.json")
check("config: ghi/đọc round-trip", t_config)

import theme; theme.load_fonts()

print("\n══ BLOCK 2 · overlay + editor ══")
def t_overlay():
    from overlay import SelectionOverlay
    for m, kw in (("free", {}), ("preset", {"initial_size": (400, 300)}),
                  ("locked", {"locked_size": (200, 200)}),
                  ("window", {"windows": []})):
        ov = SelectionOverlay(mode=m, **kw); ov  # constructs cleanly
check("overlay: 4 chế độ khởi tạo", t_overlay)

def t_editor():
    from PyQt6 import QtGui
    from editor import EditorWindow
    pm = QtGui.QPixmap(300, 200); pm.fill(QtGui.QColor("#222244"))
    ed = EditorWindow(pm, mode_label="MODE 2", scale=1.0,
                      on_copy=lambda q: None, on_save=lambda q: True)
    img = ed.flattened()
    assert img.width() >= 1 and img.height() >= 1
check("editor: dựng + flattened() ra QImage", t_editor)

print("\n══ BLOCK 3/4 · settings + notify ══")
def t_settings():
    import config
    from settings import SettingsWindow
    SettingsWindow(config.Config(path="/tmp/_fc_s.json"))
    if os.path.exists("/tmp/_fc_s.json"): os.remove("/tmp/_fc_s.json")
check("settings: dựng cửa sổ", t_settings)

def t_notify():
    import notify
    notify.show_toast("FC_test.png")
check("notify: toast", t_notify)

print("\n══ BLOCK 5 · floating bar ══")
def t_bar():
    from floatingbar import FloatingBar
    b = FloatingBar()
    assert hasattr(b, "modeTriggered") and hasattr(b, "hideRequested")
check("floatingbar: dựng + tín hiệu", t_bar)

print("\n══ BLOCK 6 · window detection ══")
def t_windows():
    import windows
    w = windows.list_windows()
    assert isinstance(w, list)
check("windows: list_windows() trả list", t_windows)

print("\n══ BLOCK 7 · capture + recorder ══")
def t_capture():
    import capture
    g = capture.virtual_geometry()
    assert len(g) == 4
    s = capture.primary_scale(); assert s >= 1.0
check("capture: geometry + scale", t_capture)

def t_recorder():
    from recorder import GifRecorder, StopButton, GifResultWindow
    GifRecorder(0, 0, 100, 100, fps=10)
    StopButton((0, 0, 100, 100))
check("recorder: dựng GifRecorder + StopButton", t_recorder)

print("\n══ BLOCK 8 · autolaunch ══")
def t_autolaunch():
    import autolaunch
    assert isinstance(autolaunch.is_enabled(), bool)
    assert isinstance(autolaunch.current_launch_command(), list)
check("autolaunch: API", t_autolaunch)

print("\n════════════════════════════════════")
print("  KẾT QUẢ:  \033[92m%d PASS\033[0m · \033[91m%d FAIL\033[0m" % (PASS, FAIL))
print("════════════════════════════════════")
sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
echo ""
[ $RC -eq 0 ] && echo "✓ TẤT CẢ BLOCK PASS" || echo "✕ CÓ BLOCK FAIL (xem ở trên)"
exit $RC
