# Lịch sử phiên bản — FC-FastCapture

Theo chuẩn [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/) + [Semantic Versioning](https://semver.org/lang/vi/) (vX.Y.Z: X lớn, Y tính năng, Z vá lỗi).
Nền tảng: macOS (Apple Silicon + Intel) · Windows x64. Tải bản mới nhất: [releases/latest](https://github.com/thanghuyenduc10x/fc-fastcapture/releases/latest).

---

## [1.5] — 2026-07-21
### Thêm
- **Mode 7 "Quét lấy chữ" (OCR)** — ⌘7 / Ctrl+Alt+7: quét vùng màn hình → nhận diện chữ (qua OpenRouter, hỗ trợ tiếng Việt có dấu) → popup xem–sửa–chọn lại → ⌘↵ sao chép / Esc thoát. Gọi mạng trong luồng riêng nên app không đơ. Nút OCR trên thanh nổi + hàng trong menu + Settings (nhập API key, che ●●●).
### Bảo mật
- API key nhập trong Settings, lưu **cục bộ từng máy**, không commit/log. Ảnh gửi lên dịch vụ khi dùng Mode 7 (có cảnh báo trong Settings).

## [1.4] — 2026-07-15
### Thêm
- Nút **Mode 6 "Chụp + tự lưu"** trên thanh nổi (icon thư mục + mũi tên).

## [1.3.1] — 2026-07-15 · Hotfix
### Sửa
- **Vết đen kẹt che màn hình** (macOS): cửa sổ toast đã đóng bị cơ chế ghim-fullscreen "dựng dậy" ở tầng cao nhất thành khối đen bất tử, rút màn hình thì di cư sang màn khác. Vá 3 lớp (chỉ ghim cửa sổ đang hiển thị · tự huỷ triệt để khi đóng · watchdog).

## [1.3] — 2026-07-15
### Thêm
- **Mode 6 "Chụp + tự lưu"** — ⌘6 / Ctrl+Alt+6: chọn vùng → tự lưu PNG vào thư mục cố định (lần đầu hỏi thư mục, sau lưu thẳng) + copy clipboard; trùng tên cùng giây → hậu tố -1/-2.
### Sửa
- **Mode 3**: hộp nhập kích thước không còn bị "nướng" vào ảnh chụp.
- **RAM quay GIF giảm ~9×** (thu nhỏ khung ngay lúc quay thay vì lúc xuất) — chất lượng file không đổi.

## [1.2] — 2026-07-15
### Thêm
- **Công cụ Vẽ tay** trong editor (nét đặc, mượt, 1 click = chấm).
- **Chụp/quay GIF khi app khác đang toàn màn hình** (macOS) — không văng khỏi fullscreen. Chuyển thành app menu-bar (không icon Dock, như CleanShot).
### Sửa
- Viền editor sáng nổi bật; ESC editor ổn định.

## [1.1] — 2026-07-03
### Thêm
- **Freeze-first**: bấm phím → cả màn hình đóng băng tức thì → chọn vùng trên ảnh đóng băng (bắt được khoảnh khắc nhanh).
### Sửa
- **Lỗi lệch toạ độ vùng chụp trên Windows** ở scaling 125/150% (ca Asus Vivobook) — nguyên nhân logical↔physical pixel; kèm bộ test DPI chạy được ngay trên Mac.

## [1.0] — 2026-06-30 → 2026-07-01
### Thêm
- Bản đầu: chụp màn hình 5 chế độ (nhanh / edit / khoá kích thước / cửa sổ / quay GIF) + editor chú thích + thanh nổi + phím tắt toàn cục.
- **macOS Apple Silicon** (30/06) → **macOS Intel** + **Windows x64** (01/07): mở rộng đủ 3 nền, phát hành qua GitHub Releases + landing 10x-lifeos.com.

---
*Mỗi bản phát hành = một mục ở đây. Bản pre-release (đang test nội bộ) không lên "latest" cho tới khi qua kiểm thử 2 nền.*
