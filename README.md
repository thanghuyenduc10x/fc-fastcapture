# FC-FastCapture

Chụp màn hình + quay GIF cho macOS & Windows · Quà tặng từ **10X Life OS** · Dev by Thắng Huyền Đức.

[![Build Windows](https://github.com/thanghuyenduc10x/fc-fastcapture/actions/workflows/build-windows.yml/badge.svg)](https://github.com/thanghuyenduc10x/fc-fastcapture/actions/workflows/build-windows.yml)
[![Release](https://img.shields.io/github/v/release/thanghuyenduc10x/fc-fastcapture)](https://github.com/thanghuyenduc10x/fc-fastcapture/releases/latest)

![FC-FastCapture](https://10x-lifeos.com/fc-fastcapture/assets/og-cover.png)

🌐 **Trang chủ & hướng dẫn:** https://10x-lifeos.com/fc-fastcapture/

## Tải bản mới nhất

| Nền tảng | Tải về |
|---|---|
| macOS Apple Silicon (M1–M4) | [FC-FastCapture.dmg](https://github.com/thanghuyenduc10x/fc-fastcapture/releases/latest/download/FC-FastCapture.dmg) |
| macOS Intel | [FC-FastCapture-Intel.dmg](https://github.com/thanghuyenduc10x/fc-fastcapture/releases/latest/download/FC-FastCapture-Intel.dmg) |
| Windows | [FC-FastCapture-Windows.exe](https://github.com/thanghuyenduc10x/fc-fastcapture/releases/latest/download/FC-FastCapture-Windows.exe) |

## Cấu trúc repo

- `app/` — mã nguồn app (Python + PyQt6) và công thức build: `build.sh` (Apple Silicon), `build-intel.sh` (Intel), `FC-FastCapture.spec`
- `.github/workflows/build-windows.yml` — CI tự build bản Windows `.exe`
- `docs/drafts/` — nháp tư liệu hành trình build (nguồn của bài blog)
- `index.html` — chỉ là trang chuyển hướng về trang chủ (giữ cho link GitHub Pages cũ còn sống)

## ⚠️ Quy ước quan trọng — đọc trước khi sửa

Trang marketing (landing / blog / one-pager) **sống ở repo [10x-lifeos-site](https://github.com/thanghuyenduc10x/10x-lifeos-site)**, folder `fc-fastcapture/`, tự động deploy lên 10x-lifeos.com khi push.

**KHÔNG tạo lại hay sửa trang marketing trong repo này.** Trước đây repo này từng chứa bản copy của landing/blog — hai bản đã lệch nhau 3 lần nên đã dọn (07/2026, xem git history). Repo này chỉ chứa code app.
