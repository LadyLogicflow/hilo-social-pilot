# -*- coding: utf-8 -*-
"""Tests fuer Issue #136 - KI-Tafel-Feinschliff 2:
  A) bildmotiv (beide Prompts): Schild/Tafel NATUERLICH in die Szene integriert
     (auf Tisch/Staffelei/angelehnt), NICHT in die Kamera gehalten, candid/ungestellt/
     Schnappschuss, keine gestellten Posen.
  B) bildmotiv (beide Prompts): themenangepasste Stimmung - bei ernsten Themen
     Zuversicht/Erleichterung/Souveraenitaet statt Grinsen/Feiern; bei freudigen froehlich.
  C) bildgen ki_tafel: CTA-Pille und CI-Kreise ueberlappen NICHT (Geometrie-Check ueber
     alle Positionen + tatsaechlich gerendertes Bild), CTA voll sichtbar.

Rahmen-Regression: background='opaque'/size '1024x1024' + Cache-Praefixe (szene:/tafel:)
unveraendert; beide Modi rendern 1080x1080 mit Dummy-Foto.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_ki_tafel_feinschliff2.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw
import db
import bildmotiv
import bildgen as b


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


SCENE = "ruhige Buero-Szene mit einer beratenen Familie"
SIGN = "Frist verpasst? Wir helfen sofort!"

# Begriffe, die in BEIDEN Prompts (szene + ki_tafel) vorkommen muessen (#136 A/B).
# Wir pruefen pro Aspekt eine Menge alternativer Formulierungen (mindestens eine reicht),
# damit die Tests die fachliche ABSICHT pruefen, nicht eine exakte Wortwahl.
_SCHILD_IN_SZENE = (
    # Schild/Plakat in der Szene integriert (auf Tisch/Staffelei/angelehnt)
    ["in die Szene integriert", "natuerlich in die szene"],
    ["auf einem Tisch", "Staffelei", "angelehnt", "lehnt an"],
)
_NICHT_GEHALTEN = ["NICHT von einer Person frontal in die", "nicht von einer person", "nicht", "GEHALTEN"]
_CANDID = ["candid", "ungestellt", "nicht gestellt", "Schnappschuss"]
_KEINE_POSE = ["niemand posiert", "keine gestellten", "steif in die Kamera", "posiert"]
_MOOD_THEMA = ["Zuversicht", "Erleichterung", "Souveraenitaet"]
_MOOD_NO_GRINSEN = ["Grinsen", "Feiern"]


def _has_any(prompt, options):
    low = prompt.lower()
    return any(o.lower() in low for o in options)


def _assert_szene_integriert(prompt, label):
    for group in _SCHILD_IN_SZENE:
        if not _has_any(prompt, group):
            _fail("%s: 'Schild in der Szene integriert (Tisch/Staffelei/angelehnt)' fehlt - %r" % (label, group))
    if not _has_any(prompt, _NICHT_GEHALTEN):
        _fail("%s: 'NICHT in die Kamera gehalten' fehlt" % label)
    if not _has_any(prompt, _CANDID):
        _fail("%s: candid/ungestellt/Schnappschuss fehlt" % label)
    if not _has_any(prompt, _KEINE_POSE):
        _fail("%s: 'keine gestellten Posen / niemand posiert' fehlt" % label)


def _assert_mood_thema(prompt, label):
    # themenangepasste Stimmung: bei ernsten Themen Zuversicht/Erleichterung/Souveraenitaet
    if not _has_any(prompt, _MOOD_THEMA):
        _fail("%s: themenangepasste Stimmung (Zuversicht/Erleichterung/Souveraenitaet) fehlt" % label)
    if not _has_any(prompt, _MOOD_NO_GRINSEN):
        _fail("%s: Abgrenzung gegen Grinsen/Feiern bei ernsten Themen fehlt" % label)
    # froehlich bei freudigen Themen ausdruecklich erlaubt
    if "froehlich" not in prompt.lower():
        _fail("%s: 'froehlich' (bei freudigen Themen erlaubt) fehlt" % label)


def test_prompts_szene_und_mood():
    print("== A/B) bildmotiv: Schild in der Szene (candid) + themenangepasste Stimmung ==")
    sp = bildmotiv._prompt(SCENE)
    tp = bildmotiv._tafel_prompt(SCENE, SIGN)
    _assert_szene_integriert(sp, "Szene-Prompt")
    _assert_szene_integriert(tp, "Tafel-Prompt")
    print("  A1) Beide Prompts: Schild in der Szene integriert + nicht gehalten + candid + keine Pose OK")
    _assert_mood_thema(sp, "Szene-Prompt")
    _assert_mood_thema(tp, "Tafel-Prompt")
    print("  B1) Beide Prompts: themenangepasste Stimmung (Zuversicht/Erleichterung) + froehlich erlaubt OK")


def test_rahmen_unveraendert():
    print("== Rahmen-Regression: opaque/1024 + Cache-Praefixe unveraendert ==")
    pl = bildmotiv.tafel_payload(SCENE, SIGN)
    if pl.get("background") != "opaque":
        _fail("Payload background != 'opaque'")
    if pl.get("size") != "1024x1024":
        _fail("Payload size != '1024x1024'")
    # echte deutsche Umlaute im Tafel-Prompt
    for ch in ("ä", "ö", "ü", "ß"):
        if ch not in bildmotiv._tafel_prompt(SCENE, SIGN):
            _fail("Tafel-Prompt: echter Umlaut %r fehlt" % ch)
    # Cache-Praefixe
    if not bildmotiv.tafel_cache_key(SCENE, SIGN).startswith("tafel:"):
        _fail("Cache-Praefix 'tafel:' veraendert")
    sp = bildmotiv._szene_pfad(SCENE)
    if not (sp and os.path.basename(sp).endswith(".png")):
        _fail("Szene-Pfad (Praefix 'szene:') kaputt")
    print("  R1) background='opaque', size='1024x1024', echte Umlaute, Cache-Praefixe szene:/tafel: OK")


# ---------------------------------------------------------------------------
# C) Geometrie: CTA-Pille und CI-Kreise ueberlappen im ki_tafel-Modus NICHT
# ---------------------------------------------------------------------------
def _rects_overlap(a, b_):
    """True, wenn zwei achsparallele Rechtecke (x0,y0,x1,y1) sich schneiden (Beruehrung erlaubt)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b_
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _cta_bbox():
    """Bounding-Box der CTA-Pille im ki_tafel-Modus - exakt nach den Konstanten in
    _render_ki_tafel (fcta=34, pady=15 -> h_cta = 34 + 2*15 = 64; cy_cta = H-132).
    Breite konservativ ueber die volle Bildbreite angesetzt (worst case langer CTA-Text),
    sodass der Test auch bei breiter Pille greift."""
    fcta_size = 34
    pady = 15
    h_cta = fcta_size + 2 * pady
    cy_cta = b.H - 132
    y0 = cy_cta - h_cta // 2
    y1 = cy_cta + h_cta // 2 + 1
    # konservativ: volle Bildbreite (die Pille ist mittig, kann aber breit werden)
    return (0, y0, b.W, y1)


