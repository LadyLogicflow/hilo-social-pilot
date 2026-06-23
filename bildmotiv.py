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
    Ein ruhiger Bereich bleibt frei fuer das spaeter daraufgesetzte weisse Textfeld.
    Die Szene ist bewusst als RAHMEN komponiert: bildwichtige Elemente liegen an den
    Raendern und umrahmen eine ruhige, weitgehend leere BILDMITTE (zentraler Negativraum),
    in die spaeter das Textfeld gesetzt wird - so wird kein Hauptmotiv vom Text verdeckt."""
    return ("Hochwertige, emotionale Magazin-/Editorial-Fotografie. Eine stimmungsvolle, "
            "authentische Szene, die %s vermittelt - Jahreszeit, Gefuehl und ein dezenter Bezug zum "
            "Thema, schoen und natuerlich gestylt (KEIN steifes Stockfoto, keine steifen Posen). "
            "Warmes, weiches Tageslicht, geringe Schaerfentiefe, harmonische warme Farben. Die Szene "
            "fuellt das ganze Bild als Hintergrund. WICHTIG fuer die Komposition: Das Bild ist wie ein "
            "RAHMEN aufgebaut - alle bildwichtigen Elemente (Personen, Gegenstaende, Deko, Glaeser usw.) "
            "liegen am OBEREN, UNTEREN und an den SEITLICHEN Raendern und UMRAHMEN die Bildmitte. Die "
            "BILDMITTE bleibt bewusst ruhig und weitgehend LEER (grosser zentraler Negativraum, weiche "
            "Flaeche / unscharfer Hintergrund / Tischflaeche) und enthaelt KEIN Hauptmotiv und kein "
            "zentrales Subjekt - dieser ruhige zentrale Bereich bleibt frei fuer ein spaeteres Textfeld, "
            "nichts Bildwichtiges darf dort verdeckt werden. KEIN Text, keine Schrift, keine Logos oder "
            "Markennamen im Bild." % motiv)

def _tafel_prompt(scene, sign_text):
    """KI-Tafel-Prompt (#132): die Bild-KI schreibt die Ueberschrift selbst auf eine Tafel/Plakat
    in der Szene. EXAKTER Wortlaut aus dem Issue, echte deutsche Umlaute. {scene} = Szene-Motiv,
    sign_text = die Ueberschrift (in Anfuehrungszeichen eingesetzt). Die Tafel traegt NUR diese
    Ueberschrift - sie ist die einzige Schrift im Bild (CTA + CI-Kreise kommen per Code-Overlay)."""
    return ("Hochwertige, emotionale Magazin-/Editorial-Fotografie, quadratisch (1:1). Warme, "
            "authentische Szene passend zu: %s. ZENTRALES, SCHARFES Hauptmotiv: eine gut lesbare "
            "TAFEL (Kreidetafel ODER schlichtes Holzschild/Plakat), natürlich in die Szene gestellt, "
            "FRONTAL zur Kamera, gut ausgeleuchtet. Auf der Tafel steht der folgende deutsche Text - "
            "exakt Wort für Wort, KORREKT geschrieben mit richtigen deutschen Umlauten (ae oe ue als "
            "ä ö ü, ß), groß, zentriert, in sauberer, gut lesbarer Schrift, OHNE Rechtschreibfehler, "
            "OHNE zusätzliche, fehlende oder veränderte Buchstaben: '%s'. Dieser Text ist die EINZIGE "
            "Schrift im gesamten Bild. KEINE weiteren Wörter, Buchstaben, Zahlen, Logos oder "
            "Wasserzeichen irgendwo sonst. Warmes, weiches Tageslicht, geringe Schärfentiefe, "
            "harmonische warme Farben. Die Tafel ist der klare Blickfang, die Szene ringsum trägt "
            "die Stimmung." % (scene, sign_text))

def ensure_photo_fuer(fields):
    """Liefert das Szene-Foto fuer den Beitrag. Bevorzugt das neue Feld 'szene_motiv'
    (emotionale Szene mit Umgebung); faellt fuer aeltere Entwuerfe auf 'bild_motiv' bzw.
    'bild_motiv_thema' zurueck, damit bestehende Entwuerfe weiter rendern.
    'icon:'-Motive (gezeichnet) bleiben unveraendert.

    Bild-Stil 'ki_tafel' (#132, Testmodus): die KI schreibt die Ueberschrift selbst auf eine Tafel
    in der Szene. Der Modus wird global aus der Einstellung gelesen (db.get_einstellung('bild_stil')).
    Default 'standard' -> unveraendertes v11-Verhalten."""
    import db
    stil = (db.get_einstellung("bild_stil", "standard") or "standard").strip()
    motiv = (fields.get("szene_motiv") or fields.get("bild_motiv")
             or fields.get("bild_motiv_thema") or "").strip()
    # 'icon:'-Motive bleiben in jedem Stil gezeichnet (kein OpenAI, keine Tafel).
    if stil == "ki_tafel" and not motiv.startswith("icon:"):
        sign_text = (fields.get("ueberschrift") or "").strip()
        scene = motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"
        return ensure_photo_tafel(scene, sign_text)
    return ensure_photo(motiv)

def tafel_cache_key(scene, sign_text):
    """Liefert den Cache-Schluessel-String fuer ein KI-Tafel-Foto (Praefix 'tafel:', enthaelt den
    sign_text). Ausgelagert, damit Tests den Schluessel pruefen koennen, ohne OpenAI aufzurufen."""
    return "tafel:" + (sign_text or "").strip() + "|" + (scene or "").strip()

def tafel_payload(scene, sign_text):
    """Baut das OpenAI-Request-Payload fuer ein KI-Tafel-Foto (ohne Netzwerkaufruf). Ausgelagert,
    damit Tests Prompt + Parameter (background='opaque', size '1024x1024') pruefen koennen."""
    quality = (os.environ.get("HILO_IMAGE_QUALITY") or "medium").strip().lower()
    if quality not in ("low", "medium", "high", "auto"):
        quality = "medium"
    return {"model": "gpt-image-1", "prompt": _tafel_prompt(scene, sign_text), "size": "1024x1024",
            "quality": quality, "background": "opaque", "output_format": "png", "n": 1}

def ensure_photo_tafel(scene, sign_text):
    """Erzeugt (oder liefert aus dem Cache) das KI-Tafel-Foto (#132): scene = Szene-Motiv,
    sign_text = die Ueberschrift, die die KI auf die Tafel schreibt. Eigener Cache-Schluessel
    (Praefix 'tafel:'), der den sign_text ENTHAELT - so bekommt jede Ueberschrift ihr eigenes Foto.
    background='opaque', size '1024x1024'. Ohne openai_api_key wird None geliefert (Creme-Fallback)."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    sign_text = (sign_text or "").strip()
    os.makedirs(MOTIV_DIR, exist_ok=True)
    h = hashlib.sha256(tafel_cache_key(scene, sign_text).lower().encode("utf-8")).hexdigest()[:16]
    path = os.path.join(MOTIV_DIR, "tafel_" + h + ".png")
    if os.path.exists(path):
        return path
    key = get_secret("openai_api_key")
    if not key:
        log.info("KI-Tafel-Foto uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    try:
        import requests
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json=tafel_payload(scene, sign_text),
            timeout=120)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        log.info("KI-Tafel-Foto erzeugt: %s", sign_text[:50])
        return path
    except Exception as ex:
        log.warning("KI-Tafel-Foto fehlgeschlagen (%s): %s", sign_text[:40], ex)
        return None

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
