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

# Prompt-Version: Wird in Cache-Key einbezogen - bei Änderung des Prompts erhöhen
# damit neue Bilder generiert werden statt alte Cache-Einträge zu verwenden!
# v3.1 = ChatGPT-optimierter Prompt (Bildidee in einem Satz, Magazin-Test, etc.)
PROMPT_VERSION = "v3.1"

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
    """Liefert den OpenAI-Bildmodell-Namen fuer den Bild-Call.

    Reihenfolge (#161): die globale Einstellung 'bild_modell' (in der Verwaltung -> Bild-Stil
    umschaltbar) hat Vorrang, ist aber auf die erlaubten Werte 'gpt-image-1'/'gpt-image-2' begrenzt -
    ein unbekannter/leerer Wert faellt auf den Default zurueck. Der Default bleibt der bisherige:
    HILO_OPENAI_IMAGE_MODEL (Env, falls gesetzt) sonst OPENAI_IMAGE_MODEL_DEFAULT ('gpt-image-1').
    So kann Catrin gpt-image-1 vs. gpt-image-2 am selben Beitrag vergleichen (A/B), ohne dass der
    Default sich aendert. Fehlt die DB (Import-/DB-Fehler), gilt der Default (kein Crash)."""
    default = (os.environ.get("HILO_OPENAI_IMAGE_MODEL") or OPENAI_IMAGE_MODEL_DEFAULT).strip()
    try:
        import db
        wert = db.get_einstellung("bild_modell", None)
    except Exception:
        wert = None
    if wert is None:
        return default
    wert = str(wert).strip()
    return wert if wert in ("gpt-image-1", "gpt-image-2") else default

def _prompt(fields_or_motiv):
    """ChatGPT Masterprompt fuer HILO Newsletterbilder - Creative Director Ansatz.
    Bekommt entweder die kompletten fields (dict) ODER ein Motiv (string) fuer Rueckwaertskompatibilitaet.
    Mit fields: OpenAI agiert als Creative Director. Mit Motiv: Fallback auf einfachen Prompt."""

    # Rueckwaertskompatibilitaet: Wenn String statt dict, nutze einfachen Fallback-Prompt
    if not isinstance(fields_or_motiv, dict):
        motiv = str(fields_or_motiv or "").strip()
        return f"""Professional editorial photography for a financial consulting newsletter.

Scene: {motiv}

Style: Modern, friendly, trustworthy, high-quality editorial look.
Colors: Incorporate navy blue, green, and lavender accents where natural (HILO brand colors).
Composition: Square 1:1, leave center area mostly empty for text overlay, place main subjects at edges.
Quality: Ultra high quality, magazine-worthy, professional lighting.
No text, no logos, no watermarks in the image."""

    # Newsletter-Text aus fields zusammenbauen
    fields = fields_or_motiv
    ueberschrift = (fields.get("ueberschrift") or "").strip()
    subline = (fields.get("subline") or "").strip()
    bullets = fields.get("bullets") or []
    if isinstance(bullets, list):
        bullets_text = "\n".join("• " + b for b in bullets if b)
    else:
        bullets_text = ""

    newsletter_text = f"{ueberschrift}\n\n{subline}\n\n{bullets_text}".strip()

    # Masterprompt v3.1 (ChatGPT-optimiert):
    # Verbesserungen gegenüber v3:
    # 1. Bildstrategie und Bildart stärker getrennt (mehr kreativer Spielraum)
    # 2. Positive Gewichtung statt negative ("bevorzuge" statt "letzte Wahl")
    # 3. Überraschungseffekt-Regel ("Art Director-Frage")
    # 4. ⭐ ZENTRALE BILDIDEE IN EINEM SATZ (größter Hebel!)
    # 5. Magazin-Test am Ende ("Würde es auffallen?")
    # 6. Neue Bildtypen: Flat Lay, Cinematic Detail Shot
    # 7. Seriencharakter-Regel (Abwechslung über Zeit)

    # Masterprompt v3.1 (Optimiert für kreative Qualität)
    return f"""Du bist gleichzeitig Creative Director, Art Director und Editorial Photographer für HILO.

Deine Aufgabe: Entwickle aus dem Newslettertext ein Bild, das wie ein Titelbild eines hochwertigen Wirtschafts- oder Verbrauchermagazins wirkt.

---

SCHRITT 1: BILDSTRATEGIE WÄHLEN

Analysiere den Text und wähle die Bildstrategie:

• **Emotion erzeugen** – Gefühl transportieren (Hoffnung, Zuversicht, Erleichterung)
• **Warnen** – Auf Risiken/Fallen hinweisen
• **Symbol verwenden** – Abstrakte Metapher für das Thema
• **Objekt in Szene setzen** – Konkreter Gegenstand als Fokus
• **Geschichte erzählen** – Narrative Szene
• **Menschen zeigen** – Emotionale Menschendarstellung
• **Vergleich darstellen** – Vorher/Nachher, Mit/Ohne
• **Erklärung visualisieren** – Prozess oder Zusammenhang zeigen

Frage dich:
"Welche Strategie transportiert die Kernaussage am stärksten?"
"Welche Bildidee macht den Leser in 3 Sekunden neugierig?"

---

SCHRITT 2: ZENTRALE BILDIDEE FORMULIEREN

**Dies ist der wichtigste Schritt!**

Formuliere die Bildidee intern in genau EINEM Satz.

Beispiele für gute Bildideen:
- "Eine geöffnete Steuerakte, aus der ein Angelhaken ragt"
- "Eine rote Warnlampe spiegelt sich auf einem Laptop"
- "Ein Kalender mit rot markiertem Datum, daneben ein geöffneter Brief"
- "Hände halten einen Steuerbescheid wie eine Schatzkarte"

**Wenn dieser Satz nicht spannend klingt, entwickle eine bessere Bildidee.**

Frage dich zusätzlich:
"Welche Bildidee würde ein Art Director eines hochwertigen Wirtschaftsmagazins wählen?"

Wenn mehrere Lösungen funktionieren, bevorzuge die originellere.

---

SCHRITT 3: BILDART WÄHLEN

Nachdem du die zentrale Bildidee formuliert hast, überlege **unabhängig davon**, welche Bildart diese Idee am stärksten transportiert.

**Die folgenden Zuordnungen sind Orientierungshilfen und keine festen Regeln:**

Warnung vor Steuerfalle → Symbolbild oder Konzeptfotografie
Emotionale Themen → Editorial Photography
Steuererstattung → Menschen (authentisch) oder Stillleben
Fristen, Termine → Objektfotografie oder Editorial Flat Lay
Finanzwissen → Illustration oder Editorial Photography
Vergleich → Infografik ODER Editorial Photography
Prozess, Ablauf → Infografik

**Bevorzuge grundsätzlich:**
1. Editorial Photography
2. Konzeptfotografie
3. Symbolbild
4. Editorial Flat Lay
5. Cinematic Detail Shot
6. Stillleben
7. Objektfotografie
8. Illustration
9. Comic (Ligne-Claire)
10. Papiercollage

**Nur wenn fotografische oder illustrative Motive die Aussage schlechter transportieren, verwende eine Infografik.**

---

FARBEN

Nutze die HILO-CI ausschließlich als dezente Akzente.

Farben:
• #1a3a6b (Navy)
• #4a8c5c (Grün)
• #b8c8e8 (Lavendel)
• Weiß

---

BILDSPRACHE

• modern
• hochwertig
• vertrauenswürdig
• authentisch
• professionell
• emotional passend
• ruhige Komposition
• klare Blickführung

---

MENSCHEN

Verwende Menschen nur, wenn sie die Aussage verbessern.

Keine gestellten Businessposen.
Keine Daumen-hoch-Gesten.
Keine übertriebenen Emotionen.

---

VERMEIDE

• Stockfoto-Look
• Geldregen
• riesige Eurozeichen
• überladene Szenen
• Logos
• QR-Codes
• Wasserzeichen
• Text im Bild

---

FORMAT

Quadratisch. 1:1.
Ultra High Quality.

---

PARAMETER

Bildwirkung: Automatisch wählen
Kreativitätsgrad: 3 (von 5)
Stilpräferenz: Automatisch

---

SERIENCHARAKTER

Behandle jedes neue Bild als Teil einer fortlaufenden HILO-Magazinserie.

Vermeide ähnliche:
• Motive (z.B. nicht immer Sparschwein/Taschenrechner)
• Perspektiven (z.B. nicht immer Aufsicht)
• Kompositionen (z.B. nicht immer zentriert)
• Farbwirkungen (z.B. nicht immer warme Holztöne)

Suche bewusst nach einer neuen visuellen Idee, die sich von typischen Finanz-/Steuermotiven abhebt.

---

QUALITÄTSTEST VOR BILDERZEUGUNG

Überprüfe abschließend:

**"Würde dieses Bild auf der Titelseite eines Magazins zwischen zehn anderen Bildern sofort auffallen?"**

Falls NEIN:
→ Verbessere die **Bildidee**, nicht den Stil.

Falls JA:
→ Erzeuge das Bild.

---

TEXT:

{newsletter_text}"""

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
# Stil "Comic Beratung" (comic_beratung): personalisierte Beratungsszene - VORNE der/die Berater:in
# der Beratungsstelle (Comic-Figur nach dem ersten Referenzbild), HINTEN der wiederkehrende
# Finanzamt-Beamte, der leer ausgeht. EXAKTER Wortlaut aus dem Auftrag.
# HILO-Masterprompt (von Catrins ChatGPT-Projekt entwickelt, deutsch, getreu): der HILO-Comic-Stil
# fuer SERIOESE Illustrationen (Beratung). Bewusst NUR fuer comic_beratung - NICHT fuer den witzigen
# 'comic'-Stil (der lebt von Karikatur; der Master sagt 'keine Karikaturen').
HILO_COMIC_MASTER = (
    "Erstelle eine hochwertige Illustration im Stil der Ligne claire (klare Linie), inspiriert von "
    "klassischen frankobelgischen Comics wie Tim & Struppi, jedoch modern interpretiert und auf "
    "hoechstem professionellen Illustrationsniveau. Elegant, zeitlos und hochwertig - nicht kindlich "
    "oder cartoonhaft; wie von einem professionellen Comiczeichner erstellt.\n"
    "Zeichenstil: kraeftige, gleichmaessige schwarze Konturen; absolut saubere, geschlossene "
    "Linienfuehrung; flaechige Farben; nur minimale weiche Schattierungen; keine Texturen, keine "
    "Pinselstriche, keine Skizzenoptik, keine Manga-, Disney- oder Chibi-Elemente, keine Karikaturen, "
    "keine ueberzeichnete Mimik. Figuren realistisch proportioniert, nur im Ligne-claire-Stil illustriert.\n"
    "Farbwelt: kraeftige, satte, flaechige Farben mit klarem Kontrast - dominierend leuchtendes "
    "HILO-Blau (#1f428d) und frisches HILO-Gruen (#60a33c), dazu warmes Papierweiss und warme "
    "Holztoene, natuerliche Hautfarben; reine, gut gesaettigte Farbflaechen, lebendig und klar, "
    "NICHT blass, verwaschen oder entsaettigt (aber nicht neon/grell); frisch, freundlich, serioes.\n"
    "Licht: weiches Tageslicht, keine harten Schatten, keine dramatische Beleuchtung, helle "
    "freundliche Atmosphaere.\n"
    "Perspektive: Augenhoehe, leichte Dreiviertelperspektive, natuerliche Kameraposition; keine "
    "extremen Brennweiten, keine Vogel- oder Froschperspektive.\n"
    "Personen: sympathisch, kompetent, aufmerksam, ruhig, authentisch, natuerlich; keine Model-Posen, "
    "keine uebertriebene Mimik, keine kuenstlichen Gesten.\n"
    "Gesicht (bei Fotovorlage): Gesicht moeglichst exakt uebernehmen - Gesichtsform, Frisur, "
    "Haarfarbe, Alter, Augen, Nase, Mund; eindeutig erkennbar dieselbe Person.\n"
    "Koerperproportionen: realistisch; keine uebergrossen Koepfe, keine verkuerzten Arme, keine "
    "Cartoon-Haende, keine Comic-Verzerrungen.\n"
    "Kleidung: modern, Business Casual, gepflegt, schlichte Stoffe, keine auffaelligen Muster; Farben "
    "harmonieren mit der HILO-CI.\n"
    "Bildqualitaet: extrem hohe Detailqualitaet, professionelle Comicillustration, Druckqualitaet, "
    "sehr saubere Konturen, perfekte Anatomie, perfekte Haende, perfekte Perspektive, klare Formen, "
    "keine KI-Artefakte.\n"
    "Negativ: keine Manga-/Disney-/Pixar-/Anime-Optik, keine Karikaturen, keine Chibi-Figuren, keine "
    "uebertriebenen Gesichtsausdruecke, keine verzerrten Haende, keine schiefen Augen, keine schiefen "
    "Perspektiven, keine ueberladenen Hintergruende, keine grellen Farben, keine Sprechblasen, keine "
    "Wasserzeichen, keine kuenstlichen Effekte, keine Koernung, keine Texturen.\n"
    "Konsistenz: alle HILO-Illustrationen gehoeren zu derselben gezeichneten Welt - Figuren, "
    "Architektur, Farbpalette, Perspektive, Linienfuehrung und Lichtstimmung bleiben konsistent; "
    "wiederkehrende Charaktere behalten stets dieselbe Gesichtsform, Frisur, Kleidung und Proportionen."
)

