# -*- coding: utf-8 -*-
"""M4 - Bild im HILO-Design v10 (1080x1080): zwei Verlaufsbaender, weisse Ueberschrift,
grosses freigestelltes Foto rechts (hinter unterem Verlauf), Text links vertikal zentriert,
CTA im unteren Band, zwei schwebende Kreise (Logo links, Slogan rechts)."""
import math, os, json, logging, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config import BASE_DIR, DATA_DIR

log = logging.getLogger("hilo.bildgen")
W = H = 1080
# Text-Unterkante: Schriften enden oberhalb der schwebenden Kreise (Kreis-Oberkante 844,
# inkl. weichem Schatten-Halo) - so wird kein Text vom Kreis oder Schatten verdeckt.
CBOT = 788
CTOPTEXT = H - CBOT        # = 292: Text-Oberkante, wenn die Kreise oben stehen (gespiegelt)
TOPB_BAND, BOTB_BAND = 192, 905   # Innenkanten der beiden Verlaufsbaender
# Eckpositionen der beiden CI-Kreise (Erkennungszeichen) - sorgen fuer Abwechslung je Beitrag
# diagonal  = Logo oben-links + Slogan unten-rechts; diagonal2 = Logo unten-links + Slogan oben-rechts
CIRCLE_POSITIONS = ["unten", "oben", "diagonal", "diagonal2"]
BLUE=(31,66,141); GREEN=(96,163,60); LIGHT=(244,247,246); NAVY=(21,51,110); GREEN2=(76,123,45); WHITE=(255,255,255)
LOGO_PATH = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
_BOLD = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_REG  = ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

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

def _gradient():
    row = Image.new("RGB", (W, 1)); px = row.load()
    for x in range(W):
        t = x / (W - 1)
        px[x, 0] = (int(BLUE[0]+(GREEN[0]-BLUE[0])*t), int(BLUE[1]+(GREEN[1]-BLUE[1])*t), int(BLUE[2]+(GREEN[2]-BLUE[2])*t))
    return row.resize((W, H))

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

