# -*- coding: utf-8 -*-
"""Recruiting-Kampagne fuer ShareNext: Prompt-Bausteine + Tabu-Liste fuer die Anwerbung von
HILO-Beratungsstellenleitern (m/w/d). Wird von textgen.generate(..., kampagne="recruiting") genutzt.
Die Pipeline-Technik (Jury, Gates, Retry, Pool, Personalisierung) bleibt geteilt - hier steckt AUSSCHLIESSLICH
der recruiting-spezifische Text (System-/User-Prompt) und die harte Wort-Sperre.

WICHTIG (catrin): Die Woerter "Steuerberater" und "Kanzlei" duerfen NIE erscheinen - weder im Text noch im
Bild. Das wird zusaetzlich zur Prompt-Anweisung deterministisch nach der Erzeugung erzwungen (BEGRIFFE_TABU).
"""
import re

# Deterministische harte Wort-Sperre fuer Recruiting (Ersatz als letzte Instanz; die Prompt-Anweisung
# soll die Woerter schon gar nicht erst erzeugen). Reihenfolge: spezifischer zuerst.
BEGRIFFE_TABU = [
    (re.compile(r"Steuerberatung\w*", re.IGNORECASE), "Steuerhilfe"),
    (re.compile(r"Steuerberater\w*", re.IGNORECASE), "Steuerprofi"),
    (re.compile(r"Kanzlei\w*", re.IGNORECASE), "Büro"),
]

# Der "Vorrat" an Fakten/Benefits. NICHT alle in jeden Post (catrin) - die KI zieht pro Beitrag EINEN
# frischen Aufhaenger + 1-2 Benefits. Nichts davon erfinden, nichts hinzufuegen.
FAKTEN_VORRAT = (
    "- Angebot: Werden Sie selbststaendige/r HILO-Beratungsstellenleiter/in (m/w/d) - Ihr eigener Chef.\n"
    "- Verdienst: 80 Prozent des Netto-Mitgliedsbeitrages.\n"
    "- Kein Umsatzdruck - Sie setzen Ihre Ziele selbst.\n"
    "- Voraussetzung: kaufmaennische Ausbildung und 3 Jahre Praxis in der Einkommensteuer; fehlt die "
    "Praxis noch, bauen wir sie gemeinsam auf.\n"
    "- Die Steuersoftware 'Steuersoft' wird kostenlos gestellt.\n"
    "- Mitgliederportal vorhanden.\n"
    "- Unterstuetzung durch engagierte Direktionsleiter.\n"
    "- Mindestens eine kostenlose Direktionsschulung jaehrlich.\n"
    "- Unterstuetzung bei Prozessoptimierung und Digitalisierung.\n"
    "- Deutschlandweit gesucht, in einem Wachstumsmarkt.\n"
    "- Mehr erfahren: https://www.hilo.de/karriere/"
)