# Beratungs-Delta (auf HILO_COMIC_MASTER): Komposition + HILO-Buero + Referenz-Zuordnung
# (1. Ref = Berater).
BERATUNG_BLOCK = (
    "Szene: eine HILO-Steuerberatung. Die beiden Personen sitzen sich GEGENUEBER an einem Schreibtisch, "
    "auf DERSELBEN Ebene, EXAKT gleich gross - keine Person wirkt dominanter; echter BLICKKONTAKT, "
    "natuerliche Gespraechssituation. Der/die Berater:in hoert aufmerksam zu, das Mitglied wirkt "
    "entspannt. Der/die Berater:in sieht aus wie die ERSTE Referenz (Gesicht, Frisur, Alter exakt "
    "uebernehmen) und traegt ein kleines HILO-Logo (Schriftzug 'HILO' in WEISSER Schrift) am Revers.\n"
    "Hintergrund: moderner deutscher Beratungsraum - helle Raeume, grosse Fenster, Pflanzen, "
    "Buecherregale, Schreibtisch, Laptop, Steuerunterlagen; ein dezentes HILO-Plakat mit dem Text "
    "'Persoenlich. Kompetent. Fuer Sie da.' (kleiner gruener Unterstrich), ein Laptop mit kleinem "
    "'Wir sind HILO', Papiere mit 'Steuererklaerung'; alles reduziert und ordentlich; der "
    "Hintergrund unterstuetzt die Szene, lenkt aber nie von den Personen ab.\n"
    "Kein Text im Bild (keine Sprechblasen, keine Beschriftung ausser den genannten kleinen Buero-Elementen).\n"
    "Komposition: Personen und Szene sitzen in der LINKEN und mittleren Bildhaelfte; die RECHTE, vor "
    "allem die rechte obere Bildhaelfte, bleibt bewusst ruhiger, heller Negativraum (schlichte Wand) "
    "fuer spaeteren Text. Das Bild NICHT randlos bis in alle Ecken fuellen - klare Luft und Freiraum "
    "rechts oben lassen, weite ruhige Einstellung wie ein professionelles Agenturbild."
)
# Figur-Steckbrief des wiederkehrenden Finanzamt-Beamten (#161, deutsch, echte Umlaute). Wird - wenn
# gesetzt - direkt NACH der Stilregel (HILO_COMIC_MASTER bzw. STIL_A_BLOCK) und VOR der Szene in den
# Prompt gesetzt (Reihenfolge Stil -> Figur -> Szene). Ein praeziser Text-Steckbrief verstaerkt das
# Referenzbild (Text ist ein starker Treiber). Markenname exakt "HILO"; die Figur traegt KEINE
# HILO-Accessoires (sie gehoert zum Finanzamt, nicht zu HILO).
FINANZAMT_FIGUR = (
    "Herr Aermelschoner: rundes freundliches Gesicht, grosse runde schwarze Brille, hoher kahler "
    "Oberkopf, kurzer dunkler Haarkranz, grauer Anzug, weisses Hemd, dunkelblaue Krawatte, beige "
    "Aermelschoner, zwei gruene Stifte in der Brusttasche. Keine HILO-Accessoires. Im Finanzamt-Buero "
    "ist der Bundesadler sichtbar."
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
# Referenz-Anker (#159): verpflichtet die Bild-KI per TEXT auf das mitgegebene Referenzportrait -
# gleiche Figur, neue Szene, NICHT neu interpretieren. Wird NUR angehaengt, wenn fuer das jeweilige
# Bild tatsaechlich eine Charakter-Referenz mitgegeben wird (kein Anker im referenzlosen Fallback).
# Bewusst allgemein formuliert (ohne Name), damit derselbe Anker fuer jede Referenz gilt (Finanzamt-
# Figur UND jedes Berater-Portrait). Ergaenzt REF_INSTRUCTION: die Text-Beschreibung ist ein starker
# Treiber - oft staerker als das Referenzbild - deshalb wird die Verpflichtung explizit verstaerkt.
REF_ANCHOR = (
    "Verwende das mitgegebene Referenzportrait als verbindliche Vorlage fuer Gesicht, Proportionen, "
    "Frisur, Brille/Bart und Mimik. Die Figur nicht neu interpretieren, sondern als dieselbe "
    "Comicfigur in einer anderen Szene zeigen; alle charakteristischen Merkmale bleiben unveraendert."
)


def _ref_signatur(path):
    """Liefert eine Cache-stabile Signatur einer Referenzdatei: '<basename>@<int(mtime)>' (#158).
    So ergibt ein ERSETZTES Referenzbild MIT GLEICHEM DATEINAMEN (neue mtime) einen NEUEN
    Cache-Schluessel -> frisches Bild; eine UNVERAENDERTE Datei behaelt ihren Schluessel (weiter
    effizient gecacht). Fehlt der Pfad oder existiert die Datei nicht -> '' (bisheriges Verhalten
    fuer fehlende Refs). Robust: kann die mtime nicht gelesen werden, faellt es auf den blossen
    Basename zurueck, damit der Schluessel trotzdem stabil bleibt."""
    p = (path or "").strip()
    if not p or not os.path.exists(p):
        return ""
    base = os.path.basename(p)
    try:
        return "%s@%d" % (base, int(os.path.getmtime(p)))
    except Exception:
        return base


def _comic_referenz_aktiv():
    """True, wenn der Referenzbild-Pfad (OpenAI images/edits) aktiv ist. Steuerung ueber
    HILO_COMIC_REFERENCE (Default '1'); '0'/'false'/'no'/'off' schaltet zurueck auf den
    bisherigen generations-Weg. Kapselt die ENV-Auswertung, damit Producer und Cache-Key
    dieselbe Quelle nutzen."""
    return (os.environ.get("HILO_COMIC_REFERENCE") or "1").strip().lower() not in (
        "0", "false", "no", "off", "")


def _comic_refs(fields):
    """Liefert die Liste der EXISTIERENDEN Referenzbild-Pfade fuer diesen Beitrag: immer die
    Stil-Referenz (stil_ref); zusaetzlich die Finanzamt-Referenz, wenn der Bild-Brief
    finanzamt_figur=True traegt. Fuer den Finanzamt-Charakter wird die globale Finanzamt-Bible
    (finanzamt_bibel_bild) bevorzugt - sonst die Default-Referenz FINANZAMT_REF_PATH
    (_finanzamt_ref_pfad); so nutzt der normale Comic denselben, konsistenten Aermelschoner wie
    'Comic Beratung' (Catrin, Variante a). Nur tatsaechlich vorhandene Dateien werden aufgenommen,
    damit ein fehlendes Asset nicht zum Fehler fuehrt (Aufrufer faellt dann zurueck)."""
    refs = []
    if os.path.exists(STIL_REF_PATH):
        refs.append(STIL_REF_PATH)
    if _comic_brief(fields).get("finanzamt_figur"):
        fa = _finanzamt_ref_pfad()
        if os.path.exists(fa):
            refs.append(fa)
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
    prompt = STIL_A_BLOCK
    # #161 (Reihenfolge Stil -> Figur -> Szene): traegt der Brief die Finanzamt-Figur, wird der
    # praezise Figur-Steckbrief FINANZAMT_FIGUR direkt NACH der Stilregel und VOR der Szene eingefuegt
    # (ergaenzend zu FINANZAMT_BLOCK, der weiter unten die Handlung/Requisiten regelt). Der Text-
    # Steckbrief verstaerkt das Referenzbild. Deterministisch aus fields -> Producer (ensure_comic_bild)
    # und Cache-Key (_comic_cache_input) sehen denselben Prompt.
    if brief.get("finanzamt_figur"):
        prompt += "\n\n" + FINANZAMT_FIGUR
    prompt += "\n\nSzene: " + szene
    if hook:
        prompt += "\n\nBild-Hook: " + hook
    if brief.get("finanzamt_figur"):
        prompt += "\n\n" + FINANZAMT_BLOCK
        fa_text = _finanzamt_bibel_text()
        if fa_text:
            prompt += ("\n\nVerbindliche Charakter-Beschreibung des Finanzamt-Beamten "
                       "(Finanzamt-Bible): " + fa_text)
    # #159: Referenz-Anker anhaengen, WENN fuer dieses Bild tatsaechlich eine Charakter-Referenz
    # genutzt wird (Referenzpfad aktiv UND mindestens ein Referenzbild vorhanden). Deterministisch aus
    # fields ableitbar, damit Producer (ensure_comic_bild) UND Cache-Key (_comic_cache_input) denselben
    # Prompt sehen. OHNE Referenz (deaktiviert/keine Assets) bleibt der Prompt unveraendert.
    if _comic_referenz_aktiv() and _comic_refs(fields):
        prompt += "\n\n" + REF_ANCHOR
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
    if stil == "comic_beratung" and not motiv.startswith("icon:"):
        # NEU (Comic Beratung): personalisierte Szene - vorne der/die Berater:in DER STELLE, hinten
        # der Finanzamt-Beamte. Der Berater-Comic-Pfad der Stelle wird im per-Stelle-Render
        # (personalisierung.render_fuer_stelle) in fields['berater_comic'] injiziert; fehlt er, faellt
        # ensure_comic_beratung_bild auf den normalen Comic zurueck (kein Crash).
        return ensure_comic_beratung_bild(fields, (fields.get("berater_comic") or "").strip())
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
    return ensure_photo(motiv, fields=fields)

def _tool_praefix(tool):
    """Liefert den Datei-Praefix fuer ein Bild-Tool. OpenAI traegt KEINEN Praefix (bestehende
    Cache-Dateien bleiben gueltig); Ideogram traegt 'ideogram_', damit beide Anbieter fuer
    dasselbe Motiv getrennte Dateien bekommen (Catrin will vergleichen, #137)."""
    return "ideogram_" if (tool or "openai") == "ideogram" else ""


def _modell_praefix(tool=None):
    """Liefert den Datei-Praefix fuer das aktive OpenAI-Bildmodell in den COMIC-Caches (#161).
    Analog zum Tool-Praefix (#137): das Default-Modell gpt-image-1 traegt KEINEN Praefix (bestehende
    Comic-Cache-Dateien bleiben gueltig); gpt-image-2 traegt 'g2_'. So erzeugt ein Modellwechsel
    FRISCHE Bilder (A/B am selben Beitrag) statt das alte, mit dem anderen Modell erzeugte Bild aus
    dem Cache zu liefern. Nur der OpenAI-Pfad ist modellabhaengig - fuer Ideogram (kein GPT-Image)
    entfaellt der Praefix, damit sich dessen Cache beim Modellwechsel NICHT unnoetig aendert."""
    if tool is None:
        tool = aktives_bild_tool()
    if tool == "ideogram":
        return ""
    return "g2_" if openai_image_model() == "gpt-image-2" else ""


def _szene_pfad(motiv, tool=None):
    """Liefert den absoluten Cache-Pfad fuer das Standard-Szene-Foto zu 'motiv'.

    NEU: Bezieht PROMPT_VERSION in den Cache-Key ein - bei Prompt-Änderungen werden
    neue Bilder generiert statt alte Cache-Einträge zu verwenden!

    Hash-Formel: sha256("szene:" + PROMPT_VERSION + ":" + motiv)

    'tool' waehlt das Bild-Backend (#137): 'openai' (Default, KEIN Praefix -> bestehende
    Dateinamen unveraendert) oder 'ideogram' (Praefix 'ideogram_'). None -> aktuelle
    Einstellung (aktives_bild_tool())."""
    motiv = (motiv or "").strip()
    if not motiv or motiv.startswith("icon:"):
        return None
    if tool is None:
        tool = aktives_bild_tool()
    # Cache-Key enthält jetzt PROMPT_VERSION - bei Prompt-Änderungen neue Bilder!
    cache_key = f"szene:{PROMPT_VERSION}:{motiv}".lower()
    h = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
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
    # #158: Signatur (basename@mtime) statt nur Basename - ein ersetztes Referenzbild mit gleichem
    # Dateinamen (neue mtime) erneuert den Cache. Reihenfolge/Format bleiben stabil.
    ref_teil = "ref=%d;%s" % (1 if refs else 0, ",".join(_ref_signatur(p) for p in refs))
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
    # #161: Modell-Praefix (g2_ fuer gpt-image-2, sonst leer) -> Modellwechsel liefert frische Bilder.
    # #162: Fidelity-Marker (hf_ bei input_fidelity=high, sonst leer) -> Umschalten auf high liefert
    # einmalig frische, treuere Bilder (Prompt/Refs unveraendert). Genau EIN Ort pro Kette (hier).
    # Reihenfolge: Fidelity VOR Modell, damit der g2_-Modell-Praefix direkt an 'comic_' grenzt (bleibt
    # rueckwaertskompatibel zur bestehenden Praefix-Konvention).
    return os.path.join(MOTIV_DIR,
                        _tool_praefix(tool) + _fidelity_marker() + _modell_praefix(tool) + "comic_" + h + ".png")

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


def _input_fidelity():
    """Liefert den input_fidelity-Modus fuer den Comic-Referenz-/Edit-Call (images/edits) aus
    HILO_INPUT_FIDELITY (Default 'high', validiert) - #162. 'high' uebernimmt die Gesichter/Details
    der mitgegebenen Referenzbilder deutlich treuer (wichtig fuer den wiederkehrenden Aermelschoner
    und die Berater-Portraits); 'low' entspricht dem alten API-Default (das Gesicht wird
    generalisiert). Ungueltige Werte fallen sicher auf 'high' zurueck. Kapselt die ENV-Auswertung,
    damit Producer (erzeuge_comic_bild_ref) UND Cache-Marker (_fidelity_marker) dieselbe Quelle
    nutzen - nur so bleiben gesendeter Parameter und Cache-Datei konsistent."""
    v = (os.environ.get("HILO_INPUT_FIDELITY") or "high").strip().lower()
    return v if v in ("high", "low") else "high"


def _fidelity_marker():
    """Cache-Datei-Marker fuer input_fidelity (#162), analog _modell_praefix: 'hf_' wenn high-fidelity
    aktiv, sonst '' (low -> bestehende Comic-Cache-Dateien bleiben gueltig, rueckwaertskompatibel).
    input_fidelity aendert das Ergebnis, OHNE dass sich Prompt/Referenzen aendern; ohne diesen Marker
    wuerde der Cache die alten low-fidelity-Bilder liefern. Der Marker sitzt (wie _modell_praefix) an
    genau EINEM Ort pro Cache-Kette - in den *_pfad-Funktionen -, sodass Producer UND Aufraeumschutz
    denselben Schluessel sehen und beim Umschalten auf 'high' EINMALIG frische Bilder entstehen."""
    return "hf_" if _input_fidelity() == "high" else ""


def openai_payload(prompt, modell=None):
    """Baut das OpenAI images/generations-Request-Payload (ohne Netzwerkaufruf). Modell aus der
    Einstellung 'bild_modell' (openai_image_model(), Default gpt-image-1), background='opaque',
    size '1024x1024', quality aus HILO_IMAGE_QUALITY. Ausgelagert, damit Tests Modell/Parameter ohne
    Netz pruefen. 'modell' (#161): erlaubt dem Aufrufer, das Modell explizit zu setzen - genutzt vom
    Fallback-Retry in erzeuge_bild_openai (gpt-image-1). None -> aktuelles Einstellungs-Modell."""
    return {"model": modell or openai_image_model(), "prompt": prompt, "size": "1024x1024",
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


def erzeuge_bild_openai(prompt, modell=None):
    """Erzeugt ein Bild via OpenAI images/generations und liefert die PNG-Bytes (oder None).
    Ohne 'openai_api_key' -> None + Log (kein Crash). Robust gegen Netz-/API-Fehler.

    'modell' (#161): das zu nutzende OpenAI-Bildmodell; None -> aktuelles Einstellungs-Modell
    (openai_image_model()). Sicherheitsnetz: schlaegt der Call mit dem gewaehlten Modell fehl (z.B.
    Modell nicht verfuegbar) UND war es NICHT bereits gpt-image-1, wird EINMAL automatisch mit
    'gpt-image-1' (dem bewaehrten Default) nachgezogen (log.warning) - kein Ausfall durch ein
    fehlendes Test-Modell."""
    key = get_secret("openai_api_key")
    if not key:
        log.info("Bild uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    if modell is None:
        modell = openai_image_model()
    try:
        import requests
        # Bildqualitaet steuert die OpenAI-Kosten stark: low (~1-2ct) < medium (~4-6ct) < high
        # (~20-25ct) je 1024x1024-Bild. Default 'medium'; per Umgebungsvariable aenderbar.
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"},
            json=openai_payload(prompt, modell=modell),
            timeout=120)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        return base64.b64decode(b64)
    except Exception as ex:
        log.warning("OpenAI-Bild fehlgeschlagen (Modell %s): %s", modell, ex)
        if modell != OPENAI_IMAGE_MODEL_DEFAULT:
            log.warning("OpenAI-Bild: Fallback-Retry mit %s statt %s.", OPENAI_IMAGE_MODEL_DEFAULT, modell)
            return erzeuge_bild_openai(prompt, modell=OPENAI_IMAGE_MODEL_DEFAULT)
        return None


def _comic_edits_versuche(modell, sende_fidelity):
    """Liefert die geordnete, ENDLICHE Liste der images/edits-Versuche fuer den Comic-Referenz-/Edit-
    Pfad (#162) als Tupel (modell, mit_fidelity). Reihenfolge des Sicherheitsnetzes:
      1. gewaehltes Modell MIT input_fidelity=high (nur wenn sende_fidelity, also HILO_INPUT_FIDELITY
         == 'high'),
      2. gewaehltes Modell OHNE input_fidelity (deckt 'Parameter unbekannt' ab - die API kennt den
         Parameter evtl. nicht),
      3. gpt-image-1 OHNE input_fidelity (bestehender Modell-Fallback #161), nur wenn das gewaehlte
         Modell NICHT bereits der Default ist.
    Duplikate (gleiche (modell, mit_fidelity)-Kombination) werden unter Erhalt der Reihenfolge
    entfernt - so entstehen bei 'low' (keine Fidelity) oder bereits gesetztem Default-Modell KEINE
    unnoetigen Doppel-Calls und garantiert keine Endlosschleife (feste, kleine Versuchsliste)."""
    versuche = []
    if sende_fidelity:
        versuche.append((modell, True))
    versuche.append((modell, False))
    if modell != OPENAI_IMAGE_MODEL_DEFAULT:
        versuche.append((OPENAI_IMAGE_MODEL_DEFAULT, False))
    entdoppelt = []
    for v in versuche:
        if v not in entdoppelt:
            entdoppelt.append(v)
    return entdoppelt


def erzeuge_comic_bild_ref(prompt, refs, modell=None):
    """Erzeugt ein Comic-Bild via OpenAI images/edits MIT Referenzbildern (Stil- + optional
    Charakter-Referenz) und liefert die PNG-Bytes (oder None). multipart/form-data wie
    erzeuge_bild_openai (gleicher Key/Bearer/Timeout-Stil):
      data:  model, prompt, size='1024x1024', quality, n='1' (KEIN background-Feld beim edits-Call);
             #162: bei HILO_INPUT_FIDELITY='high' zusaetzlich input_fidelity='high' - uebernimmt die
             Gesichter/Details der Referenzbilder deutlich treuer.
      files: fuer JEDEN Pfad in 'refs' ein Feld ('image[]', (basename, filehandle, 'image/png')) -
             gpt-image-1 akzeptiert mehrere Referenzbilder.
    Ohne 'openai_api_key', bei HTTP-/Netz-Fehler oder sonstiger Exception -> None (der Aufrufer
    faellt dann auf den generations-Weg zurueck). Der Key wird NIE geloggt; alle geoeffneten
    Dateihandles werden je Versuch im finally sauber geschlossen. Content-Type setzt requests selbst
    (multipart-Boundary) - hier NICHT manuell setzen.

    'modell' (#161): das zu nutzende OpenAI-Bildmodell; None -> aktuelles Einstellungs-Modell
    (openai_image_model()).

    Sicherheitsnetz (#162, ENDLICH, ohne Rekursion): kennt die API input_fidelity nicht (oder schlaegt
    der Call anderweitig fehl), wird die feste Versuchsliste aus _comic_edits_versuche() abgearbeitet:
    (1) gewaehltes Modell mit input_fidelity=high, (2) gewaehltes Modell OHNE input_fidelity,
    (3) gpt-image-1 OHNE input_fidelity (Modell-Fallback). Jeder Versuch oeffnet FRISCHE Dateihandles
    und schliesst sie im finally, bevor der naechste startet (log.warning je Fallback). Erst wenn ALLE
    Versuche scheitern -> None."""
    key = get_secret("openai_api_key")
    if not key:
        log.info("Comic-Referenzbild uebersprungen: kein 'openai_api_key' hinterlegt (secrets.json).")
        return None
    if modell is None:
        modell = openai_image_model()
    fidelity = _input_fidelity()
    versuche = _comic_edits_versuche(modell, fidelity == "high")
    letzter = len(versuche) - 1
    for i, (versuch_modell, mit_fidelity) in enumerate(versuche):
        handles = []
        try:
            import requests
            data = {"model": versuch_modell, "prompt": prompt, "size": "1024x1024",
                    "quality": _openai_quality(), "n": "1"}
            # #162: input_fidelity NUR im Edit-/Referenzpfad und nur solange der Versuch es vorsieht
            # (Versuch 1). Faellt der Parameter als Fehlerursache aus, laesst ihn der naechste Versuch
            # bewusst weg. Der generations-Weg (erzeuge_bild_openai) bleibt hiervon unberuehrt.
            if mit_fidelity:
                data["input_fidelity"] = fidelity
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
            log.warning("OpenAI-Comic-Referenzbild fehlgeschlagen (Modell %s, input_fidelity=%s): %s",
                        versuch_modell, fidelity if mit_fidelity else "-", ex)
            if i < letzter:
                naechst_modell, naechst_fid = versuche[i + 1]
                log.warning("OpenAI-Comic-Referenzbild: Fallback-Retry (Modell %s, input_fidelity=%s).",
                            naechst_modell, fidelity if naechst_fid else "-")
            # letzter Versuch fehlgeschlagen -> nach dem finally faellt die Schleife auf 'return None'.
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass
    return None


# --- Comic-Portrait der Beratungsstellen-Leitung (Stil "Comic Beratung", Setup) ----------------
# Exakter Prompt fuer das wiederkehrende Comic-Portrait der Leitung. Bewusst als Konstante, damit
# Producer (erzeuge_berater_comic) und Tests denselben Wortlaut nutzen.
BERATER_PORTRAIT_PROMPT = (
    "Create a friendly, modern comic portrait, head and shoulders, of the SAME person shown in the "
    "provided photograph, redrawn in a clean ligne claire comic style (clean elegant outlines, flat "
    "colours, light natural shading, a warm friendly modern comic look). Aim for a FLATTERING but "
    "AUTHENTIC likeness of a friendly adult professional. Keep their real features so they clearly "
    "look like THEMSELVES, but flattering and FRESH: fairly SMOOTH skin with only a light, subtle "
    "hint of character and MINIMAL facial lines and very soft shading - a little younger and fresher, "
    "yet still a natural adult (NOT a 20-year-old, NOT an idealised face). No deep wrinkles, no heavy "
    "face shading, no extra weight. Recognisable, dignified, likeable, with a friendly smile "
    "and bright, wide-awake, alert and attentive eyes - a lively, energetic expression, NOT tired, "
    "sleepy or droopy. They wear a small HILO logo badge with the wordmark 'HILO' in WHITE letters "
    "on the lapel or chest. Simple clean light background. Square format."
)


def erzeuge_berater_comic(foto_path):
    """Erzeugt aus dem Leitungs-Foto einer Beratungsstelle ein Comic-Portrait (Stil "Comic
    Beratung") und liefert den gespeicherten PNG-Pfad (oder None).

    Ruft erzeuge_comic_bild_ref(BERATER_PORTRAIT_PROMPT, [foto_path]) auf - NUR das Leitungs-Foto
    als Referenz (KEIN Stil-Referenzbild: das van-Gogh-Stilbild wuerde fremde Alters-/Gesichtszuege
    einmischen und die Person aelter machen; der Ligne-claire-Stil kommt aus dem Prompt). Ergebnis
    werden nach DATA_DIR/berater/comic_<stelleid>.png geschrieben (die Stellen-ID wird aus dem
    Datei-Basenamen des Fotos abgeleitet - 'stelle_<id>' oder 'foto_<id>'), der Pfad zurueckgegeben.

    Robust: fehlendes Foto, kein 'openai_api_key', API-/Netz-/Schreibfehler -> None (kein Crash).
    Das echte Gesicht/Comic wird NUR ueber login-geschuetzte Routen ausgeliefert (DSGVO)."""
    if not foto_path or not os.path.exists(foto_path):
        log.info("Berater-Comic uebersprungen: kein Leitungs-Foto vorhanden (%r).", foto_path)
        return None
    try:
        daten = erzeuge_comic_bild_ref(BERATER_PORTRAIT_PROMPT, [foto_path])
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

# --- Stil "Comic Beratung" (comic_beratung) - personalisiert pro Beratungsstelle ----------------
def _finanzamt_bibel_bild():
    """Liefert den Pfad zur globalen Finanzamt-Bible (Einstellung 'finanzamt_bibel_bild'), falls
    gesetzt UND die Datei existiert - sonst ''. Kapselt den DB-Zugriff, damit Referenz-Liste und
    Cache-Key dieselbe Quelle nutzen. Fehlertolerant (DB-/Import-Fehler -> '')."""
    try:
        import db
        p = (db.get_einstellung("finanzamt_bibel_bild") or "").strip()
        return p if (p and os.path.exists(p)) else ""
    except Exception:
        return ""

def _finanzamt_bibel_text():
    """Liefert die globale Finanzamt-Bible-Beschreibung (Einstellung 'finanzamt_bibel_text') oder ''.
    Fehlertolerant (DB-/Import-Fehler -> '')."""
    try:
        import db
        return (db.get_einstellung("finanzamt_bibel_text") or "").strip()
    except Exception:
        return ""

def _finanzamt_ref_pfad():
    """Liefert den Pfad der Finanzamt-Referenz fuer comic_beratung: die globale Finanzamt-Bible
    (finanzamt_bibel_bild), falls gesetzt+vorhanden - sonst die Default-Referenz FINANZAMT_REF_PATH.
    So kann Catrin den wiederkehrenden Finanzamt-Charakter global ueber eine eigene Bible-Vorlage
    steuern (#151), ohne dass sich ohne Bible etwas am bisherigen Verhalten aendert."""
    return _finanzamt_bibel_bild() or FINANZAMT_REF_PATH

def _comic_beratung_prompt(fields, berater_ref_pfad=None):
    """Baut den Comic-Beratung-Bildprompt: HILO_COMIC_MASTER (der von Catrins ChatGPT-Projekt
    entwickelte, ausgereifte HILO-Stil-Masterprompt) + BERATUNG_BLOCK (Komposition + HILO-Buero).
    Bewusst OHNE das Beitrags-Thema (kein 'Thema/Anlass'): das Thema trieb die Szene sonst woertlich
    (z.B. eine Gelduebergabe -> wirkte wie ein 'Deal'). 'Comic Beratung' ist IMMER eine warme
    Schreibtisch-Beratung; der inhaltliche Bezug lebt im Begleittext.

    NEU (#151, Character-Bible): Ist fuer die Stelle eine Charakter-Beschreibung hinterlegt
    (fields['bibel_text'], von personalisierung durchgereicht), wird sie ANGEHAENGT - so folgt die
    Bild-KI der verbindlichen Beschreibung des/der Berater:in. OHNE bibel_text bleibt der Prompt
    WORTGLEICH (Minimal-Change, robust gegen leer).

    #153: Der Finanzamt-Beamte ist aus 'Comic Beratung' entfernt - die globale Finanzamt-Bible wird
    hier NICHT mehr angehaengt (bleibt nur im witzigen Comic). NICHT STIL_A_BLOCK (das ist der witzige
    Comic-Stil mit Karikaturen - der Master verlangt bewusst KEINE Karikaturen)."""
    prompt = HILO_COMIC_MASTER + "\n\n" + BERATUNG_BLOCK
    f = fields if isinstance(fields, dict) else {}
    bibel_text = (f.get("bibel_text") or "").strip()
    if bibel_text:
        prompt += ("\n\nVerbindliche Charakter-Beschreibung des/der Berater:in "
                   "(Character-Bible der Stelle): " + bibel_text)
    # #159: Referenz-Anker anhaengen, WENN eine (existierende) Berater-Referenz vorliegt - dann geht
    # das Berater-Portrait als images/edits-Referenz mit und wird per Text verbindlich verankert.
    # OHNE gueltige Referenz (Default None / fehlendes Asset) bleibt der Prompt unveraendert; beide
    # Aufrufer (Cache-Key + Producer) reichen denselben Pfad durch -> identischer Prompt/Schluessel.
    if _comic_beratung_refs(berater_ref_pfad):
        prompt += "\n\n" + REF_ANCHOR
    return prompt

def _comic_beratung_refs(berater_comic_pfad):
    """Liefert die Liste der EXISTIERENDEN Referenzbild-Pfade: den Berater-Comic der Stelle
    (das 'first reference image' aus BERATUNG_BLOCK -> das Gesicht des/der Berater:in). Nur
    tatsaechlich vorhandene Dateien werden aufgenommen, damit ein fehlendes Asset nicht zum Fehler
    fuehrt.

    #153: Der Finanzamt-Beamte ist aus 'Comic Beratung' entfernt - hier wird KEINE Finanzamt-Referenz
    mehr angehaengt (der wiederkehrende Finanzamt-Charakter bleibt nur im witzigen Comic). Der
    Berater-Vorrang bibel_bild > berater_comic wird bereits in personalisierung aufgeloest (das
    bevorzugte Bild landet in fields['berater_comic'] und damit in berater_comic_pfad)."""
    refs = []
    p = (berater_comic_pfad or "").strip()
    if p and os.path.exists(p):
        refs.append(p)
    return refs

def _comic_beratung_cache_input(fields, berater_comic_pfad):
    """Hash-Eingabestring fuer den Comic-Beratung-Cache: 'comic_beratung:' + vollstaendiger Prompt +
    Basename des Berater-Comics. So bekommt JEDE Beratungsstelle (eigener Berater-Comic) eine EIGENE
    Cache-Datei - verschiedene Berater kollidieren nicht. Der Prompt enthaelt (#151) auch bibel_text,
    sodass Aenderungen an der Berater-Charakter-Beschreibung den Cache automatisch erneuern.

    #153: Der Finanzamt-Beamte ist aus 'Comic Beratung' entfernt - die Finanzamt-Bible fliesst NICHT
    mehr in den Schluessel. Da sich BERATUNG_BLOCK aendert, erneuert sich der Cache ohnehin automatisch."""
    # #158: Signatur (basename@mtime) statt nur Basename - ein ersetzter Berater-Comic mit gleichem
    # Dateinamen (neue mtime) erneuert den Cache. Format '|berater=' bleibt stabil.
    base = _ref_signatur(berater_comic_pfad)
    return ("comic_beratung:" + _comic_beratung_prompt(fields, berater_comic_pfad)
            + "|berater=" + base)

def _comic_beratung_pfad(fields, berater_comic_pfad, tool=None):
    """Absoluter Cache-Pfad fuer ein Comic-Beratung-Bild. EIGENER Praefix 'comic_beratung_'
    (sha256[:16] aus _comic_beratung_cache_input), getrennt von szene/tafel/kreativ/comic. Der
    Berater-Comic-Basename fliesst in den Hash -> pro Stelle/Berater eine eigene Datei. Tool-abhaengig
    (#137) wie die uebrigen Pfade (openai ohne, ideogram-Praefix)."""
    if tool is None:
        tool = aktives_bild_tool()
    h = hashlib.sha256(
        _comic_beratung_cache_input(fields, berater_comic_pfad).lower().encode("utf-8")).hexdigest()[:16]
    # #161: Modell-Praefix (g2_ fuer gpt-image-2, sonst leer) -> Modellwechsel liefert frische Bilder.
    # #162: Fidelity-Marker (hf_ bei input_fidelity=high) analog _modell_praefix -> frische high-Bilder.
    # Fidelity VOR Modell, damit der g2_-Praefix direkt an 'comic_beratung_' grenzt (Konvention).
    return os.path.join(MOTIV_DIR,
                        _tool_praefix(tool) + _fidelity_marker() + _modell_praefix(tool) + "comic_beratung_" + h + ".png")

def ensure_comic_beratung_bild(fields, berater_comic_pfad):
    """Erzeugt (oder liefert aus dem Cache) das personalisierte Comic-Beratung-Bild: vorne der/die
    Berater:in DER STELLE (Comic-Figur nach 'berater_comic_pfad'), hinten der Finanzamt-Beamte, der
    leer ausgeht. Prompt = STIL_A_BLOCK + BERATUNG_BLOCK (+ optional Thema aus comic_brief.szene);
    refs = [berater_comic_pfad, FINANZAMT_REF_PATH] (nur existierende Dateien) via images/edits.

    Cache pro Stelle/Berater (Berater-Comic-Basename im Hash). FALLBACK ohne gueltigen
    berater_comic_pfad: es wird auf den normalen Comic (ensure_comic_bild) zurueckgefallen - so
    entsteht nie ein Crash, nur eben ohne persoenliches Berater-Gesicht. Liefert None, wenn auch der
    Referenz- UND der generations-Weg kein Bild liefern (kein Key/Fehler) -> Creme-Fallback im Render."""
    p = (berater_comic_pfad or "").strip()
    if not p or not os.path.exists(p):
        # Kein (gueltiger) Berater-Comic -> normaler Comic, damit die Stelle trotzdem ein Bild bekommt.
        log.info("Comic-Beratung ohne Berater-Comic (%r) -> Fallback normaler Comic.", berater_comic_pfad)
        return ensure_comic_bild(fields)
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    path = _comic_beratung_pfad(fields, p, tool=tool)
    if os.path.exists(path):
        return path
    prompt = _comic_beratung_prompt(fields, p)
    refs = _comic_beratung_refs(p)
    daten = erzeuge_comic_bild_ref(prompt, refs) if refs else None
    if daten is None:
        # Referenz-Call ohne Key/Fehler -> generations-Weg (ohne Berater-Gesicht, aber kein Crash).
        daten = erzeuge_bild(prompt, tool=tool)
    if daten is None:
        return None
    try:
        with open(path, "wb") as f:
            f.write(daten)
        log.info("Comic-Beratung-Bild erzeugt (%s), Berater=%s", tool, os.path.basename(p))
        return path
    except Exception as ex:
        log.warning("Comic-Beratung-Bild speichern fehlgeschlagen: %s", ex)
        return None

# --- Stil "Comic-Strip" (comic_strip, #154) - 3-Felder-Karussell mit Sprechblasen ----------------
# Ein 3-teiliger Comic als Karussell (immer 3 Panels/Slides) mit KI-geschriebenen Sprechblasen,
# personalisiert pro Beratungsstelle. Text-Variante A: die Bild-KI schreibt den vorgegebenen
# deutschen Satz direkt in eine Sprech-/Gedankenblase (menschliche Freigabe faengt Vertipper ab).
# Panel-Delta-Texte (auf HILO_COMIC_MASTER): je Feld die Szene + Rolle. Die 1. Referenz ist der/die
# Berater:in DER STELLE (Feld 1+3), in Feld 2 der wiederkehrende Finanzamt-Beamte.
COMIC_STRIP_PANEL1_DELTA = (
    "Szene (Feld 1 von 3): der/die HILO-Berater:in sitzt mit einem Mitglied an einem Schreibtisch in "
    "einem hellen, modernen HILO-Beratungsraum und erklaert freundlich und kompetent einen Vorteil. "
    "Der/die Berater:in sieht aus wie die ERSTE Referenz (Gesicht, Frisur, Alter exakt uebernehmen) "
    "und traegt ein kleines HILO-Logo (Schriftzug 'HILO' in WEISSER Schrift) am Revers. Freundliche, "
    "zugewandte Gespraechssituation, echter Blickkontakt."
)
COMIC_STRIP_PANEL2_DELTA = (
    "Szene (Feld 2 von 3): der wiederkehrende Finanzamt-Beamte (grauer Anzug, runde Brille, beige "
    "Aermelschoner, Stifte in der Brusttasche) sitzt deprimiert und geknickt an seinem Schreibtisch "
    "unter einem gut lesbaren Schild mit der Aufschrift 'Finanzamt'. Er sieht aus wie die ERSTE "
    "Referenz (gleicher wiederkehrender Charakter). Sympathisch und komisch, nie boesartig; seine "
    "Miene ist niedergeschlagen, weil ihm Steuern entgehen."
)
COMIC_STRIP_PANEL3_DELTA = (
    "Szene (Feld 3 von 3): der/die HILO-Berater:in laechelt zufrieden und zeigt Daumen hoch. "
    "Der/die Berater:in sieht aus wie die ERSTE Referenz (Gesicht, Frisur, Alter exakt uebernehmen) "
    "und traegt ein kleines HILO-Logo (Schriftzug 'HILO' in WEISSER Schrift) am Revers. Positive, "
    "abschliessende Stimmung wie am Ende einer gelungenen Beratung."
)
# Default-Jammersatz fuer Feld 2 (v1 fest; themenspezifischer Jammersatz erst in v2). Wortlaut aus
# dem Auftrag (Catrin), Markenname exakt "HILO".
COMIC_STRIP_JAMMER = ("Jetzt entgehen mir schon wieder Steuern, weil jemand bei HILO zur Beratung "
                      "war.")
# Feste Pointe fuer Feld 3 (v1 fest, Markenname exakt "HILO").
COMIC_STRIP_POINTE = "HILO - wir machen es einfach!"

# --- v2 (#155): zwei Story-Archetypen, gesteuert ueber die Bild-2-Auswahl -------------------------
# 'vorteil'  = jemand WAR bei HILO -> trauriger/geknickter Aermelschoner (der bestehende v1-Strip).
# 'warnung'  = jemand war NICHT bei HILO -> schadenfroher Aermelschoner, der rot "ABGELEHNT"
#              stempelt. Bild 1 UND Bild 2 unterscheiden sich je Archetyp; Bild 3 zeigt in beiden
#              Faellen den/die Berater:in (Daumen hoch) - nur der Sprechblasen-Text unterscheidet sich.
COMIC_STRIP_PANEL1_DELTA_WARNUNG = (
    "Szene (Feld 1 von 3): eine Person (Nichtmitglied) sitzt GANZ ALLEIN an einem Tisch und fuellt "
    "ihre Steuererklaerung am Smartphone/Handy aus - naiv-optimistisch und gutglaeubig laechelnd, "
    "voller Vertrauen, dass das schon passt. KEIN Berater, KEINE zweite Person im Bild. Alltaegliche "
    "Wohnzimmer-/Kuechen-Umgebung, Belege und Papiere liegen unsortiert herum."
)
COMIC_STRIP_PANEL2_DELTA_WARNUNG = (
    "Szene (Feld 2 von 3): der wiederkehrende Finanzamt-Beamte (grauer Anzug, runde Brille, beige "
    "Aermelschoner, Stifte in der Brusttasche) sitzt schadenfroh grinsend und lachend an seinem "
    "Schreibtisch unter einem gut lesbaren Schild mit der Aufschrift 'Finanzamt' und stempelt gerade "
    "mit einem grossen Stempel ein deutlich lesbares, ROTES 'ABGELEHNT' auf ein Formular. Er sieht "
    "aus wie die ERSTE Referenz (gleicher wiederkehrender Charakter). Sympathisch und komisch, nie "
    "boesartig; haemisch-schadenfrohe Freude, weil hier jemand OHNE HILO-Beratung draufzahlt."
)
# Aliase fuer den bestehenden (vorteil-)Strip: Bild 1 = Beratungsszene, Bild 2 = trauriger
# Aermelschoner (v1-Wortlaut bleibt unveraendert).
COMIC_STRIP_PANEL1_DELTA_VORTEIL = COMIC_STRIP_PANEL1_DELTA
COMIC_STRIP_PANEL2_DELTA_VORTEIL = COMIC_STRIP_PANEL2_DELTA

# Bild-2-Sprechblasen-Varianten je Archetyp (Wortlaut aus dem #155-Design, Catrin 2026-07-05). Die
# gewaehlte Variante bestimmt zugleich den Archetyp; Index 0 ist der Default der KI-Vorauswahl.
COMIC_STRIP_VARIANTEN = {
    "vorteil": [
        "Schon wieder jemand, der bei HILO war ...",
        "Schade, weniger Steuern fürs Finanzamt - diese HILO-Berater!",
        "Wieder nichts zu holen - die waren bei HILO.",
        "Diese HILO-Beratung kostet mich ständig Steuern ...",
    ],
    "warnung": [
        "Ha! Mal wieder jemand, der nicht bei HILO war ...",
        "Schön blöd - ohne HILO zahlt man drauf.",
        "Herrlich, wieder einer ohne HILO-Beratung!",
        "Da freut sich das Finanzamt - kein HILO im Spiel.",
    ],
}
# Feste Pointe (Bild 3) je Archetyp (Markenname exakt "HILO").
COMIC_STRIP_POINTE_ARCHETYP = {
    "vorteil": COMIC_STRIP_POINTE,                     # "HILO - wir machen es einfach!"
    "warnung": "Komm zu HILO - wir machen es einfach!",
}

# --- #160: Szenen-/Posen-Varianten je Panel-Rolle (pro Beitrag deterministisch anders) -----------
# Damit zwei Beitraege mit derselben Rolle NICHT exakt dasselbe Bild bekommen (langweilig), variieren
# wir Umgebung/Pose je Beitrag. Der KERN (Rolle, Mimik, Sprechblase, Archetyp) bleibt im Panel-Delta
# unveraendert; die Variante ist nur ein kurzer Umgebungs-Zusatz. Deutsch, echte Umlaute.
# Feld 2 (Aermelschoner) - gilt fuer beide Archetypen (Kern -> trauriger bzw. schadenfroher Beamter):
COMIC_STRIP_SZENEN_AERMELSCHONER = (
    "an seinem ueberladenen Schreibtisch",
    "vor einem Aktenschrank voller Ordner",
    "mit einem Stempel in der Hand",
    "neben einem hohen Papierstapel",
    "am Fenster mit Blick auf graue Amtsflure",
    "vor einer Pinnwand voller Formulare",
)
# Feld 1 'vorteil' (Beratungsszene mit dem/der Berater:in):
COMIC_STRIP_SZENEN_BERATUNG = (
    "am Schreibtisch mit Laptop",
    "am Besprechungstisch mit Unterlagen",
    "mit einem Tablet erklaerend",
    "vor dem Buecherregal stehend",
)
# Feld 1 'warnung' (die Person fuellt ALLEIN am Handy aus):
COMIC_STRIP_SZENEN_ALLEIN = (
    "am Kuechentisch",
    "auf dem Sofa",
    "am heimischen Schreibtisch",
    "in einem Cafe",
)
# Feld 3 (Berater:in, Daumen hoch) - fuer beide Archetypen gleich:
COMIC_STRIP_SZENEN_DAUMEN = (
    "am Schreibtisch",
    "im Beratungsraum vor dem Regal",
    "vor einem HILO-Plakat",
    "am Fenster",
)

# Panel-Reihenfolge (vorteil = Default/v1): (Delta-Text, Zeilen-Quelle). Die Zeilen-Quelle ist ein
# Marker; die konkrete Zeile wird in _comic_strip_zeile aufgeloest (Feld 1 = Ueberschrift/Override,
# 2 = Bild-2-Variante, 3 = Pointe). v2 (#155): _comic_strip_panels(archetyp) liefert die passenden
# Panel-Deltas je Archetyp.
_COMIC_STRIP_PANELS = (
    (COMIC_STRIP_PANEL1_DELTA_VORTEIL, "ueberschrift"),
    (COMIC_STRIP_PANEL2_DELTA_VORTEIL, "jammer"),
    (COMIC_STRIP_PANEL3_DELTA, "pointe"),
)


def _norm_archetyp(val):
    """Normalisiert einen Archetyp-Wert auf 'vorteil'/'warnung' (case-insensitiv, getrimmt);
    unbekannt/leer -> '' (der Aufrufer setzt dann seinen eigenen Default)."""
    a = str(val).strip().lower() if val is not None else ""
    return a if a in ("vorteil", "warnung") else ""


def _comic_strip_panels(archetyp):
    """Liefert die 3 (Delta, Quelle)-Panels fuer den gewaehlten Archetyp. 'warnung' nutzt die
    Allein-am-Handy-Szene (Feld 1) + den schadenfrohen, 'ABGELEHNT'-stempelnden Aermelschoner
    (Feld 2); 'vorteil' (Default) den bestehenden v1-Strip. Feld 3 ist in beiden Faellen der/die
    Berater:in (Daumen hoch), nur der Text (Pointe) unterscheidet sich."""
    if _norm_archetyp(archetyp) == "warnung":
        return (
            (COMIC_STRIP_PANEL1_DELTA_WARNUNG, "ueberschrift"),
            (COMIC_STRIP_PANEL2_DELTA_WARNUNG, "jammer"),
            (COMIC_STRIP_PANEL3_DELTA, "pointe"),
        )
    return _COMIC_STRIP_PANELS


def _comic_strip_variante_archetyp(text):
    """Liefert den Archetyp ('vorteil'/'warnung') zu einer konkreten Bild-2-Variante (exakter
    Wortlaut aus COMIC_STRIP_VARIANTEN). Unbekannter/leerer Text -> None."""
    t = (text or "").strip()
    if not t:
        return None
    for arche, varianten in COMIC_STRIP_VARIANTEN.items():
        if t in varianten:
            return arche
    return None


def _comic_strip_szenen_liste(quelle, archetyp):
    """Liefert die Szenen-/Posen-Varianten-Liste (#160) fuer ein Panel je Rolle:
      - 'jammer' (Feld 2): Aermelschoner-Umgebungen (fuer beide Archetypen gleich).
      - 'pointe' (Feld 3): Berater:in Daumen-hoch-Umgebungen (fuer beide Archetypen gleich).
      - 'ueberschrift' (Feld 1): archetyp-abhaengig - 'warnung' = allein am Handy, sonst Beratungsszene.
    Der KERN der Rolle (aus dem Panel-Delta) bleibt unveraendert; die Variante ergaenzt nur Umgebung/Pose."""
    if quelle == "jammer":
        return COMIC_STRIP_SZENEN_AERMELSCHONER
    if quelle == "pointe":
        return COMIC_STRIP_SZENEN_DAUMEN
    if _norm_archetyp(archetyp) == "warnung":
        return COMIC_STRIP_SZENEN_ALLEIN
    return COMIC_STRIP_SZENEN_BERATUNG


def _comic_strip_beitrag_kennung(fields):
    """Liefert eine STABILE Beitrags-Kennung fuer die deterministische Szenen-Auswahl (#160):
    bevorzugt eine vorhandene ID (id/entwurf_id/eid/beitrag_id), sonst die Ueberschrift, sonst
    strip_zeile1. Gleicher Beitrag -> gleiche Kennung -> stabile Szenen-Variante; anderer Beitrag ->
    andere Kennung -> i.d.R. andere Variante. Leerer/ungueltiger Input -> ''."""
    f = fields if isinstance(fields, dict) else {}
    for schluessel in ("id", "entwurf_id", "eid", "beitrag_id"):
        v = f.get(schluessel)
        if v not in (None, "", 0):
            return str(v)
    return ((f.get("ueberschrift") or "").strip()
            or (f.get("strip_zeile1") or "").strip())


def _comic_strip_szene(fields, quelle, archetyp):
    """Waehlt DETERMINISTISCH die Szenen-/Posen-Variante fuer dieses Panel (#160):
    Index = sha256(Beitrags-Kennung + '|' + Rolle) % len(varianten). Die Rolle ('quelle') wird
    mit-gehasht, damit die drei Felder eines Beitrags UNABHAENGIG variieren (nicht alle denselben
    Index). Gleicher Beitrag -> gleiche Variante je Feld (stabil, gleicher Cache); anderer Beitrag ->
    i.d.R. andere Variante -> anderer Cache-Pfad -> anders aussehende Panels. Leere Kennung/leere
    Liste -> '' (kein Zusatz, bisheriges Verhalten)."""
    varianten = _comic_strip_szenen_liste(quelle, archetyp)
    kennung = _comic_strip_beitrag_kennung(fields)
    if not varianten or not kennung:
        return ""
    roh = ("%s|%s" % (kennung, quelle)).encode("utf-8")
    idx = int(hashlib.sha256(roh).hexdigest(), 16) % len(varianten)
    return varianten[idx]


def _comic_strip_archetyp(fields):
    """Ermittelt den Archetyp fuer den Comic-Strip: zuerst fields['strip_archetyp'] (explizit aus der
    UI persistiert), sonst die leichte KI-Vorauswahl (textgen.comic_strip_vorauswahl, robust mit
    Fallback ohne Key), sonst 'vorteil' (bisheriges v1-Verhalten). Nie ein Crash."""
    f = fields if isinstance(fields, dict) else {}
    a = _norm_archetyp(f.get("strip_archetyp"))
    if a:
        return a
    try:
        import textgen
        vor = textgen.comic_strip_vorauswahl(f)
        a = _norm_archetyp((vor or {}).get("archetyp"))
        if a:
            return a
    except Exception as ex:
        log.warning("Comic-Strip Archetyp-Vorauswahl fehlgeschlagen: %s", ex)
    return "vorteil"


def _comic_strip_zeile(fields, quelle, archetyp="vorteil"):
    """Liefert den Sprechblasen-Text fuer ein Panel je Quelle:
      - 'ueberschrift' (Feld 1): das optionale Override fields['strip_zeile1'] (#156) hat Vorrang,
        sonst die Beitrags-Ueberschrift, sonst die (archetyp-abhaengige) Pointe.
      - 'jammer' (Feld 2): die gewaehlte Bild-2-Variante fields['strip_zeile2'] (falls gesetzt),
        sonst der Default des Archetyps (vorteil = v1-Wortlaut COMIC_STRIP_JAMMER; warnung = erste
        schadenfrohe Variante).
      - 'pointe' (Feld 3): die feste, archetyp-abhaengige Pointe.
    Robust gegen fehlende/leere Werte; 'archetyp' default 'vorteil' (rueckwaertskompatibel zu v1)."""
    archetyp = _norm_archetyp(archetyp) or "vorteil"
    f = fields if isinstance(fields, dict) else {}
    if quelle == "jammer":
        z = (f.get("strip_zeile2") or "").strip()
        if z:
            return z
        if archetyp == "warnung":
            return COMIC_STRIP_VARIANTEN["warnung"][0]
        return COMIC_STRIP_JAMMER
    if quelle == "pointe":
        return COMIC_STRIP_POINTE_ARCHETYP.get(archetyp, COMIC_STRIP_POINTE)
    override = (f.get("strip_zeile1") or "").strip()
    if override:
        return override
    return ((f.get("ueberschrift") or "").strip()
            or COMIC_STRIP_POINTE_ARCHETYP.get(archetyp, COMIC_STRIP_POINTE))


def _comic_strip_prompt(fields, delta, zeile, hat_ref=False, szene="", figur=""):
    """Baut den Panel-Prompt: HILO_COMIC_MASTER + optionaler Figur-Steckbrief + Panel-Delta
    (Szene/Rolle) + explizite Sprechblasen-Anweisung (Variante A): die KI schreibt GENAU den gegebenen
    deutschen Satz in eine Sprech-/Gedankenblase, fehlerfrei und ohne weitere Woerter; Markenname
    exakt 'HILO'.

    #161 (Reihenfolge Stil -> Figur -> Szene): 'figur' (kurzer Figur-Steckbrief) wird - wenn gesetzt -
    zwischen die Stilregel (HILO_COMIC_MASTER) und das Panel-Delta (Szene) gesetzt. Feld 2 nutzt den
    Finanzamt-Steckbrief (FINANZAMT_FIGUR), Feld 1/3 den Berater-Steckbrief der Stelle (bibel_text) -
    beides bestimmt der Aufrufer (ensure_comic_strip_bilder). Da 'figur' Teil des Panel-Prompts ist
    und derselbe Prompt-String in _comic_strip_pfad fliesst, sehen Producer und Cache-Key denselben
    Prompt (kein Falsch-Cache, wie bei #159/#160).

    #160: 'szene' (kurzer Umgebungs-/Posen-Zusatz) wird - wenn gesetzt - an das Panel-Delta gehaengt.
    So aendert sich der Prompt je Beitrag -> _comic_strip_pfad-Cache differiert je Beitrag -> jeder
    Beitrag bekommt EIGENE, anders aussehende Panels (Kern/Rolle bleibt aus dem Delta erhalten).

    #159: 'hat_ref' - ist fuer dieses Panel tatsaechlich eine Charakter-Referenz vorhanden, wird der
    Referenz-Anker (REF_ANCHOR) angehaengt, der die KI auf das mitgegebene Referenzportrait
    verpflichtet. OHNE Referenz (generations-Fallback) bleibt der Prompt ohne Anker."""
    zeile = (zeile or "").strip()
    szene = (szene or "").strip()
    figur = (figur or "").strip()
    if szene:
        delta = delta + " Konkrete Umgebung/Pose fuer dieses Bild: " + szene + "."
    blase = ('Zeichne eine Sprech-/Gedankenblase mit exakt diesem deutschen Text, fehlerfrei und '
             'ohne weitere Woerter: "%s". Markenname exakt HILO.' % zeile)
    prompt = HILO_COMIC_MASTER
    if figur:
        prompt += "\n\n" + figur
    prompt += "\n\n" + delta + "\n\n" + blase
    if hat_ref:
        prompt += "\n\n" + REF_ANCHOR
    return prompt


def _comic_strip_refs(idx, berater_ref_pfad):
    """Liefert die EXISTIERENDEN Referenzbild-Pfade fuer Panel 'idx' (0-basiert): Feld 1+3 (idx 0/2)
    nutzen die Berater-Referenz DER STELLE, Feld 2 (idx 1) den wiederkehrenden Finanzamt-Beamten
    (_finanzamt_ref_pfad). Nur tatsaechlich vorhandene Dateien werden aufgenommen, damit ein
    fehlendes Asset nicht zum Fehler fuehrt (der Aufrufer faellt dann auf erzeuge_bild zurueck)."""
    if idx == 1:
        kandidat = _finanzamt_ref_pfad()
    else:
        kandidat = (berater_ref_pfad or "").strip()
    return [kandidat] if (kandidat and os.path.exists(kandidat)) else []


def _comic_strip_pfad(idx, prompt, berater_ref_pfad, tool=None):
    """Absoluter Cache-Pfad fuer EIN Comic-Strip-Panel. EIGENER Praefix 'comic_strip_' (sha256[:16]
    aus 'comic_strip:<idx>:' + Panel-Prompt + '|berater=' + Basename der Berater-Referenz), getrennt
    von szene/tafel/kreativ/comic/comic_beratung. Da der Panel-Prompt die Sprechblasen-Zeile (u.a.
    die Ueberschrift) enthaelt, erneuert sich der Cache bei geaenderter Ueberschrift automatisch; der
    Berater-Basename trennt die Stellen. Tool-abhaengig (#137) wie die uebrigen Pfade."""
    if tool is None:
        tool = aktives_bild_tool()
    # #158: Signatur (basename@mtime) statt nur Basename der Berater-Referenz - ein ersetztes
    # Referenzbild mit gleichem Dateinamen (neue mtime) erneuert den Cache.
    base = _ref_signatur(berater_ref_pfad)
    # ZUSAETZLICH die fuer DIESES Panel tatsaechlich genutzte Referenz (Feld 2 = Finanzamt) in den
    # Schluessel aufnehmen - so erneuert auch ein ersetztes Finanzamt-Bild Panel 2. Dieselbe Quelle
    # (_comic_strip_refs) wie der Producer (ensure_comic_strip_bilder) -> identischer Schluessel.
    panel_refs = ";".join(_ref_signatur(r) for r in _comic_strip_refs(idx, berater_ref_pfad))
    schluessel = "comic_strip:%d:%s|berater=%s|refs=%s" % (idx, prompt, base, panel_refs)
    h = hashlib.sha256(schluessel.lower().encode("utf-8")).hexdigest()[:16]
    # #161: Modell-Praefix (g2_ fuer gpt-image-2, sonst leer) -> Modellwechsel liefert frische Bilder.
    # #162: Fidelity-Marker (hf_ bei input_fidelity=high) analog _modell_praefix -> frische high-Bilder.
    # Fidelity VOR Modell, damit der g2_-Praefix direkt an 'comic_strip_' grenzt (Konvention).
    return os.path.join(MOTIV_DIR,
                        _tool_praefix(tool) + _fidelity_marker() + _modell_praefix(tool) + "comic_strip_" + h + ".png")


def ensure_comic_strip_bilder(fields, berater_ref_pfad):
    """Erzeugt (oder liefert aus dem Cache) die DREI Panels des Comic-Strips (#154) und liefert die
    Liste der 3 existierenden Panel-Pfade in Reihenfolge (Feld 1..3). Pro Panel:
      - Prompt = HILO_COMIC_MASTER + Panel-Delta + Sprechblasen-Anweisung (Variante A) mit der
        Panel-Zeile (Feld 1 = Ueberschrift, Feld 2 = Default-Jammer, Feld 3 = feste Pointe).
      - refs: Feld 1+3 = [Berater-Referenz der Stelle], Feld 2 = [Finanzamt-Referenz]; nur wenn die
        Datei existiert. Erzeugung via erzeuge_comic_bild_ref(prompt, refs); sind KEINE Referenzen
        vorhanden (z.B. Stelle ohne Berater-Bible), wird auf erzeuge_bild(prompt) zurueckgefallen -
        das Panel entsteht dann OHNE Berater-Gesicht, ES GIBT ABER KEINEN CRASH.
      - Cache pro Panel (eigener Praefix, Berater-Basename + Ueberschrift im Hash) -> verschiedene
        Stellen/Ueberschriften kollidieren nicht.
    Liefert nur die tatsaechlich vorhandenen (erfolgreich erzeugten oder gecachten) Panel-Pfade;
    liefert ein Panel weder Referenz- noch generations-Bild (kein Key/Fehler), fehlt es in der Liste
    (der Render/Aufrufer degradiert dann sichtbar, ohne zu crashen)."""
    os.makedirs(MOTIV_DIR, exist_ok=True)
    tool = aktives_bild_tool()
    berater = (berater_ref_pfad or "").strip()
    # v2 (#155): Archetyp bestimmen (explizit aus fields['strip_archetyp'], sonst KI-Vorauswahl/
    # Fallback). Danach je Archetyp die passenden Panel-Deltas + Zeilen; der Panel-Prompt (Delta +
    # Zeilen) fliesst weiter in den Cache-Key -> Archetyp-/Zeilen-Wechsel erneuert den Cache.
    archetyp = _comic_strip_archetyp(fields)
    # #161: Berater-Steckbrief der Stelle (bibel_text) fuer Feld 1/3 (von personalisierung durchgereicht).
    f = fields if isinstance(fields, dict) else {}
    bibel_text = (f.get("bibel_text") or "").strip()
    pfade = []
    for idx, (delta, quelle) in enumerate(_comic_strip_panels(archetyp)):
        zeile = _comic_strip_zeile(fields, quelle, archetyp)
        # #160: pro Beitrag deterministisch gewaehlte Szenen-/Posen-Variante (Kern der Rolle bleibt).
        szene = _comic_strip_szene(fields, quelle, archetyp)
        # #161 (Reihenfolge Stil -> Figur -> Szene): der Figur-Steckbrief je Panel. Feld 2 (idx 1,
        # der Aermelschoner) -> FINANZAMT_FIGUR; Feld 1/3 (der/die Berater:in) -> bibel_text der Stelle
        # (falls vorhanden, sonst ''). Der Steckbrief fliesst in den Panel-Prompt (nur wenn nicht leer).
        figur = FINANZAMT_FIGUR if idx == 1 else bibel_text
        # #159: existieren fuer dieses Panel Referenzen (Feld 1/3 Berater, Feld 2 Finanzamt), wird der
        # Referenz-Anker in den Prompt aufgenommen. refs VOR der Pfad-Berechnung ermitteln, damit
        # Producer und _comic_strip_pfad DENSELBEN Prompt/Schluessel nutzen.
        refs = _comic_strip_refs(idx, berater)
        prompt = _comic_strip_prompt(fields, delta, zeile, hat_ref=bool(refs), szene=szene, figur=figur)
        path = _comic_strip_pfad(idx, prompt, berater, tool=tool)
        if os.path.exists(path):
            pfade.append(path)
            continue
        daten = erzeuge_comic_bild_ref(prompt, refs) if refs else None
        if daten is None:
            # Keine Referenz vorhanden ODER Referenz-Call ohne Key/Fehler -> generations-Weg
            # (Panel ohne Berater-Gesicht, aber kein Crash).
            daten = erzeuge_bild(prompt, tool=tool)
        if daten is None:
            log.warning("Comic-Strip Panel %d konnte nicht erzeugt werden (kein Key/Fehler).", idx + 1)
            continue
        try:
            with open(path, "wb") as f:
                f.write(daten)
            log.info("Comic-Strip Panel %d erzeugt (%s), Berater=%s", idx + 1, tool,
                     os.path.basename(berater) or "-")
            pfade.append(path)
        except Exception as ex:
            log.warning("Comic-Strip Panel %d speichern fehlgeschlagen: %s", idx + 1, ex)
    return pfade

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

def ensure_photo(motiv, typ=None, fields=None):
    """Erzeugt (oder liefert aus dem Cache) das Szene-Foto zu 'motiv'. Der Parameter 'typ' wird
    aus Rueckwaerts-Kompatibilitaet noch akzeptiert, aber nicht mehr ausgewertet (einheitliche
    Szene-Logik). 'icon:'-Motive werden weiterhin gezeichnet (kein OpenAI noetig).
    NEU: 'fields' (optional) wird an _prompt() durchgereicht fuer Masterprompt mit vollem Text."""
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
    # Mit fields: Masterprompt, ohne: Fallback auf einfachen Prompt
    prompt_input = fields if fields else motiv
    daten = erzeuge_bild(_prompt(prompt_input), tool=tool)
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