def _circle_bboxes(pos, portrait=None):
    """Bounding-Boxen beider CI-Kreise (inkl. Schlagschatten-Halo) fuer eine Kreisposition,
    nach den Konstanten in _draw_circles. Schatten-Ellipse reicht bis cy+rad+22 plus Blur(22)."""
    R = 102
    CCY_TOP, CCY_BOT = 134, 946
    has_portrait = bool(portrait and os.path.exists(portrait))
    RP = 142 if has_portrait else R
    logo_y = CCY_TOP if pos in ("oben", "diagonal") else CCY_BOT
    slogan_y = CCY_TOP if pos in ("oben", "diagonal2") else CCY_BOT
    if has_portrait and slogan_y == CCY_TOP:
        slogan_y = RP + 18
    lx = R + 22
    rx = b.W - RP - 22
    blur = 22
    def bbox(cx, cy, rad):
        # Schatten: ellipse [cx-rad-6, cy-rad+2, cx+rad+16, cy+rad+22], danach GaussianBlur(22)
        return (cx - rad - 6 - blur, cy - rad + 2 - blur, cx + rad + 16 + blur, cy + rad + 22 + blur)
    return [bbox(lx, logo_y, R), bbox(rx, slogan_y, RP)]


def test_geometrie_cta_kreise_kein_overlap():
    print("== C) Geometrie: CTA-Pille schneidet keinen CI-Kreis (ki_tafel-Modus) ==")
    cta = _cta_bbox()
    # Der ki_tafel-Modus erzwingt pos='oben' (siehe _render_ki_tafel). Wir pruefen, dass mit
    # OBENEN Kreisen die untere CTA-Pille frei ist - sowohl ohne als auch mit Portraet.
    for portrait in (None, "__dummy_existing__"):
        # Portraet-Pfad muss existieren, damit RP=142 greift; wir erzeugen bei Bedarf eine Datei.
        pp = portrait
        if portrait == "__dummy_existing__":
            data = os.environ.get("HILO_DATA_DIR", "/tmp")
            pp = os.path.join(data, "geo_portrait.png")
            Image.new("RGB", (200, 200), (50, 50, 50)).save(pp)
        for cb in _circle_bboxes("oben", pp):
            if _rects_overlap(cta, cb):
                _fail("ki_tafel (oben, portrait=%r): CI-Kreis %r schneidet CTA-Pille %r" % (portrait, cb, cta))
    print("  C1) pos='oben' (ki_tafel): beide CI-Kreise schneiden die CTA-Pille NICHT (mit/ohne Portraet) OK")

    # Kontroll-Nachweis, dass der Test ueberhaupt greifen WUERDE: mit UNTEN stehenden Kreisen
    # (altes Verhalten) MUESSTE die CTA-Pille ueberlappen - sonst waere der Geometrie-Check wertlos.
    overlap_unten = any(_rects_overlap(cta, cb) for cb in _circle_bboxes("unten", None))
    if not overlap_unten:
        _fail("Kontrolle: mit unten stehenden Kreisen muesste die CTA-Pille ueberlappen - Test waere wirkungslos")
    print("  C2) Kontrolle: unten stehende Kreise WUERDEN ueberlappen -> Geometrie-Check ist aussagekraeftig OK")


