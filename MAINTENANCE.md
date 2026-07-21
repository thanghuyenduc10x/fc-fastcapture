# FC-FastCapture — Quy trình bảo trì A→Z

> Sổ tay vận hành: nhận bug/feature từ đội nghiệp vụ → sửa/phát triển → kiểm chứng 2 nền → phát hành. Áp Khung TẶNG (Ý→Khuôn→Dựng→Chữa→Trao→Mở→Ngẫm) cho mỗi vòng.

**Luật vàng (từ 2026-07):** *Không qua đủ checklist test tay trên CẢ Mac lẫn VM Windows = KHÔNG ship.* Đội nghiệp vụ từng báo bản Windows "không ổn" vì các bản trước ship chỉ với CI smoke-import, chưa chạy thật.

---

## Phân vai
| Vai | Người | Việc |
|---|---|---|
| Chủ sản phẩm / QA nghiệp vụ | Anh Thắng | Báo bug/feature, duyệt cổng spike (feature rủi ro cao), dùng thử & xác nhận lần cuối trước khi phát cho đội |
| Kỹ thuật | AI (Claude) | Code, test 2 nền (Mac + VM Windows), build 3 nền, CI, phát hành, verify |

---

## 6 bước A→Z

### 1 · Tiếp nhận
Mẫu báo cáo 4 dòng (bug hoặc feature) — dán vào issue/chat:
```
• Máy gì:        (macOS Apple Silicon / macOS Intel / Windows + scaling %)
• Bước tái hiện: (1... 2... 3...)
• Kỳ vọng vs thực tế:
• Ảnh/GIF/video: (đính kèm)
```
Feature thì thay 3 dòng cuối bằng: *cho ai · giải nỗi đau gì · "xong" nghĩa là gì*.

### 2 · Triage
- Tái hiện được trên nền nào? (Mac dev-mode / VM Windows).
- **Chặn người dùng** (crash, sai dữ liệu, mất tính năng lõi) → hotfix ngay.
- Còn lại → backlog trong `CLAUDE.md` / ghi chú, gộp vào bản kế.

### 3 · Sửa / Phát triển (Khung TẶNG)
- **Bug** — Luật Sắt: TÁI HIỆN trước → ĐO → sửa GỐC → chặn tái phát → ghi 1 dòng vào **sổ bẫy** (memory `fc-macos-gotchas`).
- **Feature** — spec 1 trang (xong là gì · KHÔNG làm gì · 1 chỉ số). Chẻ lát mỏng, tự chạy xác nhận từng lát.
- **Feature rủi ro cao** (đụng NSWindow level, tap, DPI…) → **SPIKE dev-mode có cổng đánh giá** TRƯỚC khi tích hợp/build. Cổng không đạt → dừng, báo lý do kỹ thuật, không tốn công build.

### 4 · Kiểm chứng (bắt buộc đủ 2 nền)
```
cd app
python3 -m py_compile *.py                 # cú pháp
PATH="$PWD/.venv/bin:$PATH" bash test.sh   # 12-test harness → 12 PASS · 0 FAIL
# + unit test cho phần mới (vd crop DPI @125%)
```
Rồi **test tay** theo checklist (mục cuối file) trên:
- **Mac** (dev-mode `bash run.sh` hoặc bản .app đã cài),
- **VM Windows** (UTM · Win11 ARM) ở scaling **100% VÀ 125%** (tái hiện ca Vivobook).

### 5 · Ship
```
# bump version ở mọi nơi cho khớp (config/about, tên release)
git add app/ && git commit -m "vX.Y: <1 câu changelog>"
git push                                   # CI tự build FC-FastCapture-Windows.exe
cd app && ./build.sh && ./build-intel.sh   # 2 bản .dmg (arm64 + Intel)
```
- Tạo release MỚI vX.Y (giữ bản cũ làm **đường lùi**), đính 3 asset:
  `FC-FastCapture.dmg` · `FC-FastCapture-Intel.dmg` · `FC-FastCapture-Windows.exe`.
- Landing dùng link `/releases/latest/` → tự trỏ bản mới, KHÔNG cần sửa web.
- Verify: `curl -sIL .../releases/latest/download/<asset>` → redirect về vX.Y, HTTP 200.

### 6 · Sau ship
- Cập nhật landing/blog nếu đổi tính năng người dùng thấy.
- Ghi bài học vào memory + sổ bẫy; cập nhật cẩm nang `La Bàn Vibe-Code` nếu có pattern mới.
- **Một release = một dòng CHANGELOG.**

---

