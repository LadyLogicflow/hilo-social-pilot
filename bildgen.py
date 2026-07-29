# -*- coding: utf-8 -*-
"""M4 - Bild im aufgefrischten HILO-Magazin-Stil (1080x1080): vollflaechiges Foto als Hintergrund,
darueber ein integriertes weisses Textfeld (Saison-Pille, Ueberschrift, optionale Hero-Zahl,
gezeichnete Symbol-Bullets, warme CTA-Pille). Die beiden CI-Kreise (Logo + Slogan 'Wir sind HILO')
bleiben als Erkennungszeichen und rotieren je Beitrag. Ohne Foto: warmer cremefarbener Fallback."""
import math, os, json, logging, random, re
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config import BASE_DIR, DATA_DIR

log = logging.getLogger("hilo.bildgen")
W = H = 1080
# Text-Unterkante: Schriften enden oberhalb der schwebenden Kreise (Kreis-Oberkante 844,
# inkl. weichem Schatten-Halo) - so wird kein Text vom Kreis oder Schatten verdeckt.
CBOT = 788
CTOPTEXT = H - CBOT        # = 292: Text-Oberkante, wenn die Kreise oben stehen (gespiegelt)
TOPB_BAND, BOTB_BAND = 192, 905   # Innenkanten der beiden Verlaufsbaender (Karussell-Slides)
# Eckpositionen der beiden CI-Kreise (Erkennungszeichen) - sorgen fuer Abwechslung je Beitrag
# diagonal  = Logo oben-links + Slogan unten-rechts; diagonal2 = Logo unten-links + Slogan oben-rechts
CIRCLE_POSITIONS = ["unten", "oben", "diagonal", "diagonal2"]
BLUE=(31,66,141); GREEN=(96,163,60); LIGHT=(244,247,246); NAVY=(21,51,110); GREEN2=(76,123,45); WHITE=(255,255,255)
ACCENT=(96,163,60)   # HILO-CI-Gruen fuer die CTA-Pille (#135: Aktionsfarbe statt Gold/Orange), weisse Schrift
# Abgenommene Magazin-Vorschau: warmer Creme-Verlauf (oben hell -> unten warm) als Fallback-Hintergrund,
# weisses Textfeld (Alpha) mit dezentem Rand fuer das integrierte Textfeld.
CREME_TOP=(255,249,239); CREME_BOT=(244,227,199); CARD_FILL=(255,255,255,243); CARD_BORDER=(232,224,210)

