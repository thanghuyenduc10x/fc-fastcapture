# Từ "muốn bỏ cuộc" đến "10 điểm ưng ý": Hành trình vibe-coding một app chụp màn hình trên macOS

> Câu chuyện về một con app tưởng chừng đơn giản — chụp màn hình và quay GIF — nhưng đã suýt khiến tôi bỏ cuộc. Và về cách con người + AI ngồi cạnh nhau, gõ tiếng Việt cụt lủn, sửa từng lỗi một, cho đến khi nó chạy mượt thật sự.

---

## Mở đầu: một lời thú nhận

Tôi phải nói thẳng ngay từ đầu: **đã có lúc tôi muốn bỏ.**

Không phải vì ý tưởng tệ. Ý tưởng rất rõ: một app menu-bar trên macOS tên **FC-FastCapture**, mang trọn bộ nhận diện thương hiệu **10X-LifeOS**, có 5 chế độ chụp, quay GIF, trình chỉnh sửa ngay trên ảnh, phím tắt toàn cục, tự khởi động cùng máy, đóng gói thành `.dmg` để tặng bạn bè.

Mà vì nó **cứ hỏng**. Hỏng theo những cách kỳ lạ, sâu trong lòng hệ điều hành, ở những chỗ mà không một bài hướng dẫn nào nhắc tới. Build xong → chạy → crash. Sửa → build lại → mất sạch quyền. Cấp quyền lại → lỗi khác. Có những buổi tôi gõ đúng một câu: *"Kiểm tra lại ít nhất 3 lần trước khi ship."*

Và rồi… nó tốt thật. Mượt thật. Bài viết này kể lại toàn bộ chặng đường đó — không tô hồng.

---

## Chương 1 — Giấc mơ (và bộ công cụ)

Bối cảnh: **macOS 26 (Tahoe)**, máy **Apple Silicon M-series**, **Python 3.9**, giao diện **PyQt6 6.10**. Tham vọng:

- **5 chế độ chụp:** Chụp nhanh → clipboard · Chụp + Edit · Chụp khóa kích thước · Chụp cửa sổ · Quay GIF
- **Trình edit ngay trên ảnh:** mũi tên, khung, bút dạ quang, làm mờ che thông tin, đánh số bước, chữ, màu, độ dày, undo/redo
- **Thanh nổi**, **phím tắt đổi được**, **tự mở khi khởi động máy**
- Một chữ ký kiêu hãnh ở chân app: *"Dev by Thắng Huyền Đức · 10X-LifeOS.Com"*

Nghe thì gọn. Thực tế là một bãi mìn.

---

## Chương 2 — Cú vấp đầu tiên: app tự thoát

Bản build đầu tiên cài vào máy và… **SIGABRT**. Crash ngay khi khởi động.

Thủ phạm: tính năng *"tự mở khi khởi động"*. Code nạp một `LaunchAgent` rồi tự `launchctl load` — khiến launchd mở một bản thứ hai trong môi trường không phải Aqua, và macOS giết tiến trình. Bài học đầu tiên hiện ra:

