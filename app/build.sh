#!/usr/bin/env bash
# FC-FastCapture — package into a shareable FC-FastCapture.app + .dmg.
#   1) PyInstaller → dist/FC-FastCapture.app  (menu-bar utility, no dock icon)
#   2) ad-hoc codesign (required to run on Apple Silicon)
#   3) hdiutil → dist/FC-FastCapture.dmg  (drag-to-Applications installer)
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
APP="dist/FC-FastCapture.app"
DMG="dist/FC-FastCapture.dmg"
PLIST="$APP/Contents/Info.plist"

if [ ! -d "$VENV" ]; then
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "▸ Cài thư viện + PyInstaller…"
python -m pip install --quiet --upgrade pip wheel >/dev/null
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pyinstaller

echo "▸ Dọn build cũ…"
rm -rf build dist FC-FastCapture.spec

echo "▸ Tạo app icon (FC) → .icns…"
mkdir -p build/FC.iconset
QT_QPA_PLATFORM=offscreen python - <<'PYI' 2>/dev/null
import sys
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import theme; theme.load_fonts()
theme.app_icon_pixmap(512).save("build/icon_master.png")   # 1024px master
PYI
ICON_FLAG=""
if [ -f build/icon_master.png ]; then
  for s in 16 32 128 256 512; do
    sips -z $s $s build/icon_master.png --out "build/FC.iconset/icon_${s}x${s}.png" >/dev/null 2>&1
    s2=$((s * 2))
    sips -z $s2 $s2 build/icon_master.png --out "build/FC.iconset/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  if iconutil -c icns build/FC.iconset -o build/FC.icns 2>/dev/null && [ -f build/FC.icns ]; then
    ICON_FLAG="--icon=build/FC.icns"
    echo "  ✓ FC.icns"
  fi
fi

echo "▸ Đóng gói FC-FastCapture.app (PyInstaller)…"
python -m PyInstaller \
  --name "FC-FastCapture" \
  --windowed \
  --noconfirm \
  --clean \
  $ICON_FLAG \
  --osx-bundle-identifier "com.10xlifeos.fcfastcapture" \
  --hidden-import Quartz \
  --hidden-import AppKit \
  --hidden-import Foundation \
  --hidden-import ApplicationServices \
  --hidden-import objc \
  --collect-submodules imageio \
  --collect-submodules mss \
  --collect-all imageio_ffmpeg \
  main.py

if [ ! -d "$APP" ]; then
  echo "✕ PyInstaller không tạo được .app — xem log ở trên."
  exit 1
fi

echo "▸ Tinh chỉnh Info.plist (Dock + Spotlight + retina)…"
if [ -f "$PLIST" ]; then
  set_key () { /usr/libexec/PlistBuddy -c "Add :$1 $2 $3" "$PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Set :$1 $3" "$PLIST" 2>/dev/null || true; }
  # NOTE: NO LSUIElement → app appears in Dock, Spotlight and Cmd-Tab so it's
  # easy to find and launch (the menu-bar "FC" icon is still shown too).
  set_key NSHighResolutionCapable bool true
  set_key CFBundleDisplayName string "FC-FastCapture"
  set_key NSHumanReadableCopyright string "Dev by Thắng Huyền Đức · 10XLifeOS"
fi

# Sign with the STABLE self-signed identity if present → its designated
# requirement is identical every rebuild, so macOS keeps Screen-Recording /
# Accessibility grants across builds (no more re-granting). Falls back to ad-hoc.
SIGN_ID="FC-FastCapture Dev (10XLifeOS)"
SIGN_KC="$HOME/Library/Keychains/fc-codesign.keychain-db"
echo "▸ Codesign…"
if [ -f "$SIGN_KC" ] && security find-identity -p codesigning "$SIGN_KC" 2>/dev/null | grep -q "$SIGN_ID"; then
  security unlock-keychain -p "fcsign10x" "$SIGN_KC" 2>/dev/null || true
  if codesign --force --deep --sign "$SIGN_ID" --keychain "$SIGN_KC" "$APP" 2>/dev/null; then
    echo "  ✓ đã ký bằng chứng chỉ CỐ ĐỊNH (giữ quyền qua các bản build)"
  else
    codesign --force --deep --sign - "$APP" 2>/dev/null && echo "  ⚠ fallback ad-hoc"
  fi
else
  codesign --force --deep --sign - "$APP" 2>/dev/null \
    && echo "  ✓ đã ký ad-hoc" || echo "  ⚠ bỏ qua codesign"
fi

echo "▸ Tạo DMG cài đặt…"
STAGE="dist/.dmg_stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # kéo-thả để cài
hdiutil create \
  -volname "FC-FastCapture" \
  -srcfolder "$STAGE" \
  -ov -format UDZO \
  "$DMG" >/dev/null
rm -rf "$STAGE"

echo ""
echo "════════════════════════════════════════════════"
echo "✓ XONG!"
echo "  • App : $APP"
echo "  • DMG : $DMG"
[ -f "$DMG" ] && echo "  • Size: $(du -h "$DMG" | cut -f1)"
echo ""
echo "  Gửi bạn bè: chia sẻ FC-FastCapture.dmg."
echo "  Lần đầu mở: kéo app vào Applications → chuột phải > Open (app chưa ký Apple)"
echo "  → cấp quyền Screen Recording + Accessibility, rồi mở lại."
echo "════════════════════════════════════════════════"
