# -*- coding: utf-8 -*-
"""Erzeugt situative, freigestellte Fotomotive via OpenAI gpt-image-1 (transparenter Hintergrund).
Caching pro Motiv. Ohne openai_api_key wird None geliefert (Bild dann ohne Foto)."""
import base64, hashlib, logging, os, re
from secrets_store import get_secret
from config import DATA_DIR

log = logging.getLogger("hilo.bildmotiv")
MOTIV_DIR = os.path.join(DATA_DIR, "motive")

def _prompt(motiv, geschlecht="frau"):
    # Geschlecht der HILO-Beratungsperson deterministisch vorgeben (Abwechslung Beraterin/Berater).
    # Einen evtl. im Motivtext genannten 'Beraterin/Berater' neutralisieren, damit kein Widerspruch
    # zur vorgegebenen Person entsteht.
    motiv = re.sub(r"\bBeraterin(?:nen)?\b", "Beratungsperson", motiv, flags=re.IGNORECASE)
    motiv = re.sub(r"\bBerater(?:s|n)?\b", "Beratungsperson", motiv, flags=re.IGNORECASE)
    if geschlecht == "mann":
        person, kleidung = "ein Mann", "ein weisses Hemd"
    else:
        person, kleidung = "eine Frau", "eine weisse Bluse"
    return ("Sauber freigestelltes Foto als PNG mit ECHTEM transparentem Hintergrund (Alphakanal). "
            "ABSOLUT KEIN Hintergrund, KEIN Raum, KEIN Tisch, KEIN Schreibtisch, KEIN Boden, KEINE Wand, "
            "KEINE Moebel - nur die Personen frei vor Transparenz, wie ein sauberer Scherenschnitt. "
            "Motiv: %s. Warme, AUTHENTISCHE Reportage-Fotografie eines ECHTEN Beratungsgespraechs: eine "
            "HILO-Beratungsperson und ein Kunde oder eine Kundin (zwei Personen, hoechstens drei), KOMPAKT "
            "und nah beieinander, schauen gemeinsam auf Unterlagen oder einen Laptop - natuerliche, "
            "lebendige Interaktion und echte, ungestellte Mimik. KEIN gestelltes Stockfoto, KEINE steifen "
            "Posen, NIEMAND laechelt gekuenstelt direkt in die Kamera; der Blick gilt einander oder den "
            "Unterlagen. Requisiten NUR in der Hand oder auf dem Schoss gehalten (KEIN Tisch, KEIN Raum): "
            "eine Mappe/Unterlagen oder ein Laptop und eine Kaffeetasse, die deutlich den blauen Schriftzug "
            "'HILO' traegt - sauber mitfreigestellt. Aus der Gruppe ist IMMER eine Person deutlich als "
            "HILO-Beratungsperson erkennbar: Diese Person ist %s und traegt IMMER %s mit gut sichtbarem "
            "BLAUEM HILO-Schriftzug am Kragen oder auf der Brusttasche. "
            "Die Personen werden FORMATFUELLEND dargestellt und FUELLEN das Hochformat vertikal VOLLSTAENDIG aus: "
            "Koepfe reichen bis knapp unter den oberen Rand, Huefte/Oberschenkel bis zum unteren Rand. "
            "KEIN Leerraum ueber den Koepfen oder unter der Huefte. Enger Bildausschnitt wie ein "
            "Zeitschriften-Cover-Crop. WICHTIG: Koepfe NICHT anschneiden und links und rechts etwas Rand "
            "lassen, sodass niemand am linken oder rechten Rand abgeschnitten wird. "
            "Ausser dem 'HILO' auf der Tasse und dem HILO-Logo an der Kleidung KEINE weiteren "
            "Texte, Logos oder Markennamen." % (motiv, person, kleidung))

def _prompt_thema(motiv):
    """Gegenstaendliches Themenbild OHNE Personen - freigestellt vor transparentem Hintergrund,
    gleiche Bildlogik wie die Personenszene (wird im Layout rechts platziert)."""
    return ("Sauber freigestelltes Foto als PNG mit ECHTEM transparentem Hintergrund (Alphakanal). "
            "ABSOLUT KEIN Hintergrund, KEIN Raum, KEINE Wand, KEIN Boden - nur das Motiv frei vor "
            "Transparenz, wie ein sauberer Scherenschnitt. Motiv: %s. KEINE Menschen, keine Gesichter, "
            "keine Koerperteile - nur die Gegenstaende. Warme, hochwertige Werbefotografie, freundliche "
            "Farben, klar erkennbare, einzeln stehende Gegenstaende, KOMPAKT gruppiert. Die Gegenstaende "
            "FUELLEN das Hochformat moeglichst aus und werden NICHT an den Raendern abgeschnitten. KEIN "
            "Text, KEINE Logos, KEINE Markennamen." % motiv)

def ensure_photo_fuer(fields):
    """Waehlt anhand von fields['bild_typ'] das passende Motiv: 'thema' nutzt das gegenstaendliche
    bild_motiv_thema (ohne Personen), sonst die Personenszene bild_motiv. Fallback: Personenszene."""
    typ = (fields.get("bild_typ") or "person").strip().lower()
    thema_motiv = (fields.get("bild_motiv_thema") or "").strip()
    if typ == "thema" and thema_motiv:
        return ensure_photo(thema_motiv, "thema")
    return ensure_photo(fields.get("bild_motiv"), "person")

def ensure_photo(motiv, typ="person"):
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
    # Themen-Motive bekommen einen eigenen Cache-Schluessel (Praefix), damit die bestehenden
    # Personen-Bilder (ohne Praefix) im Cache unveraendert bleiben.
    key_src = ("thema:" + motiv) if typ == "thema" else motiv
    h = hashlib.sha256(key_src.lower().encode("utf-8")).hexdigest()[:16]
    path = os.path.join(MOTIV_DIR, h + ".png")
    if os.path.exists(path):
        return path
    # Geschlecht der HILO-Beratungsperson deterministisch aus dem Motiv-Hash (Abwechslung Frau/Mann);
    # gleiches Motiv -> gleiches Bild (cache-stabil), ueber viele Motive ~halbe/halbe.
    geschlecht = "mann" if int(h, 16) % 2 == 0 else "frau"
    prompt = _prompt_thema(motiv) if typ == "thema" else _prompt(motiv, geschlecht)
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
            json={"model": "gpt-image-1", "prompt": prompt, "size": "1024x1536",
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