def render(fields, photo_path, slogan, out_path, portrait=None):
    cut = None
    if photo_path and os.path.exists(photo_path):
        try:
            cut = Image.open(photo_path).convert("RGBA")
            bb = cut.getchannel("A").getbbox()
            if bb:
                cut = cut.crop(bb)
        except Exception:
            cut = None

    grad = _gradient()
    base = Image.new("RGB", (W, H), LIGHT)
    TOPB, BOTB = 192, 905
    mt = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mt).polygon([(0,0),(W,0)]+[(x, TOPB+22*math.sin((x/W)*2*math.pi)) for x in range(W,-1,-15)], fill=255)
    base.paste(grad, (0, 0), mt)

    if cut is not None:
        # Foto gross (ca. 2/3 der Breite), Schwerpunkt rechts; Text liegt darueber (wird danach
        # gezeichnet) und ueberschneidet nur die linke, meist transparente Foto-Haelfte.
        pw = 720; sc = pw / cut.width; chh = int(cut.height * sc)
        cut2 = cut.resize((pw, chh), Image.LANCZOS)
        base.paste(cut2, (W - 8 - pw, 205), cut2)

    mb = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mb).polygon([(0,H),(W,H)]+[(x, BOTB+22*math.sin((x/W)*2*math.pi+1.0)) for x in range(W,-1,-15)], fill=255)
    base.paste(grad, (0, 0), mb)

    dr = ImageDraw.Draw(base); margin = 54
    # Mit Portraet: feste Position (Logo unten-links, Portraet oben-rechts = 'diagonal2').
    # Nur ohne Portraet wechselt die Eckposition je Beitrag.
    pos = "diagonal2" if portrait else pick_circle_pos()
    ct, cb = _content_bounds(pos)
    head_w = (W - 2*margin) if pos == "unten" else (W - 2*246)
    fh, HL = _fit(dr, fields.get("ueberschrift", ""), _BOLD, 46, 30, head_w, 2)
    yy = 72 if len(HL) == 2 else 96
    for ln in HL:
        dr.text((W//2, yy), ln, font=fh, fill=WHITE, anchor="mm"); yy += fh.size + 6

    LCOL = 372 if cut is not None else (W - margin)   # Text bleibt im linken Drittel (Bullets duerfen umbrechen)
    tx0 = margin + 18 + 18 + 16
    fsb = _font(_REG, 31); SL = _wrap(dr, fields.get("subline", ""), fsb, LCOL - margin)
    fb = _font(_BOLD, 30); bw = LCOL - tx0
    bullets = [b for b in (fields.get("bullets") or [])[:3] if b]
    blocks = [_wrap(dr, b, fb, bw) for b in bullets]
    lh = fb.size + 6
    # Gleichmaessiger Abstand: jeder Bullet bekommt denselben vertikalen Schritt (Hoehe des
    # groessten Bullets + fester Abstand), unabhaengig davon ob er ein- oder zweizeilig ist.
    maxlines = max((len(bl) for bl in blocks), default=1)
    step = maxlines * lh + 22
    bh = len(SL)*(fsb.size+8) + 30 + len(blocks)*step
    y = ct + (cb - ct - bh)//2 + fsb.size//2   # Inhalt bleibt frei von den Kreisen
    for ln in SL:
        dr.text((margin, y), ln, font=fsb, fill=GREEN2, anchor="lm"); y += fsb.size + 8
    y += 30
    for i, bl in enumerate(blocks):
        cy = y + i*step + step//2          # Mitte des gleich grossen Slots -> konstanter Abstand
        r = 17; bx = margin + r
        dr.ellipse([bx-r, cy-r, bx+r, cy+r], fill=GREEN)
        dr.line([(bx-8, cy), (bx-1, cy+8), (bx+9, cy-9)], fill=WHITE, width=5, joint="curve")
        ty = cy - (len(bl)-1)*lh//2
        for ln in bl:
            dr.text((tx0, ty), ln, font=fb, fill=NAVY, anchor="lm"); ty += lh

    fc, CL = _fit(dr, fields.get("cta", ""), _BOLD, 28, 20, W - 2*255, 2)
    cyy = (BOTB + H)//2 + 12; ty = cyy - (len(CL)-1)*(fc.size+4)//2
    for ln in CL:
        dr.text((W//2, ty), ln, font=fc, fill=WHITE, anchor="mm"); ty += fc.size + 4

    _draw_circles(base, slogan, pos, portrait)   # schwebende Kreise, Eckposition variiert je Beitrag

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    base.save(out_path)
    return out_path

# ---------------------------------------------------------------------------
# R1 Karussell - mehrere Slides je Thema (Title -> je Bullet eine Slide -> CTA)
# Gleiches HILO-Design (zwei Verlaufsbaender, Logo-/Slogan-Kreise) wie das Einzelbild.
# ---------------------------------------------------------------------------
def _load_cut(photo_path):
    if photo_path and os.path.exists(photo_path):
        try:
            cut = Image.open(photo_path).convert("RGBA")
            bb = cut.getchannel("A").getbbox()
            if bb:
                cut = cut.crop(bb)
            return cut
        except Exception:
            return None
    return None

def _draw_bands(base):
    """Zeichnet die zwei Verlaufsbaender (oben/unten) und liefert deren Innenkanten."""
    grad = _gradient()
    TOPB, BOTB = 192, 905
    mt = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mt).polygon([(0,0),(W,0)]+[(x, TOPB+22*math.sin((x/W)*2*math.pi)) for x in range(W,-1,-15)], fill=255)
    base.paste(grad, (0, 0), mt)
    mb = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mb).polygon([(0,H),(W,H)]+[(x, BOTB+22*math.sin((x/W)*2*math.pi+1.0)) for x in range(W,-1,-15)], fill=255)
    base.paste(grad, (0, 0), mb)
    return TOPB, BOTB

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
        ring = 7; d = 2*(R-ring)
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
    logo_y = CCY_TOP if pos in ("oben", "diagonal") else CCY_BOT
    slogan_y = CCY_TOP if pos in ("oben", "diagonal2") else CCY_BOT
    def shadow(cx, cy):
        # weicher, etwas groesserer Schlagschatten mit Versatz nach unten-rechts -
        # bildet einen sichtbaren Halo, der auch auf dem farbigen Band zeigt, dass
        # beide Kreise schweben (kleiner Versatz wurde sonst vom Kreis verdeckt)
        sh = Image.new("RGBA", base.size, (0,0,0,0))
        ImageDraw.Draw(sh).ellipse([cx-R-6, cy-R+2, cx+R+16, cy+R+22], fill=(0,0,0,165))
        blr = sh.filter(ImageFilter.GaussianBlur(22)); base.paste(blr, (0,0), blr)
    lx = R + 22; shadow(lx, logo_y)
    dr.ellipse([lx-R, logo_y-R, lx+R, logo_y+R], fill=WHITE)
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA"); lw = 170; lh2 = int(logo.height*lw/logo.width)
        logo = logo.resize((lw, lh2), Image.LANCZOS); base.paste(logo, (int(lx-lw/2), int(logo_y-lh2/2)), logo)
    rx = W - R - 22; shadow(rx, slogan_y)
    if portrait and os.path.exists(portrait) and _circle_portrait(base, rx, slogan_y, R, portrait):
        return   # Kreis-Portraet ersetzt den blauen Slogan-Punkt
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

def _fit_photo(cut, max_h, max_w):
    """Skaliert ein freigestelltes Motiv auf max. Hoehe/Breite (Seitenverhaeltnis erhalten)."""
    if cut is None:
        return None
    sc = max_h / cut.height
    if cut.width * sc > max_w:
        sc = max_w / cut.width
    return cut.resize((max(1, int(cut.width*sc)), max(1, int(cut.height*sc))), Image.LANCZOS)

def _slide_title(fields, photo_path, slogan, idx, total, pos="unten", portrait=None):
    cut = _load_cut(photo_path)
    base = Image.new("RGB", (W, H), LIGHT)
    TOPB, BOTB = _draw_bands(base)
    ct, cb = _content_bounds(pos)
    dr = ImageDraw.Draw(base); margin = 54
    # Ueberschrift gross, fett, zentriert im oberen Band; sobald oben ein Kreis steht
    # schmaler, damit sie die Eck-Kreise nicht beruehrt
    head_w = (W - 2*margin) if pos == "unten" else (W - 2*246)
    fh, HL = _fit(dr, fields.get("ueberschrift", ""), _BOLD, 56, 36, head_w, 2)
    yy = 64 if len(HL) == 2 else 92
    for ln in HL:
        dr.text((W//2, yy), ln, font=fh, fill=WHITE, anchor="mm"); yy += fh.size + 6
    # Eyecatcher (zentriert) + subline (fett, gross, zentriert) als vertikal+horizontal
    # zentrierte Gruppe im freien Feld zwischen den Kreis-Grenzen (ct..cb)
    fsb = _font(_BOLD, 42); SL = _wrap(dr, fields.get("subline", ""), fsb, W - 2*margin)
    sub_h = len(SL)*(fsb.size + 12)
    photo_max = max(140, (cb - ct) - sub_h - 30 - 36)
    cut2 = _fit_photo(cut, min(440, photo_max), W - 2*margin)
    ph = cut2.height if cut2 is not None else 0
    gap = 30 if cut2 is not None else 0
    group_h = ph + gap + sub_h
    gy = ct + (cb - ct - group_h)//2
    if cut2 is not None:
        base.paste(cut2, (int(W//2 - cut2.width//2), int(gy)), cut2)
        gy += ph + gap
    sy = gy + fsb.size//2
    for ln in SL:
        dr.text((W//2, sy), ln, font=fsb, fill=NAVY, anchor="mm"); sy += fsb.size + 12
    # "Weiterwischen"-Hinweis unten-zentriert (klart die Eck-Kreise in jeder Position)
    fc = _font(_BOLD, 30)
    dr.text((W//2, (BOTB + H)//2 + 12), u"Weiterwischen →", font=fc, fill=WHITE, anchor="mm")
    _draw_circles(base, slogan, pos, portrait)
    _draw_pager(base, idx, total)
    return base

def _slide_bullet(text, slogan, idx, total, nummer, pos="unten", portrait=None):
    base = Image.new("RGB", (W, H), LIGHT)
    TOPB, BOTB = _draw_bands(base)
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
    cut = _load_cut(photo_path)
    base = Image.new("RGB", (W, H), LIGHT)
    TOPB, BOTB = _draw_bands(base)
    ct, cb = _content_bounds(pos)
    dr = ImageDraw.Draw(base); margin = 78
    head = _font(_BOLD, 40)
    dr.text((W//2, ct + 70), "Aktiv werden!", font=head, fill=GREEN2, anchor="mm")
    fc, CL = _fit(dr, fields.get("cta", ""), _BOLD, 52, 30, W - 2*margin, 4)
    sub_h = len(CL)*(fc.size + 12)
    top = ct + 128
    # Foto-Hoehe adaptiv aus Restplatz; Gruppe bleibt frei von den Kreisen
    photo_max = max(140, (cb - top) - sub_h - 28 - 30)
    cut2 = _fit_photo(cut, min(360, photo_max), W - 2*margin)
    ph = cut2.height if cut2 is not None else 0
    gap = 28 if cut2 is not None else 0
    group_h = ph + gap + sub_h
    gy = top + (cb - top - group_h)//2
    if cut2 is not None:
        base.paste(cut2, (int(W//2 - cut2.width//2), int(gy)), cut2)
        gy += ph + gap
    y = gy + fc.size//2
    for ln in CL:
        dr.text((W//2, y), ln, font=fc, fill=NAVY, anchor="mm"); y += fc.size + 12
    _draw_circles(base, slogan, pos, portrait)
    _draw_pager(base, idx, total)
    return base

def render_slides(fields, photo_path, slogan, out_dir, prefix, max_slides=6, portrait=None):
    """Rendert ein Karussell: Title-Slide + je Bullet eine Slide + CTA-Slide.
    Liefert die Liste der Slide-Pfade in Reihenfolge. max_slides begrenzt die Gesamtzahl."""
    os.makedirs(out_dir, exist_ok=True)
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
        photo = bildmotiv.ensure_photo(fields.get("bild_motiv"))
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