LOGO_PATH = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
# Font-Lookup (#135): echtes Arial / Arial Bold ZUERST (CI-Wunsch), dann Liberation Sans als
# Fallback (metrisch Arial-kompatibel), zuletzt DejaVu. Erweitert die bestehende Kette additiv -
# fehlt echtes Arial (z.B. msttcorefonts nicht installiert), greift weiterhin Liberation Sans.
_BOLD = ["/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_REG  = ["/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

STANDARD_SLOGANS = ["Wir sind HILO", "HILO - wir machen's einfach", "Steuern? Machen wir.",
                    "Mehr Netto für Sie", "Ihr gutes Recht", "Einfach mehr rausholen"]

def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def _wrap(dr, text, font, max_w):
    out, cur = [], ""
    for w in (text or "").split():
        s = (cur + " " + w).strip()
        if dr.textlength(s, font=font) <= max_w or not cur:
            cur = s
        else:
            out.append(cur); cur = w
    if cur:
        out.append(cur)
    return out or [""]

def _fit(dr, text, paths, start, mn, max_w, max_lines):
    s = start
    while s >= mn:
        f = _font(paths, s); L = _wrap(dr, text, f, max_w)
        if len(L) <= max_lines:
            return f, L
        s -= 2
    return _font(paths, mn), _wrap(dr, text, _font(paths, mn), max_w)

def _creme_bg():
    """Warmer cremefarbener Verlaufs-Hintergrund (oben hell -> unten warm) mit einer dezenten,
    warmen Sonne oben rechts und einer weichen gruenen Flaeche unten links - so wirkt das Bild
    auch OHNE KI-Foto stimmungsvoll (Fallback)."""
    col = Image.new("RGB", (1, H)); px = col.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = (int(CREME_TOP[0]+(CREME_BOT[0]-CREME_TOP[0])*t),
                    int(CREME_TOP[1]+(CREME_BOT[1]-CREME_TOP[1])*t),
                    int(CREME_TOP[2]+(CREME_BOT[2]-CREME_TOP[2])*t))
    base = col.resize((W, H))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    od.ellipse([W-300, -160, W+160, 300], fill=(255, 214, 150, 95))   # warme Sonne oben rechts
    od.ellipse([-260, H-360, 320, H+220], fill=(GREEN[0], GREEN[1], GREEN[2], 60))  # gruene Flaeche unten links
    ov = ov.filter(ImageFilter.GaussianBlur(70))
    base.paste(ov, (0, 0), ov)
    return base

def _cover_photo(photo_path):
    """Laedt ein opakes Foto und skaliert/croppt es formatfuellend (cover) auf 1080x1080.
    Liefert ein RGB-Image oder None (kein/ungueltiges Foto)."""
    if not (photo_path and os.path.exists(photo_path)):
        return None
    try:
        im = Image.open(photo_path).convert("RGB")
        sc = max(W / im.width, H / im.height)
        nw, nh = max(W, int(im.width * sc)), max(H, int(im.height * sc))
        im = im.resize((nw, nh), Image.LANCZOS)
        x0, y0 = (nw - W) // 2, (nh - H) // 2
        return im.crop((x0, y0, x0 + W, y0 + H))
    except Exception:
        return None

def _background(photo_path):
    """Vollflaechiger Bildhintergrund: das Szene-Foto (cover) falls vorhanden, sonst warmer Creme-Fallback."""
    bg = _cover_photo(photo_path)
    return bg if bg is not None else _creme_bg()

def _pill(base, cx, cy, text, font, fill, fg, padx=26, pady=11):
    """Zeichnet eine abgerundete Pille (Label/CTA) mittig um (cx, cy). Liefert (x0, y0, x1, y1)."""
    dr = ImageDraw.Draw(base)
    tw = dr.textlength(text, font=font)
    w, h = tw + 2*padx, font.size + 2*pady
    x0, y0, x1, y1 = cx - w/2, cy - h/2, cx + w/2, cy + h/2
    dr.rounded_rectangle([x0, y0, x1, y1], radius=h/2, fill=fill)
    dr.text((cx, cy), text, font=font, fill=fg, anchor="mm")
    return x0, y0, x1, y1

def _bullet_icon(base, cx, cy, r, kind):
    """Einfach gezeichnetes Symbol-Icon fuer einen Bullet (gruen), mittig um (cx, cy), Radius r.
    kind: 'sonne' (Kreis + Strahlen), 'kalender' (Rechteck + Linien), 'check' (Kreis + Haken)."""
    dr = ImageDraw.Draw(base)
    if kind == "sonne":
        rr = int(r*0.52)
        dr.ellipse([cx-rr, cy-rr, cx+rr, cy+rr], fill=GREEN)
        for a in range(8):
            ang = math.radians(a*45)
            x0 = cx + (rr+5)*math.cos(ang); y0 = cy + (rr+5)*math.sin(ang)
            x1 = cx + (r+1)*math.cos(ang); y1 = cy + (r+1)*math.sin(ang)
            dr.line([(x0, y0), (x1, y1)], fill=GREEN, width=4)
    elif kind == "kalender":
        x0, y0, x1, y1 = cx-r, cy-int(r*0.8), cx+r, cy+int(r*0.85)
        dr.rounded_rectangle([x0, y0, x1, y1], radius=5, outline=GREEN, width=4)
        dr.line([(x0+3, y0+int(r*0.5)), (x1-3, y0+int(r*0.5))], fill=GREEN, width=4)  # Kopfzeile
        for fx in (x0+r*0.6, cx, x1-r*0.6):                                          # Aufhaenge-Ringe
            dr.line([(fx, y0-6), (fx, y0+5)], fill=GREEN, width=4)
        for gy in (y0+int(r*0.9), y0+int(r*1.25)):                                   # Gitterzeilen
            dr.line([(x0+6, gy), (x1-6, gy)], fill=GREEN, width=3)
    else:   # 'check' / 'haekchen'
        dr.ellipse([cx-r, cy-r, cx+r, cy+r], fill=GREEN)
        dr.line([(cx-int(r*0.45), cy), (cx-int(r*0.05), cy+int(r*0.42)),
                 (cx+int(r*0.5), cy-int(r*0.45))], fill=WHITE, width=5, joint="curve")

_BULLET_ICONS = ["check", "sonne", "kalender"]   # rotieren je Bullet (Abwechslung)

def _card(base, x0, y0, x1, y1, radius=38):
    """Integriertes weisses Textfeld (abgerundet, leicht transparent) mit weichem Schatten und
    dezentem Rand - schwebt ueber dem Foto-Hintergrund (Magazin-Optik)."""
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0+4, y0+10, x1+4, y1+16], radius=radius, fill=(0, 0, 0, 95))
    blur = sh.filter(ImageFilter.GaussianBlur(22)); base.paste(blur, (0, 0), blur)
    card = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([x0, y0, x1, y1], radius=radius,
                                           fill=CARD_FILL, outline=CARD_BORDER, width=2)
    base.paste(card, (0, 0), card)

def _last_slogan_path():
    return os.path.join(DATA_DIR, "last_slogan.txt")

def pick_slogan(s):
    s = (s or "").strip()
    if s and len(s) <= 22 and len(s.split()) <= 4:
        chosen = s
    else:
        last = ""
        try:
            last = open(_last_slogan_path(), encoding="utf-8").read().strip()
        except Exception:
            pass
        opts = [x for x in STANDARD_SLOGANS if x != last] or STANDARD_SLOGANS
        chosen = random.choice(opts)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        open(_last_slogan_path(), "w", encoding="utf-8").write(chosen)
    except Exception:
        pass
    return chosen

