# -*- coding: utf-8 -*-
"""Spruchkachel in BSt-Next-CI (deterministisch, keine Bild-KI).

Aufbau wie beim Post vom 07.11.2026: Navy-Flaeche, weisse Headline (Archivo Black), die letzten
Worte in Lime, unten links Logo mit Claim. Die Zeilenumbrueche gibt der Aufrufer vor, damit die
Serie einheitlich aussieht (kein automatischer Umbruch)."""
from PIL import Image, ImageDraw, ImageFont

from . import brand

_RAND_X = 90
_SCHRIFT = 95
_ZEILENABSTAND = 118
_OBEN = 164
_LOGO_BREITE = 447
_LOGO_UNTEN = 95      # Abstand der Logo-Unterkante zum unteren Bildrand (bei 1080 hoch)


class KachelFehler(ValueError):
    pass


def _logo_weiss(breite):
    """Logo fuer dunklen Grund: dunkle Anteile ('BSt') werden weiss, Lime bleibt Lime."""
    logo = Image.open(brand.LOGO_MIT_CLAIM).convert("RGBA")
    box = logo.split()[3].getbbox()
    if box:
        logo = logo.crop(box)
    px = logo.load()
    for y in range(logo.size[1]):
        for x in range(logo.size[0]):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            t = max(0.0, min(1.0, (g - 60) / (230 - 60)))     # 0 = dunkel, 1 = lime
            px[x, y] = (round(255 * (1 - t) + 163 * t), round(255 * (1 - t) + 230 * t),
                        round(255 * (1 - t) + 53 * t), a)
    hoehe = round(logo.size[1] * breite / logo.size[0])
    return logo.resize((breite, hoehe), Image.LANCZOS)


def render(weisse_zeilen, lime_zeilen, ziel_pfad, format="quadrat"):
    """Rendert die Kachel nach ziel_pfad (PNG). Gibt den Pfad zurueck.

    weisse_zeilen / lime_zeilen: Listen kurzer Zeilen (jede Zeile ist eine Bildzeile).
    Wirft KachelFehler, wenn eine Zeile breiter als die Satzbreite ist oder nichts uebergeben wird."""
    if format not in brand.FORMATE:
        raise KachelFehler("Unbekanntes Format: %s" % format)
    weisse_zeilen = [z.strip() for z in weisse_zeilen if z and z.strip()]
    lime_zeilen = [z.strip() for z in (lime_zeilen or []) if z and z.strip()]
    if not weisse_zeilen:
        raise KachelFehler("Keine Headline-Zeilen.")
    breite, hoehe = brand.FORMATE[format]
    max_breite = breite - 2 * _RAND_X
    font = ImageFont.truetype(brand.FONT_HEADLINE, _SCHRIFT)
    for z in weisse_zeilen + lime_zeilen:
        if font.getlength(z) > max_breite:
            raise KachelFehler("Zeile zu breit (%d > %d px): %s" % (font.getlength(z), max_breite, z))
    logo = _logo_weiss(_LOGO_BREITE)
    logo_oben = hoehe - _LOGO_UNTEN - logo.size[1] + (0 if format != "quadrat" else 0)
    zeilen = len(weisse_zeilen) + len(lime_zeilen)
    if _OBEN + (zeilen - 1) * _ZEILENABSTAND + _SCHRIFT > logo_oben - 40:
        raise KachelFehler("Zu viele Zeilen fuer dieses Format (%d)." % zeilen)
    im = Image.new("RGB", (breite, hoehe), brand.NAVY)
    d = ImageDraw.Draw(im)
    captop = font.getbbox("W")[1]
    y = _OBEN
    for z in weisse_zeilen:
        d.text((_RAND_X, y - captop), z, font=font, fill=brand.WHITE)
        y += _ZEILENABSTAND
    for z in lime_zeilen:
        d.text((_RAND_X, y - captop), z, font=font, fill=brand.LIME)
        y += _ZEILENABSTAND
    im.paste(logo, (_RAND_X, logo_oben), logo)
    im.save(ziel_pfad, "PNG")
    return ziel_pfad
