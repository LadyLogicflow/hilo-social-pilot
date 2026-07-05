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

# Default-Bildmodell fuer den OpenAI-Pfad. gpt-image-1 = genau das Modell, das ChatGPT fuer die
# Bilderzeugung nutzt und mit dem unsere genehmigten Comic-Referenzen entstanden sind - deutlich
# reicher/plastischer als gpt-image-2. Per Umgebungsvariable HILO_OPENAI_IMAGE_MODEL ueberschreibbar.
OPENAI_IMAGE_MODEL_DEFAULT = "gpt-image-1"
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
            "STIL: authentische, dokumentarische/redaktionelle REPORTAGE-Fotografie - KEIN glattes "
            "Hochglanz-Stockfoto, KEINE sterile Werbe-/Corporate-Optik, KEINE makellosen, "
            "austauschbaren Models. MENSCHEN: echte, individuelle, charaktervolle Personen mit "
            "natuerlicher Hautstruktur und gelebten Gesichtern (verschiedene Altersgruppen und Typen), "
            "KEINE perfekten Model-Gesichter. UMGEBUNG: echte, gelebte, leicht unperfekte Raeume mit "
            "konkreten, spezifischen Alltags-Details (kein steriles Studio/Showroom). ANMUTUNG: "
            "natuerlich, ungestellt, candid, wie ein echtes Foto aus dem Alltag - leichte natuerliche "
            "Imperfektion ist erwuenscht. "
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

def tafel_sign_text(fields):
    """Baut den Tafel-Text (sign_text) fuer den ki_tafel-Modus aus den Entwurfs-fields (#139).

    NEU (#139): nicht nur die Ueberschrift, sondern Ueberschrift + die Stichpunkte
    (fields['bullets'], Liste kurzer Strings) - jeder Stichpunkt in einer eigenen Zeile mit
    '- '-Prefix, unter der Ueberschrift. Ohne (oder mit leeren) bullets bleibt es bei der
    reinen Ueberschrift -> Fallback = bisheriges #132-Verhalten, voll rueckwaertskompatibel.

    EHRLICH (#139): mehr Text auf der Tafel = hoeheres KI-Fehlerrisiko (Tippfehler/fehlende
    Buchstaben durch die Bild-KI). Deshalb bewusst nur Ueberschrift + Stichpunkte - NICHT die
    lange caption/subline -, damit der Schild-Text im handhabbaren Rahmen bleibt.

    Robust gegen fehlende/leere Felder und gegen nicht-string Bullets (werden zu str() und
    getrimmt; leere fallen raus). Liefert immer einen (ggf. leeren) String, crasht nie."""
    if not isinstance(fields, dict):
        return ""
    ueberschrift = (fields.get("ueberschrift") or "").strip()
    bullets_raw = fields.get("bullets")
    zeilen = []
    if isinstance(bullets_raw, (list, tuple)):
        for b in bullets_raw:
            text = (str(b) if b is not None else "").strip()
            if text:
                zeilen.append("- " + text)
    if not zeilen:
        return ueberschrift
    if ueberschrift:
        return ueberschrift + "\n" + "\n".join(zeilen)
    return "\n".join(zeilen)

def _tafel_scene(fields):
    """Liefert die Szene fuer den KI-Tafel-Modus (#140): bevorzugt den gewaehlten Schauplatz
    (fields['schauplatz'], eine schoene saisonale Umgebung), faellt sonst auf das bisherige
    Motiv (szene_motiv -> bild_motiv -> bild_motiv_thema) und zuletzt auf den Default zurueck.

    WICHTIG (#134-Retention): Producer (ensure_photo_fuer) UND Aufraeumschutz
    (cache_dateien_fuer_fields) MUESSEN denselben scene-Wert nutzen, sonst zeigt _tafel_pfad
    auf eine andere Datei -> Falsch-Loeschen. Darum diese gemeinsame Helper-Funktion."""
    if not isinstance(fields, dict):
        return "ein ruhiger, vertrauensvoller Moment im Alltag"
    schauplatz = (fields.get("schauplatz") or "").strip()
    if schauplatz:
        return schauplatz
    motiv = (fields.get("szene_motiv") or fields.get("bild_motiv")
             or fields.get("bild_motiv_thema") or "").strip()
    return motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"

def _tafel_traeger(fields):
    """Liefert den gewaehlten Traeger (Botschafts-Device, fields['traeger']) fuer den KI-Tafel-Modus
    (#142) oder "" (-> Prompt/Cache fallen auf das bisherige #140-Bilderrahmen-Device zurueck).

    WICHTIG (#134-Retention): Producer (ensure_photo_fuer) UND Aufraeumschutz
    (cache_dateien_fuer_fields) MUESSEN denselben traeger-Wert nutzen, sonst zeigt _tafel_pfad auf
    eine andere Datei -> Falsch-Loeschen. Darum diese gemeinsame Helper-Funktion (analog
    _tafel_scene)."""
    if not isinstance(fields, dict):
        return ""
    return (fields.get("traeger") or "").strip()

