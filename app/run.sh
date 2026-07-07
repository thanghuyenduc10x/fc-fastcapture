#!/usr/bin/env bash
# FC-FastCapture — install deps into a local venv and launch (test/dev mode).
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"

echo "▸ FC-FastCapture · 10XLifeOS"
echo "▸ Python: $("$PY" --version 2>&1)"

if [ ! -d "$VENV" ]; then
  echo "▸ Tạo virtualenv ($VENV)…"
  "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "▸ Cập nhật pip…"
python -m pip install --quiet --upgrade pip wheel >/dev/null

echo "▸ Cài thư viện (lần đầu hơi lâu)…"
python -m pip install --quiet -r requirements.txt

echo "▸ Khởi động app…  (biểu tượng 'FC' sẽ xuất hiện trên menu bar)"
echo "  ⌘⌥1 Quick · ⌘⌥2 Edit · ⌘⌥3 Khóa · ⌘⌥4 Cửa sổ · ⌘⌥5 GIF · ⌘⌥0 Thanh nổi"
exec python main.py
