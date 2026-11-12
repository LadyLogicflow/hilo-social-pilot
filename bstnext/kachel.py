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


def render(weisse_zeilen, lime_zeilen, ziel_pfad, format="quadrat", mit_logo=True, weisse_nach=None):
    """Rendert die Kachel nach ziel_pfad (PNG). Gibt den Pfad zurueck.

    weisse_zeilen / lime_zeilen: Listen kurzer Zeilen (jede Zeile ist eine Bildzeile).
    weisse_nach: optionale weisse Zeilen NACH dem Lime-Teil (z. B. ein Schlusssatz).
    mit_logo=False: Text-Slide ohne Logo (Karussell-Slide 1 und 2), die Zeilen duerfen weiter nach
    unten reichen.
    Wirft KachelFehler, wenn eine Zeile breiter als die Satzbreite ist oder nichts uebergeben wird."""
    if format not in brand.FORMATE:
        raise KachelFehler("Unbekanntes Format: %s" % format)
    weisse_zeilen = [z.strip() for z in weisse_zeilen if z and z.strip()]
    lime_zeilen = [z.strip() for z in (lime_zeilen or []) if z and z.strip()]
    nach = [z.strip() for z in (weisse_nach or []) if z and z.strip()]
    if not weisse_zeilen:
        raise KachelFehler("Keine Headline-Zeilen.")
    breite, hoehe = brand.FORMATE[format]
    max_breite = breite - 2 * _RAND_X
    font = ImageFont.truetype(brand.FONT_HEADLINE, _SCHRIFT)
    for z in weisse_zeilen + lime_zeilen + nach:
        if font.getlength(z) > max_breite:
            raise KachelFehler("Zeile zu breit (%d > %d px): %s" % (font.getlength(z), max_breite, z))
    logo = _logo_weiss(_LOGO_BREITE) if mit_logo else None
    logo_oben = (hoehe - _LOGO_UNTEN - logo.size[1]) if mit_logo else (hoehe - _LOGO_UNTEN + 40)
    zeilen = len(weisse_zeilen) + len(lime_zeilen) + len(nach)
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
    for z in nach:
        d.text((_RAND_X, y - captop), z, font=font, fill=brand.WHITE)
        y += _ZEILENABSTAND
    if logo is not None:
        im.paste(logo, (_RAND_X, logo_oben), logo)
    im.save(ziel_pfad, "PNG")
    return ziel_pfad