## Gotchas hạ tầng (đã trả học phí — đừng dính lại)
- **PyInstaller không cross-compile** → Windows PHẢI build trên `windows-latest` (CI); bincache hỏng → `rm -rf ~/Library/Application\ Support/pyinstaller`.
- **KHÔNG chạy 2 build PyInstaller SONG SONG** (arm64 + Intel cùng lúc) — chúng đua nhau ghi cùng bincache root → "Failed to process binary …" ở cả 2 phía (dính khi build v1.3). Build TUẦN TỰ: arm xong mới intel.
- **File workflow** (`.github/workflows/`) đẩy qua **Git Data API** (Contents API chặn nếu thiếu scope `workflow`). *(Repo local giờ là clone chuẩn → `git push` thường là đủ.)*
- **Chữ ký macOS cố định** ("FC-FastCapture Dev (10XLifeOS)", keychain `fc-codesign.keychain-db`) → giữ quyền TCC qua các build; đổi chữ ký = reset quyền người dùng.
- **DPI Windows**: overlay trả toạ độ *logical*, mss nhận *physical* → phải map qua `capture.logical_rect_to_physical` / crop từ ảnh freeze. Test ở 100/125/150%.
- Cài .app xong: `lsregister -f /Applications/FC-FastCapture.app` (Spotlight thấy).
- **CI trên `windows-latest`: run-step mặc định là POWERSHELL** — cú pháp biến bash `"$VAR"` nở thành chuỗi RỖNG không báo lỗi (dính 3 lần: `gh release upload "$GITHUB_REF_NAME"` → "release not found"). Luôn dùng `${{ github.x }}` expression (thay thế trước khi shell chạy) hoặc `$env:VAR`.
- **Dialog modal đóng ≠ biến khỏi màn hình** — mode 3: freeze sau dialog 60ms vẫn "nướng" dialog vào ảnh đóng băng (cả 2 nền, VM rõ nhất). Fix: `hide()` + `deleteLater()` + `processEvents()` ngay khi đóng + freeze đợi 300ms (`_start_frozen_overlay(delay_ms=300)`).
- **Dialog trong capture-callback (mode 6 first-run)**: nested `exec()` → phải `_suspend_tap()`/`_resume_tap()` (pattern mode 3) + `activate_app()` (app Accessory không tự lấy bàn phím) + MỌI đường thoát đều `overlay=None` + `_end_capture()` (kể cả Huỷ — quên là busy-guard kẹt vĩnh viễn).
- **RAM quay GIF**: frame phải downscale NGAY LÚC QUAY (`_grab`, cap `_MAX_LONG_SIDE=1000px`) chứ không chỉ lúc export — đo thật: 75 frame vùng 2400×1600 = 1102 MB → 121 MB (giảm 9×), chất lượng file GIF không đổi (export vốn thu về đúng cap đó; `_downscale_factor` thấy ≤cap → 1.0, không resize 2 lần).
- **Toast zombie / "vết đen che màn hình" (v1.3.1)** — toast đóng xong nhưng QWidget sống lay lắt (vòng tham chiếu self↔fade-animation chờ cyclic GC); xác NSWindow ẩn vẫn nằm trong `NSApp.windows()`; lần ghim toast SAU match theo-kích-thước vớ nhầm xác + `orderFrontRegardless()` → **dựng xác dậy ở tầng shield, bất tử, đè mọi Space**; rút màn hình thì xác di cư sang màn còn lại. Fix 3 lớp: (1) `raise_window_over_fullscreen` chỉ match cửa sổ `isVisible()`; (2) Toast set `WA_DeleteOnClose` + phá vòng `self._fade = None` trong closeEvent; (3) watchdog `deleteLater` ở 2× vòng đời. Chẩn đoán loại bug này: liệt kê cửa sổ bằng `CGWindowListCopyWindowInfo` lọc theo OwnerName — thấy level 2147483628 onscreen là cửa sổ shield kẹt.
- **Mode 7 OCR qua OpenRouter (v1.5)** — engine OCR = cloud LLM (một API key routes tới Gemini/GPT/Qwen-VL) thay vì OCR cục bộ, vì đó là 1 code path cho cả Mac+Win + tiếng Việt tốt (Windows.Media.Ocr KHÔNG có gói vi). Bẫy:
  - **Slug model LỖI THỜI → 404 "No endpoints found"** (không phải lỗi key/credit). Model đổi tên theo thời gian (gemini-2.0 → 2.5 → 3.x). Khi 404: tra slug hiện hành bằng `curl -s https://openrouter.ai/api/v1/models` (public, không cần key) lọc `input_modalities` chứa "image". Mặc định hiện tại: `google/gemini-2.5-flash-lite` (rẻ, non-reasoning, tiếng Việt tốt).
  - **Gọi mạng PHẢI ở QThread** (`ocr_popup.OcrWorker`) — 1-3s, chạy trên UI thread sẽ đơ app. Busy-guard nhả NGAY khi crop xong (OCR có vòng đời riêng qua popup).
  - **API key: người dùng nhập trong Settings** (echo Password), lưu local `~/.fc_fastcapture.json`, **KHÔNG hard-code / commit / log**. Ảnh RỜI MÁY lên OpenRouter → cảnh báo rõ trong Settings, không dùng cho nội dung nhạy cảm.
  - **urllib stdlib, không thêm dependency** (tránh phình PyInstaller). `ocr.py` thuần (không Qt) → test bằng mock `_open`.
