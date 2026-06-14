# -*- coding: utf-8 -*-
"""M4 - Bild im HILO-Design v10 (1080x1080): zwei Verlaufsbaender, weisse Ueberschrift,
grosses freigestelltes Foto rechts (hinter unterem Verlauf), Text links vertikal zentriert,
CTA im unteren Band, zwei schwebende Kreise (Logo links, Slogan rechts)."""
import math, os, json, logging, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config import BASE_DIR, DATA_DIR

log = logging.getLogger("hilo.bildgen")
W = H = 1080
BLUE=(31,66,141); GREEN=(96,163,60); LIGHT=(244,247,246); NAVY=(21,51,110); GREEN2=(76,123,45); WHITE=(255,255,255)
LOGO_PATH = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
_BOLD = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
_REG  = ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

STANDARD_SLOGANS = ["Wir sind HILO", "HILO - wir machen's einfach", "Steuern? Machen wir.",
                    "Mehr Netto fuer Sie", "Ihr gutes Recht", "Einfach mehr rausholen"]

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
    return _wrap(dr, slogan, font, max_w)[:3]

def render(fields, photo_path, slogan, out_path):
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
        pw = 625; sc = pw / cut.width; chh = int(cut.height * sc)
        cut2 = cut.resize((pw, chh), Image.LANCZOS)
        base.paste(cut2, (W - 16 - pw, 205), cut2)

    mb = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mb).polygon([(0,H),(W,H)]+[(x, BOTB+22*math.sin((x/W)*2*math.pi+1.0)) for x in range(W,-1,-15)], fill=255)
    base.paste(grad, (0, 0), mb)

    dr = ImageDraw.Draw(base); margin = 54
    fh, HL = _fit(dr, fields.get("ueberschrift", ""), _BOLD, 46, 30, W - 2*margin, 2)
    yy = 72 if len(HL) == 2 else 96
    for ln in HL:
        dr.text((W//2, yy), ln, font=fh, fill=WHITE, anchor="mm"); yy += fh.size + 6

    LCOL = 430 if cut is not None else (W - margin)
    tx0 = margin + 18 + 18 + 16
    fsb = _font(_REG, 31); SL = _wrap(dr, fields.get("subline", ""), fsb, LCOL - margin)
    fb = _font(_BOLD, 30); bw = LCOL - tx0
    bullets = [b for b in (fields.get("bullets") or [])[:3] if b]
    blocks = [_wrap(dr, b, fb, bw) for b in bullets]
    lh = fb.size + 6
    bh = len(SL)*(fsb.size+8) + 30 + sum(len(bl)*lh + 16 for bl in blocks)
    y = TOPB + (BOTB - TOPB - bh)//2 + fsb.size//2
    for ln in SL:
        dr.text((margin, y), ln, font=fsb, fill=GREEN2, anchor="lm"); y += fsb.size + 8
    y += 30
    for bl in blocks:
        r = 17; bx = margin + r
        dr.ellipse([bx-r, y-r, bx+r, y+r], fill=GREEN)
        dr.line([(bx-8, y), (bx-1, y+8), (bx+9, y-9)], fill=WHITE, width=5, joint="curve")
        ty = y - (len(bl)-1)*lh//2
        for ln in bl:
            dr.text((tx0, ty), ln, font=fb, fill=NAVY, anchor="lm"); ty += lh
        y += len(bl)*lh + 16

    fc, CL = _fit(dr, fields.get("cta", ""), _BOLD, 28, 20, W - 2*255, 2)
    cyy = (BOTB + H)//2 + 12; ty = cyy - (len(CL)-1)*(fc.size+4)//2
    for ln in CL:
        dr.text((W//2, ty), ln, font=fc, fill=WHITE, anchor="mm"); ty += fc.size + 4

    R = 102; ccy = 946
    def shadow(cx, cy):
        sh = Image.new("RGBA", base.size, (0,0,0,0))
        ImageDraw.Draw(sh).ellipse([cx-R+5, cy-R+13, cx+R+5, cy+R+13], fill=(0,0,0,100))
        blr = sh.filter(ImageFilter.GaussianBlur(15)); base.paste(blr, (0,0), blr)
    lx = R + 22; shadow(lx, ccy)
    dr.ellipse([lx-R, ccy-R, lx+R, ccy+R], fill=WHITE)
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA"); lw = 170; lh2 = int(logo.height*lw/logo.width)
        logo = logo.resize((lw, lh2), Image.LANCZOS); base.paste(logo, (int(lx-lw/2), int(ccy-lh2/2)), logo)
    rx = W - R - 22; shadow(rx, ccy)
    dr.ellipse([rx-R, ccy-R, rx+R, ccy+R], fill=BLUE)
    fsl = _font(_BOLD, 33); lines = _slogan_lines(dr, slogan, fsl, 2*R - 36)
    sy = ccy - (len(lines)-1)*(fsl.size+4)//2
    for ln in lines:
        dr.text((rx, sy), ln, font=fsl, fill=WHITE, anchor="mm"); sy += fsl.size + 4

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    base.save(out_path)
    return out_path

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