def _slogan_lines(dr, slogan, font, max_w):
    # in maximal 3 kurze Zeilen umbrechen
    lines = _wrap(dr, slogan, font, max_w)[:3]
    # Markenwort "HILO" soll allein in seiner Zeile stehen (Hervorhebung): endet die
    # letzte Zeile auf HILO mit weiteren Woertern davor, wird HILO abgetrennt
    last = lines[-1].split()
    if len(last) >= 2 and last[-1].rstrip(".!,").upper() == "HILO" and len(lines) < 3:
        lines[-1] = " ".join(last[:-1])
        lines.append(last[-1])
    return lines

def _safe(s):
    """Entfernt Zeichen, die die Standard-Bildschrift nicht darstellen kann (v.a. Emojis),
    damit auf dem Bild keine leeren Kaestchen erscheinen. Emojis gehoeren in die Caption
    (Social-Media-Text), nicht in die auf das Bild gezeichnete Ueberschrift/Bullets/CTA."""
    if not s:
        return s
    out = []
    for ch in str(s):
        o = ord(ch)
        if (0x1F000 <= o or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF
                or 0x2300 <= o <= 0x23FF or 0x2190 <= o <= 0x21FF
                or 0xFE00 <= o <= 0xFE0F or o in (0x200D, 0x20E3)):
            continue   # Emoji / Symbol / Pfeil / Variantenselektor -> weglassen
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()

def _safe_fields(fields):
    """Liefert eine Kopie der Felder, in der die auf das Bild gezeichneten Texte emoji-bereinigt sind."""
    f = dict(fields or {})
    for k in ("ueberschrift", "subline", "cta", "ort"):
        if k in f:
            f[k] = _safe(f.get(k))
    if "bullets" in f:
        f["bullets"] = [_safe(b) for b in (f.get("bullets") or [])]
    return f

def _pille_text(fields):
    """Kurzer Saison-/Themen-Text fuer die gruene Pille oben im Textfeld. Bevorzugt ein explizites
    Feld ('pille'/'saison'/'thema_label'), sonst ein dezenter Standard - nie erfunden, nur Label."""
    for k in ("pille", "saison", "thema_label"):
        v = _safe((fields.get(k) or "")).strip()
        if v:
            return v[:32]
    return "HILO Steuertipp"

def _cta_scrim(base, cy0):
    """Dezenter dunkler Verlauf-Scrim ab cy0 bis zur Bildunterkante - hebt die Gold-CTA-Pille im
    ki_tafel-Modus vom KI-Foto ab, ohne das Foto zu ueberdecken (Lesbarkeit)."""
    band = H - cy0
    if band <= 0:
        return
    scrim = Image.new("L", (1, band), 0); sp = scrim.load()
    for yy in range(band):
        sp[0, yy] = int(150 * (yy / max(1, band - 1)) ** 1.3)   # nach unten dunkler
    scrim = scrim.resize((W, band))
    dark = Image.new("RGB", (W, band), (10, 22, 44))
    base.paste(dark, (0, cy0), scrim)

