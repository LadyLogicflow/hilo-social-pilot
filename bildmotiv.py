# -*- coding: utf-8 -*-
"""Erzeugt stimmungsvolle, vollflaechige Magazin-/Editorial-Fotos via OpenAI gpt-image-1
(opakes Foto MIT Umgebung, als Hintergrund fuer das neue Bild-Layout).
Caching pro Motiv. Ohne openai_api_key wird None geliefert (Bild dann ohne Foto -> warmer Fallback)."""
import base64, hashlib, logging, os
from secrets_store import get_secret
from config import DATA_DIR

log = logging.getLogger("hilo.bildmotiv")
MOTIV_DIR = os.path.join(DATA_DIR, "motive")

def _prompt(motiv):
    """Einheitlicher Szene-Prompt fuer ein vollflaechiges, opakes Magazin-/Editorial-Foto MIT
    Umgebung (kein freigestelltes Motiv mehr). Das Motiv beschreibt Jahreszeit, Gefuehl und einen
    dezenten Themenbezug; das Foto fuellt spaeter das ganze 1080x1080-Bild als Hintergrund.
    Ein ruhiger Bereich bleibt frei fuer das spaeter daraufgesetzte weisse Textfeld."""
    return ("Hochwertige, emotionale Magazin-/Editorial-Fotografie. Eine stimmungsvolle, "
            "authentische Szene, die %s vermittelt - Jahreszeit, Gefuehl und ein dezenter Bezug zum "
            "Thema, schoen und natuerlich gestylt (KEIN steifes Stockfoto, keine steifen Posen). "
            "Warmes, weiches Tageslicht, geringe Schaerfentiefe, harmonische warme Farben. Die Szene "
            "fuellt das ganze Bild als Hintergrund. Ein ruhiger, wenig detaillierter Bereich bleibt "
            "frei (fuer ein spaeteres Textfeld). KEIN Text, keine Schrift, keine Logos oder "
            "Markennamen im Bild." % motiv)

def ensure_photo_fuer(fields):
    """Liefert das Szene-Foto fuer den Beitrag. Bevorzugt das neue Feld 'szene_motiv'
    (emotionale Szene mit Umgebung); faellt fuer aeltere Entwuerfe auf 'bild_motiv' bzw.
    'bild_motiv_thema' zurueck, damit bestehende Entwuerfe weiter rendern.
    'icon:'-Motive (gezeichnet) bleiben unveraendert."""
    motiv = (fields.get("szene_motiv") or fields.get("bild_motiv")
             or fields.get("bild_motiv_thema") or "").strip()
    return ensure_photo(motiv)

def ensure_photo(motiv, typ=None):
    """Erzeugt (oder liefert aus dem Cache) das Szene-Foto zu 'motiv'. Der Parameter 'typ' wird
    aus Rueckwaerts-Kompatibilitaet noch akzeptiert, aber nicht mehr ausgewertet (einheitliche
    Szene-Logik). 'icon:'-Motive werden weiterhin gezeichnet (kein OpenAI noetig)."""
    motiv = (motiv or "").strip()
    # Gezeichnete Motiv-Icons (z.B. 'icon:kalender') - kein OpenAI noetig
    if motiv.startswith("icon:"):
        import countdown_motive
        os.makedirs(MOTIV_DIR, exist_ok=True)
        name = motiv.split(":", 1)[1]
        path = os.path.join(MOTIV_DIR, "icon_%s.png" % name)
        return path if os.path.exists(path) else countdown_motive.render_icon(name, path)
    motiv = motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"
    os.makedirs(MOTIV_DIR, exist_ok=True)
    # Szene-Motive bekommen einen eigenen Cache-Schluessel (Praefix 'szene:'), damit alte,
    # freigestellte Personen-/Themenbilder im Cache nicht mit den neuen Szenen kollidieren.
    h = hashlib.sha256(("szene:" + motiv).lower().encode("utf-8")).hexdigest()[:16]
    path = os.path.join(MOTIV_DIR, h + ".png")
    if os.path.exists(path):
        return path
    prompt = _prompt(motiv)
    key = get_secret("openai_api_key")
    if not key:
        log.info("Bildmotiv uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    try:
        import requests
        # Bildqualitaet steuert die OpenAI-Kosten stark: low (~1-2ct) < medium (~4-6ct) < high (~20-25ct)
        # je 1024x1024-Bild. Default 'medium' (guter Kompromiss); per Umgebungsvariable aenderbar.
        quality = (os.environ.get("HILO_IMAGE_QUALITY") or "medium").strip().lower()
        if quality not in ("low", "medium", "high", "auto"):
            quality = "medium"
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024",
                  "quality": quality, "background": "opaque", "output_format": "png", "n": 1},
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
