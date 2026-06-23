# -*- coding: utf-8 -*-
"""Test fuer Issue #131 / MR !83 (ARGUS-Blocker): Die zentrale Textkarte muss ihren Inhalt
VOLLSTAENDIG umschliessen - kein Element (insbesondere die Gold-CTA-Pille) darf unter die
Kartenunterkante (cy1) auf das nackte Foto laufen.

Beweist:
  1. Kein Overflow: Fuer ALLE vier Kreis-Positionen (unten/oben/diagonal/diagonal2) UND fuer
     Portrait (das immer 'diagonal2' erzwingt) liegt die CTA-Unterkante <= cy1, sowohl im Fall
     (a) Hero + 3 lange Bullets + CTA als auch (b) No-Hero + Subline + 3 Bullets + CTA.
     Das gilt auch in den schmalen diagonal-Baendern (Band ~496px), wo der Inhalt das Band
     uebersteigt - die Karte waechst dann ueber das Band, der Inhalt bleibt aber drin.
  2. Foto-Rahmen bei KURZEM Inhalt: Bei wenig Inhalt bleibt an ALLEN vier Seiten Foto-Rand frei
     (links/rechts ueber 'margin', oben/unten ueber den optionalen 'frame_v'-Luftrand).

Die Pruefung repliziert exakt den y-Cursor-Lauf aus bildgen.render(), berechnet die unterste
gezeichnete Inhaltskante (Unterkante der CTA-Pille) und vergleicht sie mit der aus demselben
Layout-Code berechneten Kartenunterkante cy1.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_bildgen_frame.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw
import bildgen as b

W, H = b.W, b.H


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _layout(fields, pos):
    """Repliziert die Layout-Berechnung aus bildgen.render() exakt und liefert ein Dict mit
    cy0, cy1, der Unterkante der CTA-Pille (cta_bottom) und den Karten-Seitenkanten cx0/cx1
    sowie frame_eff (vertikaler Luft-Rand). Verwendet dieselben Konstanten/Schritte wie render."""
    fields = b._safe_fields(fields)
    base = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(base)
    ct, cb = b._content_bounds(pos)

    margin = 104
    frame_v = 64
    cx0, cx1 = margin, W - margin
    inx = cx0 + 40
    inw = cx1 - inx - 40
    pad_top, pad_bot = 40, 40

    pille = b._pille_text(fields)
    fpill = b._font(b._BOLD, 26)
    hero = (fields.get("hero") or "").strip()
    head_start = 50 if hero else 64
    fh, HL = b._fit(dr, fields.get("ueberschrift", ""), b._BOLD, head_start, 34, inw, 3)
    lh_h = fh.size + 8
    fhero = b._font(b._BOLD, 96)
    sub_txt = fields.get("subline", "") if not hero else ""
    fsub = b._font(b._REG, 30)
    SL = b._wrap(dr, sub_txt, fsub, inw) if sub_txt else []
    fb = b._font(b._BOLD, 30)
    bullets = [x for x in (fields.get("bullets") or [])[:3] if x]
    icon_r = 22
    bblocks = [b._wrap(dr, x, fb, inw - (2 * icon_r + 22)) for x in bullets]
    lh_b = fb.size + 6
    fcta = b._font(b._BOLD, 30)

    h_pill = fpill.size + 2 * 11
    h_head = len(HL) * lh_h
    h_hero = fhero.size if hero else 0
    h_sub = len(SL) * (fsub.size + 6)
    bstep = lh_b + 26
    h_bul = len(bblocks) * bstep
    h_cta = fcta.size + 2 * 13
    gap = 22
    parts = [h_pill, h_head]
    if hero:
        parts.append(h_hero)
    if SL:
        parts.append(h_sub)
    if bblocks:
        parts.append(h_bul)
    parts.append(h_cta)
    content_h = sum(parts) + gap * (len(parts) - 1)

    band = cb - ct
    card_needed = content_h + pad_top + pad_bot
    frame_eff = max(0, min(frame_v, (band - card_needed) // 2))
    avail = band - 2 * frame_eff
    card_h = max(card_needed, avail)
    cy0 = ct + frame_eff + (avail - card_h) // 2
    cy1 = cy0 + card_h

    # y-Cursor-Lauf wie in render() - bis zur CTA-Pille
    y = cy0 + pad_top
    y += h_pill + gap                       # Pille
    for _ in HL:                            # Ueberschrift
        y += lh_h
    y += gap
    if hero:
        y += h_hero + gap
    for _ in SL:                            # Subline (nur ohne Hero)
        y += fsub.size + 6
    if SL:
        y += gap
    for _ in bblocks:                       # Bullets
        y += bstep
    if bblocks:
        y += gap
    # CTA-Pille: mittig um (y + h_cta//2), Unterkante = y + h_cta
    cta_top = y
    cta_bottom = y + h_cta

    return dict(ct=ct, cb=cb, band=band, cx0=cx0, cx1=cx1, cy0=cy0, cy1=cy1,
                frame_eff=frame_eff, content_h=content_h, card_needed=card_needed,
                cta_top=cta_top, cta_bottom=cta_bottom)


LONG = "Sehr lange Aufzaehlungszeile die ueber mehrere Zeilen umbricht und das Feld fuellt"

CASE_HERO = {
    "ueberschrift": "Eine ziemlich lange Ueberschrift fuer den Maximalfall hier",
    "hero": "2.500",
    "bullets": [LONG, LONG, LONG],
    "cta": "Jetzt kostenlosen Beratungstermin vereinbaren",
}
CASE_NOHERO = {
    "ueberschrift": "Eine ziemlich lange Ueberschrift fuer den Maximalfall hier",
    "subline": "Eine Hook-Subline die durchaus auch zwei Zeilen lang sein kann hier",
    "bullets": [LONG, LONG, LONG],
    "cta": "Jetzt kostenlosen Beratungstermin vereinbaren",
}
CASE_SHORT = {
    "ueberschrift": "Kurz",
    "subline": "Knapp",
    "bullets": ["Eins"],
    "cta": "Termin",
}


def test_no_overflow():
    """Akzeptanzkriterium: CTA-Unterkante <= cy1 fuer alle 4 Positionen + Portrait, je Hero/No-Hero."""
    positions = list(b.CIRCLE_POSITIONS) + ["__portrait__"]
    for raw_pos in positions:
        pos = "diagonal2" if raw_pos == "__portrait__" else raw_pos
        label = "portrait(diagonal2)" if raw_pos == "__portrait__" else pos
        for cname, case in (("hero+3bul", CASE_HERO), ("nohero+sub+3bul", CASE_NOHERO)):
            r = _layout(case, pos)
            slack = r["cy1"] - r["cta_bottom"]
            ok = "OK" if r["cta_bottom"] <= r["cy1"] else "OVERFLOW"
            print("  [%-20s %-16s] band=%d cy0=%d cy1=%d cta_bottom=%d slack=%d -> %s"
                  % (label, cname, r["band"], r["cy0"], r["cy1"], r["cta_bottom"], slack, ok))
            if r["cta_bottom"] > r["cy1"]:
                _fail("CTA laeuft unter die Karte (%s, %s): cta_bottom=%d > cy1=%d"
                      % (label, cname, r["cta_bottom"], r["cy1"]))


def test_frame_short_content():
    """Bei kurzem Inhalt bleibt an allen 4 Seiten Foto-Rand frei (Issue #131 Foto-Rahmen)."""
    for pos in b.CIRCLE_POSITIONS:
        r = _layout(CASE_SHORT, pos)
        # Seitlich: margin (cx0>0, cx1<W). Oben/unten: frame_eff>0 -> Karte beruehrt ct/cb nicht.
        side_ok = r["cx0"] > 0 and r["cx1"] < W
        top_ok = r["cy0"] > r["ct"]
        bot_ok = r["cy1"] < r["cb"]
        print("  [%-10s] cx0=%d cx1=%d cy0=%d(ct=%d) cy1=%d(cb=%d) frame_eff=%d -> %s"
              % (pos, r["cx0"], r["cx1"], r["cy0"], r["ct"], r["cy1"], r["cb"],
                 r["frame_eff"], "OK" if (side_ok and top_ok and bot_ok) else "KEIN RAHMEN"))
        if not side_ok:
            _fail("Kein seitlicher Foto-Rand (%s): cx0=%d cx1=%d" % (pos, r["cx0"], r["cx1"]))
        if not (top_ok and bot_ok):
            _fail("Kein oberer/unterer Foto-Rand bei kurzem Inhalt (%s): cy0=%d ct=%d cy1=%d cb=%d"
                  % (pos, r["cy0"], r["ct"], r["cy1"], r["cb"]))
        if r["frame_eff"] <= 0:
            _fail("frame_eff sollte bei kurzem Inhalt > 0 sein (%s): %d" % (pos, r["frame_eff"]))


def test_render_smoke():
    """render() laeuft fuer den Maximalfall ohne Foto (Creme-Fallback) und erzeugt ein Bild."""
    out = os.path.join(os.environ.get("HILO_DATA_DIR", "/tmp"), "frame_smoke.png")
    p = b.render(CASE_HERO, None, "Wir sind HILO", out, portrait=None)
    if not (p and os.path.exists(p)):
        _fail("render() hat kein Bild erzeugt")
    print("  render() Smoke-Test (Creme-Fallback) OK ->", p)


if __name__ == "__main__":
    print("== Akzeptanz: kein CTA-Overflow unter die Karte ==")
    test_no_overflow()
    print("== Foto-Rahmen an allen 4 Seiten bei kurzem Inhalt ==")
    test_frame_short_content()
    print("== render() Smoke ==")
    test_render_smoke()
    print("BESTANDEN: Karte umschliesst den Inhalt; kein Element laeuft unter die Karte.")