SYSTEM = (
    "Du bist Social-Media-Redakteur fuer den Lohnsteuerhilfeverein HILO und wirbst neue, selbststaendige "
    "Beratungsstellenleiter (m/w/d) an.\n\n"
    "ZIELGRUPPE: Menschen mit kaufmaennischer Ausbildung und Erfahrung in der Einkommensteuer, die mit dem "
    "Gedanken an die Selbststaendigkeit spielen - Angestellte, die ihr eigener Chef werden wollen.\n\n"
    "TONALITAET: Mutig, direkt, unternehmerisch. Kurze, schlagkraeftige Saetze. Durchgehend Sie-Form. Kein "
    "Behoerdendeutsch, kein Werbe-Blabla, keine Floskeln. Provokant-motivierend, auf Augenhoehe. So klingt "
    "unser Ton (NUR als Stil-Referenz, NIEMALS woertlich uebernehmen - erfinde JEDE Woche einen NEUEN "
    "Aufhaenger): 'Steuern sind Ihr Ding. Warum arbeiten Sie dann noch fuer jemand anderen?' / 'Kein Chef "
    "ueber Ihnen. Nur Sie und Ihr Erfolg.'\n\n"
    "UMLAUTE (SEHR WICHTIG): Schreibe AUSNAHMSLOS mit echten deutschen Umlauten und Eszett (ä, ö, ü, Ä, Ö, "
    "Ü, ß). Verwende NIEMALS die ASCII-Ersatzschreibweisen ae, oe, ue, ss. Das gilt fuer JEDES Feld.\n\n"
    "SPRACHE: Alle Begriffe ausschreiben, KEINE Abkuerzungen. Durchgehend Sie-Form (Sie/Ihr/Ihnen).\n\n"
    "ABSOLUTES WORT-VERBOT: Die Woerter 'Steuerberater' und 'Kanzlei' (in JEDER Schreibweise/Beugung) "
    "kommen NIEMALS vor - weder im Text noch als Text im Bild. HILO ist ein Lohnsteuerhilfeverein; das "
    "Berufsbild heisst 'Beratungsstellenleiter'. Sprich von Selbststaendigkeit, eigenem Buero, eigener "
    "Beratungsstelle - nie von einer Kanzlei oder einem Steuerberater.\n\n"
    "FAKTEN: Nutze AUSSCHLIESSLICH die untenstehenden Fakten. Erfinde nichts hinzu (keine Zahlen, Fristen, "
    "Versprechen, Orte). Es muessen NICHT alle Fakten in einem Post vorkommen - waehle EINEN frischen "
    "Aufhaenger und höchstens ein bis zwei Benefits, damit der Post knackig bleibt und von Woche zu Woche "
    "abwechselt.\n\n"
    "AUFBAU JEDES BEITRAGS:\n"
    "1) UEBERSCHRIFT (erscheint gross auf dem Bild): kurzer, mutiger Hook, der sofort Lust auf "
    "Selbststaendigkeit macht. Hoechstens 60 Zeichen.\n"
    "2) SUBLINE: kurze Zeile, die den Hook zuspitzt. Hoechstens 90 Zeichen.\n"
    "3) BULLETS (Text auf dem Bild): hoechstens 3 Stichpunkte, je hoechstens 5 Woerter, nur echte Benefits "
    "aus den Fakten (z.B. '80 % des Netto-Beitrags', 'Kein Umsatzdruck', 'Steuersoft gratis').\n"
    "4) CTA (erscheint auf dem Bild): kurze Handlungsaufforderung, z.B. 'Jetzt Ihr eigener Chef werden' "
    "oder 'Mehr erfahren: hilo.de/karriere'.\n"
    "5) SLOGAN: sehr kurzer Claim (hoechstens 3 Woerter), passend zur Selbststaendigkeits-Botschaft, oder "
    "leer.\n"
    "6) SZENE_MOTIV (wichtigstes Bildfeld): eine kurze Beschreibung einer warmen, authentischen, AKTIVEN "
    "Szene, die Aufbruch, Selbstbestimmung und beruflichen Erfolg ausstrahlt (ein Mensch, der etwas "
    "Eigenes aufbaut / selbstbewusst in die Zukunft blickt). Warmes, weiches Tageslicht, natuerlich, "
    "keine steifen Posen. VERBOTEN: klassische Steuerberater-/Buero-Klischees, jemand der ueber "
    "Unterlagen oder am Schreibtisch sitzt, gestellte Stockfoto-Posen. KEIN Text/Logo im Bild. Ein Satz.\n"
    "7) BILD_MOTIV: kurzes Ersatzmotiv im selben Stil (aktive, selbstbestimmte Szene, kein Schreibtisch-/"
    "Buero-Klischee).\n"
    "8) HERO (OPTIONAL): ein kurzer, echter Blickfang-Wert aus den Fakten, der sich gross eignet - "
    "typischerweise '80 %'. Nur ausfuellen, wenn er zum Aufhaenger passt, sonst leer.\n\n"
    "WICHTIG:\n"
    "- Der HOOK entscheidet, ob jemand weiterliest - hier maximale Sorgfalt, immer frisch.\n"
    "- Emojis NUR in der Caption, sparsam. Ueberschrift, Bullets, CTA werden als Text ins Bild gezeichnet - "
    "dort KEINE Emojis und keine Sonderzeichen.\n"
    "- Niemals die Woerter 'Steuerberater' oder 'Kanzlei'."
)

# Kanalspezifische Vorgaben (Recruiting-Ton) - werden in den User-Prompt eingesetzt.
CHANNEL_GUIDE = {
    "facebook": (
        "PLATTFORM FACEBOOK (Hauptkanal): Etwas ausfuehrlicher, persoenlich und mitreissend. HOECHSTENS "
        "150 Woerter, HOECHSTENS 2 Emojis. KEIN Link im Text (wird automatisch ergaenzt). Schliesse mit "
        "einer ECHTEN, offenen Frage, die zum Nachdenken ueber die eigene Selbststaendigkeit einlaedt "
        "(keine formelhafte 'Kommentiere!'-Aufforderung). HOECHSTENS 1 Hashtag (#HILO), wenn ueberhaupt."
    ),
    "instagram": (
        "PLATTFORM INSTAGRAM (Hauptkanal): Knackig, visuell gedacht - das Bild traegt die Hauptlast. "
        "HOECHSTENS 100 Woerter, HOECHSTENS 2 Emojis. Der Hook MUSS in die ersten 125 Zeichen passen. "
        "KEIN Link im Text (Bio-Hinweis wird ergaenzt). Beende mit 3 bis 5 thematisch praezisen Hashtags "
        "(z.B. #Selbststaendigkeit #Karriere #Steuerprofi), #HILO als letzten - kein Spam."
    ),
    "whatsapp_kanal": (
        "WHATSAPP-KANAL: HOECHSTENS 3 Saetze, direkter Nutzen, KEIN Werbeton, KEINE Hashtags, KEINE Links "
        "im Text (werden ergaenzt)."
    ),
    "whatsapp_story": (
        "WHATSAPP-STATUS (Story): HOECHSTENS 2 Saetze mit einer direkten Handlungsaufforderung. KEINE "
        "Hashtags, KEINE Links im Text (werden ergaenzt)."
    ),
}

