# -*- coding: utf-8 -*-
"""Erzeugt situative, freigestellte Fotomotive via OpenAI gpt-image-1 (transparenter Hintergrund).
Caching pro Motiv. Ohne openai_api_key wird None geliefert (Bild dann ohne Foto)."""
import base64, hashlib, logging, os
from secrets_store import get_secret
from config import DATA_DIR

log = logging.getLogger("hilo.bildmotiv")
MOTIV_DIR = os.path.join(DATA_DIR, "motive")

def _prompt(motiv):
    return ("Sauber freigestelltes Foto als PNG mit ECHTEM transparentem Hintergrund (Alphakanal). "
            "ABSOLUT KEIN Hintergrund, KEIN Raum, KEIN Tisch, KEIN Schreibtisch, KEIN Boden, KEINE Wand, "
            "KEINE Moebel - nur die Personen frei vor Transparenz, wie ein sauberer Scherenschnitt. "
            "Motiv: %s. Warme, hochwertige Werbefotografie - freundliche, laechelnde Menschen (zwei "
            "Personen, hoechstens drei), KOMPAKT und nah beieinander, in zugewandter Interaktion (kein "
            "nachdenklicher Ausdruck, kein Einzelportrait). Requisiten NUR in der Hand gehalten (kein "
            "Tisch): eine Mappe oder Unterlagen und eine Kaffeetasse, die deutlich den Schriftzug 'HILO' "
            "traegt - sauber mitfreigestellt. Aus der Gruppe ist IMMER eine Person deutlich als "
            "HILO-Beraterin oder HILO-Berater erkennbar: Diese Person traegt IMMER eine weisse Bluse oder "
            "ein weisses Hemd mit gut sichtbarem HILO-Schriftzug am Kragen oder auf der Brusttasche. "
            "Die Personen FUELLEN das Hochformat vertikal VOLLSTAENDIG aus: "
            "Koepfe reichen bis knapp unter den oberen Rand, Huefte/Oberschenkel bis zum unteren Rand. "
            "KEIN Leerraum ueber den Koepfen oder unter der Huefte. Enger Bildausschnitt wie ein "
            "Zeitschriften-Cover-Crop. WICHTIG: Koepfe NICHT anschneiden und links und rechts etwas Rand "
            "lassen, sodass niemand am linken oder rechten Rand abgeschnitten wird. "
            "Ausser dem 'HILO' auf der Tasse und dem HILO-Logo an der Kleidung KEINE weiteren "
            "Texte, Logos oder Markennamen." % motiv)

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
        # Bildqualitaet steuert die OpenAI-Kosten stark: low (~1-2ct) < medium (~4-6ct) < high (~20-25ct)
        # je 1024x1536-Bild. Default 'medium' (guter Kompromiss); per Umgebungsvariable aenderbar.
        quality = (os.environ.get("HILO_IMAGE_QUALITY") or "medium").strip().lower()
        if quality not in ("low", "medium", "high", "auto"):
            quality = "medium"
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": _prompt(motiv), "size": "1024x1536",
                  "quality": quality, "background": "transparent", "output_format": "png", "n": 1},
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