def _kreativ_scene(fields):
    """Liefert die Bildszene fuer den Bild-Stil 'kreativ' (#143): bevorzugt das vom Art-Director-
    Schritt (textgen) erzeugte fields['kreativ_motiv'] (eine konkrete, fotorealistische Szene zur
    ueberraschendsten Erkenntnis des Beitrags), faellt sonst auf szene_motiv -> bild_motiv ->
    bild_motiv_thema und zuletzt auf den Default zurueck.

    WICHTIG (#134-Retention, KRITISCH): Producer (ensure_photo_fuer) UND Aufraeumschutz
    (cache_dateien_fuer_fields) MUESSEN denselben Szene-Wert nutzen, sonst zeigt _kreativ_pfad auf
    eine ANDERE Datei -> Falsch-Loeschen der aktiven kreativ-Datei. Darum diese gemeinsame Helper-
    Funktion (genauso konsistent wie _tafel_scene/_tafel_traeger)."""
    if not isinstance(fields, dict):
        return "ein ruhiger, vertrauensvoller Moment im Alltag"
    motiv = (fields.get("kreativ_motiv") or fields.get("szene_motiv")
             or fields.get("bild_motiv") or fields.get("bild_motiv_thema") or "").strip()
    return motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"

def _kreativ_prompt(scene):
    """Kreativ-Bildprompt (#143): ein kinoreifes, fotorealistisches Editorial-/Award-Foto OHNE Text.
    Stil-Wrapper + die konkrete Szene ({scene} = kreativ_motiv mit Fallback). Die Botschaft + HILO-CI
    traegt spaeter der Code als Overlay (Textfeld + Kreise + CTA, Standard-Layout) - das Foto selbst
    enthaelt KEINE Schrift. Echte deutsche Umlaute."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    return ("Fotorealistisches, KINOREIF beleuchtetes Bild in Editorial-/Award-Winning-Qualitaet. "
            "KEINE Stockfoto-Aesthetik, KEINE Klischees (keine Taschenrechner, keine Ordner, "
            "keine Haendedruecke). Szene: %s. Nutze visuellen Kontrast, Spannung oder Ironie fuer "
            "Stopping Power. ABSOLUT KEIN Text, keine Buchstaben, Zahlen, Logos oder Wasserzeichen "
            "irgendwo im Bild." % scene)

# --- Comic-Stil (Ligne claire / Herge) ---------------------------------------------------------
# EXAKTER Wortlaut aus dem Auftrag. STIL_A_BLOCK ist der Stil-Wrapper; FINANZAMT_BLOCK wird NUR
# angehaengt, wenn comic_brief['finanzamt_figur'] true ist (Buerger-vs-Finanzamt-Dreh).
STIL_A_BLOCK = (
    "Comic illustration in a refined, richly detailed ligne claire style (like Herge / Tintin): "
    "clean elegant black outlines of fine-to-medium weight, flat colours enriched with subtle soft "
    "shading and gentle depth - polished and characterful, NOT crude, overly flat or sticker-like, "
    "premium editorial quality. Brand accents in deep navy blue (#0B2545) and fresh lime-green "
    "(#A3E635) on a warm off-white background, with a full lively range of colours where the scene "
    "calls for it. A carefully illustrated setting with fine background detail, plus generous empty "
    "negative space on the right side for later text. High-quality, detailed, professional linework. "
    "Square format."
)
FINANZAMT_BLOCK = (
    "Recurring 'Finanzamt' character (draw him consistently): a slightly over-correct bureaucrat - "
    "grey suit, round glasses, beige sleeve garters, pens in breast pocket, a smug friendly smile; "
    "sympathetic and comic, never a villain. His ACTION and props MUST fit the scene/topic described "
    "above - do NOT force a stamp. ONLY if the topic is genuinely about something being rejected, "
    "struck out or denied does he stamp a red 'GESTRICHEN' (green only for approvals; show mainly the "
    "wooden handle, not the mirrored rubber underside). For any other topic he does something fitting "
    "instead - e.g. pointing at a rising tax-rate arrow, holding or handing over an official letter, "
    "tapping a calculator - and shows NO 'GESTRICHEN' stamp or other symbol that would contradict the "
    "topic."
)

# --- Comic per Referenzbild (OpenAI images/edits) ----------------------------------------------
# Referenz-Assets liegen im Repo (assets/comic_refs/), Pfad relativ zum Modul, damit es auch auf
# dem Pi funktioniert. stil_ref = allgemeine Stil-Referenz (Ligne claire, genehmigt),
# finanzamt_ref = der wiederkehrende Finanzamt-Beamte (Charakter-Konstanz).
_COMIC_REF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "comic_refs")
STIL_REF_PATH = os.path.join(_COMIC_REF_DIR, "stil_ref.png")
FINANZAMT_REF_PATH = os.path.join(_COMIC_REF_DIR, "finanzamt_ref.png")
# OpenAI images/edits (Bild-zu-Bild mit Referenzen). gpt-image-1 akzeptiert mehrere Referenzbilder.
COMIC_EDITS_URL = "https://api.openai.com/v1/images/edits"
# Instruktion, die dem Comic-Prompt beim Referenz-Call vorangestellt wird: die KI soll den STIL und
# den wiederkehrenden Charakter der Referenz uebernehmen, aber NICHT deren Szene/Inhalt kopieren.
REF_INSTRUCTION = (
    "Create a NEW original illustration of the scene described below. Match the drawing style, "
    "linework, colouring and finish of the provided reference image(s). If a tax-office "
    "('Finanzamt') official appears, draw him as the SAME recurring character shown in the "
    "reference. Do NOT copy the reference's scene or content - only its style and that character.\n\n"
)


def _comic_referenz_aktiv():
    """True, wenn der Referenzbild-Pfad (OpenAI images/edits) aktiv ist. Steuerung ueber
    HILO_COMIC_REFERENCE (Default '1'); '0'/'false'/'no'/'off' schaltet zurueck auf den
    bisherigen generations-Weg. Kapselt die ENV-Auswertung, damit Producer und Cache-Key
    dieselbe Quelle nutzen."""
    return (os.environ.get("HILO_COMIC_REFERENCE") or "1").strip().lower() not in (
        "0", "false", "no", "off", "")


def _comic_refs(fields):
    """Liefert die Liste der EXISTIERENDEN Referenzbild-Pfade fuer diesen Beitrag: immer die
    Stil-Referenz (stil_ref); zusaetzlich die Finanzamt-Referenz (finanzamt_ref), wenn der
    Bild-Brief finanzamt_figur=True traegt. Nur tatsaechlich vorhandene Dateien werden aufgenommen,
    damit ein fehlendes Asset nicht zum Fehler fuehrt (Aufrufer faellt dann zurueck)."""
    refs = []
    if os.path.exists(STIL_REF_PATH):
        refs.append(STIL_REF_PATH)
    if _comic_brief(fields).get("finanzamt_figur") and os.path.exists(FINANZAMT_REF_PATH):
        refs.append(FINANZAMT_REF_PATH)
    return refs

def _comic_brief(fields):
    """Liefert das comic_brief-dict des Beitrags (Stimmung/Szene/Hook/Finanzamt-Figur). Fehlt es
    oder ist es kein dict, wird ein neutraler Fallback aus der Ueberschrift gebaut - so bleibt der
    Comic-Prompt auch fuer alte Entwuerfe ohne comic_brief robust."""
    f = fields if isinstance(fields, dict) else {}
    brief = f.get("comic_brief")
    if isinstance(brief, dict) and brief:
        return brief
    szene = (f.get("ueberschrift") or f.get("szene_motiv")
             or "eine ruhige Alltagsszene am Kuechentisch").strip()
    return {"stimmung": "sachlich", "szene": szene, "hook": "", "finanzamt_figur": False}

def _comic_prompt(fields):
    """Baut den vollstaendigen Comic-Bildprompt aus STIL_A_BLOCK + der Alltagsszene des Bild-Briefs
    (+ optionalem Hook, + FINANZAMT_BLOCK falls finanzamt_figur). Ausgelagert, damit Producer
    (ensure_comic_bild) und Cache-Pfad (_comic_pfad) denselben String nutzen (konsistent, testbar)."""
    brief = _comic_brief(fields)
    szene = (brief.get("szene") or "").strip() or "eine ruhige Alltagsszene am Kuechentisch"
    hook = (brief.get("hook") or "").strip()
    prompt = STIL_A_BLOCK + "\n\nSzene: " + szene
    if hook:
        prompt += "\n\nBild-Hook: " + hook
    if brief.get("finanzamt_figur"):
        prompt += "\n\n" + FINANZAMT_BLOCK
    return prompt

def _tafel_prompt(scene, sign_text, traeger=None):
    """KI-Tafel-Prompt (#132): die Bild-KI schreibt die Ueberschrift selbst auf eine Tafel/Plakat
    in der Szene. EXAKTER Wortlaut aus dem Issue, echte deutsche Umlaute. {scene} = Szene-Motiv,
    sign_text = die Ueberschrift (in Anfuehrungszeichen eingesetzt). Die Tafel traegt NUR diese
    Ueberschrift - sie ist die einzige Schrift im Bild (CTA + CI-Kreise kommen per Code-Overlay).

    NEU (#139): sign_text ist jetzt MEHRZEILIG - erste Zeile(n) die Ueberschrift, darunter die
    Stichpunkte (je '- '-Zeile). Der Prompt weist die KI an, die UEBERSCHRIFT prominent/gross und
    die Stichpunkte darunter kleiner, aber gut lesbar aufs Schild zu bringen. EHRLICH: mehr Text =
    hoeheres KI-Fehlerrisiko; bewusst nur Ueberschrift + Bullets (NICHT die lange caption), damit
    der Schild-Text handhabbar bleibt.

    NEU (#142): 'traeger' = das gewaehlte Botschafts-DEVICE (prompt_snippet, z.B. 'eine schwarze
    Kreidetafel ...'). Ist es gesetzt, ersetzt es das frueher hartkodierte
    Bilderrahmen/Tisch-Aufsteller-Device - das Device wechselt also, alles uebrige (Szene, Stil,
    Text-Anweisungen) bleibt gleich. OHNE traeger (None/leer) bleibt der Prompt WORTGLEICH zum
    bisherigen #140-Verhalten (Bilderrahmen/Tisch-Aufsteller) -> voll rueckwaertskompatibel.

    HINWEIS (#135): Schriftart (serifenlos/Arial-aehnlich) und Textfarbe (HILO-Dunkelblau) auf
    dem KI-Bild sind NICHT 100% erzwingbar - die Bild-KI approximiert beides; das Ergebnis wird
    nach dem Render geprueft. Wir formulieren den Wunsch dennoch moeglichst praezise."""
    traeger = (traeger or "").strip()
    if not traeger:
        # --- #140-Fallback: WORTGLEICHES Bilderrahmen/Tisch-Aufsteller-Device (rueckwaertskompatibel)
        hauptmotiv = ("ZENTRALES, SCHARFES Hauptmotiv: ein "
                      "eleganter, gut lesbarer, eher HELLES Schild in einem BILDERRAHMEN bzw. TISCH-AUFSTELLER "
                      "(helles Schild oder helle Karte im Rahmen statt schwarzer Kreidetafel). Dieser "
                      "Bilderrahmen/Tisch-Aufsteller ist NATUERLICH in die Szene integriert - er steht auf einem ")
        device_sichtbar = "Der Bilderrahmen/Tisch-Aufsteller"
        device_text_auf = "Auf dem hellen Schild im Bilderrahmen/Aufsteller steht der "
        device_blickfang = "Der helle Bilderrahmen/Tisch-Aufsteller"
    else:
        # --- #142: gewaehlter Traeger ersetzt das Device (Szene/Stil/Text bleiben unveraendert)
        hauptmotiv = ("ZENTRALES, SCHARFES Hauptmotiv: %s. Dieser Traeger der Botschaft "
                      "ist NATUERLICH in die Szene integriert - er steht auf einem " % traeger)
        device_sichtbar = "Dieser Traeger"
        device_text_auf = "Auf diesem Traeger (%s) steht der " % traeger
        device_blickfang = "Dieser Traeger"
    return ("Hochwertige, emotionale Magazin-/Editorial-Fotografie, quadratisch (1:1). "
            "Authentische Szene passend zu: %s. Natuerliche, ausgewogene, realitaetsnahe Farben "
            "bei neutralem Tageslicht; NICHT uebertrieben warm, golden oder amber - normale, "
            "neutrale Farbtemperatur. STIMMUNG zum Thema passend: grundsaetzlich froh, positiv und "
            "geloest, KEINE traurigen, gestressten, sorgenvollen oder depressiven Gesichter. ABER themen"
            "angemessen - bei ERNSTEN oder Warn-Themen (z.B. verpasste Frist, Kosten, Zuschlag) "
            "ruhige ZUVERSICHT, Erleichterung und Souveraenitaet ausstrahlen (man fuehlt sich gut "
            "aufgehoben und beraten), KEIN froehliches Grinsen oder Feiern, das dem Ernst des Themas "
            "widerspricht; bei freudigen Themen darf die Stimmung froehlich und feiernd sein. Also "
            "positiv UND zum Thema passend, nicht pauschal Party. %s"
            "TISCH im VORDERGRUND der Szene, lehnt an einer Wand oder steht auf einer Staffelei - und "
            "wird NICHT von einer Person frontal in die Kamera GEHALTEN, niemand haelt ihn hoch. KEINE "
            "gestellten Stockfoto-Posen, niemand posiert oder blickt steif in die Kamera. Stattdessen "
            "eine spontane, ungestellte, lebendige Alltagsszene (candid), natuerliche Bewegung und "
            "Interaktion, wie ein echter, nicht gestellter Schnappschuss. "
            "STIL: authentische, dokumentarische/redaktionelle REPORTAGE-Fotografie - KEIN glattes "
            "Hochglanz-Stockfoto, KEINE sterile Werbe-/Corporate-Optik, KEINE makellosen, "
            "austauschbaren Models. MENSCHEN: echte, individuelle, charaktervolle Personen mit "
            "natürlicher Hautstruktur und gelebten Gesichtern (verschiedene Altersgruppen und Typen), "
            "KEINE perfekten Model-Gesichter. UMGEBUNG: echte, gelebte, leicht unperfekte Räume mit "
            "konkreten, spezifischen Alltags-Details (kein steriles Studio/Showroom). ANMUTUNG: "
            "natürlich, ungestellt, candid, wie ein echtes Foto aus dem Alltag - leichte natürliche "
            "Imperfektion ist erwünscht. %s bleibt dabei gut "
            "sichtbar und lesbar (frontal genug zur Kamera, scharf, gut ausgeleuchtet) - nur eben als "
            "Teil der Szene auf dem Tisch, nicht als gehaltenes Plakat. %s"
            "folgende mehrzeilige deutsche Text - exakt Wort für Wort und Zeile für Zeile, KORREKT "
            "geschrieben mit richtigen deutschen Umlauten (ae oe ue als ä ö ü, ß), zentriert, in "
            "HILO-Dunkelblau und in einer klaren, modernen SERIFENLOSEN Schrift (Arial-aehnlich, "
            "ohne Serifen), perfekt lesbar, OHNE Rechtschreibfehler, OHNE zusätzliche, fehlende oder "
            "veränderte Buchstaben. Die ERSTE Zeile ist die UEBERSCHRIFT - sie steht prominent und "
            "GROSS oben; die darunter folgenden, mit '- ' beginnenden Zeilen sind die STICHPUNKTE - "
            "sie stehen darunter KLEINER, aber weiterhin gut und klar lesbar. Der gesamte Text "
            "lautet:\n'%s'. Dieser Text ist die EINZIGE Schrift im gesamten Bild. KEINE weiteren Wörter, "
            "Buchstaben, Zahlen, Logos oder Wasserzeichen irgendwo sonst. Weiches, neutrales "
            "Tageslicht, geringe Schärfentiefe. %s ist der klare "
            "Blickfang im Vordergrund, die Schauplatz-Szene ringsum traegt die zum Thema passende, "
            "geloeste Stimmung." % (scene, hauptmotiv, device_sichtbar, device_text_auf,
                                    sign_text, device_blickfang))

def ensure_photo_fuer(fields):
    """Liefert das Szene-Foto fuer den Beitrag. Bevorzugt das neue Feld 'szene_motiv'
    (emotionale Szene mit Umgebung); faellt fuer aeltere Entwuerfe auf 'bild_motiv' bzw.
    'bild_motiv_thema' zurueck, damit bestehende Entwuerfe weiter rendern.
    'icon:'-Motive (gezeichnet) bleiben unveraendert.

    Bild-Stil 'ki_tafel' (#132, Testmodus): die KI schreibt die Ueberschrift selbst auf eine Tafel
    in der Szene.

    Stil PRO BEITRAG (#144): der Stil wird ueber stilwahl.aktiver_stil(fields) bestimmt -
    fields['bild_stil'] (stabil je Beitrag gewuerfelt) ODER die globale Einstellung 'bild_stil'
    ODER 'standard'. So koennen verschiedene Entwuerfe gleichzeitig verschiedene Stile haben;
    Entwuerfe ohne fields['bild_stil'] bleiben rueckwaertskompatibel (Fallback global/'standard')."""
    import stilwahl
    stil = stilwahl.aktiver_stil(fields)
    motiv = (fields.get("szene_motiv") or fields.get("bild_motiv")
             or fields.get("bild_motiv_thema") or "").strip()
    # 'icon:'-Motive bleiben in jedem Stil gezeichnet (kein OpenAI, keine Tafel, kein kreativ-Foto).
    if stil == "comic" and not motiv.startswith("icon:"):
        # NEU (Comic): Ligne-claire-Illustration. Prompt = STIL_A_BLOCK + Alltagsszene (aus
        # comic_brief) + optional FINANZAMT_BLOCK. Eigener Cache-Praefix 'comic_'.
        return ensure_comic_bild(fields)
    if stil == "kreativ" and not motiv.startswith("icon:"):
        # NEU (#143): kreativ-Foto OHNE Text. Szene = das vom Art-Director-Schritt (textgen)
        # erzeugte kreativ_motiv (Fallback szene_motiv/bild_motiv/bild_motiv_thema) - _kreativ_scene
        # haelt diesen Wert konsistent zwischen Producer und cache_dateien_fuer_fields (#134).
        return ensure_photo_kreativ(_kreativ_scene(fields))
    if stil == "ki_tafel" and not motiv.startswith("icon:"):
        # NEU (#139): mehr Text aufs Schild - Ueberschrift + Stichpunkte (tafel_sign_text)
        # statt nur der Ueberschrift. Ohne bullets bleibt es bei der Ueberschrift (Fallback).
        sign_text = tafel_sign_text(fields)
        # NEU (#140): scene = der gewaehlte Schauplatz (schoene saisonale Umgebung), Fallback auf
        # das bisherige Motiv. _tafel_scene() haelt diese Fallback-Logik konsistent zwischen
        # Producer und cache_dateien_fuer_fields (#134-Retention).
        scene = _tafel_scene(fields)
        # NEU (#142): das Botschafts-Device (Traeger). Leer -> bisheriges Bilderrahmen-Device (#140).
        # _tafel_traeger() haelt den Wert konsistent zwischen Producer und cache_dateien_fuer_fields.
        traeger = _tafel_traeger(fields)
        return ensure_photo_tafel(scene, sign_text, traeger)
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

def tafel_cache_key(scene, sign_text, traeger=None):
    """Liefert den Cache-Schluessel-String fuer ein KI-Tafel-Foto (Praefix 'tafel:', enthaelt den
    sign_text). Ausgelagert, damit Tests den Schluessel pruefen koennen, ohne OpenAI aufzurufen.

    NEU (#142): ist 'traeger' (Botschafts-Device) gesetzt, fliesst es ZUSAETZLICH in den Schluessel
    ein -> verschiedene Traeger fuers gleiche Motiv ergeben verschiedene Bilder/Cache-Dateien.
    OHNE traeger bleibt der Schluessel UNVERAENDERT (alter Hash, rueckwaertskompatibel mit #140)."""
    key = "tafel:" + (sign_text or "").strip() + "|" + (scene or "").strip()
    traeger = (traeger or "").strip()
    if traeger:
        key += "|traeger:" + traeger
    return key

def _tafel_pfad(scene, sign_text, tool=None, traeger=None):
    """Liefert den absoluten Cache-Pfad fuer ein KI-Tafel-Foto (Praefix 'tafel_', sha256[:16]).
    Kapselt die BESTEHENDE Schluessel-Berechnung aus ensure_photo_tafel(); Hash-Formel UNVERAENDERT.
    Verwendet dieselbe scene-Default-Logik wie ensure_photo_tafel/ensure_photo_fuer.

    'tool' waehlt das Bild-Backend (#137): 'openai' (Default, Dateiname unveraendert 'tafel_<h>')
    oder 'ideogram' (Praefix 'ideogram_tafel_<h>'). None -> aktuelle Einstellung.
    'traeger' (#142): fliesst in den Cache-Key ein, WENN gesetzt (sonst alter Key)."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    sign_text = (sign_text or "").strip()
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(tafel_cache_key(scene, sign_text, traeger).lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(MOTIV_DIR, _tool_praefix(tool) + "tafel_" + h + ".png")

def _kreativ_pfad(scene, tool=None):
    """Liefert den absoluten Cache-Pfad fuer ein kreativ-Foto (#143). EIGENER Cache-Praefix
    'kreativ_' (sha256[:16] aus 'kreativ:' + scene), getrennt von szene/tafel/ideogram_ - so
    kollidiert das kreativ-Foto NICHT mit den Standard-/Tafel-Caches.

    Wie bei _szene_pfad/_tafel_pfad ist der Pfad zusaetzlich tool-abhaengig (#137): OpenAI (kein
    zusaetzlicher Tool-Praefix vor 'kreativ_') vs. Ideogram ('ideogram_kreativ_<h>'). None ->
    aktuelle Einstellung (aktives_bild_tool())."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(("kreativ:" + scene).lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(MOTIV_DIR, _tool_praefix(tool) + "kreativ_" + h + ".png")

def _comic_cache_input(fields):
    """Baut den Hash-Eingabestring fuer den Comic-Cache-Key: 'comic:' + vollstaendiger Comic-Prompt
    PLUS der Referenz-Modus. In den Modus fliessen ein: ob der Referenzpfad (images/edits) aktiv ist
    UND die Basisnamen der tatsaechlich verwendeten Referenzbilder. So kollidieren Referenz- vs.
    Nicht-Referenz-Bilder NICHT und finanzamt- vs. nicht-finanzamt-Referenzen bekommen getrennte
    Dateien. Producer (_comic_pfad) und Aufraeumschutz (cache_dateien_fuer_fields, via _comic_pfad)
    nutzen exakt diesen Bauer -> kein Falsch-Loeschen."""
    aktiv = _comic_referenz_aktiv()
    refs = _comic_refs(fields) if aktiv else []
    ref_teil = "ref=%d;%s" % (1 if refs else 0, ",".join(os.path.basename(p) for p in refs))
    return "comic:" + _comic_prompt(fields) + "|" + ref_teil

def _comic_pfad(fields, tool=None):
    """Liefert den absoluten Cache-Pfad fuer ein Comic-Bild. EIGENER Cache-Praefix 'comic_'
    (sha256[:16] aus _comic_cache_input: 'comic:' + vollstaendiger Comic-Prompt + Referenz-Modus),
    getrennt von szene/tafel/kreativ - so kollidiert das Comic-Bild NICHT mit den anderen Caches.
    Der Prompt (via _comic_prompt) enthaelt Stil + Szene + optional Finanzamt-Block, der Referenz-Teil
    unterscheidet Referenz- von Nicht-Referenz-Bildern, sodass verschiedene Briefs/Modi verschiedene
    Dateien ergeben. Tool-abhaengig (#137) wie die uebrigen Pfade (openai ohne, ideogram-Praefix)."""
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(_comic_cache_input(fields).lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(MOTIV_DIR, _tool_praefix(tool) + "comic_" + h + ".png")

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
    # WICHTIG (#139): denselben sign_text-Bauer wie ensure_photo_fuer nutzen (Ueberschrift +
    # Stichpunkte), sonst zeigt _tafel_pfad hier auf eine ANDERE Datei als die tatsaechlich
    # erzeugte -> die aktive Tafel-Datei wuerde nach der Schonfrist faelschlich geloescht.
    sign_text = tafel_sign_text(fields)
    # NEU (#140): die KI-Tafel-Szene ist der gewaehlte Schauplatz (mit Motiv-Fallback). Producer
    # (ensure_photo_fuer) und dieser Aufraeumschutz MUESSEN denselben scene-Wert nutzen -> _tafel_scene.
    tafel_scene = _tafel_scene(fields)
    # NEU (#142, KRITISCH): GENAU derselbe traeger-Wert wie der Producer (ensure_photo_fuer ->
    # _tafel_traeger). Da der Traeger in den Cache-Key einfliesst, wuerde ein abweichender Wert hier
    # auf eine ANDERE Datei zeigen -> die aktive Tafel-Datei wuerde nach der Schonfrist faelschlich
    # geloescht (#134). Leer -> alter Schluessel (Bilderrahmen-Default), rueckwaertskompatibel.
    tafel_traeger = _tafel_traeger(fields)
    # NEU (#143, KRITISCH): GENAU derselbe Szene-Wert wie der kreativ-Producer (ensure_photo_fuer ->
    # _kreativ_scene). Da die Szene in den kreativ-Cache-Key einfliesst, wuerde ein abweichender Wert
    # hier auf eine ANDERE Datei zeigen -> die aktive kreativ-Datei wuerde nach der Schonfrist
    # faelschlich geloescht (#134). Konsistent wie bei _tafel_scene/_tafel_traeger.
    kreativ_scene = _kreativ_scene(fields)
    for tool in ("openai", "ideogram"):
        # Standard-Szene-Variante (jedes Motiv aus der Fallback-Kette kann den Cache-Treffer liefern).
        for m in (fields.get("szene_motiv"), fields.get("bild_motiv"), fields.get("bild_motiv_thema")):
            sp = _szene_pfad(m, tool=tool)
            if sp:
                pfade.add(sp)
        # Standard-Szene-Default (#134): bei LEEREM Motiv wendet ensure_photo/ensure_photo_fuer den
        # Default auf die Standard-Szene an (ensure_photo: motiv = motiv or "..."). _szene_pfad(None)
        # liefert sonst None, sodass die Default-Szene-Datei NICHT als 'in Benutzung' gilt und nach
        # der Schonfrist faelschlich geloescht wuerde (ARGUS-Blocker #134). Darum den Default-Szene-
        # Pfad mit aufnehmen - exakt derselbe Default-String -> exakt derselbe Hash/Dateiname.
        szene_default = motiv or "ein ruhiger, vertrauensvoller Moment im Alltag"
        sp_def = _szene_pfad(szene_default, tool=tool)
        if sp_def:
            pfade.add(sp_def)
        # KI-Tafel-Variante (#140/#142): scene = der Schauplatz (mit Motiv-Fallback, _tafel_scene),
        # traeger = das Botschafts-Device (_tafel_traeger) - exakt dieselben Werte wie im Producer
        # ensure_photo_fuer -> selber _tafel_pfad, kein Falsch-Loeschen der aktiven Tafel-Datei.
        pfade.add(_tafel_pfad(tafel_scene, sign_text, tool=tool, traeger=tafel_traeger))
        # kreativ-Variante (#143): Szene = _kreativ_scene (kreativ_motiv mit Fallback) - exakt
        # derselbe Wert wie im Producer ensure_photo_fuer -> selber _kreativ_pfad, kein
        # Falsch-Loeschen der aktiven kreativ-Datei.
        pfade.add(_kreativ_pfad(kreativ_scene, tool=tool))
        # comic-Variante: derselbe Prompt-Bau wie im Producer (ensure_comic_bild -> _comic_prompt)
        # -> selber _comic_pfad, kein Falsch-Loeschen der aktiven Comic-Datei nach der Schonfrist.
        pfade.add(_comic_pfad(fields, tool=tool))
    return pfade

def _openai_quality():
    """Liefert die OpenAI-Bildqualitaet aus HILO_IMAGE_QUALITY (Default 'medium', validiert)."""
    quality = (os.environ.get("HILO_IMAGE_QUALITY") or "high").strip().lower()
    return quality if quality in ("low", "medium", "high", "auto") else "high"


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


def erzeuge_comic_bild_ref(prompt, refs):
    """Erzeugt ein Comic-Bild via OpenAI images/edits MIT Referenzbildern (Stil- + optional
    Charakter-Referenz) und liefert die PNG-Bytes (oder None). multipart/form-data wie
    erzeuge_bild_openai (gleicher Key/Bearer/Timeout-Stil):
      data:  model, prompt, size='1024x1024', quality, n='1' (KEIN background-Feld beim edits-Call)
      files: fuer JEDEN Pfad in 'refs' ein Feld ('image[]', (basename, filehandle, 'image/png')) -
             gpt-image-1 akzeptiert mehrere Referenzbilder.
    Ohne 'openai_api_key', bei HTTP-/Netz-Fehler oder sonstiger Exception -> None (der Aufrufer
    faellt dann auf den generations-Weg zurueck). Der Key wird NIE geloggt; alle geoeffneten
    Dateihandles werden im finally sauber geschlossen. Content-Type setzt requests selbst
    (multipart-Boundary) - hier NICHT manuell setzen."""
    key = get_secret("openai_api_key")
    if not key:
        log.info("Comic-Referenzbild uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    handles = []
    try:
        import requests
        data = {"model": openai_image_model(), "prompt": prompt, "size": "1024x1024",
                "quality": _openai_quality(), "n": "1"}
        files = []
        for path in refs:
            fh = open(path, "rb")
            handles.append(fh)
            files.append(("image[]", (os.path.basename(path), fh, "image/png")))
        r = requests.post(
            COMIC_EDITS_URL,
            headers={"Authorization": "Bearer %s" % key},
            data=data, files=files, timeout=120)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)
    except Exception as ex:
        log.warning("OpenAI-Comic-Referenzbild fehlgeschlagen: %s", ex)
        return None
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass


# --- Comic-Portrait der Beratungsstellen-Leitung (Stil "Comic Beratung", Setup) ----------------
# Exakter Prompt fuer das wiederkehrende Comic-Portrait der Leitung. Bewusst als Konstante, damit
# Producer (erzeuge_berater_comic) und Tests denselben Wortlaut nutzen.
BERATER_PORTRAIT_PROMPT = (
    "Create a friendly, modern comic portrait, head and shoulders, of the SAME person shown in the "
    "provided photograph, redrawn in a clean ligne claire comic style (clean elegant outlines, flat "
    "colours, light natural shading) matching the style reference image. Aim for a FLATTERING but "
    "AUTHENTIC likeness that is TRUE TO THE PERSON'S REAL AGE and character - a mature adult "
    "professional. Keep their natural character and real features so they clearly look like "
    "THEMSELVES (some age and character is welcome and good): do NOT smooth them into a generic, "
    "idealised or unrealistically young face, and do NOT harshly age them or add heavy shading, "
    "deep wrinkles or extra weight either. Recognisable, dignified, likeable, with a friendly smile. "
    "Simple clean light background. Square format."
)


def erzeuge_berater_comic(foto_path):
    """Erzeugt aus dem Leitungs-Foto einer Beratungsstelle ein Comic-Portrait (Stil "Comic
    Beratung") und liefert den gespeicherten PNG-Pfad (oder None).

    Ruft erzeuge_comic_bild_ref(BERATER_PORTRAIT_PROMPT, [foto_path, STIL_REF_PATH]) auf - das
    Leitungs-Foto liefert die Person, STIL_REF_PATH den Ligne-claire-Stil. Die Ergebnis-Bytes
    werden nach DATA_DIR/berater/comic_<stelleid>.png geschrieben (die Stellen-ID wird aus dem
    Datei-Basenamen des Fotos abgeleitet - 'stelle_<id>' oder 'foto_<id>'), der Pfad zurueckgegeben.

    Robust: fehlendes Foto, kein 'openai_api_key', API-/Netz-/Schreibfehler -> None (kein Crash).
    Das echte Gesicht/Comic wird NUR ueber login-geschuetzte Routen ausgeliefert (DSGVO)."""
    if not foto_path or not os.path.exists(foto_path):
        log.info("Berater-Comic uebersprungen: kein Leitungs-Foto vorhanden (%r).", foto_path)
        return None
    try:
        daten = erzeuge_comic_bild_ref(BERATER_PORTRAIT_PROMPT, [foto_path, STIL_REF_PATH])
    except Exception as ex:
        log.warning("Berater-Comic (Referenz-Call) fehlgeschlagen: %s", ex)
        return None
    if not daten:
        return None
    base = os.path.splitext(os.path.basename(foto_path))[0]
    teil = base.split("_")[-1]
    stelleid = teil if teil.isdigit() else base
    ziel_dir = os.path.join(DATA_DIR, "berater")
    ziel = os.path.join(ziel_dir, "comic_%s.png" % stelleid)
    try:
        os.makedirs(ziel_dir, exist_ok=True)
        with open(ziel, "wb") as fh:
            fh.write(daten)
    except Exception as ex:
        log.warning("Berater-Comic konnte nicht gespeichert werden: %s", ex)
        return None
    return ziel


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


def tafel_payload(scene, sign_text, traeger=None):
    """Baut das OpenAI images/generations-Request-Payload fuer ein KI-Tafel-Foto (ohne
    Netzwerkaufruf). Modell aus HILO_OPENAI_IMAGE_MODEL (Default 'gpt-image-2'), background='opaque',
    size '1024x1024'. Ausgelagert, damit Tests Prompt + Parameter pruefen koennen.
    'traeger' (#142): das Botschafts-Device; leer -> bisheriges Bilderrahmen-Device (#140)."""
    return openai_payload(_tafel_prompt(scene, sign_text, traeger))

def kreativ_payload(scene):
    """Baut das OpenAI images/generations-Request-Payload fuer ein kreativ-Foto (#143, ohne
    Netzwerkaufruf). background='opaque', size '1024x1024' (ueber openai_payload). Ausgelagert,
    damit Tests Prompt + Parameter ohne Netz pruefen koennen."""
    return openai_payload(_kreativ_prompt(scene))

def ensure_photo_kreativ(scene):
    """Erzeugt (oder liefert aus dem Cache) das kreativ-Foto (#143): ein kinoreifes, fotorealistisches
    Bild OHNE Text zur uebergebenen Szene (scene = kreativ_motiv mit Fallback, via _kreativ_scene).
    Eigener Cache-Praefix 'kreativ_' (getrennt von szene/tafel). background='opaque', size '1024x1024'.
    Tool-Routing (OpenAI/Ideogram) wie bei den anderen Stilen. Ohne API-Key -> None (Creme-Fallback)."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    path = _kreativ_pfad(scene, tool=tool)
    if os.path.exists(path):
        return path
    daten = erzeuge_bild(_kreativ_prompt(scene), tool=tool)
    if daten is None:
        return None
    try:
        with open(path, "wb") as f:
            f.write(daten)
        log.info("Kreativ-Foto erzeugt (%s): %s", tool, scene[:50])
        return path
    except Exception as ex:
        log.warning("Kreativ-Foto speichern fehlgeschlagen (%s): %s", scene[:40], ex)
        return None

def ensure_comic_bild(fields):
    """Erzeugt (oder liefert aus dem Cache) das Comic-Bild (Ligne claire): eine Illustration in
    HILO-Palette, die die STIMMUNG + ein Alltagsmotiv des Beitrags zeigt (nicht das Steuerthema
    woertlich). Prompt = STIL_A_BLOCK + Szene aus comic_brief (+ optional Hook + FINANZAMT_BLOCK).
    Eigener Cache-Praefix 'comic_' (getrennt von szene/tafel/kreativ). Tool-Routing (OpenAI/Ideogram)
    wie bei den anderen Stilen. Ohne API-Key -> None (Creme-Fallback im Render).

    NEU (Referenzbild): Ist HILO_COMIC_REFERENCE aktiv (Default) UND liegt mindestens eine
    Referenzdatei vor, wird das Bild ueber OpenAI images/edits mit Referenzen erzeugt
    (Stil-Referenz + optional der wiederkehrende Finanzamt-Charakter) - REF_INSTRUCTION + Comic-Prompt.
    Ist der Referenzpfad deaktiviert, fehlt jede Referenz ODER liefert der Referenz-Call None
    (kein Key/Fehler), faellt die Erzeugung auf den bisherigen generations-Weg (erzeuge_bild) zurueck."""
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    path = _comic_pfad(fields, tool=tool)
    if os.path.exists(path):
        return path
    daten = None
    refs = _comic_refs(fields)
    if _comic_referenz_aktiv() and refs:
        prompt_ref = REF_INSTRUCTION + _comic_prompt(fields)
        daten = erzeuge_comic_bild_ref(prompt_ref, refs)
    if daten is None:
        # Fallback: Referenzpfad deaktiviert, keine Referenz vorhanden ODER kein Key/Fehler.
        daten = erzeuge_bild(_comic_prompt(fields), tool=tool)
    if daten is None:
        return None
    try:
        with open(path, "wb") as f:
            f.write(daten)
        log.info("Comic-Bild erzeugt (%s): %s", tool, _comic_brief(fields).get("szene", "")[:50])
        return path
    except Exception as ex:
        log.warning("Comic-Bild speichern fehlgeschlagen: %s", ex)
        return None

def ensure_photo_tafel(scene, sign_text, traeger=None):
    """Erzeugt (oder liefert aus dem Cache) das KI-Tafel-Foto (#132): scene = Szene-Motiv,
    sign_text = die Ueberschrift, die die KI auf die Tafel schreibt. Eigener Cache-Schluessel
    (Praefix 'tafel:'), der den sign_text ENTHAELT - so bekommt jede Ueberschrift ihr eigenes Foto.
    background='opaque', size '1024x1024'. Ohne openai_api_key wird None geliefert (Creme-Fallback).
    'traeger' (#142): das Botschafts-Device; fliesst in Cache-Key + Prompt ein, WENN gesetzt
    (sonst alter Key/Prompt = bisheriges Bilderrahmen-Device, #140-rueckwaertskompatibel)."""
    scene = (scene or "ein ruhiger, vertrauensvoller Moment im Alltag").strip()
    sign_text = (sign_text or "").strip()
    traeger = (traeger or "").strip()
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    # Cache-Pfad ist tool-abhaengig (#137) und traeger-abhaengig (#142): OpenAI/Ideogram und
    # verschiedene Traeger kollidieren NICHT.
    path = _tafel_pfad(scene, sign_text, tool=tool, traeger=traeger)
    if os.path.exists(path):
        return path
    daten = erzeuge_bild(_tafel_prompt(scene, sign_text, traeger), tool=tool)
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
