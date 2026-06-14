# -*- coding: utf-8 -*-
"""Programmatisch gezeichnete Motiv-Icons fuer Countdown-Beitraege (rauschfrei,
HILO-Farben, transparenter Hintergrund). Werden wie ein Foto rechts ins Bild gesetzt."""
import math
from PIL import Image, ImageDraw

BLUE = (31, 66, 141, 255)
GREEN = (76, 123, 45, 255)
WHITE = (255, 255, 255, 255)
LIGHT = (214, 222, 233, 255)
GLAS = (245, 248, 252, 255)

S = 640  # Zeichenflaeche

def _canvas():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)

def kalender():
    img, d = _canvas()
    x0, y0, x1, y1 = 70, 170, 570, 560
    for rx in (x0 + 95, x1 - 95):                      # Aufhaenge-Ringe
        d.rounded_rectangle([rx - 15, y0 - 52, rx + 15, y0 + 28], radius=15, fill=BLUE)
    d.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=WHITE, outline=BLUE, width=9)
    d.rounded_rectangle([x0, y0, x1, y0 + 96], radius=26, fill=BLUE)
    d.rectangle([x0, y0 + 60, x1, y0 + 96], fill=BLUE)  # Kopf-Unterkante eckig
    gy0 = y0 + 96
    for i in range(1, 4):                              # waagerechte Linien
        yy = gy0 + i * (y1 - gy0) // 4
        d.line([(x0 + 16, yy), (x1 - 16, yy)], fill=LIGHT, width=4)
    for i in range(1, 7):                              # senkrechte Linien
        xx = x0 + i * (x1 - x0) // 7
        d.line([(xx, gy0 + 12), (xx, y1 - 14)], fill=LIGHT, width=4)
    cx, cy, r = x1 - 108, y1 - 96, 50                  # markierter Tag (gruen, Haken)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    d.line([(cx - 22, cy + 2), (cx - 6, cy + 20), (cx + 24, cy - 22)], fill=WHITE, width=11, joint="curve")
    return img

def wecker():
    img, d = _canvas()
    cx, cy, r = 320, 350, 178
    d.line([(cx - 118, cy + r - 26), (cx - 176, cy + r + 44)], fill=BLUE, width=24)   # Beine
    d.line([(cx + 118, cy + r - 26), (cx + 176, cy + r + 44)], fill=BLUE, width=24)
    d.ellipse([cx - 214, cy - r - 64, cx - 96, cy - r + 28], fill=BLUE)               # Glocken
    d.ellipse([cx + 96, cy - r - 64, cx + 214, cy - r + 28], fill=BLUE)
    d.arc([cx - 150, cy - r - 120, cx + 150, cy - r + 40], 205, 335, fill=BLUE, width=20)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE, outline=BLUE, width=15)   # Ziffernblatt
    for a in range(12):
        ang = math.radians(a * 30)
        d.line([(cx + (r - 26) * math.sin(ang), cy - (r - 26) * math.cos(ang)),
                (cx + (r - 9) * math.sin(ang), cy - (r - 9) * math.cos(ang))], fill=BLUE, width=6)
    d.line([(cx, cy), (cx + 6, cy - r + 60)], fill=BLUE, width=13)                    # Minutenzeiger
    d.line([(cx, cy), (cx + r - 86, cy + 26)], fill=GREEN, width=13)                  # Stundenzeiger
    d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=BLUE)
    return img

def sanduhr():
    img, d = _canvas()
    cx, top, bot, w = 320, 150, 560, 150
    mid = (top + bot) // 2
    d.line([(cx - w - 6, top + 18), (cx - w - 6, bot - 18)], fill=BLUE, width=12)     # Seitenpfosten
    d.line([(cx + w + 6, top + 18), (cx + w + 6, bot - 18)], fill=BLUE, width=12)
    d.polygon([(cx - w, top + 26), (cx + w, top + 26), (cx, mid)], fill=GLAS, outline=BLUE, width=9)
    d.polygon([(cx - w, bot - 26), (cx + w, bot - 26), (cx, mid)], fill=GLAS, outline=BLUE, width=9)
    d.polygon([(cx - w + 26, top + 40), (cx + w - 26, top + 40), (cx, mid - 46)], fill=GREEN)  # Sand oben
    d.line([(cx, mid - 8), (cx, mid + 16)], fill=GREEN, width=9)                      # Sandstrahl
    d.polygon([(cx - 78, bot - 34), (cx + 78, bot - 34), (cx, mid + 54)], fill=GREEN) # Sandhaufen
    d.rounded_rectangle([cx - w - 24, top - 8, cx + w + 24, top + 26], radius=10, fill=BLUE)
    d.rounded_rectangle([cx - w - 24, bot - 26, cx + w + 24, bot + 8], radius=10, fill=BLUE)
    return img

MOTIVE = {"kalender": kalender, "wecker": wecker, "sanduhr": sanduhr}

def render_icon(name, out_path):
    fn = MOTIVE.get(name)
    if not fn:
        return None
    img = fn()
    bb = img.getchannel("A").getbbox()
    if bb:
        img = img.crop(bb)
    img.save(out_path)
    return out_path
