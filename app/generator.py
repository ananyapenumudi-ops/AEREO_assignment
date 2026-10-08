import math
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIR = Path(__file__).parent / "fonts"
for font_name, file_name in {
    "Fraunces": "Fraunces72pt-SemiBold.ttf",
    "Fraunces-Italic": "Fraunces72pt-SemiBoldItalic.ttf",
    "Lora": "Lora-Regular.ttf",
    "Lora-Italic": "Lora-Italic.ttf",
    "Mono": "CourierPrime-Regular.ttf",
    "Mono-Bold": "CourierPrime-Bold.ttf",
}.items():
    pdfmetrics.registerFont(TTFont(font_name, FONT_DIR / file_name))

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CENTRE = PAGE_WIDTH / 2

CREAM = colors.HexColor("#FFFAEA")
GRID = colors.HexColor("#D6DEFA")
COCOA = colors.HexColor("#4A2A1F")
COCOA_SOFT = colors.HexColor("#76503F")
COCOA_MUTE = colors.HexColor("#A4826F")
LILAC = colors.HexColor("#DCC5EF")
PERI = colors.HexColor("#A4B6EC")
CORAL = colors.HexColor("#FF8A5C")

# the cream card sitting on grid paper
CARD_X, CARD_Y = 48, 52
CARD_W, CARD_H = PAGE_WIDTH - 2 * CARD_X, PAGE_HEIGHT - CARD_Y - 44
TEXT_WIDTH = CARD_W - 120


def render_certificate(
    path: Path,
    name: str,
    course_name: str,
    issued_on: date,
    issued_by: str | None,
    verification_code: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"Certificate - {name}")

    _draw_background(c)
    _draw_card(c)

    top = CARD_Y + CARD_H
    _draw_label_pill(c, "CERTIFICATE OF COMPLETION", top - 62)

    _centred(c, "This is to certify that", "Lora-Italic", 15, COCOA_SOFT, top - 118)
    _centred(c, name, "Fraunces-Italic", 46, COCOA, top - 178)
    c.setFillColor(CORAL)
    c.roundRect(CENTRE - 36, top - 200, 72, 4, 2, stroke=0, fill=1)
    _centred(c, "has successfully completed", "Lora-Italic", 15, COCOA_SOFT, top - 240)
    _centred(c, course_name, "Fraunces", 24, COCOA, top - 278)

    _signature(c, CARD_X + 170, "Date of issue", issued_on.strftime("%d %B %Y"))
    if issued_by:
        _signature(c, CARD_X + CARD_W - 170, "Issued by", issued_by)
    _draw_seal(c, CENTRE, CARD_Y + 82, str(issued_on.year))

    _spaced(c, f"VERIFICATION CODE  {verification_code}", "Mono", 8.5, COCOA_SOFT, 26, spacing=1)

    c.showPage()
    c.save()
    return path


def _draw_background(c: canvas.Canvas) -> None:
    c.setFillColor(CREAM)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    c.setStrokeColor(GRID)
    c.setLineWidth(0.6)
    step = 18
    for x in range(0, int(PAGE_WIDTH) + step, step):
        c.line(x, 0, x, PAGE_HEIGHT)
    for y in range(0, int(PAGE_HEIGHT) + step, step):
        c.line(0, y, PAGE_WIDTH, y)


def _draw_card(c: canvas.Canvas) -> None:
    # hard offset shadow, then the card on top of it
    c.setFillColor(COCOA)
    c.roundRect(CARD_X + 6, CARD_Y - 6, CARD_W, CARD_H, 22, stroke=0, fill=1)
    c.setFillColor(CREAM)
    c.setStrokeColor(COCOA)
    c.setLineWidth(2)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 22, stroke=1, fill=1)

    # three-colour tab along the top edge
    tab_w, tab_h = 54, 7
    start = CENTRE - 1.5 * tab_w
    for i, colour in enumerate((LILAC, PERI, CORAL)):
        c.setFillColor(colour)
        c.rect(start + i * tab_w, CARD_Y + CARD_H - tab_h - 1, tab_w, tab_h, stroke=0, fill=1)
    c.setLineWidth(1.5)
    c.line(start, CARD_Y + CARD_H - tab_h - 1, start + 3 * tab_w, CARD_Y + CARD_H - tab_h - 1)


def _draw_label_pill(c: canvas.Canvas, text: str, y: float) -> None:
    font, size, spacing = "Mono-Bold", 11, 2.5
    width = _spaced_width(text, font, size, spacing) + 44
    c.setFillColor(COCOA)
    c.roundRect(CENTRE - width / 2 + 3, y - 12, width, 30, 15, stroke=0, fill=1)
    c.setFillColor(LILAC)
    c.setStrokeColor(COCOA)
    c.setLineWidth(1.5)
    c.roundRect(CENTRE - width / 2, y - 9, width, 30, 15, stroke=1, fill=1)
    _spaced(c, text, font, size, COCOA, y + 2, spacing=spacing)


def _signature(c: canvas.Canvas, x: float, label: str, value: str) -> None:
    _centred(c, value, "Lora", 13, COCOA, CARD_Y + 82, x=x, max_width=210)
    c.setStrokeColor(COCOA_MUTE)
    c.setLineWidth(1)
    c.line(x - 105, CARD_Y + 72, x + 105, CARD_Y + 72)
    _spaced(c, label.upper(), "Mono", 8.5, COCOA_SOFT, CARD_Y + 56, x=x, spacing=1.5)


def _draw_seal(c: canvas.Canvas, x: float, y: float, year: str) -> None:
    """Scalloped badge, same shape as the stickers in Elementium."""
    def scallop(cx, cy, colour, grow=0.0):
        # a ring of small circles around a big one gives the wavy edge
        c.setFillColor(colour)
        c.circle(cx, cy, 31 + grow, stroke=0, fill=1)
        for i in range(16):
            angle = 2 * math.pi * i / 16
            c.circle(cx + 31 * math.cos(angle), cy + 31 * math.sin(angle), 6.5 + grow, stroke=0, fill=1)

    scallop(x + 3, y - 3, COCOA, grow=1.5)  # shadow
    scallop(x, y, COCOA, grow=1.5)          # outline
    scallop(x, y, CORAL)
    c.setFillColor(CREAM)
    c.setStrokeColor(COCOA)
    c.setLineWidth(1.5)
    c.circle(x, y, 25, stroke=1, fill=1)

    _spaced(c, "CERTIFIED", "Mono-Bold", 6.5, COCOA, y + 4, x=x, spacing=1)
    _centred(c, year, "Fraunces", 12, COCOA, y - 9, x=x)


def _centred(c, text, font, size, colour, y, x=CENTRE, max_width=TEXT_WIDTH) -> None:
    # shrink long names/titles until they fit on one line
    while size > 10 and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 1
    c.setFillColor(colour)
    c.setFont(font, size)
    c.drawCentredString(x, y, text)


def _spaced(c, text, font, size, colour, y, x=CENTRE, spacing=2.0) -> None:
    """Letter-spaced uppercase label, centred on x."""
    t = c.beginText()
    t.setFont(font, size)
    t.setCharSpace(spacing)
    t.setFillColor(colour)
    t.setTextOrigin(x - _spaced_width(text, font, size, spacing) / 2, y)
    t.textOut(text)
    t.setCharSpace(0)  # otherwise the spacing carries over to later text
    c.drawText(t)


def _spaced_width(text, font, size, spacing) -> float:
    return pdfmetrics.stringWidth(text, font, size) + spacing * (len(text) - 1)