def _render_ki_tafel(fields, photo_path, slogan, out_path, portrait=None):
    """Bild-Stil 'ki_tafel' (#132, Testmodus): Das KI-Foto traegt die Ueberschrift selbst auf einer
    Tafel in der Szene. Hier wird das Foto VOLLFLAECHIG (cover) gezeigt; per CODE-Overlay kommen NUR
    (1) die Gold-CTA-Pille unten (exakter, personalisierbarer CTA-Text mit dezentem Scrim) und
    (2) die blau-weissen CI-Kreise (Logo + Slogan, rotierend) + optionales Portraet.
    KEINE Text-Karte, KEINE Code-Ueberschrift, KEINE Bullets. Fallback ohne Foto: Creme-Hintergrund."""
    base = _background(photo_path).convert("RGB")
    # #136-C: Im ki_tafel-Modus stehen BEIDE CI-Kreise OBEN ('oben'), damit die untere CTA-Pille
    # frei und voll lesbar bleibt - ein unten stehender CI-Kreis hatte die CTA-Pille ueberlappt
    # und den Text verdeckt. Die Kreis-Rotation des Standard-Modus bleibt davon unberuehrt
    # (pick_circle_pos wird hier bewusst NICHT mehr aufgerufen). Gilt auch mit Portraet, sonst
    # saesse der Logo-Kreis (diagonal2: unten-links) weiter unten und kollidierte mit der Pille.
    pos = "oben"

    # Gold-CTA-Pille unten - selbe Quelle/Default wie der Standard-CTA (fields['cta']).
    cta_txt = (_safe(fields.get("cta")) or "Jetzt Termin vereinbaren").strip()
    fcta = _font(_BOLD, 34)
    h_cta = fcta.size + 2*15
    cy_cta = H - 132                          # Pillen-Mitte: unten, jetzt frei (Kreise oben)
    _cta_scrim(base, cy_cta - h_cta//2 - 26)  # dezenter Schatten/Scrim hinter der Pille
    _pill(base, W//2, cy_cta, cta_txt, fcta, ACCENT, WHITE, padx=36, pady=15)

    _draw_circles(base, slogan, pos, portrait)   # blau-weisse CI-Kreise OBEN (Grafik, kein Text)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base.save(out_path)
    return out_path

def _render_kreativ(fields, photo_path, slogan, out_path, portrait=None):
    """Bild-Stil 'kreativ' (#145): EINFACH NUR das kinoreife KI-Foto (vollflaechig, cover) -
    KEIN Textfeld/Card, KEINE Ueberschrift/Bullets/Hero, KEINE CTA-Pille, KEINE Saison-Pille,
    keine Tafel. Per Code-Overlay kommen NUR die blau-weissen CI-Kreise (Logo + Slogan) +
    optionales Portraet, damit die Marke erkennbar bleibt und das Foto voll wirkt. Die Botschaft
    (Ueberschrift/CTA/Buchungslink) traegt der Begleittext (Caption). Fallback ohne Foto: Creme."""
    base = _background(photo_path).convert("RGB")
    # Kreis-Position rotiert je Beitrag wie im Standard-Modus; mit Portraet feste Position
    # (diagonal2: Logo unten-links, Portraet oben-rechts).
    pos = "diagonal2" if portrait else pick_circle_pos()
    _draw_circles(base, slogan, pos, portrait)   # NUR die CI-Kreise (Grafik) - kein Text/CTA
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base.save(out_path)
    return out_path

def add_logo_circles(image_path, slogan, output_path, portrait=None):
    """Fügt NUR die Logo-Kreise zu einem bestehenden Bild hinzu (für 3-Stufen-Workflow).

    Args:
        image_path: Pfad zum Eingangsbild (z.B. von GPT Image 2)
        slogan: Slogan für den zweiten Kreis (oder None für Zufallsauswahl)
        output_path: Pfad für das Ausgabebild
        portrait: Optionales Portrait-Bild (für feste Position diagonal2)

    Returns:
        output_path
    """
    base = Image.open(image_path).convert("RGB")
    pos = "diagonal2" if portrait else pick_circle_pos()
    _draw_circles(base, slogan, pos, portrait)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    base.save(output_path)
    return output_path


def _render_comic(fields, photo_path, out_path, portrait=None):
    """Bild-Stil 'comic': Das von ensure_comic_bild erzeugte Comic-Bild (photo_path) IST bereits das
    fertige Bild (Illustration in HILO-Palette mit freiem Negativraum). Es wird nur noch
    formatfuellend (cover) auf die Zielleinwand skaliert/eingepasst und gespeichert.
    KEINE weisse Textkarte, KEINE Bullet-Overlays, KEINE CTA-Pille. Fallback ohne Foto: Creme."""
    base = _background(photo_path).convert("RGB")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base.save(out_path)
    return out_path


def render(fields, photo_path, slogan, out_path, portrait=None):
    """Rendert das Magazin-Bild: Foto (oder Creme-Fallback) als Vollbild-Hintergrund, darueber das
    weisse Textfeld (Pille, Ueberschrift, optionale Hero-Zahl ODER groessere Ueberschrift + Hook,
    Symbol-Bullets, Gold-CTA) und die beiden CI-Kreise. Signatur unveraendert (rueckwaertskompatibel:
    die Felder ueberschrift/subline/bullets/cta/ort werden weiter genutzt).

    Bild-Stil 'ki_tafel' (#132): Modus wird intern aus der Einstellung gelesen (kein neuer Pflicht-
    Parameter). Default 'standard' -> unveraendertes v11-Layout unten.

    Bild-Stil 'kreativ' (#145): EINFACH NUR das KI-Foto + die CI-Kreise (kein Textfeld/CTA) ->
    eigener _render_kreativ-Zweig. 'standard' nutzt das v11-Layout unten; nur 'ki_tafel' geht in
    den _render_ki_tafel-Zweig."""
    fields = _safe_fields(fields); slogan = _safe(slogan)
    try:
        # Stil PRO BEITRAG (#144): aus fields['bild_stil'] (stabil) ODER global ODER 'standard'.
        import stilwahl
        stil = stilwahl.aktiver_stil(fields)
    except Exception:
        stil = "standard"
    # #143/#145: ki_tafel -> Tafel-Layout; kreativ -> reines Foto + Kreise; standard -> v11 unten.
    # comic / comic_beratung -> reine Comic-Illustration (kein Overlay), da das Comic-Bild selbst
    # schon fertig ist (bei comic_beratung inkl. Berater vorne + Finanzamt hinten - die Szene IST
    # das Bild, KEINE weisse Textkarte drueber).
    # v5.1+: Wenn Masterprompt v5.1 (Text-im-Bild) verwendet wurde, dann auch für "standard"
    # nur Foto + Kreise rendern, da OpenAI den Text schon ins Bild integriert hat!
    import bildmotiv
    if bildmotiv.PROMPT_VERSION.startswith("v5") and stil == "standard":
        return _render_kreativ(fields, photo_path, slogan, out_path, portrait)
    if stil in ("comic", "comic_beratung"):
        return _render_comic(fields, photo_path, out_path, portrait)
    if stil == "ki_tafel":
        return _render_ki_tafel(fields, photo_path, slogan, out_path, portrait)
    if stil == "kreativ":
        return _render_kreativ(fields, photo_path, slogan, out_path, portrait)
    base = _background(photo_path).convert("RGB")

    # Mit Portraet feste Position (Logo unten-links, Portraet oben-rechts = 'diagonal2');
    # nur ohne Portraet wechselt die Eckposition je Beitrag (Kreis-Rotation).
    pos = "diagonal2" if portrait else pick_circle_pos()
    ct, cb = _content_bounds(pos)

    dr = ImageDraw.Draw(base)
    # Issue #131: Das Foto soll das Textfeld UMRAHMEN. Darum spuerbarer Rand an ALLEN vier
    # Seiten - seitlich etwas breiter als zuvor, damit das umrahmende Motiv links/rechts
    # sichtbar bleibt (frueher 70; das Feld war fast vollbreit).
    margin = 104                             # seitlicher Foto-Rand (links/rechts sichtbar)
    frame_v = 64                             # mindest. Foto-Rand oben/unten (vertikaler Rahmen)
    cx0, cx1 = margin, W - margin           # Textfeld-Spalte (mit deutlichem Seitenrand)
    inx = cx0 + 40                           # Innenrand im Textfeld
    inw = cx1 - inx - 40
    pad_top, pad_bot = 40, 40

    # --- Inhalte vorbereiten (Hoehe vorab berechnen, damit das Feld zentriert sitzt) ---
    pille = _pille_text(fields)
    fpill = _font(_BOLD, 26)
    hero = _safe((fields.get("hero") or "")).strip()   # optionale, echte Zahl/Datum (nie erfunden)
    # Hero vorhanden -> Ueberschrift normal gross; sonst Ueberschrift selbst als Hingucker (groesser)
    head_start = 50 if hero else 64
    fh, HL = _fit(dr, fields.get("ueberschrift", ""), _BOLD, head_start, 34, inw, 3)
    lh_h = fh.size + 8
    fhero = _font(_BOLD, 96)
    sub_txt = fields.get("subline", "") if not hero else ""   # ohne Hero zusaetzlich eine Hook-Subline
    fsub = _font(_REG, 30); SL = _wrap(dr, sub_txt, fsub, inw) if sub_txt else []
    fb = _font(_BOLD, 30)
    bullets = [b for b in (fields.get("bullets") or [])[:3] if b]
    icon_r = 22; bx_text = inx + 2*icon_r + 22
    bblocks = [_wrap(dr, b, fb, inw - (2*icon_r + 22)) for b in bullets]
    lh_b = fb.size + 6
    cta_txt = (_safe(fields.get("cta")) or "Jetzt Termin vereinbaren").strip()
    fcta = _font(_BOLD, 30)

    # Hoehen der einzelnen Bloecke (mit Abstaenden)
    h_pill = fpill.size + 2*11
    h_head = len(HL)*lh_h
    h_hero = fhero.size if hero else 0
    h_sub = len(SL)*(fsub.size + 6)
    bstep = lh_b + 26
    h_bul = len(bblocks)*bstep
    h_cta = fcta.size + 2*13
    gap = 22
    parts = [h_pill, h_head]
    if hero: parts.append(h_hero)
    if SL: parts.append(h_sub)
    if bblocks: parts.append(h_bul)
    parts.append(h_cta)
    content_h = sum(parts) + gap*(len(parts)-1)

    # Issue #131 (ARGUS-Blocker behoben): Die Karte muss den Inhalt VOLLSTAENDIG umschliessen,
    # sonst laeuft der Inhalt (v.a. die Gold-CTA-Pille) unter die Kartenunterkante aufs nackte
    # Foto. Darum wird die Karte an den Inhalt gekoppelt: card_h = Inhalt + Innenabstaende.
    band = cb - ct                          # verfuegbares Band zwischen den Kreisen
    card_needed = content_h + pad_top + pad_bot
    # frame_v ist nur ein OPTIONALER Luft-Rand oben/unten: er wird so weit angewendet, wie nach
    # dem Inhalt noch Platz im Band bleibt - nie so weit, dass der Inhalt nicht mehr passt.
    # Reicht das Band selbst ohne Rand nicht (sehr enge diagonal-Baender + Maximal-Content),
    # fuellt die Karte das ganze Band (frame_v effektiv 0) - lieber kein oberer/unterer
    # Foto-Rand als CTA auf nacktem Foto. Der Inhalt bleibt so immer INNERHALB der Karte.
    frame_eff = max(0, min(frame_v, (band - card_needed)//2))
    avail = band - 2*frame_eff
    card_h = max(card_needed, avail)        # Karte umschliesst den Inhalt immer vollstaendig
    cy0 = ct + frame_eff + (avail - card_h)//2
    cy1 = cy0 + card_h
    _card(base, cx0, cy0, cx1, cy1)

    cxc = (cx0 + cx1)//2   # horizontale Mitte des Felds
    y = cy0 + pad_top

    # gruene Saison-/Themen-Pille
    _pill(base, cxc, y + h_pill//2, pille, fpill, GREEN, WHITE)
    y += h_pill + gap

    # Ueberschrift (zentriert)
    for ln in HL:
        dr.text((cxc, y + fh.size//2), ln, font=fh, fill=NAVY, anchor="mm"); y += lh_h
    y += gap

    # Hero-Zahl als grosser gruener Blickfang (nur wenn echt vorhanden)
    if hero:
        dr.text((cxc, y + fhero.size//2), hero, font=fhero, fill=GREEN, anchor="mm")
        y += h_hero + gap
    # ohne Hero: kurze Hook-Subline unter der (groesseren) Ueberschrift
    for ln in SL:
        dr.text((cxc, y + fsub.size//2), ln, font=fsub, fill=NAVY, anchor="mm"); y += fsub.size + 6
    if SL:
        y += gap

    # Symbol-Bullets (gezeichnete Icons, gruen) - linksbuendig im Feld
    for i, bl in enumerate(bblocks):
        cyb = y + bstep//2
        _bullet_icon(base, inx + icon_r, cyb, icon_r, _BULLET_ICONS[i % len(_BULLET_ICONS)])
        ty = cyb - (len(bl)-1)*lh_b//2
        for ln in bl:
            dr.text((bx_text, ty), ln, font=fb, fill=NAVY, anchor="lm"); ty += lh_b
        y += bstep
    if bblocks:
        y += gap

    # warme CTA-Pille (Gold) - der Ortsbezug steckt bereits im personalisierten cta-Text
    _pill(base, cxc, y + h_cta//2, cta_txt, fcta, ACCENT, WHITE, padx=34, pady=13)

    _draw_circles(base, slogan, pos, portrait)   # schwebende CI-Kreise, Eckposition rotiert je Beitrag

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    base.save(out_path)
    return out_path

# ---------------------------------------------------------------------------
# R1 Karussell - mehrere Slides je Thema (Title -> je Bullet eine Slide -> CTA)
# Gleicher Magazin-Stil wie das Einzelbild: Foto-Hintergrund (cover) bzw. Creme-Fallback,
# weisser Text auf dezentem Scrim, dieselben Logo-/Slogan-Kreise (Eckposition rotiert je Beitrag).
# ---------------------------------------------------------------------------
def _last_circlepos_path():
    return os.path.join(DATA_DIR, "last_circlepos.txt")

def pick_circle_pos():
    """Waehlt die Eckposition der beiden CI-Kreise je Beitrag (Abwechslung) - bevorzugt
    eine andere als zuletzt: 'unten' (beide unten), 'oben' (beide oben),
    'diagonal' (Logo oben-links + Slogan unten-rechts)."""
    last = ""
    try:
        last = open(_last_circlepos_path(), encoding="utf-8").read().strip()
    except Exception:
        pass
    opts = [p for p in CIRCLE_POSITIONS if p != last] or CIRCLE_POSITIONS
    chosen = random.choice(opts)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        open(_last_circlepos_path(), "w", encoding="utf-8").write(chosen)
    except Exception:
        pass
    return chosen

def _content_bounds(pos):
    """Vertikale Textgrenzen je nach Kreisposition, damit kein Text einen Kreis beruehrt:
    sobald oben ein Kreis steht, startet der Text tiefer; sobald unten ein Kreis steht,
    endet er hoeher (bei diagonal/diagonal2 also beidseitig begrenzt)."""
    ct = TOPB_BAND if pos == "unten" else CTOPTEXT   # nur bei 'unten' kein oberer Kreis
    cb = BOTB_BAND if pos == "oben" else CBOT         # nur bei 'oben' kein unterer Kreis
    return ct, cb

def _circle_portrait(base, cx, cy, R, portrait):
    """Setzt ein kreisrund zugeschnittenes Portraet (mit weissem Rand) an die Kreis-Position -
    ersetzt den blauen Slogan-Kreis. Liefert True bei Erfolg, sonst False (dann blauer Punkt)."""
    try:
        ImageDraw.Draw(base).ellipse([cx-R, cy-R, cx+R, cy+R], fill=WHITE)  # weisser Rand
        ring = 10; d = 2*(R-ring)
        pim = Image.open(portrait).convert("RGB")
        pw, ph = pim.size; s = min(pw, ph)
        pim = pim.crop(((pw-s)//2, (ph-s)//2, (pw-s)//2+s, (ph-s)//2+s)).resize((d, d), Image.LANCZOS)
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, d-1, d-1], fill=255)
        base.paste(pim, (int(cx-R+ring), int(cy-R+ring)), mask)
        return True
    except Exception:
        return False

def _draw_circles(base, slogan, pos="unten", portrait=None):
    """Logo-Kreis (links) und Slogan-Kreis (rechts) als schwebende Erkennungszeichen in den
    Ecken. pos = 'unten' (beide unten), 'oben' (beide oben),
    'diagonal' (Logo oben-links + Slogan unten-rechts) oder
    'diagonal2' (Logo unten-links + Slogan oben-rechts) - Abwechslung je Beitrag.
    portrait = optionaler Bildpfad; ist er gesetzt, ersetzt ein Kreis-Portraet den blauen
    Slogan-Kreis (z.B. das Foto/Logo der Beratungsstelle)."""
    dr = ImageDraw.Draw(base)
    R = 102; CCY_TOP, CCY_BOT = 134, 946
    # Mit hinterlegtem Beraterfoto wird der Portraet-Kreis deutlich groesser und prominenter
    # (~26 % der Bildbreite) - bewusste Abweichung von der einheitlichen Kreisgroesse.
    has_portrait = bool(portrait and os.path.exists(portrait))
    RP = 142 if has_portrait else R
    logo_y = CCY_TOP if pos in ("oben", "diagonal") else CCY_BOT
    slogan_y = CCY_TOP if pos in ("oben", "diagonal2") else CCY_BOT
    if has_portrait and slogan_y == CCY_TOP:
        slogan_y = RP + 18   # groesseres Portraet oben etwas tiefer setzen, damit es nicht anschneidet
    def shadow(cx, cy, rad):
        # weicher, etwas groesserer Schlagschatten mit Versatz nach unten-rechts -
        # bildet einen sichtbaren Halo, der auch auf dem farbigen Band zeigt, dass die Kreise schweben
        sh = Image.new("RGBA", base.size, (0,0,0,0))
        ImageDraw.Draw(sh).ellipse([cx-rad-6, cy-rad+2, cx+rad+16, cy+rad+22], fill=(0,0,0,165))
        blr = sh.filter(ImageFilter.GaussianBlur(22)); base.paste(blr, (0,0), blr)
    lx = R + 22; shadow(lx, logo_y, R)
    dr.ellipse([lx-R, logo_y-R, lx+R, logo_y+R], fill=WHITE)
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA"); lw = 170; lh2 = int(logo.height*lw/logo.width)
        logo = logo.resize((lw, lh2), Image.LANCZOS); base.paste(logo, (int(lx-lw/2), int(logo_y-lh2/2)), logo)
    rx = W - RP - 22; shadow(rx, slogan_y, RP)
    if has_portrait and _circle_portrait(base, rx, slogan_y, RP, portrait):
        return   # Kreis-Portraet (vergroessert) ersetzt den blauen Slogan-Punkt
    dr.ellipse([rx-R, slogan_y-R, rx+R, slogan_y+R], fill=BLUE)
    fsl = _font(_BOLD, 33); lines = _slogan_lines(dr, slogan, fsl, 2*R - 36)
    sy = slogan_y - (len(lines)-1)*(fsl.size+4)//2
    for ln in lines:
        dr.text((rx, sy), ln, font=fsl, fill=WHITE, anchor="mm"); sy += fsl.size + 4

def _draw_pager(base, idx, total):
    """Seitenpunkte im oberen Band zeigen die Position in der Karussell-Folge."""
    if total <= 1:
        return
    dr = ImageDraw.Draw(base)
    r = 7; gap = 26; x0 = W//2 - (total-1)*gap//2; y = 168
    for i in range(total):
        cx = x0 + i*gap
        if i == idx:
            dr.ellipse([cx-r, y-r, cx+r, y+r], fill=WHITE)
        else:
            dr.ellipse([cx-r, y-r, cx+r, y+r], outline=WHITE, width=2)

def _slide_bg(photo_path):
    """Slide-Hintergrund im neuen Magazin-Stil: Szene-Foto (cover) mit dezentem dunklem Verlauf-Scrim
    fuer Textlesbarkeit, sonst warmer Creme-Fallback. Liefert ein RGB-Image."""
    bg = _cover_photo(photo_path)
    if bg is None:
        return _creme_bg()
    # Vertikaler Scrim (oben/unten dunkler), damit der weisse Text auf dem Foto lesbar bleibt
    scrim = Image.new("L", (1, H), 0); sp = scrim.load()
    for yy in range(H):
        t = abs((yy/(H-1)) - 0.5)*2     # 0 in der Mitte, 1 an den Raendern
        sp[0, yy] = int(150 * (t**1.4))
    scrim = scrim.resize((W, H))
    dark = Image.new("RGB", (W, H), (12, 24, 48))
    bg.paste(dark, (0, 0), scrim)
    return bg

def _slide_title(fields, photo_path, slogan, idx, total, pos="unten", portrait=None):
    base = _slide_bg(photo_path)
    ct, cb = _content_bounds(pos)
    dr = ImageDraw.Draw(base); margin = 54
    head_w = (W - 2*margin) if pos == "unten" else (W - 2*246)
    fh, HL = _fit(dr, fields.get("ueberschrift", ""), _BOLD, 60, 36, head_w, 3)
    fsb = _font(_BOLD, 42); SL = _wrap(dr, fields.get("subline", ""), fsb, W - 2*margin)
    head_h = len(HL)*(fh.size + 6); sub_h = len(SL)*(fsb.size + 12)
    group_h = head_h + (28 if SL else 0) + sub_h
    y = ct + (cb - ct - group_h)//2 + fh.size//2
    for ln in HL:
        dr.text((W//2, y), ln, font=fh, fill=WHITE, anchor="mm"); y += fh.size + 6
    y += 28 - fh.size//2 + fsb.size//2 if SL else 0
    for ln in SL:
        dr.text((W//2, y), ln, font=fsb, fill=WHITE, anchor="mm"); y += fsb.size + 12
    fc = _font(_BOLD, 30)
    dr.text((W//2, H - 64), u"Weiterwischen →", font=fc, fill=WHITE, anchor="mm")
    _draw_circles(base, slogan, pos, portrait)
    _draw_pager(base, idx, total)
    return base

def _slide_bullet(text, slogan, idx, total, nummer, pos="unten", portrait=None):
    base = _slide_bg(None)   # Bullet-Slides bleiben auf warmem Creme-Hintergrund (klare Lesbarkeit)
    ct, cb = _content_bounds(pos)
    dr = ImageDraw.Draw(base); margin = 78
    nr = 44; ncx = W//2; ncy = ct + 96   # Nummern-Badge unter der oberen Grenze
    dr.ellipse([ncx-nr, ncy-nr, ncx+nr, ncy+nr], fill=GREEN)
    dr.text((ncx, ncy), str(nummer), font=_font(_BOLD, 46), fill=WHITE, anchor="mm")
    f, L = _fit(dr, text, _BOLD, 58, 32, W - 2*margin, 6)
    top = ncy + nr + 40
    th = len(L)*(f.size+12)
    y = top + (cb - top - th)//2 + f.size//2   # Text bleibt frei von den Kreisen
    for ln in L:
        dr.text((W//2, y), ln, font=f, fill=NAVY, anchor="mm"); y += f.size + 12
    _draw_circles(base, slogan, pos, portrait)
    _draw_pager(base, idx, total)
    return base

def _slide_cta(fields, photo_path, slogan, idx, total, pos="unten", portrait=None):
    base = _slide_bg(photo_path)
    ct, cb = _content_bounds(pos)
    dr = ImageDraw.Draw(base); margin = 78
    head = _font(_BOLD, 40)
    dr.text((W//2, ct + 70), "Aktiv werden!", font=head, fill=WHITE, anchor="mm")
    fc, CL = _fit(dr, fields.get("cta", ""), _BOLD, 52, 30, W - 2*margin, 4)
    sub_h = len(CL)*(fc.size + 12)
    top = ct + 128
    y = top + (cb - top - sub_h)//2 + fc.size//2
    for ln in CL:
        dr.text((W//2, y), ln, font=fc, fill=WHITE, anchor="mm"); y += fc.size + 12
    _draw_circles(base, slogan, pos, portrait)
    _draw_pager(base, idx, total)
    return base

def render_slides(fields, photo_path, slogan, out_dir, prefix, max_slides=6, portrait=None):
    """Rendert ein Karussell: Title-Slide + je Bullet eine Slide + CTA-Slide.
    Liefert die Liste der Slide-Pfade in Reihenfolge. max_slides begrenzt die Gesamtzahl."""
    os.makedirs(out_dir, exist_ok=True)
    fields = _safe_fields(fields); slogan = _safe(slogan)
    # #145: 'kreativ' ist ein Einzelbild-Stil (reines Foto + Kreise) - genau EINE Slide, keine
    # Text-Slides. Standard/ki_tafel-Karussell bleibt unveraendert.
    try:
        import stilwahl
        aktiv = stilwahl.aktiver_stil(fields)
        if aktiv == "kreativ":
            p = os.path.join(out_dir, "%s_01.png" % prefix)
            return [_render_kreativ(fields, photo_path, slogan, p, portrait)]
        if aktiv == "comic_strip":
            # #154: comic_strip ist ein 3-Felder-Comic-Karussell (rohe KI-Panels, kein Overlay).
            # Der personalisierte Weg laeuft ueber personalisierung.render_slides_fuer_stelle (mit
            # Berater-Referenz der Stelle). Hier (stellenlos, z.B. Detail-Vorschau/FB-Seite) wird
            # ohne Berater-Gesicht degradiert - die Panels sind bereits fertige Bilder.
            import bildmotiv
            return bildmotiv.ensure_comic_strip_bilder(fields, "")
    except Exception:
        pass
    bullets = [b for b in (fields.get("bullets") or []) if b]
    bullets = bullets[:max(1, max_slides - 2)]   # Title + CTA belegen 2 Slides
    total = 1 + len(bullets) + 1
    # Mit Portraet feste Position (Logo unten-links, Portraet oben-rechts); sonst Abwechslung
    pos = "diagonal2" if portrait else pick_circle_pos()
    slides = [_slide_title(fields, photo_path, slogan, 0, total, pos, portrait)]
    for i, b in enumerate(bullets):
        slides.append(_slide_bullet(b, slogan, 1 + i, total, i + 1, pos, portrait))
    slides.append(_slide_cta(fields, photo_path, slogan, total - 1, total, pos, portrait))
    paths = []
    for i, img in enumerate(slides):
        p = os.path.join(out_dir, "%s_%02d.png" % (prefix, i + 1))
        img.save(p); paths.append(p)
    return paths

def render_drafts():
    import bildmotiv
    from db import get_conn
    out_dir = os.path.join(DATA_DIR, "bilder")
    done = 0
    with get_conn() as conn:
        rows = conn.execute("SELECT id, text FROM entwuerfe WHERE status='entwurf' "
                            "AND (bild_pfad IS NULL OR bild_pfad='')").fetchall()
    for r in rows:
        try:
            fields = json.loads(r["text"])
        except Exception:
            continue
        photo = bildmotiv.ensure_photo_fuer(fields)
        slogan = pick_slogan(fields.get("slogan"))
        out = os.path.join(out_dir, "entwurf_%d.png" % r["id"])
        try:
            render(fields, photo, slogan, out)
            with get_conn() as conn:
                conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (out, r["id"]))
            done += 1
            log.info("Bild erzeugt: Entwurf %s", r["id"])
        except Exception as ex:
            log.warning("Bilderzeugung fehlgeschlagen (Entwurf %s): %s", r["id"], ex)
    return done
