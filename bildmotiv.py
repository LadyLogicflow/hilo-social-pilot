# -*- coding: utf-8 -*-
"""Erzeugt situative, freigestellte Fotomotive via OpenAI gpt-image-1 (transparenter Hintergrund).
Caching pro Motiv. Ohne openai_api_key wird None geliefert (Bild dann ohne Foto)."""
import base64, hashlib, logging, os
from secrets_store import get_secret
from config import DATA_DIR

log = logging.getLogger("hilo.bildmotiv")
MOTIV_DIR = os.path.join(DATA_DIR, "motive")

def _prompt(motiv):
    return ("Freigestellt vor transparentem Hintergrund: %s. Warme, hochwertige Werbefotografie einer "
            "positiven Steuerberatungs-Szene; freundliche, laechelnde Menschen in zugewandter Interaktion "
            "(kein nachdenklicher oder sorgenvoller Ausdruck, kein einzelnes Portraitfoto). Passende "
            "Requisiten wie Laptop, Unterlagen und eine schlichte Kaffeetasse duerfen vorkommen und werden "
            "sauber mitfreigestellt. Die gesamte Gruppe als Halbkoerper bis etwa Tischhoehe, vollstaendig "
            "im Bild mit deutlichem Abstand zum linken und rechten Rand. Sauber freigestellt, KEIN "
            "Hintergrund, KEIN Tisch-Hintergrund, KEINE Texte, KEINE Logos, KEINE Markennamen." % motiv)

def ensure_photo(motiv):
    motiv = (motiv or "").strip()
    # Gezeichnete Motiv-Icons (z.B. 'icon:kalender') - kein OpenAI noetig
    if motiv.startswith("icon:"):
        import countdown_motive
        os.makedirs(MOTIV_DIR, exist_ok=True)
        name = motiv.split(":", 1)[1]
        path = os.path.join(MOTIV_DIR, "icon_%s.png" % name)
        return path if os.path.exists(path) else countdown_motive.render_icon(name, path)
    motiv = motiv or "freundliche Person mittleren Alters"
    os.makedirs(MOTIV_DIR, exist_ok=True)
    h = hashlib.sha256(motiv.lower().encode("utf-8")).hexdigest()[:16]
    path = os.path.join(MOTIV_DIR, h + ".png")
    if os.path.exists(path):
        return path
    key = get_secret("openai_api_key")
    if not key:
        log.info("Bildmotiv uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    try:
        import requests
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": _prompt(motiv), "size": "1024x1536",
                  "background": "transparent", "output_format": "png", "n": 1},
            timeout=120)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        log.info("Bildmotiv erzeugt: %s", motiv[:50])
        return path
    except Exception as ex:
        log.warning("Bildmotiv fehlgeschlagen (%s): %s", motiv[:40], ex)
        return None
