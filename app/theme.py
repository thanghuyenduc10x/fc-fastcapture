"""
theme.py — FC-FastCapture brand design system ("10XLifeOS").

SINGLE SOURCE OF TRUTH for every color, font, radius, spacing value and the
global QSS stylesheet. Every other module imports brand values from here so the
design stays perfectly consistent and is trivial to re-tune in one place.

Pure-data constants (colors / radii / strings) import with no Qt dependency.
Anything that touches QFont / QColor / QFontDatabase is wrapped in functions that
must be called AFTER a QApplication exists.

Target: Python 3.9+, PyQt6.
"""
from __future__ import annotations

import os

# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────
APP_NAME = "FC-FastCapture"
APP_VERSION = "1.4"        # single source of truth — build scripts + About read this
BRAND = "10XLifeOS"
SIGNATURE = "Dev by Thắng Huyền Đức · 10X-LifeOS.Com"

# ─────────────────────────────────────────────────────────────────────────────
# Colors (the 10XLifeOS palette — exact brand values)
# ─────────────────────────────────────────────────────────────────────────────
# Apple-style neutral-dark palette (modern & simple) keeping the 10XLifeOS
# orange accent. Backgrounds went from saturated navy → clean neutral charcoal
# so the brand orange pops and the UI feels like a native macOS app.
BG = "#16161A"               # App background (neutral near-black)
PANEL = "#1F1F25"            # Panel / elevated surface
CONTROL = "#2C2C33"          # secondary buttons / input fill
PANEL_BORDER = "rgba(255,255,255,0.07)"
SECONDARY_BORDER = "rgba(255,255,255,0.12)"

ACCENT = "#C96028"           # primary accent (brand)
ACCENT_HOVER = "#D97538"     # hover lighten
ACCENT_PRESSED = "#A84F20"   # pressed darken

TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#9A9AA2"    # neutral secondary label (Apple-style gray)
TEXT_MUTED = "#6A6A72"        # tertiary labels

ANNOTATION = "#C96028"       # arrows / text / rect default
SUCCESS = "#30D158"          # Apple system green

# Lighter accent tint (used sparingly). Shadows are now neutral, not glowing.
ACCENT_LIGHT = "#E07A3E"
ACCENT_GLOW = "#000000"      # soft neutral drop-shadow color (Apple-style)

# Annotation color swatches the editor offers (first = brand accent default).
SWATCHES = ["#C96028", "#EF4444", "#FACC15", "#4ADE80",
            "#3B82F6", "#A855F7", "#FFFFFF", "#111111"]
# Highlighter colors (semi-transparent feel) keyed off swatches.
HIGHLIGHT = "#FACC15"
# Pen thickness presets: (label, px).
THICKNESSES = [("Mảnh", 2), ("Vừa", 4), ("Đậm", 7)]

# Capture overlay dimming (neutral dark veil over the screen)
OVERLAY_DIM = "rgba(0, 0, 0, 0.50)"
# Brighter tint of the live selection rectangle border
SELECTION_BORDER = ACCENT

# ─────────────────────────────────────────────────────────────────────────────
# Geometry / spacing
# ─────────────────────────────────────────────────────────────────────────────
RADIUS_BUTTON = 6
RADIUS_PANEL = 12
PAD = 14                      # generous padding 12–16px
PAD_SM = 10
GAP = 10

TRANSITION = "0.2s"          # documented; Qt has no CSS transition but we keep
                             # the value here as the single source of truth.

# ─────────────────────────────────────────────────────────────────────────────
# Font family preference stacks (first available wins, else Qt default)
# ─────────────────────────────────────────────────────────────────────────────
# Apple-first font stacks (SF Pro) for a native, modern feel; brand fonts kept
# as fallbacks if SF Pro isn't present.
HEADING_STACK = ["SF Pro Display", "SF Pro Text", ".AppleSystemUIFont",
                 "Helvetica Neue", "Montserrat", "Arial"]
BODY_STACK = ["SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",
              "Be Vietnam Pro", "Arial"]
NUMBER_STACK = ["SF Mono", "SF Pro Text", "Menlo", "Inter", "Helvetica Neue",
                "Arial"]

# Optional bundled fonts directory (assets/fonts/*.ttf). Absent by default —
# the app falls back to system families gracefully.
_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets", "fonts")

_FONTS_LOADED = False
_RESOLVED = {}  # role -> resolved family string (cached after QApplication)