def _bereinigen(weisse_zeilen, lime_zeilen, format, mit_logo=True, weisse_nach=None):
    if format not in brand.FORMATE:
        raise KachelFehler("Unbekanntes Format: %s" % format)
    weisse = [z.strip() for z in (weisse_zeilen or []) if z and z.strip()]
    lime = [z.strip() for z in (lime_zeilen or []) if z and z.strip()]
    nach = [z.strip() for z in (weisse_nach or []) if z and z.strip()]
    if not weisse:
        raise KachelFehler("Keine Headline-Zeilen.")
    breite, hoehe = brand.FORMATE[format]
    font = ImageFont.truetype(brand.FONT_HEADLINE, _SCHRIFT)
    for z in weisse + lime + nach:
        if font.getlength(z) > breite - 2 * _RAND_X:
            raise KachelFehler("Zeile zu breit (%d > %d px): %s" % (font.getlength(z), breite - 2 * _RAND_X, z))
    logo = _logo_weiss(_LOGO_BREITE) if mit_logo else None
    logo_oben = (hoehe - _LOGO_UNTEN - logo.size[1]) if mit_logo else (hoehe - _LOGO_UNTEN + 40)
    if _OBEN + (len(weisse) + len(lime) + len(nach) - 1) * _ZEILENABSTAND + _SCHRIFT > logo_oben - 40:
        maximal = int((logo_oben - 40 - _OBEN - _SCHRIFT) // _ZEILENABSTAND) + 1
        raise KachelFehler("Zu viele Zeilen fuer dieses Format (%d, hoechstens %d). Bitte den Text kuerzen."
                           % (len(weisse) + len(lime) + len(nach), maximal))
    return weisse, lime, font, logo, logo_oben, (breite, hoehe)


def pruefe_zeilen(weisse_zeilen, lime_zeilen, format="quadrat", mit_logo=True, weisse_nach=None):
    """Wie render(), aber nur die Pruefung (Breite, Zeilenzahl); wirft KachelFehler."""
    _bereinigen(weisse_zeilen, lime_zeilen, format, mit_logo, weisse_nach)


def render_foto(foto, weisse_zeilen, lime_zeilen, ziel_pfad, format="quadrat"):
    """Foto-Look (Typ C): KI-Foto als Hintergrund (zugeschnitten auf das Format), oben und unten
    ein Navy-Verlauf, darueber Headline (weiss, Lime-Akzent) und Logo mit Claim - gesetzt per Pillow,
    nie von der KI. Gibt den Pfad zurueck."""
    weisse, lime, font, logo, logo_oben, (breite, hoehe) = _bereinigen(weisse_zeilen, lime_zeilen, format)
    bild = foto.convert("RGB")
    # Cover-Zuschnitt auf das Zielformat
    faktor = max(breite / bild.size[0], hoehe / bild.size[1])
    neu = (round(bild.size[0] * faktor), round(bild.size[1] * faktor))
    bild = bild.resize(neu, Image.LANCZOS)
    links, oben = (neu[0] - breite) // 2, (neu[1] - hoehe) // 2
    bild = bild.crop((links, oben, links + breite, oben + hoehe)).convert("RGBA")
    # Navy-Verlauf oben (Headline) und unten (Logo): Alpha-Maske als 1-Pixel-Spalte, dann gestreckt
    oben_h, unten_h = int(hoehe * 0.55), int(hoehe * 0.28)
    werte = []
    for y in range(hoehe):
        a = 0.0
        if y < oben_h:
            a = max(a, 0.88 * (1 - y / oben_h))
        if y > hoehe - unten_h:
            a = max(a, 0.85 * ((y - (hoehe - unten_h)) / unten_h))
        werte.append(round(255 * a))
    spalte = Image.new("L", (1, hoehe))
    spalte.putdata(werte)
    maske = spalte.resize((breite, hoehe))
    im = Image.composite(Image.new("RGBA", (breite, hoehe), brand.NAVY + (255,)), bild, maske).convert("RGB")
    d = ImageDraw.Draw(im)
    captop = font.getbbox("W")[1]
    y = _OBEN
    for z in weisse:
        d.text((_RAND_X, y - captop), z, font=font, fill=brand.WHITE)
        y += _ZEILENABSTAND
    for z in lime:
        d.text((_RAND_X, y - captop), z, font=font, fill=brand.LIME)
        y += _ZEILENABSTAND
    im.paste(logo, (_RAND_X, logo_oben), logo)
    im.save(ziel_pfad, "PNG")
    return ziel_pfad


def umbrechen(zeilen, format="quadrat"):
    """Bricht zu breite Zeilen nach Woertern so um, dass jede Zeile in die Kachel passt.
    Bestehende Zeilenumbrueche des Aufrufers bleiben erhalten. Ein einzelnes Wort, das allein zu
    breit ist, bleibt stehen (render/pruefe_zeilen melden es dann als Fehler)."""
    if format not in brand.FORMATE:
        raise KachelFehler("Unbekanntes Format: %s" % format)
    max_breite = brand.FORMATE[format][0] - 2 * _RAND_X
    font = ImageFont.truetype(brand.FONT_HEADLINE, _SCHRIFT)
    aus = []
    for z in zeilen or []:
        z = (z or "").strip()
        if not z:
            continue
        if font.getlength(z) <= max_breite:
            aus.append(z)
            continue
        aktuell = ""
        for wort in z.split():
            probe = (aktuell + " " + wort).strip()
            if aktuell and font.getlength(probe) > max_breite:
                aus.append(aktuell)
                aktuell = wort
            else:
                aktuell = probe
        if aktuell:
            aus.append(aktuell)
    return aus
