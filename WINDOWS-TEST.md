# FC-FastCapture — Tiêu chí test Windows (3 tầng, nhanh → chậm)

> Trả lời câu hỏi: *"test Windows TRƯỚC khi phải đẩy lên GitHub tạo .exe không?"* → **Có.** 2 tầng đầu chạy ngay trên Mac/không cần push. Chỉ tầng 3 mới cần .exe.

Đội nghiệp vụ từng báo bản Windows "không ổn" vì mọi bản trước ship chỉ với CI smoke-import. 3 tầng dưới đóng khoảng trống đó theo thứ tự chi phí tăng dần — **fail ở tầng rẻ thì sửa ngay, không tốn công tầng đắt.**

---

## Tầng 1 · Unit test toán toạ độ — CHẠY TRÊN MAC, ~1 GIÂY (không cần Windows)
Bug đội báo (vùng chụp lệch ở scaling 125%) là **bug TOÁN thuần** (logical↔physical). Đã tách lõi ra `capture.map_logical_to_physical` để test không cần Qt/mss/Windows.

```bash
cd app
python3 test_dpi.py                        # bộ test riêng, in từng ca
PATH="$PWD/.venv/bin:$PATH" bash test.sh   # đã nhúng BLOCK 9 · DPI vào harness chuẩn
```
Bao phủ: Vivobook 1 màn @100/125/150/175% · đa màn khác size (match theo size) · 2 màn giống hệt (tiebreak trái→phải) · ca mơ hồ → fallback identity. **Xanh = toán toạ độ đúng ở mọi scaling.**

## Tầng 2 · Chạy TỪ SOURCE trong VM — không cần build .exe
`.exe` không cross-compile được (PyInstaller), NHƯNG chạy source bằng Python thì được → test **API Windows thật** (RegisterHotKey, mss grab, DPI-aware) mà **không cần push/CI**:
```powershell
# Trong VM Windows (1 lần cài):
winget install Python.Python.3.11        # hoặc python.org
cd <thư mục app đã copy vào VM>
py -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
python main.py                            # chạy thẳng, không đóng gói
```
→ Test được toàn bộ nghiệp vụ; iterate nhanh (sửa .py → chạy lại), không chờ CI ~5 phút/lần.
*(Copy source vào VM: qua thư mục chia sẻ UTM, hoặc `git clone` trong VM.)*

## Tầng 3 · `.exe` đóng gói từ CI — cổng CUỐI, giống hệt máy người dùng
```bash
git push                                   # CI build .exe (KHÔNG đụng release)
gh run watch                               # theo dõi
gh run download -n FC-FastCapture-Windows  # tải .exe về (artifact)
```
Cài .exe trong VM (SmartScreen → More info → Run anyway) → chạy checklist tay bên dưới ở **100% VÀ 125% scaling**.

---

## Checklist tay trong VM (tầng 2 hoặc 3) — CHẠY Ở CẢ 100% VÀ 125%
> Settings → System → Display → Scale để đổi. 125% tái hiện đúng ca Vivobook.

- [ ] Mở app → tray icon 'FC' hiện (SmartScreen nếu .exe)
- [ ] **Mode 1 (Ctrl+Alt+1)**: freeze ngay → kéo chọn vùng → **clipboard KHỚP ĐÚNG vùng chọn** *(bug cũ: lệch 25% @125% — đây là mục quan trọng nhất)*
- [ ] **Mode 2/3 (Ctrl+Alt+2/3)**: chọn → editor mở đúng ảnh → vẽ (mũi tên/khung/**vẽ tay**/bút dạ/mờ/số) → undo/redo → copy + lưu file
- [ ] **Mode 4 (Ctrl+Alt+4)**: chọn cửa sổ → ảnh đúng nội dung cửa sổ
- [ ] **Mode 5 (Ctrl+Alt+5)**: quay GIF vùng chọn → file GIF ĐÚNG VÙNG, đúng nội dung, không frame rác
- [ ] Settings: đổi hotkey → hiệu lực; toggle tự-khởi-động
- [ ] ESC hủy ở mọi mode
- [ ] *(v1.2)* fullscreen là khái niệm của macOS — trên Windows chỉ cần: chụp khi 1 app maximize/borderless vẫn đúng

## Giới hạn coverage (nói thẳng)
- VM hiện là **Windows 11 ARM** (chạy .exe x64 qua Prism). Khác biệt so với **Windows 10** hoặc **x64 gốc** (như Vivobook thật) là **DPI scaling + RegisterHotKey** — cả hai đều test được trong VM bằng cách đổi Scale. Không mô phỏng được đúng GPU/driver hãng máy khác.
- "Các loại Windows khác nhau" ≈ test **ma trận scaling 100/125/150%** trong 1 VM, KHÔNG phải nhiều máy vật lý. Máy thật của đội (Vivobook) là cổng xác nhận cuối.

*Cập nhật: 2026-07 (v1.2).*