# ─────────────────────────────────────────────────────────────────────────────
# Color helpers  (require QtGui — call after QApplication or at least import-safe)
# ─────────────────────────────────────────────────────────────────────────────
def qcolor(value):
    """Convert a brand color string ('#RRGGBB' or 'rgba(r,g,b,a)') to QColor."""
    from PyQt6.QtGui import QColor
    if value is None:
        return QColor(0, 0, 0, 0)
    v = value.strip()
    if v.startswith("rgba") or v.startswith("rgb"):
        inside = v[v.index("(") + 1:v.index(")")]
        parts = [p.strip() for p in inside.split(",")]
        r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
        a = int(float(parts[3]) * 255) if len(parts) > 3 else 255
        return QColor(r, g, b, a)
    c = QColor(v)
    if not c.isValid():
        c = QColor("#000000")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# Font loading / resolution  (call load_fonts() once after QApplication())
# ─────────────────────────────────────────────────────────────────────────────
def load_fonts():
    """Register any bundled .ttf fonts. Safe to call once after QApplication."""
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    try:
        from PyQt6.QtGui import QFontDatabase, QGuiApplication
        # QFontDatabase access before a QGuiApplication is a non-catchable
        # qFatal (SIGABRT). Never touch it until the app exists.
        if QGuiApplication.instance() is None:
            return
        if os.path.isdir(_FONTS_DIR):
            for fn in sorted(os.listdir(_FONTS_DIR)):
                if fn.lower().endswith((".ttf", ".otf")):
                    QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, fn))
    except Exception:
        return
    _FONTS_LOADED = True


def _available_families():
    # IMPORTANT: QFontDatabase.families() before a QGuiApplication exists raises
    # an uncatchable Qt qFatal → SIGABRT. Guard on the app instance so app_qss()
    # / family() are always safe to call (they just fall back to system fonts).
    try:
        from PyQt6.QtGui import QFontDatabase, QGuiApplication
        if QGuiApplication.instance() is None:
            return set()
        return set(QFontDatabase.families())
    except Exception:
        return set()


def family(role):
    """Return the best available family for 'heading' | 'body' | 'number'."""
    if role in _RESOLVED:
        return _RESOLVED[role]
    stacks = {"heading": HEADING_STACK, "body": BODY_STACK, "number": NUMBER_STACK}
    stack = stacks.get(role, BODY_STACK)
    avail = _available_families()
    chosen = stack[-1]
    for fam in stack:
        if fam in avail:
            chosen = fam
            break
    _RESOLVED[role] = chosen
    return chosen


def _qweight(weight):
    from PyQt6.QtGui import QFont
    table = [
        (100, QFont.Weight.Thin), (200, QFont.Weight.ExtraLight),
        (300, QFont.Weight.Light), (400, QFont.Weight.Normal),
        (500, QFont.Weight.Medium), (600, QFont.Weight.DemiBold),
        (700, QFont.Weight.Bold), (800, QFont.Weight.ExtraBold),
        (900, QFont.Weight.Black),
    ]
    best = QFont.Weight.Normal
    bestd = 1e9
    for val, enum in table:
        d = abs(val - weight)
        if d < bestd:
            bestd, best = d, enum
    return best


def font(role, size, weight=400, italic=False):
    """Build a QFont for a brand role.

    role: 'heading' | 'body' | 'number'
    size: point size (int)
    weight: 100..900 CSS-style
    """
    from PyQt6.QtGui import QFont
    f = QFont(family(role), size)
    try:
        f.setWeight(_qweight(weight))
    except Exception:
        f.setBold(weight >= 600)
    f.setItalic(italic)
    if role == "heading":
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0)
    return f


# Convenience builders ----------------------------------------------------------
def heading_font(size=18, weight=800):
    return font("heading", size, weight)


def body_font(size=13, weight=500):
    return font("body", size, weight)


def number_font(size=13, weight=500):
    return font("number", size, weight)


