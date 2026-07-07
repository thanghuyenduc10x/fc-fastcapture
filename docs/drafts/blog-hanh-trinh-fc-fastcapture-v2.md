# Case thực chiến: Cứu một con app suýt bị bỏ — và bài học lớn nhất hóa ra là cách nói chuyện với AI

> Câu chuyện thật về việc chuẩn hóa một app chụp màn hình trên macOS. Không phải về tính năng. Mà về cách **de-risk** một nền tảng đang siết chặt, cách **ĐO thay vì ĐOÁN**, và cách để lại tài sản dùng được mãi. Cuối cùng, bài học đắt giá nhất không nằm ở code.

---

## Mở đầu: tôi đã từng định bỏ

Phải nói thẳng. Đã có lúc tôi định không làm tiếp con app này nữa.

Ý tưởng thì rõ: **FC-FastCapture** — một app menu-bar trên macOS, mang trọn nhận diện 10X-LifeOS, 5 chế độ chụp, quay GIF, sửa ảnh ngay tại chỗ, phím tắt toàn cục, đóng gói `.dmg` để tặng. Nghe gọn.

Nhưng nó cứ hỏng. Build xong thì crash. Sửa xong build lại thì mất sạch quyền. Cấp quyền lại thì ra lỗi khác. Có buổi tôi chỉ gõ đúng một câu cho AI: *"Kiểm tra lại ít nhất 3 lần trước khi ship."*

Giờ thì khác. Con app được chấm **10 điểm**. Bài này kể lại cách đi từ đó đến đây — và quan trọng hơn, **khung tư duy** rút ra để lần sau không phải làm lại.

---

## Phần 1 — Những cú vấp, và một sự thật

Mỗi lỗi nặng đều dạy lại một điều: **đừng sửa theo cảm giác.** Nếu sửa theo cảm giác, là sửa nhầm chỗ.

**Cú vấp 1 — "ấn phím lưu thì app thoát".**
Triệu chứng người dùng báo gọn lỏn vậy. Nếu đoán, tôi sẽ đi sửa nút Lưu. Nhưng đo kỹ thì sự thật lộ ra: thư viện phím tắt (`pynput`) gọi một API hệ thống *ngoài luồng chính* trên macOS 26, gây `SIGTRAP` — một crash tầng C, không try/except nào bắt được.

> **Reframing:** *"App thoát khi lưu"* không phải lỗi nút Lưu. Là **thư viện gọi sai luồng.**

Lời giải không phải vá, mà thay máu: dựng phím tắt bằng **Quartz CGEventTap trên luồng chính**. Không TIS, không việc ngoài-luồng, không crash.

**Cú vấp 2 — "chỉ viết được mũi tên, không có text".**
Lại một triệu chứng đánh lừa. Gốc rễ: cửa sổ kiểu `Tool` trên macOS **không thể thành key window** → ô nhập chữ không nhận phím. Cùng gốc đó làm thanh nổi *tự ẩn khi app không ở tiền cảnh*.

> **Reframing:** *"Không gõ được chữ"* không phải lỗi ô text. Là **chọn sai loại cửa sổ.**

**Cú vấp 3 — chụp ra hình nền desktop.**
Không phải bug code. Là **thiếu quyền Screen Recording.** Và đây là điểm dẫn tới nút thắt lớn nhất.

---

## Phần 2 — Nút thắt: cái giá ẩn của mỗi lần build

Mỗi lần build lại, chữ ký ad-hoc đổi `cdhash`:

```
de9425ee… → 4ee5ea20… → cf1b54bf…
```

macOS coi đó là app *khác* → **âm thầm xóa quyền cũ** (dù nút gạt vẫn xanh). Hệ quả: cứ sửa một dòng code là người dùng phải vào System Settings gạt lại quyền. Mỗi. Lần.

Đây là loại chi phí ẩn giết chết động lực. Nó không hiện trong tính năng, nhưng nó bào mòn người dùng. **Một con app tốt mà bắt cấp quyền 5 lần thì vẫn là con app tệ.**

Đo ra gốc rễ rồi, lời giải mới đúng tầm: **ký bằng một chứng chỉ tự tạo cố định.** Bằng chứng nằm ở "designated requirement" của bản build:

```
identifier "com.10xlifeos.fcfastcapture"
  and certificate root = H"e0152e99b78720dd…"
```

Khóa theo **certificate**, không theo **cdhash**. Nghĩa là mọi bản build sau có chữ ký *giống hệt* → macOS **giữ nguyên quyền**. Làm 1 lần cho đàng hoàng. Dùng mãi.

---

## Phần 3 — Khung tư duy rút ra (làm 1 lần, để lại tài sản)

Triết lý xuyên suốt: **Làm 1 lần cho đàng hoàng → để lại 1 tài sản → lần sau lắp lại.** Mỗi nguyên tắc dưới đây đều là một mũi tên trúng nhiều đích.