- **Thêm 1 mode mới = đúng 6 điểm data-driven**: `config._DEFAULT_HOTKEYS` (CẢ 2 nhánh OS) · `main._rebuild_combos` (list cứng) · `main.dispatch` · `modeN()`+`_after_modeN()` (mirror mode 1) · tray `_build_tray` · `settings._HOTKEY_ROWS` · `hotkeys_win._HOTKEY_NAMES`. Deep-merge tự bơm hotkey mới vào config cũ — không cần migration.
- **Chụp/quay khi app khác FULLSCREEN (v1.2)** — chốt sau nhiều lần thử:
  - App phải chạy **Accessory** (`setActivationPolicy(Accessory)` lúc khởi động + `LSUIElement=1` trong plist) → **mất icon Dock** (đánh đổi đã chốt, như CleanShot). Đây là *tiền đề* để cửa sổ join được Space fullscreen của app khác.
  - **KHÔNG flip** Regular↔Accessory theo từng lần chụp: sau chu kỳ flip đầu, cửa sổ tạo mới hết join được Space → lần 1 hiện, lần 2+ vô hình. Set 1 lần, giữ suốt đời app.
  - Overlay/toast/nút-Dừng/khung-quay: set `collectionBehavior=CanJoinAllSpaces|FullScreenAuxiliary|Stationary` **TRƯỚC `show()`** (macOS gán Space lúc order-in) + level = `CGShieldingWindowLevel()` (ScreenSaver level chưa đủ). Dùng `NSApp.windows()` khớp theo *size* — KHÔNG cast `winId()`→NSWindow (segfault).
  - Accessory **không tự activate** → editor/settings/kết quả/cửa-sổ-xin-quyền phải gọi `activate_app()` mới nhận bàn phím. ESC trong editor: forward qua **CGEventTap** (không phụ thuộc focus), trừ khi đang gõ chữ inline.
  - Vì sao GIỜ làm được (mà 30/06 bỏ): **freeze-first** chốt pixel ngay lúc bấm phím → tách bạch việc chụp khỏi Space, không cần giữ nguyên fullscreen tới lúc chụp.

---

## Checklist test tay chuẩn (chạy sau MỖI build · CẢ 2 nền)
- [ ] Mở lần đầu (Gatekeeper chuột-phải-Open / SmartScreen Run anyway) → tray icon hiện
- [ ] Hotkey từng mode (1–5, 0) kích hoạt đúng
- [ ] **Mode 1**: bấm → màn hình FREEZE ngay → chọn vùng trên ảnh đóng băng → clipboard **khớp đúng vùng chọn** *(Windows: test ở 100% VÀ 125%)*
- [ ] **Mode 2/3**: chọn → editor mở đúng ảnh → vẽ (mũi tên/khung/**vẽ tay**/bút dạ/mờ/số) → undo/redo → copy + lưu file
- [ ] **Mode 4**: chọn cửa sổ → ảnh đúng nội dung cửa sổ
- [ ] **Mode 5**: quay GIF vùng chọn → file GIF ra đúng vùng, đúng nội dung, không frame rác
- [ ] Settings: đổi hotkey → hiệu lực; toggle tự-khởi-động
- [ ] ESC hủy được ở mọi mode; đa màn hình (Mac); (VM 1 màn)
- [ ] *(v1.2)* Vẽ tay: nét đặc/mượt, 1-click = chấm, đổi màu giữa chừng không đổi nét cũ, export đúng ở 1x + 2x
- [ ] *(v1.2)* Chụp/quay khi app khác đang FULLSCREEN (Mac): overlay hiện đè, không văng khỏi fullscreen
- [ ] *(v1.3)* **Mode 6** (⌘6 / Ctrl+Alt+6): lần đầu → hộp chọn thư mục (không checkbox) → lưu; lần 2+ → lưu thẳng + toast tên file; clipboard vẫn có ảnh; 2 lần cùng giây → `-1.png`; đổi thư mục + hotkey trong Settings có hiệu lực; Huỷ hộp chọn → app không kẹt
- [ ] *(v1.3)* **Mode 3**: hộp nhập kích thước KHÔNG bị dính vào ảnh đóng băng/ảnh chụp
- [ ] *(v1.3)* **GIF RAM**: quay vùng lớn 10s → RAM app không vượt ~vài trăm MB (Activity Monitor / Task Manager)
- [ ] *(v1.5)* **Mode 7 OCR** (⌘7 / Ctrl+Alt+7): nhập key OpenRouter trong Settings → quét vùng chữ (thử tiếng Việt CÓ DẤU + tiếng Anh) → popup ra text đúng, ⌘↵ copy / bôi chọn lấy một phần / Esc thoát; app KHÔNG đơ lúc gọi mạng; key sai/mất mạng → báo lỗi rõ, không crash

*Cập nhật lần cuối: 2026-07 · v1.5: Mode 7 Quét lấy chữ (OCR qua OpenRouter). (v1.4: nút Mode 6 thanh nổi · v1.3.1: fix vết đen toast · v1.3: Mode 6 + fix Mode 3 + RAM GIF · v1.2: Vẽ tay + fullscreen.)*
