"""
make_icon.py — generate FC.ico for the Windows build from the brand mark.

Run headless in CI (QT_QPA_PLATFORM=offscreen). Renders the same FC squircle the
app uses, then writes a multi-resolution .ico. If Qt/theme rendering is
unavailable for any reason it falls back to a plain Pillow-drawn mark, so this
script NEVER fails the build.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _via_theme():
    """Render the real brand icon through the app's own theme."""
    import sys
    from PyQt6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    import theme
    try:
        theme.load_fonts()
    except Exception:
        pass
    pm = theme.app_icon_pixmap(512)
    pm.save("icon_master.png", "PNG")
    from PIL import Image
    return Image.open("icon_master.png").convert("RGBA")


def _fallback():
    """A brand-orange squircle with white 'FC' — no Qt needed."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 40, 472, 472], radius=110, fill=(201, 96, 40, 255))
    font = None
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, 210)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    d.text((256, 268), "FC", fill="white", anchor="mm", font=font)
    return img


def main():
    try:
        img = _via_theme()
    except Exception as e:
        print("theme icon unavailable, using fallback:", e)
        img = _fallback()
    img.save("FC.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    print("FC.ico written")


if __name__ == "__main__":
    main()
