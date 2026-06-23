# -*- coding: utf-8 -*-
"""Erzeugt stimmungsvolle, vollflaechige Magazin-/Editorial-Fotos (opakes Foto MIT Umgebung,
als Hintergrund fuer das neue Bild-Layout).

Das BACKEND (welche KI das Foto erzeugt) ist umschaltbar (#137), orthogonal zum Bild-STIL
(standard/ki_tafel). Einstellung 'bild_tool':
  - 'openai'   (Default): OpenAI images/generations, Modell aus HILO_OPENAI_IMAGE_MODEL
                          (Default 'gpt-image-2'). Braucht 'openai_api_key'.
  - 'ideogram': Ideogram v4 (Text-Spezialist, bessere Schrift im Bild). Braucht
                'ideogram_api_key'. KEIN stiller Fallback auf OpenAI bei fehlendem Key.
Der Prompt-Bau (Szene/Tafel je bild_stil) bleibt UNVERAENDERT; nur die Erzeugung wird je
bild_tool an den passenden Anbieter geroutet (erzeuge_bild).

Caching pro Motiv UND Tool: OpenAI- und Ideogram-Bilder fuer dasselbe Motiv kollidieren NICHT
(Ideogram-Dateien tragen den Praefix 'ideogram_'). Der Modell-Bump gpt-image-1 -> gpt-image-2
braucht KEINEN Cache-Key-Wechsel (bestehende 'openai'-Cache-Dateien bleiben gueltig).
Ohne passenden API-Key wird None geliefert (Bild dann ohne Foto -> warmer Fallback)."""
import base64, hashlib, logging, os
from secrets_store import get_secret
from config import DATA_DIR

log = logging.getLogger("hilo.bildmotiv")
MOTIV_DIR = os.path.join(DATA_DIR, "motive")

# Default-Bildmodell fuer den OpenAI-Pfad (#137 Ergaenzung: Bump gpt-image-1 -> gpt-image-2).
# Per Umgebungsvariable HILO_OPENAI_IMAGE_MODEL ohne Code-Aenderung ueberschreibbar, falls der
# exakte images/generations-Modellname beim OpenAI-API abweicht.
OPENAI_IMAGE_MODEL_DEFAULT = "gpt-image-2"
# Ideogram v4 Generate-Endpoint (Text-Spezialist). Quadratisches Format per Default; per
# Umgebungsvariable HILO_IDEOGRAM_RESOLUTION ueberschreibbar, falls der Enum-Name abweicht.
IDEOGRAM_URL = "https://api.ideogram.ai/v1/ideogram-v4/generate"
IDEOGRAM_RESOLUTION_DEFAULT = "1024x1024"
IDEOGRAM_RENDERING_SPEED_DEFAULT = "DEFAULT"


def aktives_bild_tool():
    """Liefert das aktuell eingestellte Bild-Tool ('openai' Default | 'ideogram').
    Liest db.get_einstellung('bild_tool'); unbekannte Werte fallen auf 'openai' zurueck.
    Kapselt den DB-Zugriff, damit Routing und Cache-Pfade dieselbe Quelle nutzen."""
    import db
    tool = (db.get_einstellung("bild_tool", "openai") or "openai").strip().lower()
    return tool if tool in ("openai", "ideogram") else "openai"


