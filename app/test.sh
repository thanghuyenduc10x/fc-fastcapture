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

print("\n══ BLOCK 9 · DPI Windows (lõi thuần · bug Vivobook) ══")
def t_dpi():
    import capture
    M = capture.map_logical_to_physical
    lap125 = [{"x": 0, "y": 0, "w": 1536, "h": 864, "dpr": 1.25}]
    m = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
    assert M((100, 100, 200, 150), lap125, m) == (125, 125, 250, 188, 1.25)
    lap100 = [{"x": 0, "y": 0, "w": 1920, "h": 1080, "dpr": 1.0}]
    assert M((10, 20, 30, 40), lap100, m) == (10, 20, 30, 40, 1.0)
check("DPI: map_logical_to_physical @125% + @100%", t_dpi)

print("\n══ BLOCK 10 · Mode 6 (tự lưu) + GIF downscale ══")
def t_mode6_config():
    import config, json, tempfile
    # hotkey mode6 có mặt trong DEFAULTS
    assert config._DEFAULT_HOTKEYS.get("mode6") in ("<cmd>+6", "<ctrl>+<alt>+6")
    # deep-merge bơm mode6 vào config CŨ trên đĩa (không cần migration)
    tmp = tempfile.mktemp(suffix=".json")
    json.dump({"hotkeys": {"mode1": "<cmd>+1"}}, open(tmp, "w"))
    c = config.Config(path=tmp)
    assert c.hotkey("mode6") == config._DEFAULT_HOTKEYS["mode6"]
    # mode6_dir round-trip + normpath (bỏ separator cuối) + không đụng save_dir
    assert c.mode6_dir() == ""
    c.set_mode6_dir("/tmp/fc_m6/")
    d = config.Config(path=tmp)
    assert d.mode6_dir() == "/tmp/fc_m6"
    assert d.get("save_dir") == config.DEFAULT_SAVE_DIR
    os.remove(tmp)
check("config: mode6 hotkey deep-merge + mode6_dir round-trip", t_mode6_config)

def t_unique_path():
    import capture
    taken = {os.path.join("/d", "a.png"), os.path.join("/d", "a-1.png")}
    assert capture.unique_path("/d", "a", ".png",
                               exists=lambda p: False).endswith("a.png")
    assert capture.unique_path("/d", "a", ".png",
                               exists=lambda p: p in taken).endswith("a-2.png")
check("unique_path: hậu tố -1/-2 khi trùng tên cùng giây", t_unique_path)

def t_gif_downscale():
    # Frame quá cap phải được thu nhỏ NGAY lúc quay (fix "app ăn RAM") và
    # export không thu nhỏ lần 2 (factor = 1.0 khi frame đã <= cap).
    from PIL import Image
    import recorder
    f = Image.new("RGB", (2400, 1600))
    try:
        rs = Image.Resampling.LANCZOS
    except AttributeError:
        rs = Image.LANCZOS
    f.thumbnail((recorder._MAX_LONG_SIDE, recorder._MAX_LONG_SIDE), rs)
    assert max(f.size) == recorder._MAX_LONG_SIDE == 1000
    r = recorder.GifRecorder(0, 0, 100, 100, fps=10)
    assert r._downscale_factor(f) == 1.0   # đã nhỏ → export giữ nguyên
check("GIF: downscale lúc quay + export không resize lần 2", t_gif_downscale)

print("\n════════════════════════════════════")
print("  KẾT QUẢ:  \033[92m%d PASS\033[0m · \033[91m%d FAIL\033[0m" % (PASS, FAIL))
print("════════════════════════════════════")
sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
echo ""
[ $RC -eq 0 ] && echo "✓ TẤT CẢ BLOCK PASS" || echo "✕ CÓ BLOCK FAIL (xem ở trên)"
exit $RC