# ─────────────────────────────────────────────────────────────────────────────
# QSS — global application stylesheet + reusable component snippets
# ─────────────────────────────────────────────────────────────────────────────
def app_qss():
    """Global stylesheet applied to the whole QApplication.

    Styles base widgets, primary/secondary/ghost buttons (selected via the
    'variant' dynamic property), inputs, checkboxes, labels (via the 'role'
    dynamic property), scrollbars and tooltips — all from brand constants.
    """
    return f"""
    * {{
        font-family: "{family('body')}";
        color: {TEXT_PRIMARY};
        outline: none;
    }}
    QWidget {{
        background-color: {BG};
        color: {TEXT_PRIMARY};
    }}
    QWidget#panel, QFrame#panel {{
        background-color: {PANEL};
        border: 1px solid {PANEL_BORDER};
        border-radius: {RADIUS_PANEL}px;
    }}

    /* Primary button (accent) */
    QPushButton {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
        border: none;
        border-radius: {RADIUS_BUTTON}px;
        padding: 9px 16px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}
    QPushButton:pressed {{ background-color: {ACCENT_PRESSED}; }}
    QPushButton:disabled {{ background-color: {CONTROL}; color: {TEXT_MUTED}; }}

    /* Secondary button (subtle neutral fill, Apple-style) */
    QPushButton[variant="secondary"] {{
        background-color: {CONTROL};
        border: none;
        color: {TEXT_PRIMARY};
    }}
    QPushButton[variant="secondary"]:hover {{ background-color: #3A3A43; }}
    QPushButton[variant="secondary"]:pressed {{ background-color: #26262C; }}

    /* Ghost / icon tool button (used by toolbars & floating bar) */
    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_BUTTON}px;
        padding: 6px 8px;
        color: {TEXT_SECONDARY};
        font-weight: 600;
    }}
    QPushButton[variant="ghost"]:hover {{
        background-color: rgba(201,96,40,0.18);
        border: 1px solid {ACCENT};
        color: {TEXT_PRIMARY};
    }}
    QPushButton[variant="ghost"]:checked {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
        border: 1px solid {ACCENT};
    }}

    /* Inputs */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {CONTROL};
        border: 1px solid transparent;
        border-radius: {RADIUS_BUTTON}px;
        padding: 7px 10px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT};
        font-family: "{family('number')}";
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}

    /* Checkbox toggle */
    QCheckBox {{ spacing: 10px; color: {TEXT_PRIMARY}; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 5px;
        border: 1px solid {SECONDARY_BORDER};
        background-color: {BG};
    }}
    QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border: 1px solid {ACCENT};
        image: none;
    }}

    /* Labels via role property */
    QLabel[role="title"] {{
        font-family: "{family('heading')}";
        font-weight: 800;
        font-size: 22px;
        color: {TEXT_PRIMARY};
    }}
    QLabel[role="subtitle"] {{
        font-family: "{family('heading')}";
        font-weight: 700;
        font-size: 14px;
        color: {TEXT_PRIMARY};
    }}
    QLabel[role="signature"] {{
        color: {TEXT_MUTED};
        font-size: 12px;
    }}
    QLabel[role="muted"] {{ color: {TEXT_MUTED}; font-size: 12px; }}
    QLabel[role="secondary"] {{ color: {TEXT_SECONDARY}; }}
    QLabel[role="size"] {{
        font-family: "{family('number')}";
        color: {ACCENT};
        font-weight: 600;
        font-size: 13px;
    }}

    QToolTip {{
        background-color: {PANEL};
        color: {TEXT_PRIMARY};
        border: 1px solid {ACCENT};
        border-radius: {RADIUS_BUTTON}px;
        padding: 6px 8px;
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {TEXT_MUTED}; border-radius: 5px; min-height: 24px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


# Reusable QSS snippets for frameless / translucent windows that style their own
# root container (floating bar, toast, editor toolbar) ────────────────────────
def qss_panel():
    return (f"background-color:{PANEL};"
            f"border:1px solid {PANEL_BORDER};"
            f"border-radius:{RADIUS_PANEL}px;")


def qss_primary_btn():
    # Flat solid accent (Apple-style) — clean, no gradient.
    return (f"QPushButton{{background:{ACCENT};color:{TEXT_PRIMARY};border:none;"
            f"border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-weight:600;}}"
            f"QPushButton:hover{{background:{ACCENT_HOVER};}}"
            f"QPushButton:pressed{{background:{ACCENT_PRESSED};}}")


def qss_secondary_btn():
    # Subtle neutral fill (Apple-style), no border.
    return (f"QPushButton{{background:{CONTROL};color:{TEXT_PRIMARY};border:none;"
            f"border-radius:{RADIUS_BUTTON}px;padding:8px 16px;font-weight:600;}}"
            f"QPushButton:hover{{background:#3A3A43;}}"
            f"QPushButton:pressed{{background:#26262C;}}")


def qss_tool_btn():
    return (f"QPushButton{{background:transparent;color:{TEXT_SECONDARY};"
            f"border:1px solid transparent;border-radius:{RADIUS_BUTTON}px;"
            f"padding:6px 9px;font-weight:600;}}"
            f"QPushButton:hover{{background:rgba(201,96,40,0.18);"
            f"border:1px solid {ACCENT};color:{TEXT_PRIMARY};}}"
            f"QPushButton:checked{{background:{ACCENT};color:{TEXT_PRIMARY};"
            f"border:1px solid {ACCENT};}}")


# ─────────────────────────────────────────────────────────────────────────────
# Premium effects + vector icon system (call after a QApplication exists)
# ─────────────────────────────────────────────────────────────────────────────
def apply_glow(widget, color=None, blur=22, dy=6, alpha=75):
    """Attach a soft, subtle NEUTRAL drop shadow (Apple-style) to a widget.
    Defaults are intentionally restrained — no flashy glow. Best-effort."""
    try:
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur)
        c = qcolor(color or ACCENT_GLOW)
        c.setAlpha(alpha)
        eff.setColor(c)
        eff.setOffset(0, dy)
        widget.setGraphicsEffect(eff)
        return eff
    except Exception:
        return None


def qss_bar():
    """Clean flat panel for floating bars / toast (Apple-style, no gradient)."""
    return (f"background:{PANEL};"
            f"border:1px solid {SECONDARY_BORDER};"
            f"border-radius:{RADIUS_PANEL}px;")


def _icon_canvas(size):
    """Return (QPixmap, QPainter) at 2x dpr with antialiasing for a crisp icon."""
    from PyQt6.QtGui import QPixmap, QPainter
    pm = QPixmap(int(size * 2), int(size * 2))
    pm.setDevicePixelRatio(2.0)
    pm.fill(qcolor("rgba(0,0,0,0)"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    return pm, p


def _stroke(p, color, w):
    from PyQt6.QtGui import QPen
    from PyQt6.QtCore import Qt as _Qt
    pen = QPen(qcolor(color))
    pen.setWidthF(w)
    pen.setCapStyle(_Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(_Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    from PyQt6.QtGui import QBrush
    p.setBrush(_Qt.BrushStyle.NoBrush)


def mode_icon(n, size=22, color=None):
    """Crisp vector icon (QPixmap) for each capture mode 1..5, in `color`."""
    from PyQt6 import QtGui
    from PyQt6.QtCore import Qt as _Qt, QPointF, QRectF
    col = color or ACCENT
    pm, p = _icon_canvas(size)
    S = float(size)
    _stroke(p, col, 2.0)
    if n == 1:                      # Quick → lightning bolt (filled)
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        pts = [(0.58, 0.10), (0.26, 0.56), (0.46, 0.56),
               (0.40, 0.90), (0.74, 0.42), (0.52, 0.42)]
        poly = QtGui.QPolygonF([QPointF(x * S, y * S) for x, y in pts])
        p.drawPolygon(poly)
    elif n == 2:                    # Edit → pencil
        p.drawLine(QPointF(0.24 * S, 0.76 * S), QPointF(0.70 * S, 0.30 * S))
        p.drawLine(QPointF(0.70 * S, 0.30 * S), QPointF(0.80 * S, 0.40 * S))
        p.drawLine(QPointF(0.80 * S, 0.40 * S), QPointF(0.34 * S, 0.86 * S))
        p.drawLine(QPointF(0.24 * S, 0.76 * S), QPointF(0.34 * S, 0.86 * S))
        p.drawLine(QPointF(0.20 * S, 0.80 * S), QPointF(0.28 * S, 0.84 * S))
    elif n == 3:                    # Locked size → padlock
        body = QRectF(0.28 * S, 0.46 * S, 0.44 * S, 0.40 * S)
        p.drawRoundedRect(body, 0.06 * S, 0.06 * S)
        path = QtGui.QPainterPath()
        path.moveTo(0.36 * S, 0.46 * S)
        path.lineTo(0.36 * S, 0.34 * S)
        path.arcTo(QRectF(0.36 * S, 0.18 * S, 0.28 * S, 0.30 * S), 180, -180)
        path.lineTo(0.64 * S, 0.46 * S)
        p.drawPath(path)
    elif n == 4:                    # Window
        outer = QRectF(0.18 * S, 0.24 * S, 0.64 * S, 0.52 * S)
        p.drawRoundedRect(outer, 0.06 * S, 0.06 * S)
        p.drawLine(QPointF(0.18 * S, 0.38 * S), QPointF(0.82 * S, 0.38 * S))
        p.setBrush(qcolor(col))
        p.setPen(_Qt.PenStyle.NoPen)
        for i in range(3):
            p.drawEllipse(QPointF((0.25 + i * 0.07) * S, 0.31 * S),
                          0.018 * S, 0.018 * S)
    elif n == 5:                    # Record → GIF
        p.drawEllipse(QRectF(0.20 * S, 0.20 * S, 0.60 * S, 0.60 * S))
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        p.drawEllipse(QPointF(0.50 * S, 0.50 * S), 0.16 * S, 0.16 * S)
    elif n == 6:                    # Auto-save → folder + down arrow
        # Folder: tab + body (outline, consistent 2px stroke).
        path = QtGui.QPainterPath()
        path.moveTo(0.14 * S, 0.34 * S)
        path.lineTo(0.14 * S, 0.26 * S)
        path.lineTo(0.38 * S, 0.26 * S)          # tab top
        path.lineTo(0.46 * S, 0.34 * S)          # tab slope
        path.lineTo(0.86 * S, 0.34 * S)
        path.lineTo(0.86 * S, 0.78 * S)
        path.lineTo(0.14 * S, 0.78 * S)
        path.closeSubpath()
        p.drawPath(path)
        # Arrow dropping INTO the folder (filled head, stroked shaft).
        p.drawLine(QPointF(0.50 * S, 0.06 * S), QPointF(0.50 * S, 0.52 * S))
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        head = QtGui.QPolygonF([QPointF(0.38 * S, 0.50 * S),
                                QPointF(0.62 * S, 0.50 * S),
                                QPointF(0.50 * S, 0.66 * S)])
        p.drawPolygon(head)
    p.end()
    return pm


def tool_icon(name, size=20, color=None):
    """Crisp vector icon (QPixmap) for an editor tool, in `color`."""
    from PyQt6 import QtGui
    from PyQt6.QtCore import Qt as _Qt, QPointF, QRectF
    col = color or TEXT_SECONDARY
    pm, p = _icon_canvas(size)
    S = float(size)
    _stroke(p, col, 2.0)
    if name == "select":            # pointer arrow
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        pts = [(0.28, 0.18), (0.28, 0.78), (0.44, 0.62),
               (0.55, 0.86), (0.66, 0.80), (0.55, 0.57), (0.74, 0.55)]
        p.drawPolygon(QtGui.QPolygonF([QPointF(x * S, y * S) for x, y in pts]))
    elif name == "text":            # bold T
        f = heading_font(int(S * 0.8), 800)
        p.setFont(f)
        p.setPen(qcolor(col))
        p.drawText(QRectF(0, 0, S, S), int(_Qt.AlignmentFlag.AlignCenter), "T")
    elif name == "arrow":
        p.drawLine(QPointF(0.22 * S, 0.78 * S), QPointF(0.74 * S, 0.26 * S))
        p.drawLine(QPointF(0.74 * S, 0.26 * S), QPointF(0.52 * S, 0.26 * S))
        p.drawLine(QPointF(0.74 * S, 0.26 * S), QPointF(0.74 * S, 0.48 * S))
    elif name == "rect":
        p.drawRoundedRect(QRectF(0.20 * S, 0.26 * S, 0.60 * S, 0.48 * S),
                          0.05 * S, 0.05 * S)
    elif name == "highlight":       # marker nib + stroke
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        nib = QtGui.QPolygonF([QPointF(0.30 * S, 0.20 * S),
                               QPointF(0.46 * S, 0.20 * S),
                               QPointF(0.66 * S, 0.56 * S),
                               QPointF(0.50 * S, 0.56 * S)])
        p.drawPolygon(nib)
        hl = qcolor(col)
        hl.setAlpha(110)
        p.setBrush(hl)
        p.drawRect(QRectF(0.30 * S, 0.66 * S, 0.40 * S, 0.16 * S))
    elif name == "pen":             # pen nib + freehand squiggle (opaque)
        # Diagonal pen body
        p.drawLine(QPointF(0.40 * S, 0.56 * S), QPointF(0.72 * S, 0.24 * S))
        # Filled nib tip at lower-left of the body
        p.setPen(_Qt.PenStyle.NoPen)
        p.setBrush(qcolor(col))
        nib = QtGui.QPolygonF([QPointF(0.28 * S, 0.68 * S),
                               QPointF(0.40 * S, 0.56 * S),
                               QPointF(0.46 * S, 0.62 * S),
                               QPointF(0.34 * S, 0.74 * S)])
        p.drawPolygon(nib)
        # Freehand squiggle underneath — SOLID (vs highlight's alpha bar)
        _stroke(p, col, 2.2)
        path = QtGui.QPainterPath()
        path.moveTo(QPointF(0.22 * S, 0.88 * S))
        path.cubicTo(QPointF(0.38 * S, 0.78 * S), QPointF(0.50 * S, 0.98 * S),
                     QPointF(0.68 * S, 0.86 * S))
        p.drawPath(path)
    elif name == "blur":            # mosaic grid
        p.setPen(_Qt.PenStyle.NoPen)
        for r in range(3):
            for c in range(3):
                cc = qcolor(col)
                cc.setAlpha(90 + ((r + c) % 2) * 120)
                p.setBrush(cc)
                p.drawRect(QRectF((0.24 + c * 0.18) * S, (0.24 + r * 0.18) * S,
                                  0.14 * S, 0.14 * S))
    elif name == "step":            # numbered circle "1"
        p.drawEllipse(QRectF(0.20 * S, 0.20 * S, 0.60 * S, 0.60 * S))
        f = number_font(int(S * 0.46), 800)
        p.setFont(f)
        p.setPen(qcolor(col))
        p.drawText(QRectF(0.20 * S, 0.20 * S, 0.60 * S, 0.60 * S),
                   int(_Qt.AlignmentFlag.AlignCenter), "1")
    elif name in ("undo", "redo"):  # curved arrow
        rect = QRectF(0.24 * S, 0.26 * S, 0.52 * S, 0.46 * S)
        if name == "undo":
            p.drawArc(rect, 40 * 16, 260 * 16)
            tip = QPointF(0.30 * S, 0.34 * S)
            p.drawLine(tip, QPointF(0.30 * S, 0.50 * S))
            p.drawLine(tip, QPointF(0.44 * S, 0.34 * S))
        else:
            p.drawArc(rect, 140 * 16, -260 * 16)
            tip = QPointF(0.70 * S, 0.34 * S)
            p.drawLine(tip, QPointF(0.70 * S, 0.50 * S))
            p.drawLine(tip, QPointF(0.56 * S, 0.34 * S))
    p.end()
    return pm


# ─────────────────────────────────────────────────────────────────────────────
# FC brand mark — ONE consistent symbol shared by the app icon (.icns), the
# menu-bar tray icon and the floating bar, so all three match.
# ─────────────────────────────────────────────────────────────────────────────
def fc_mark(size, margin_ratio=0.0, radius_ratio=0.24, bg=None, fg="#FFFFFF"):
    """An accent squircle with a white 'FC' monogram (full-bleed by default).

    margin_ratio: transparent margin around the squircle (use ~0.10 for an
                  .icns where macOS expects padding; 0 for tray/bar).
    """
    from PyQt6 import QtGui
    from PyQt6.QtCore import Qt as _Qt, QRectF
    pm, p = _icon_canvas(size)
    S = float(size)
    m = S * margin_ratio
    side = S - 2 * m
    r = side * radius_ratio
    p.setPen(_Qt.PenStyle.NoPen)
    p.setBrush(qcolor(bg or ACCENT))
    p.drawRoundedRect(QRectF(m, m, side, side), r, r)
    # 'FC' monogram, centered, optically nudged.
    f = heading_font(int(side * 0.40), 800)
    p.setFont(f)
    p.setPen(qcolor(fg))
    p.drawText(QRectF(m, m, side, side),
               int(_Qt.AlignmentFlag.AlignCenter), "FC")
    p.end()
    return pm


def app_icon_pixmap(size=1024):
    """The macOS app icon: a rounded accent square with white 'FC', with the
    ~10% transparent margin macOS app icons use."""
    return fc_mark(size, margin_ratio=0.10, radius_ratio=0.235)