def openai_image_model():
    """Liefert den OpenAI-Bildmodell-Namen aus HILO_OPENAI_IMAGE_MODEL (Default 'gpt-image-2')."""
    return (os.environ.get("HILO_OPENAI_IMAGE_MODEL") or OPENAI_IMAGE_MODEL_DEFAULT).strip()

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
            "Eine spontane, ungestellte, lebendige Alltagsszene (candid), natuerliche Bewegung und "
            "Interaktion, wie ein echter, nicht gestellter Schnappschuss - niemand posiert steif in "
            "die Kamera. Falls ein Schild oder ein Plakat in der Szene vorkommt, ist es "
            "NATUERLICH in die Szene integriert (steht auf einem Tisch, lehnt an einer Wand, steht "
            "auf einer Staffelei oder ist angelehnt) und wird NICHT von einer Person frontal in die "
            "Kamera GEHALTEN. "
            "Natuerliche, ausgewogene, realitaetsnahe Farben bei neutralem Tageslicht; NICHT "
            "uebertrieben warm, golden oder amber - normale, neutrale Farbtemperatur. Die STIMMUNG "
            "ist zum Thema passend: grundsaetzlich froh, entspannt, erleichtert und positiv "
            "(laechelnd, geloest); KEINE traurigen, gestressten, sorgenvollen oder depressiven "
            "Gesichter. ABER themenangemessen - bei ERNSTEN oder Warn-Themen ruhige ZUVERSICHT, "
            "Erleichterung und Souveraenitaet statt froehlichem Grinsen oder Feiern, das dem Ernst "
            "des Themas widerspricht; bei freudigen Themen darf es froehlich und feiernd sein. Also "
            "positiv UND zum Thema passend, nicht pauschal Party - auch bei "
            "Problem-Themen wird die Erleichterung und Loesung gezeigt, nicht die Sorge. Weiches "
            "Tageslicht, geringe Schaerfentiefe. Die Szene "
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
    Ueberschrift - sie ist die einzige Schrift im Bild (CTA + CI-Kreise kommen per Code-Overlay).

    HINWEIS (#135): Schriftart (serifenlos/Arial-aehnlich) und Textfarbe (HILO-Dunkelblau) auf
    dem KI-Bild sind NICHT 100% erzwingbar - die Bild-KI approximiert beides; das Ergebnis wird
    nach dem Render geprueft. Wir formulieren den Wunsch dennoch moeglichst praezise."""
    return ("Hochwertige, emotionale Magazin-/Editorial-Fotografie, quadratisch (1:1). "
            "Authentische Szene passend zu: %s. Natuerliche, ausgewogene, realitaetsnahe Farben "
            "bei neutralem Tageslicht; NICHT uebertrieben warm, golden oder amber - normale, "
            "neutrale Farbtemperatur. STIMMUNG zum Thema passend: grundsaetzlich froh, positiv und "
            "geloest, KEINE traurigen, gestressten, sorgenvollen oder depressiven Gesichter. ABER themen"
            "angemessen - bei ERNSTEN oder Warn-Themen (z.B. verpasste Frist, Kosten, Zuschlag) "
            "ruhige ZUVERSICHT, Erleichterung und Souveraenitaet ausstrahlen (man fuehlt sich gut "
            "aufgehoben und beraten), KEIN froehliches Grinsen oder Feiern, das dem Ernst des Themas "
            "widerspricht; bei freudigen Themen darf die Stimmung froehlich und feiernd sein. Also "
            "positiv UND zum Thema passend, nicht pauschal Party. ZENTRALES, SCHARFES Hauptmotiv: ein "
            "gut lesbares, eher HELLES Schild/Plakat/Tafel (helles Schild oder Plakat statt schwarzer "
            "Kreidetafel). Das Schild/die Tafel ist NATUERLICH in die Szene integriert - es steht auf "
            "einem Tisch, lehnt an einer Wand, steht auf einer Staffelei oder ist angelehnt - und wird "
            "NICHT von einer Person frontal in die Kamera GEHALTEN, niemand haelt es hoch. KEINE "
            "gestellten Stockfoto-Posen, niemand posiert oder blickt steif in die Kamera. Stattdessen "
            "eine spontane, ungestellte, lebendige Alltagsszene (candid), natuerliche Bewegung und "
            "Interaktion, wie ein echter, nicht gestellter Schnappschuss. Das Schild bleibt dabei gut "
            "sichtbar und lesbar (frontal genug zur Kamera, scharf, gut ausgeleuchtet) - nur eben als "
            "Teil der Szene, nicht als gehaltenes Plakat. Auf dem hellen Schild steht der "
            "folgende deutsche Text - exakt Wort für Wort, KORREKT geschrieben mit richtigen "
            "deutschen Umlauten (ae oe ue als ä ö ü, ß), groß, zentriert, in HILO-Dunkelblau und in "
            "einer klaren, modernen SERIFENLOSEN Schrift (Arial-aehnlich, ohne Serifen), perfekt "
            "lesbar, OHNE Rechtschreibfehler, OHNE zusätzliche, fehlende oder veränderte Buchstaben: "
            "'%s'. Dieser Text ist die EINZIGE Schrift im gesamten Bild. KEINE weiteren Wörter, "
            "Buchstaben, Zahlen, Logos oder Wasserzeichen irgendwo sonst. Weiches, neutrales "
            "Tageslicht, geringe Schärfentiefe. Das helle Schild ist der klare Blickfang, die Szene "
            "ringsum trägt die zum Thema passende, geloeste Stimmung." % (scene, sign_text))

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

def _tool_praefix(tool):
    """Liefert den Datei-Praefix fuer ein Bild-Tool. OpenAI traegt KEINEN Praefix (bestehende
    Cache-Dateien bleiben gueltig); Ideogram traegt 'ideogram_', damit beide Anbieter fuer
    dasselbe Motiv getrennte Dateien bekommen (Catrin will vergleichen, #137)."""
    return "ideogram_" if (tool or "openai") == "ideogram" else ""


def _szene_pfad(motiv, tool=None):
    """Liefert den absoluten Cache-Pfad fuer das Standard-Szene-Foto zu 'motiv'.
    Kapselt die BESTEHENDE Schluessel-Berechnung (Praefix 'szene:', sha256[:16]) aus
    ensure_photo(), damit sie wiederverwendbar ist. Die Hash-Formel bleibt UNVERAENDERT -
    sonst wuerden bestehende Cache-Dateien nicht mehr getroffen. Liefert None fuer leere
    Motive und fuer 'icon:'-Motive (die liefert _icon_pfad).

    'tool' waehlt das Bild-Backend (#137): 'openai' (Default, KEIN Praefix -> bestehende
    Dateinamen unveraendert) oder 'ideogram' (Praefix 'ideogram_'). None -> aktuelle
    Einstellung (aktives_bild_tool())."""
    motiv = (motiv or "").strip()
    if not motiv or motiv.startswith("icon:"):
        return None
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(("szene:" + motiv).lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(MOTIV_DIR, _tool_praefix(tool) + h + ".png")

def _icon_pfad(motiv):
    """Liefert den absoluten Cache-Pfad fuer ein gezeichnetes 'icon:'-Motiv (Praefix 'icon_'),
    sonst None. Spiegelt die Pfadbildung aus ensure_photo()."""
    motiv = (motiv or "").strip()
    if not motiv.startswith("icon:"):
        return None
    name = motiv.split(":", 1)[1]
    return os.path.join(MOTIV_DIR, "icon_%s.png" % name)

def tafel_cache_key(scene, sign_text):
    """Liefert den Cache-Schluessel-String fuer ein KI-Tafel-Foto (Praefix 'tafel:', enthaelt den
    sign_text). Ausgelagert, damit Tests den Schluessel pruefen koennen, ohne OpenAI aufzurufen."""
    return "tafel:" + (sign_text or "").strip() + "|" + (scene or "").strip()

def _tafel_pfad(scene, sign_text, tool=None):
    """Liefert den absoluten Cache-Pfad fuer ein KI-Tafel-Foto (Praefix 'tafel_', sha256[:16]).
    Kapselt die BESTEHENDE Schluessel-Berechnung aus ensure_photo_tafel(); Hash-Formel UNVERAENDERT.
    Verwendet dieselbe scene-Default-Logik wie ensure_photo_tafel/ensure_photo_fuer.

    'tool' waehlt das Bild-Backend (#137): 'openai' (Default, Dateiname unveraendert 'tafel_<h>')
    oder 'ideogram' (Praefix 'ideogram_tafel_<h>'). None -> aktuelle Einstellung."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    sign_text = (sign_text or "").strip()
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(tafel_cache_key(scene, sign_text).lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(MOTIV_DIR, _tool_praefix(tool) + "tafel_" + h + ".png")

def cache_dateien_fuer_fields(fields):
    """Liefert ein set() ALLER absoluten Cache-Dateipfade unter MOTIV_DIR, die ein Beitrag mit
    diesen 'fields' (Entwurfs-JSON-dict) nutzen KOENNTE - ueber BEIDE Stil-Varianten hinweg
    (Standard-Szene UND KI-Tafel). So bleiben beim Aufraeumen beide Varianten geschuetzt,
    unabhaengig vom aktuell eingestellten Bild-Stil.

    Beruecksichtigt - analog ensure_photo_fuer() - die Motiv-Fallback-Kette
    szene_motiv -> bild_motiv -> bild_motiv_thema sowie den ki_tafel-Fall
    (sign_text = ueberschrift). Gezeichnete 'icon:'-Motive werden mit aufgenommen, damit
    auch deren Pfad als 'in Benutzung' gilt (geloescht werden icon_-Dateien ohnehin nie).

    Robust: fehlerhafte/nicht-dict fields liefern ein leeres set, ohne zu crashen."""
    pfade = set()
    if not isinstance(fields, dict):
        return pfade
    motiv = (fields.get("szene_motiv") or fields.get("bild_motiv")
             or fields.get("bild_motiv_thema") or "").strip()
    if motiv.startswith("icon:"):
        ip = _icon_pfad(motiv)
        if ip:
            pfade.add(ip)
        return pfade
    # WICHTIG (#137-Retention): BEIDE Bild-Tools (openai + ideogram) werden als 'in Benutzung'
    # aufgenommen. Da der Cache tool-abhaengige Dateinamen vergibt (ideogram_-Praefix), wuerde
    # die Aufraeumung (#134) sonst das jeweils ANDERE Tool faelschlich loeschen, sobald Catrin
    # umschaltet. Wir nehmen darum fuer jeden Motiv-Pfad beide Tool-Varianten auf.
    sign_text = (fields.get("ueberschrift") or "").strip()
    scene = motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"
    for tool in ("openai", "ideogram"):
        # Standard-Szene-Variante (jedes Motiv aus der Fallback-Kette kann den Cache-Treffer liefern).
        for m in (fields.get("szene_motiv"), fields.get("bild_motiv"), fields.get("bild_motiv_thema")):
            sp = _szene_pfad(m, tool=tool)
            if sp:
                pfade.add(sp)
        # KI-Tafel-Variante: scene = dasselbe Motiv (mit Default), sign_text = Ueberschrift.
        # Bei LEEREM Motiv wendet ensure_photo/ensure_photo_fuer denselben Default auf die
        # Standard-Szene an (ensure_photo: motiv = motiv or "..."). _szene_pfad(None) liefert hier
        # aber None, sodass die Default-Szene-Datei sonst NICHT als 'in Benutzung' gilt und nach
        # der Schonfrist faelschlich geloescht wuerde, obwohl ein aktiver/Pool-Entwurf sie nutzt
        # (ARGUS-Blocker #134). Darum den Default-Szene-Pfad mit aufnehmen - exakt derselbe
        # Default-String -> exakt derselbe Hash/Dateiname. Normale Entwuerfe (mit Motiv) bekommen
        # keinen zusaetzlichen Pfad, da scene dann = motiv ist und _szene_pfad(motiv) oben schon drin.
        sp_def = _szene_pfad(scene, tool=tool)
        if sp_def:
            pfade.add(sp_def)
        pfade.add(_tafel_pfad(scene, sign_text, tool=tool))
    return pfade

def _openai_quality():
    """Liefert die OpenAI-Bildqualitaet aus HILO_IMAGE_QUALITY (Default 'medium', validiert)."""
    quality = (os.environ.get("HILO_IMAGE_QUALITY") or "medium").strip().lower()
    return quality if quality in ("low", "medium", "high", "auto") else "medium"


def openai_payload(prompt):
    """Baut das OpenAI images/generations-Request-Payload (ohne Netzwerkaufruf). Modell aus
    HILO_OPENAI_IMAGE_MODEL (Default 'gpt-image-2'), background='opaque', size '1024x1024',
    quality aus HILO_IMAGE_QUALITY. Ausgelagert, damit Tests Modell/Parameter ohne Netz pruefen."""
    return {"model": openai_image_model(), "prompt": prompt, "size": "1024x1024",
            "quality": _openai_quality(), "background": "opaque", "output_format": "png", "n": 1}


def ideogram_payload(prompt):
    """Baut das Ideogram-v4-Request-Payload (ohne Netzwerkaufruf). 'text_prompt' = unser Prompt,
    quadratisches Format (resolution aus HILO_IDEOGRAM_RESOLUTION, Default '1024x1024') und
    rendering_speed aus HILO_IDEOGRAM_RENDERING_SPEED (Default 'DEFAULT'). Beide per ENV
    ueberschreibbar, falls der Enum-Name in der Ideogram-Doku abweicht. Ausgelagert, damit Tests
    URL/Body-Struktur ohne Netz pruefen koennen."""
    resolution = (os.environ.get("HILO_IDEOGRAM_RESOLUTION") or IDEOGRAM_RESOLUTION_DEFAULT).strip()
    speed = (os.environ.get("HILO_IDEOGRAM_RENDERING_SPEED") or IDEOGRAM_RENDERING_SPEED_DEFAULT).strip()
    return {"text_prompt": prompt, "resolution": resolution, "rendering_speed": speed}


def erzeuge_bild_openai(prompt):
    """Erzeugt ein Bild via OpenAI images/generations und liefert die PNG-Bytes (oder None).
    Ohne 'openai_api_key' -> None + Log (kein Crash). Robust gegen Netz-/API-Fehler."""
    key = get_secret("openai_api_key")
    if not key:
        log.info("Bild uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    try:
        import requests
        # Bildqualitaet steuert die OpenAI-Kosten stark: low (~1-2ct) < medium (~4-6ct) < high
        # (~20-25ct) je 1024x1024-Bild. Default 'medium'; per Umgebungsvariable aenderbar.
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json=openai_payload(prompt),
            timeout=120)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)
    except Exception as ex:
        log.warning("OpenAI-Bild fehlgeschlagen: %s", ex)
        return None


def erzeuge_bild_ideogram(prompt):
    """Erzeugt ein Bild via Ideogram v4 (Text-Spezialist) und liefert die PNG-Bytes (oder None).
    POST IDEOGRAM_URL mit Header 'Api-Key' + JSON-Body (text_prompt, quadratisches Format). Die
    Antwort liefert eine Bild-URL (data[0].url), die hier heruntergeladen wird. Ohne
    'ideogram_api_key' -> None + Log (KEIN stiller Fallback auf OpenAI). Robust gegen Fehler/Timeout."""
    key = get_secret("ideogram_api_key")
    if not key:
        log.info("Ideogram-Bild uebersprungen: kein 'ideogram_api_key' hinterlegt (secrets.json).")
        return None
    try:
        import requests
        r = requests.post(
            IDEOGRAM_URL,
            headers={"Api-Key": key, "Content-Type": "application/json"},
            json=ideogram_payload(prompt),
            timeout=120)
        r.raise_for_status()
        url = r.json()["data"][0]["url"]
        img = requests.get(url, timeout=120)
        img.raise_for_status()
        return img.content
    except Exception as ex:
        log.warning("Ideogram-Bild fehlgeschlagen: %s", ex)
        return None


def erzeuge_bild(prompt, tool=None):
    """Routet die Bild-Erzeugung je Bild-Tool (#137) an den richtigen Anbieter und liefert die
    PNG-Bytes (oder None). 'tool' None -> aktuelle Einstellung (aktives_bild_tool()):
    'openai' (Default, gpt-image-2) oder 'ideogram' (Text-Spezialist). Der Prompt-Bau bleibt
    unveraendert; hier wird NUR die Erzeugung umgeschaltet."""
    if tool is None:
        tool = aktives_bild_tool()
    if tool == "ideogram":
        return erzeuge_bild_ideogram(prompt)
    return erzeuge_bild_openai(prompt)


def tafel_payload(scene, sign_text):
    """Baut das OpenAI images/generations-Request-Payload fuer ein KI-Tafel-Foto (ohne
    Netzwerkaufruf). Modell aus HILO_OPENAI_IMAGE_MODEL (Default 'gpt-image-2'), background='opaque',
    size '1024x1024'. Ausgelagert, damit Tests Prompt + Parameter pruefen koennen."""
    return openai_payload(_tafel_prompt(scene, sign_text))

def ensure_photo_tafel(scene, sign_text):
    """Erzeugt (oder liefert aus dem Cache) das KI-Tafel-Foto (#132): scene = Szene-Motiv,
    sign_text = die Ueberschrift, die die KI auf die Tafel schreibt. Eigener Cache-Schluessel
    (Praefix 'tafel:'), der den sign_text ENTHAELT - so bekommt jede Ueberschrift ihr eigenes Foto.
    background='opaque', size '1024x1024'. Ohne openai_api_key wird None geliefert (Creme-Fallback)."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    sign_text = (sign_text or "").strip()
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    # Cache-Pfad ist tool-abhaengig (#137): OpenAI- und Ideogram-Tafel kollidieren NICHT.
    path = _tafel_pfad(scene, sign_text, tool=tool)
    if os.path.exists(path):
        return path
    daten = erzeuge_bild(_tafel_prompt(scene, sign_text), tool=tool)
    if daten is None:
        return None
    try:
        with open(path, "wb") as f:
            f.write(daten)
        log.info("KI-Tafel-Foto erzeugt (%s): %s", tool, sign_text[:50])
        return path
    except Exception as ex:
        log.warning("KI-Tafel-Foto speichern fehlgeschlagen (%s): %s", sign_text[:40], ex)
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
        path = _icon_pfad(motiv)
        return path if os.path.exists(path) else countdown_motive.render_icon(name, path)
    motiv = motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    # Szene-Motive bekommen einen eigenen Cache-Schluessel (Praefix 'szene:'), damit alte,
    # freigestellte Personen-/Themenbilder im Cache nicht mit den neuen Szenen kollidieren.
    # Der Pfad ist zusaetzlich tool-abhaengig (#137): OpenAI vs. Ideogram kollidieren NICHT.
    path = _szene_pfad(motiv, tool=tool)
    if os.path.exists(path):
        return path
    daten = erzeuge_bild(_prompt(motiv), tool=tool)
    if daten is None:
        return None
    try:
        with open(path, "wb") as f:
            f.write(daten)
        log.info("Bildmotiv erzeugt (%s): %s", tool, motiv[:50])
        return path
    except Exception as ex:
        log.warning("Bildmotiv speichern fehlgeschlagen (%s): %s", motiv[:40], ex)
        return None