> **Bằng chứng (gotcha #1):** Trên macOS, đừng `launchctl load -w` một job `RunAtLoad`. Chỉ cần *ghi* file plist; launchd sẽ tự nạp ở lần đăng nhập sau.

Sửa xong cái này, một con quái vật lớn hơn ló mặt.

---

## Chương 3 — Cuộc chiến với nền tảng

### Nút thắt #1: "ấn phím lưu thì app thoát"

Phím tắt toàn cục lúc đầu dùng thư viện `pynput` — thư viện *chuẩn mực* mà ai cũng dùng. Nhưng trên macOS 26, mỗi lần đăng ký lại listener, một luồng nền của pynput gọi vào API Text-Input-Source **ngoài luồng chính**:

```
TSMGetInputSourceProperty → dispatch_assert_queue_fail → SIGTRAP
```

Triệu chứng phía người dùng gọn lỏn: **"ấn phím lưu thì app thoát"**. Đúng vào nút Lưu — nơi tôi re-register hotkey — app chết.

Đây là loại lỗi không vá được bằng `try/except`: nó là crash ở tầng C, không bắt được. Lời giải không phải vá, mà là **thay máu**:

> **Bước ngoặt:** Bỏ hẳn pynput. Thay bằng **Quartz CGEventTap gắn vào run-loop của luồng chính** (`CGEventTapCreate(kCGSessionEventTap, …)`). Callback đọc thẳng `kCGKeyboardEventKeycode` + cờ modifier, khớp phím → bắn, trả `None` để "nuốt" phím. Không TIS, không việc ngoài-luồng-chính, không crash.

### Nút thắt #2: cửa sổ cứ biến mất, chữ không gõ được

Người dùng nhắn: **"Thanh nổi này xấu quá / mode 02-03-04 chỉ viết được mũi tên — không có text."**

Hai lỗi, một gốc rễ: `Qt.WindowType.Tool`.

- Cửa sổ kiểu `Tool` trên macOS **tự ẩn khi app không phải frontmost** → thanh nổi, toast, nút Dừng cứ chớp tắt.
- Cửa sổ `Tool` **không thể trở thành key window** → ô nhập chữ không nhận được phím → chỉ vẽ được mũi tên (chuột), không gõ được text.

> **Gotcha:** Bỏ `Tool`, dùng `FramelessWindowHint | WindowStaysOnTopHint`. Cửa sổ frameless thường *vẫn* nhận phím được (đã kiểm chứng bằng osascript).

Cùng giai đoạn đó là hàng loạt vết thương nhỏ: `winId()→NSWindow` bridging qua objc gây **EXC_BAD_ACCESS** (segfault không bắt được — gỡ bỏ); `QFontDatabase` gọi trước `QGuiApplication` gây **qFatal**; mode 5 trùng phím mặc định của macOS.

---

## Chương 4 — Địa ngục cấp quyền (và khoảnh khắc muốn buông)

Đây là nơi tôi suýt bỏ cuộc.

Mỗi lần app chụp ra **hình nền desktop thay vì nội dung thật** — vì thiếu quyền Screen Recording. Mà mỗi lần build lại, chữ ký ad-hoc đổi `cdhash`:

```
de9425ee… → 4ee5ea20… → cf1b54bf…
```

→ macOS **âm thầm vô hiệu hóa quyền cũ** (dù nút gạt vẫn xanh!). Người dùng phải vào System Settings gạt lại Screen Recording + Accessibility, **mỗi lần**. Rồi:

> **"Kiểm tra lại xem đã chạy chưa? Tôi không tìm thấy trong spotlight"** — hóa ra chỉ số Spotlight ổ Data của máy bị hỏng (`unknown indexing state`), một lỗi hệ thống.
>
> **"phím tắt đang không chạy. Kiểm tra lại ít nhất 3 lần trước khi ship."**
>
> **"Ấn phím lưu thì app thoát. Chạy test kỹ 03 lần trước khi đưa bản cuối cùng."**

Cứ vá một lỗ, một lỗ khác mở ra. Settings lưu phím tắt thành `^N` vì Qt **hoán đổi Cmd↔Ctrl** trong `event.modifiers()`. Mode 3 không đổi được phím vì event-tap *nuốt* mất phím khi đang ghi. Vòng lặp tưởng như vô tận.

Cảm giác lúc đó: con app này không đáng. Nó chỉ là cái nút chụp màn hình thôi mà.

---

## Chương 5 — Những bước ngoặt

Điều giữ chân chúng tôi lại là một thay đổi tư duy: **không debug code nữa, mà debug nền tảng.** Mỗi lỗi được ghi lại thành một "gotcha" — một viên gạch kiến trúc.

Lần lượt các nút thắt được tháo:

- **Recorder phím tắt** đọc `event.nativeModifiers()` (cờ Cocoa thật: Cmd = `0x100000`) thay vì `event.modifiers()` (đã bị Qt hoán đổi) → hết cảnh `^N`.
- **Mode 3** đổi được phím nhờ tạm dừng event-tap khi mở Settings.
- Một **bài audit 5 chiều** (màu sắc · bố cục · kiến trúc · rủi ro · hiệu năng) phát hiện **6 lỗi nghiêm trọng** — nút Lưu của Settings nằm ngoài vùng cuộn (ẩn mất), mode 5 vào lại làm rơi thread quay, editor không cuộn được ảnh lớn… — và vá hết.
- **Gỡ sạch để cài lại từ đầu:** tìm ra *mọi* dấu vết (config, lock, **LaunchAgent tự khởi động**, đăng ký LaunchServices, quyền TCC) và xóa gọn:

```
Successfully reset All approval status for com.10xlifeos.fcfastcapture
✓✓ SẠCH HOÀN TOÀN — không còn dấu vết nào
```

Và một bộ test tự động chạy sau mỗi thay đổi:

```
KẾT QUẢ:  12 PASS · 0 FAIL
```

---

## Chương 6 — Đỉnh điểm: chấm dứt địa ngục cấp quyền

Vấn đề gốc của mọi mệt mỏi là **chữ ký ad-hoc đổi mỗi lần build**. Lời giải triệt để: **ký bằng một chứng chỉ tự tạo cố định.**

Tạo một chứng chỉ code-signing tự ký, đặt trong keychain riêng, cập nhật `build.sh` để ký bằng nó. Bằng chứng quyết định nằm ở "designated requirement" của bản build:

```
designated => identifier "com.10xlifeos.fcfastcapture"
              and certificate root = H"e0152e99b78720dd…"
```

Nó khóa theo **certificate**, không theo **cdhash**. Nghĩa là: mọi bản build sau ký cùng cert này có **chữ ký giống hệt** → macOS **giữ nguyên quyền**. Lần cấp quyền cuối cùng đã đến. Không bao giờ phải gạt lại nữa.

Đó là khoảnh khắc con app ngừng chống lại chúng tôi.

---

## Chương 7 — Mài giũa: những chi tiết làm nên "10 điểm"

Khi nền móng đã vững, app được mài đến độ bóng:

- **Phím tắt rút còn 1 modifier.** Người dùng: *"dùng combo phím cmd + option + 1 thì mất nhiều thời gian quá."* → đổi mặc định sang **⌘1–⌘5, ⌘0** (kèm cảnh báo trung thực: ⌘+số sẽ bị app chiếm toàn cục).
- **ESC để thoát vùng chọn** — sửa tận gốc: bỏ `Tool`, kéo app lên front khi overlay mở, `setFocus`. Kiểm chứng tự động: gửi ESC → `cancelled=True` ✓.
- **Quay GIF mà vẫn click được** — khung viền dùng `WindowTransparentForInput` (NSWindow `ignoresMouseEvents`) → chuột xuyên qua, thao tác app bình thường trong lúc quay.
- **Edit ngay trên vùng chọn.** Ở đây tôi *dừng lại để hỏi* thay vì đoán — và bạn chọn: *"Giữ ô kích thước, thả là vào edit."* → kéo đặt vị trí, thả chuột là vào editor ngay, bỏ nút "✓ Chụp". (Kéo resize thì *không* tự confirm, để chỉnh size trước.)
- **GIF không ra file** → truy ra: bản đóng gói thiếu plugin GIF của imageio nên export bỏ cuộc sớm. Vá bằng **fallback ghi GIF trực tiếp bằng Pillow** (bulletproof) + **ghi log ra file** để chẩn đoán được cả khi app chạy từ Finder (không có console).

---

## Khoảnh khắc "10 điểm"

Rồi tin nhắn ấy đến:

> **"Tuyệt vời rồi, 10đ ưng ý."**

Từ một con app suýt bị bỏ rơi, đến một công cụ mà chính chủ nhân của nó chấm 10 điểm. Cả chặng đường gói gọn trong khoảng cách giữa hai câu: *"ấn phím lưu thì app thoát"* và *"10đ ưng ý"*.

---

## Đúc kết — những bài học mang đi

1. **Debug nền tảng, không chỉ debug code.** macOS 26 phá vỡ pynput, cửa sổ Tool, và các API off-main-thread. Thư viện "chuẩn" vẫn gãy trên hệ điều hành mới nhất. Phải hiểu nền tảng, không chỉ ngôn ngữ.
2. **Kiến trúc "không bao giờ crash".** Mọi lời gọi native (Quartz/mss/imageio/IO) đều phải bọc guard — vì crash tầng C *không* bắt được bằng try/except, nên phải *phòng* nó.
3. **Một nguồn chân lý cho thiết kế.** Toàn bộ màu/font/QSS/icon nằm trong `theme.py` → đổi một chỗ, nhất quán toàn app.
4. **Hiểu cái giá của chữ ký.** Ad-hoc = mất quyền mỗi build. Chứng chỉ cố định = giữ quyền mãi mãi. Một chi tiết hạ tầng nhỏ quyết định toàn bộ trải nghiệm.
5. **Test nghiêm khi người dùng không thấy log.** Test tự động + ghi log ra file + tự kiểm chứng (gửi phím thật, đọc kết quả) thay cho "tôi nghĩ là nó chạy".
6. **Biết khi nào hỏi, khi nào cứ làm.** Vụ "edit tại chỗ" có nhiều cách hiểu → dừng lại hỏi 1 câu, tránh build sai rồi phải cấp quyền lại. Sự gián đoạn 30 giây rẻ hơn một vòng lặp hỏng.
7. **Vượt qua điểm muốn-buông là nơi giá trị nằm.** Con app chỉ thực sự tốt *sau* khoảnh khắc khó nhất.

---

## Chặng tiếp theo — lộ trình

- ✅ **Chuẩn hóa bản Mac M-series** — *xong*. Đây là cột mốc của bài viết này: ổn định, đẹp, ký cố định, đóng gói `.dmg`.
- ⏭️ **Bản Mac Intel** — build `universal2` / `x86_64` để chạy trên máy Mac chip Intel.
- ⏭️ **Bản Windows** — tách lớp nền tảng (Quartz → win32, autolaunch, capture, hotkey theo Windows); Qt6 hỗ trợ Win10/11; build riêng từng OS.
- 🎁 **Một Landing Page (LDP)** để chia sẻ và tặng app — đóng gói câu chuyện + nút tải về cho cộng đồng.

---

## Kết

FC-FastCapture không phải là một app phức tạp về tính năng. Cái khó — và cái đáng — nằm ở việc bắt một công cụ nhỏ chạy *thật sự mượt* trên một nền tảng đang siết chặt từng ngày. Đó là bản chất của **vibe coding**: con người ra hướng và đòi hỏi sự tử tế trong từng chi tiết, AI cày xới tầng sâu của hệ điều hành, và cả hai cùng kiên trì qua hết nút thắt này đến nút thắt khác.

Đã có lúc muốn bỏ. Giờ thì: 10 điểm. Và hành trình mới chỉ bắt đầu.

*— Dev by Thắng Huyền Đức · 10X-LifeOS.Com*