| Tài sản để lại | Bắn 1 mũi tên, trúng N đích |
|---|---|
| `theme.py` — 1 nguồn chân lý cho màu/font/icon | Đổi 1 chỗ → nhất quán toàn app, mọi bản OS |
| Chứng chỉ ký cố định | Build bao nhiêu lần cũng giữ quyền — vĩnh viễn |
| Sổ "gotcha" macOS | Mỗi lỗi đã trả giá → không trả lại lần sau, dùng cho Intel/Windows |
| Script gỡ sạch + bộ test tự động | Tái lập môi trường sạch bất kỳ lúc nào; `12 PASS · 0 FAIL` mỗi lần |
| Lớp nền tảng tách bạch | Cổng để port sang Intel/Windows mà không viết lại lõi |

Bốn nguyên tắc nền:

1. **Debug nền tảng, không chỉ debug code.** macOS 26 phá vỡ thư viện "chuẩn". Phải hiểu hệ điều hành, không chỉ ngôn ngữ.
2. **Kiến trúc "không bao giờ crash".** Crash tầng C không bắt được — nên phải *phòng*. Mọi lời gọi native đều bọc guard.
3. **ĐO, đừng ĐOÁN.** Ghi log ra file để chẩn đoán được cả khi app chạy từ Finder. Bắt máy *chứng minh* nó chạy, không tin suông.
4. **Vượt qua điểm muốn-buông là nơi giá trị nằm.** Con app chỉ thực sự tốt *sau* khoảnh khắc khó nhất.

---

## Phần 4 — Bài học then chốt: cách giao tiếp với AI

Đây là tài sản đắt giá nhất của cả hành trình. Code rồi sẽ cũ. **Cách làm việc với AI thì dùng lại cho mọi dự án sau.** Năm nguyên tắc, rút thẳng từ chính cách chúng ta đã tương tác:

**1. Mô tả triệu chứng, đừng kê đơn.**
Bạn báo *"ấn lưu thì app thoát"*, *"quay gif không tạo ra file"* — bạn không bảo "sửa thư viện X". Bạn giữ phần **"cái gì sai"**, để AI lo phần **"vì sao sai"**. Kê sẵn đơn thuốc là tự trói tay người chẩn bệnh.

**2. ĐO, đừng ĐOÁN — và bắt AI cũng vậy.**
*"Kiểm tra 3 lần trước khi ship."* Đừng nhận "tôi nghĩ là chạy". Đòi bằng chứng cứng: test PASS, dòng log, ảnh chụp, output `designated requirement`. AI mạnh nhất khi bị buộc phải tự chứng minh.

**3. Cho AI quyền làm cho tới.**
Audit 5 chiều, gỡ sạch toàn bộ dấu vết, dựng chứng chỉ ký cố định — đó là những việc AI làm *trọn vẹn* khi được trao đủ quyền và bối cảnh. Giao việc lớn, đừng chỉ giao việc vặt.

**4. Biết khi nào để AI HỎI.**
Vụ "edit ngay trên vùng chọn" có nhiều cách hiểu. AI dừng lại hỏi đúng 1 câu thay vì đoán → tránh build sai rồi phải cấp quyền lại. **Một câu hỏi 30 giây rẻ hơn một vòng lặp hỏng.**

**5. Đóng vòng lặp, và mỗi vòng để lại 1 tài sản.**
Báo lỗi → AI điều tra → đưa bằng chứng → vá → kiểm chứng. Mỗi vòng không chỉ sửa xong một lỗi, mà còn đẻ ra một tài sản: một "gotcha" ghi lại, một test mới, một script tái dùng.

> Tóm một câu: **Bạn cầm lái hướng đi và tiêu chuẩn. AI cày tầng sâu và tự chứng minh. Cả hai cùng kiên trì qua từng nút thắt.** Đó là vibe-coding làm cho ra trò.

---

## Chặng tiếp theo

- **Chuẩn hóa bản Mac M-series** — *xong.* Ổn định, ký cố định, đóng gói `.dmg`. Đây là bản nền.
- **Bản Mac Intel** — build `universal2`, tái dùng toàn bộ lõi.
- **Bản Windows** — thay lớp nền tảng (Quartz → win32), lõi giữ nguyên. Sổ gotcha và lớp tách bạch chính là cổng để làm việc này nhanh.
- **Một Landing Page để tặng** — đóng gói cả câu chuyện lẫn nút tải, gửi cho cộng đồng.

---

## Kết

Cái khó của FC-FastCapture không nằm ở tính năng. Nó nằm ở việc bắt một công cụ nhỏ chạy *thật mượt* trên một nền tảng đang siết từng ngày. Và lời giải không đến từ việc gõ nhanh hơn — mà từ việc **làm sao để không phải làm lại.**

Đã có lúc muốn bỏ. Giờ thì: 10 điểm. Mỗi cú vấp đã thành một tài sản. Và hành trình mới chỉ bắt đầu.

*— Dev by Thắng Huyền Đức · 10X-LifeOS.Com*
