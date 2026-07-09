"""
test_dpi.py — TẦNG TEST NHANH cho bug toạ độ Windows (Vivobook DPI).

Chạy: python3 test_dpi.py   (ngay trên Mac, ~1 giây — KHÔNG cần Windows/VM/.exe)

Kiểm chứng `capture.map_logical_to_physical` (lõi thuần của
`logical_rect_to_physical`) đúng ở MỌI mức scaling + đa màn hình. Đây là lớp bug
mà đội nghiệp vụ đã report (vùng chụp lệch 25% ở scaling 125%). Nếu file này
PASS thì phần TOÁN toạ độ đã đúng — chỉ còn phần API thật (RegisterHotKey, mss
grab, DPI-awareness) cần test trên Windows.
"""
from capture import map_logical_to_physical as M

_fail = 0


def check(name, got, want):
    global _fail
    ok = got == want
    print(("✓" if ok else "✗") + " " + name)
    if not ok:
        _fail += 1
        print("    got : %r" % (got,))
        print("    want: %r" % (want,))


# Helper: 1 màn hình vật lý pw×ph ở scaling s% → Qt logical = phys / (s/100).
def laptop(pw, ph, scale_pct, x=0, y=0):
    dpr = scale_pct / 100.0
    return {"x": x, "y": y, "w": int(round(pw / dpr)), "h": int(round(ph / dpr)),
            "dpr": dpr}


def mon(left, top, width, height):
    return {"left": left, "top": top, "width": width, "height": height}


print("── VIVOBOOK: 1 màn 1920×1080, các mức scaling ──")

# 100%: logical == physical, identity.
s100 = [laptop(1920, 1080, 100)]
m100 = [mon(0, 0, 1920, 1080)]
check("100% · rect (100,100,200,150) → giữ nguyên ×1.0",
      M((100, 100, 200, 150), s100, m100), (100, 100, 200, 150, 1.0))

# 125% (đúng ca Vivobook): Qt logical 1536×864, mss physical 1920×1080.
s125 = [laptop(1920, 1080, 125)]         # → {0,0,1536,864,1.25}
m125 = [mon(0, 0, 1920, 1080)]
check("125% · góc (0,0,100,100) → (0,0,125,125) ×1.25",
      M((0, 0, 100, 100), s125, m125), (0, 0, 125, 125, 1.25))
check("125% · (100,100,200,150) → (125,125,250,188) ×1.25",
      M((100, 100, 200, 150), s125, m125), (125, 125, 250, 188, 1.25))
check("125% · giữa màn (768,432,100,100) → (960,540,125,125)",
      M((768, 432, 100, 100), s125, m125), (960, 540, 125, 125, 1.25))

# 150%: Qt logical 1280×720.
s150 = [laptop(1920, 1080, 150)]         # → {0,0,1280,720,1.5}
m150 = [mon(0, 0, 1920, 1080)]
check("150% · (200,100,300,200) → (300,150,450,300) ×1.5",
      M((200, 100, 300, 200), s150, m150), (300, 150, 450, 300, 1.5))

# 175% (4K laptop phổ biến): 3840×2160 @175% → logical ~2194×1234.
s175 = [laptop(3840, 2160, 175)]
m175 = [mon(0, 0, 3840, 2160)]
r = M((500, 300, 400, 250), s175, m175)
check("175% · scale trả về đúng 1.75", r[4], 1.75)
check("175% · origin = 500×1.75, 300×1.75", (r[0], r[1]), (875, 525))

print("\n── ĐA MÀN HÌNH: khác kích thước (match theo size) ──")
# Màn ngoài 1920×1080 @100% ở trái + laptop 1920×1080 @125% ở phải.
ext = {"x": 0, "y": 0, "w": 1920, "h": 1080, "dpr": 1.0}
lap = laptop(1920, 1080, 125, x=1920, y=0)   # logical rộng 1536, đặt sau màn ngoài
screens_multi = [ext, lap]
mons_multi = [mon(0, 0, 1920, 1080), mon(1920, 0, 1920, 1080)]
# Rect trên màn NGOÀI (100%): identity.
check("đa màn · rect màn ngoài (200,200,100,100) → giữ nguyên",
      M((200, 200, 100, 100), screens_multi, mons_multi), (200, 200, 100, 100, 1.0))
# Rect trên LAPTOP (bắt đầu x=1920 logical): local=(x-1920)*1.25 + mon.left=1920.
check("đa màn · rect laptop (1920,0,100,100) → (1920,0,125,125) ×1.25",
      M((1920, 0, 100, 100), [lap, ext], mons_multi), (1920, 0, 125, 125, 1.25))

print("\n── HAI MÀN GIỐNG HỆT: tiebreak theo thứ tự trái→phải ──")
a = {"x": 0, "y": 0, "w": 1920, "h": 1080, "dpr": 1.0}
b = {"x": 1920, "y": 0, "w": 1920, "h": 1080, "dpr": 1.0}
mons_id = [mon(0, 0, 1920, 1080), mon(1920, 0, 1920, 1080)]
# Rect ở màn phải (b) → phải chọn mss monitor phải (left=1920).
check("2 màn giống · rect ở màn phải → origin dời sang mss phải",
      M((1920, 0, 100, 100), [b, a], mons_id), (1920, 0, 100, 100, 1.0))
check("2 màn giống · rect ở màn trái → mss trái",
      M((0, 0, 100, 100), [a, b], mons_id), (0, 0, 100, 100, 1.0))

print("\n── 1 MÀN: luôn dùng màn đó dù size mss lệch (an toàn hơn identity) ──")
# Chỉ 1 monitor → dùng nó + scaling theo Qt DPR (fallback identity sẽ SAI ở 125%).
check("1 màn · size mss lệch nhưng vẫn áp scaling 1.25",
      M((0, 0, 100, 100), [laptop(1920, 1080, 125)], [mon(0, 0, 1366, 768)]),
      (0, 0, 125, 125, 1.25))

print("\n── FALLBACK an toàn: ĐA màn không màn nào khớp size → None (giữ identity) ──")
# >1 monitor và KHÔNG monitor nào khớp size Qt-screen → mơ hồ → None.
check("2 màn, không khớp size nào → None",
      M((0, 0, 100, 100),
        [{"x": 0, "y": 0, "w": 800, "h": 600, "dpr": 1.0},
         {"x": 800, "y": 0, "w": 800, "h": 600, "dpr": 1.0}],
        [mon(0, 0, 1920, 1080), mon(1920, 0, 1366, 768)]), None)

print("\n" + "═" * 42)
if _fail == 0:
    print("✓ TẤT CẢ DPI TEST PASS — toán toạ độ Windows đúng")
    raise SystemExit(0)
else:
    print("✗ %d test DPI FAIL" % _fail)
    raise SystemExit(1)