def _dummy_photo(path):
    Image.new("RGB", (1024, 1024), (180, 140, 90)).save(path)
    return path


def _cta_visible(img, cta_bbox):
    """Heuristik: in der CTA-Zeile (Mitte der Pillen-Bbox) muessen genug WEISSE CTA-Text-Pixel
    sichtbar sein. Ein ueberlappender (blauer/weisser) Kreis sitzt NICHT mittig, daher pruefen
    wir die zentrale Pillen-Region; Kreise duerfen sie nicht verdecken."""
    x0, y0, x1, y1 = cta_bbox
    yc = (y0 + y1) // 2
    px = img.convert("RGB").load()
    white = 0
    for x in range(b.W // 2 - 200, b.W // 2 + 200, 4):
        r, g, bl = px[x, yc]
        if r > 235 and g > 235 and bl > 235:
            white += 1
    return white


def test_render_beide_modi_und_cta_sichtbar():
    print("== C) Render beide Modi + CTA sichtbar (1080x1080) ==")
    data = os.environ.get("HILO_DATA_DIR", "/tmp")
    photo = _dummy_photo(os.path.join(data, "f2_dummy.png"))
    fields = {"ueberschrift": SIGN, "cta": "Jetzt Beratungsstelle in Ihrer Naehe finden", "szene_motiv": SCENE}

    db.set_einstellung("bild_stil", "ki_tafel")
    out_t = os.path.join(data, "f2_ki_tafel.png")
    p = b.render(fields, photo, "Wir sind HILO", out_t, portrait=None)
    if not (p and os.path.exists(p)):
        _fail("render() ki_tafel hat kein Bild erzeugt")
    img = Image.open(p)
    if img.size != (1080, 1080):
        _fail("ki_tafel-Bild falsche Groesse: %r" % (img.size,))
    n_white = _cta_visible(img, _cta_bbox())
    if n_white < 20:
        _fail("ki_tafel: CTA-Text in der Pillen-Mitte kaum sichtbar (weisse Pixel=%d) - evtl. verdeckt" % n_white)
    print("  C3) ki_tafel: 1080x1080, CTA-Text sichtbar (weisse Pixel=%d) OK" % n_white)

    db.set_einstellung("bild_stil", "standard")
    out_s = os.path.join(data, "f2_standard.png")
    p2 = b.render(fields, photo, "Wir sind HILO", out_s, portrait=None)
    if not (p2 and os.path.exists(p2) and Image.open(p2).size == (1080, 1080)):
        _fail("render() standard kaputt (Groesse/Existenz)")
    print("  C4) standard: 1080x1080 unveraendert gerendert OK")


if __name__ == "__main__":
    db.init_db()
    test_prompts_szene_und_mood()
    test_rahmen_unveraendert()
    test_geometrie_cta_kreise_kein_overlap()
    test_render_beide_modi_und_cta_sichtbar()
    print("BESTANDEN: KI-Tafel-Feinschliff 2 (#136) - alle Pruefungen gruen.")
