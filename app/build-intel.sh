#!/usr/bin/env bash
# FC-FastCapture — build the INTEL (x86_64) .app + .dmg on an Apple-Silicon Mac
# via Rosetta 2. Mirrors build.sh but runs under `arch -x86_64` with an x86_64
# venv, into a SEPARATE dist-intel/ so the arm64 build is untouched.
set -e
cd "$(dirname "$0")"

VENV=".venv-x86"
DIST="dist-intel"
APP="$DIST/FC-FastCapture.app"
DMG="$DIST/FC-FastCapture-Intel.dmg"
PLIST="$APP/Contents/Info.plist"
X="arch -x86_64"

echo "▸ Tạo venv x86_64 (Rosetta)…"
[ -d "$VENV" ] || $X /usr/bin/python3 -m venv "$VENV"
PYX="$VENV/bin/python"

echo "▸ Cài thư viện x86_64 + PyInstaller…"
$X "$PYX" -m pip install --quiet --upgrade pip wheel >/dev/null
$X "$PYX" -m pip install --quiet -r requirements.txt
$X "$PYX" -m pip install --quiet pyinstaller
$X "$PYX" -c "import platform; print('  ✓ interpreter:', platform.machine())"

echo "▸ Dọn build cũ…"
rm -rf build-intel "$DIST" build-intel.spec

echo "▸ Tạo app icon (FC) → .icns…"
mkdir -p build-intel/FC.iconset
QT_QPA_PLATFORM=offscreen $X "$PYX" - <<'PYI' 2>/dev/null
import sys
from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import theme; theme.load_fonts()
theme.app_icon_pixmap(512).save("build-intel/icon_master.png")
PYI
# Use an ARRAY, not a string — the project path may contain spaces
# ("10X-App Vibe Coding/…"); an unquoted `$ICON_FLAG` word-splits the icon
# path into extra args → "pyinstaller: error: unrecognized arguments: main.py".
ICON_ARGS=()
if [ -f build-intel/icon_master.png ]; then
  for s in 16 32 128 256 512; do
    sips -z $s $s build-intel/icon_master.png --out "build-intel/FC.iconset/icon_${s}x${s}.png" >/dev/null 2>&1
    s2=$((s * 2))
    sips -z $s2 $s2 build-intel/icon_master.png --out "build-intel/FC.iconset/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  if iconutil -c icns build-intel/FC.iconset -o build-intel/FC.icns 2>/dev/null && [ -f build-intel/FC.icns ]; then
    ICON_ARGS=(--icon "$(pwd)/build-intel/FC.icns"); echo "  ✓ FC.icns"
  fi
fi

echo "▸ Đóng gói .app x86_64 (PyInstaller dưới Rosetta)…"
$X "$PYX" -m PyInstaller \
  --name "FC-FastCapture" \
  --windowed --noconfirm --clean \
  --distpath "$DIST" --workpath build-intel/work --specpath build-intel \
  "${ICON_ARGS[@]}" \
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

[ -d "$APP" ] || { echo "✕ PyInstaller không tạo được .app"; exit 1; }

echo "▸ Tinh chỉnh Info.plist…"
set_key () { /usr/libexec/PlistBuddy -c "Add :$1 $2 $3" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :$1 $3" "$PLIST" 2>/dev/null || true; }
# Menu-bar (Accessory) app — no Dock icon; enables fullscreen capture (v1.2).
set_key LSUIElement bool true
set_key NSHighResolutionCapable bool true
APP_VER=$(python -c "import theme; print(theme.APP_VERSION)" 2>/dev/null || echo "1.2")
set_key CFBundleShortVersionString string "$APP_VER"
set_key CFBundleVersion string "$APP_VER"
set_key CFBundleDisplayName string "FC-FastCapture"
set_key NSHumanReadableCopyright string "Dev by Thắng Huyền Đức · 10XLifeOS"

echo "▸ Codesign (chứng chỉ cố định)…"
SIGN_ID="FC-FastCapture Dev (10XLifeOS)"
SIGN_KC="$HOME/Library/Keychains/fc-codesign.keychain-db"
if [ -f "$SIGN_KC" ] && security find-identity -p codesigning "$SIGN_KC" 2>/dev/null | grep -q "$SIGN_ID"; then
  security unlock-keychain -p "fcsign10x" "$SIGN_KC" 2>/dev/null || true
  if codesign --force --deep --sign "$SIGN_ID" --keychain "$SIGN_KC" "$APP" 2>/dev/null; then
    echo "  ✓ đã ký bằng chứng chỉ CỐ ĐỊNH"
  else
    codesign --force --deep --sign - "$APP" 2>/dev/null && echo "  ⚠ fallback ad-hoc"
  fi
else
  codesign --force --deep --sign - "$APP" 2>/dev/null && echo "  ✓ đã ký ad-hoc"
fi

echo "▸ Tạo DMG…"
STAGE="$DIST/.stage"; rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "FC-FastCapture (Intel)" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo ""
echo "════════════════════════════════════════════════"
echo "✓ XONG (Intel / x86_64)!"
echo "  • App : $APP"
echo "  • DMG : $DMG  ($([ -f "$DMG" ] && du -h "$DMG" | cut -f1))"
echo -n "  • Kiến trúc: "; lipo -info "$APP/Contents/MacOS/FC-FastCapture" 2>/dev/null | sed 's/.*: //'
echo "════════════════════════════════════════════════"