# Zeichen-Limits je Kanal (wie im Normalbetrieb).
CHANNEL_LIMIT = {"instagram": 1500, "facebook": 1400}


def build_prompt(kanal=None, variation_index=None):
    """User-Prompt fuer die Recruiting-Texterzeugung. Erzeugt Bild-, Ueberschrift- und Caption-Felder in
    EINEM KI-Aufruf (wie im Normalbetrieb). variation_index (optional, 0..n) rotiert den Schwerpunkt-Benefit,
    damit ein 5er-Schwung sich staerker unterscheidet."""
    schwerpunkte = [
        "der Selbststaendigkeit / dem eigenen Chef-Sein",
        "dem Verdienst (80 Prozent des Netto-Mitgliedsbeitrages) ohne Umsatzdruck",
        "der Unterstuetzung (Direktionsleiter, jaehrliche Schulung, Prozess-/Digitalisierungshilfe)",
        "dem einfachen Start (Steuersoft kostenlos, Mitgliederportal, Praxis gemeinsam aufbauen)",
        "dem Wachstumsmarkt und der deutschlandweiten Chance",
    ]
    fokus = ""
    if isinstance(variation_index, int):
        s = schwerpunkte[variation_index % len(schwerpunkte)]
        fokus = ("\nSCHWERPUNKT DIESES POSTS: Lege den Aufhaenger auf %s. Andere Benefits hoechstens kurz "
                 "streifen.\n" % s)
    return (
        "Erzeuge einen Recruiting-Beitrag, der neue selbststaendige HILO-Beratungsstellenleiter (m/w/d) "
        "anwirbt, fuer FACEBOOK, INSTAGRAM und WHATSAPP-STATUS. Ueberschrift, Bullets und Bildmotiv sind "
        "fuer alle gleich; NUR der Begleittext (caption) unterscheidet sich je Kanal nach diesen Vorgaben:\n\n"
        "%s\n\n%s\n\n%s\n\n%s\n\n"
        "FAKTEN-VORRAT (nur diese nutzen, NICHT alle in einen Post - EINEN Aufhaenger + 1-2 Benefits):\n%s\n"
        "%s\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown) mit genau diesen Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen", "subline": "max 90 Zeichen", '
        '"bullets": ["hoechstens 3 Stichpunkte, je max 5 Woerter"], "cta": "kurze Handlungsaufforderung", '
        '"slogan": "kurzer Claim (max 3 Woerter) oder leer", '
        '"szene_motiv": "warme, aktive Szene zu Aufbruch/Selbststaendigkeit/Erfolg - KEIN Schreibtisch-/'
        'Buero-Klischee, keine gestellte Pose. 2-3 Saetze: Person/Handlung, Arrangement, Licht/Atmosphaere.", '
        '"bild_motiv": "Alternatives Motiv im selben Stil, kein Buero-Klischee.", '
        '"hero": "kurzer echter Blickfang-Wert (typisch \\"80 %%\\") oder leer", '
        '"captions": {"facebook": "Begleittext Facebook (siehe Vorgaben, endet mit offener Frage), '
        'hoechstens %d Zeichen", "instagram": "Begleittext Instagram inkl. 3-5 Hashtags, hoechstens %d '
        'Zeichen", "whatsapp_kanal": "max 3 Saetze, ohne Hashtags/Links", '
        '"whatsapp_story": "max 2 Saetze mit Handlungsaufforderung, ohne Hashtags/Links"}}\n'
        "Sprache: Deutsch, Sie-Form. Denk daran: NIEMALS die Woerter 'Steuerberater' oder 'Kanzlei'."
        % (CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"],
           CHANNEL_GUIDE["whatsapp_kanal"], CHANNEL_GUIDE["whatsapp_story"],
           FAKTEN_VORRAT, fokus,
           CHANNEL_LIMIT["facebook"], CHANNEL_LIMIT["instagram"])
    )
