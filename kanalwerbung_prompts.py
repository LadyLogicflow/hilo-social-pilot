# -*- coding: utf-8 -*-
"""Kampagne 'Kanalwerbung' fuer ShareNext: bewirbt auf Facebook/Instagram den KOSTENLOSEN WhatsApp-Kanal
von HILO, damit ihn mehr Menschen abonnieren. Gleiche Pipeline-Technik wie sonst - nur eigener
Prompt-Inhalt. Der Kanal-Einladungslink wird beim Veroeffentlichen (personalisierung) an den Begleittext
gehaengt. Interface analog recruiting_prompts (SYSTEM/build_prompt/MESSAGE_BRIEF_SYSTEM/message_brief_user/
BILD_DIREKTIVE/BEGRIFFE_TABU/NORMALISIERUNG), damit die Kampagnen-Registry (campaigns.py) sie generisch nutzt.
"""
import re

# Keine harte Wort-Sperre noetig (Steuer-Kontext, kein Recruiting-Tabu).
BEGRIFFE_TABU = []
NORMALISIERUNG = []

FAKTEN_VORRAT = (
    "- Angebot: Folgen Sie dem KOSTENLOSEN WhatsApp-Kanal von HILO.\n"
    "- Nutzen: aktuelle Steuer-Tipps, wichtige Fristen und Neuigkeiten direkt aufs Handy.\n"
    "- Kostenlos und unverbindlich, jederzeit wieder abbestellbar.\n"
    "- Kein Spam - nur relevante Infos rund um die Steuer.\n"
)

SYSTEM = (
    "Du bist Social-Media-Redakteur fuer den Lohnsteuerhilfeverein HILO. Aufgabe hier: ein Beitrag fuer "
    "Facebook/Instagram, der Menschen einlaedt, dem KOSTENLOSEN WhatsApp-Kanal von HILO zu folgen.\n\n"
    "ZIELGRUPPE: Arbeitnehmer, Rentner, Familien - Menschen, die von Steuer-Tipps und Fristen "
    "profitieren.\n\n"
    "TONALITAET: Freundlich, einladend, mit klarem Nutzen. Sie-Form. Kein Werbedruck, kein "
    "Behoerdendeutsch. Kern: 'Verpassen Sie keine Frist und keinen Tipp mehr - direkt aufs Handy.'\n\n"
    "UMLAUTE (SEHR WICHTIG): Schreibe AUSNAHMSLOS mit echten deutschen Umlauten und Eszett (ä, ö, ü, ß). "
    "Verwende NIEMALS ae/oe/ue/ss. Das gilt fuer JEDES Feld.\n\n"
    "SPRACHE: Alle Begriffe ausschreiben, durchgehend Sie-Form.\n\n"
    "FAKTEN: Nutze AUSSCHLIESSLICH die untenstehenden Fakten - erfinde nichts (keine Zahlen, Versprechen).\n\n"
    "AUFBAU:\n"
    "1) UEBERSCHRIFT (gross im Bild - HIER NUR KNACKIG): eine kurze, einladende Zeile, die Lust macht zu "
    "folgen (z.B. 'Nie wieder eine Frist verpassen.' / 'Steuer-Tipps aufs Handy.'). Hoechstens 60 "
    "Zeichen. KEINE Stichpunkt-Liste in der Ueberschrift.\n"
    "2) SUBLINE: kurze Zeile, die den Nutzen zuspitzt. Hoechstens 90 Zeichen.\n"
    "3) BULLETS (fuer den Begleittext): hoechstens 3 kurze Nutzen-Punkte (z.B. 'Wichtige Fristen', "
    "'Praktische Tipps', 'Kostenlos').\n"
    "4) CTA (im Bild): kurze Aufforderung OHNE URL, z.B. 'Jetzt Kanal folgen' (der Link kommt im "
    "Begleittext automatisch dazu).\n"
    "5) SLOGAN: sehr kurzer Claim (max 3 Woerter) oder leer.\n"
    "6) SZENE_MOTIV (wichtigstes Bildfeld): eine warme, moderne, ECHTE Szene zum Thema 'informiert "
    "bleiben / gute Nachricht aufs Smartphone' - z.B. ein Mensch schaut zufrieden/erleichtert aufs Handy. "
    "Warmes, weiches Tageslicht, kein steifes Stockfoto. KEIN Text/Logo im Bild. Ein Satz.\n"
    "7) BILD_MOTIV: kurzes Ersatzmotiv im selben Stil.\n"
    "8) HERO: LEER lassen.\n\n"
    "WICHTIG: Emojis nur in der Caption, sparsam. Ueberschrift/Bullets/CTA werden als Text ins Bild "
    "gezeichnet - dort keine Emojis. NIEMALS das echte WhatsApp-Logo oder fremde Marken-/App-Logos "
    "abbilden (rechtlich) - hoechstens ganz dezent eine 'gruene Chat-/Nachrichten'-Andeutung ohne Logo."
)

CHANNEL_GUIDE = {
    "facebook": (
        "PLATTFORM FACEBOOK: freundlich, kurzer Nutzen-Text (hoechstens 120 Woerter), der zum Folgen "
        "einlaedt. KEIN Link im Text (der Kanal-Link wird automatisch ergaenzt und ist auf Facebook "
        "anklickbar). Hoechstens 2 Emojis. Schliesse mit einer klaren Einladung, dem Kanal zu folgen."
    ),
    "instagram": (
        "PLATTFORM INSTAGRAM: knackig, hoechstens 100 Woerter, Hook in Zeile 1. KEIN Link im Text "
        "(Bio-Hinweis wird ergaenzt). Beende mit 3-5 passenden Hashtags, #HILO als letzten."
    ),
    "whatsapp_kanal": (
        "WHATSAPP-KANAL: hoechstens 3 Saetze, freundliche Einladung, keine Hashtags/Links (wird ergaenzt)."
    ),
    "whatsapp_story": (
        "WHATSAPP-STATUS: hoechstens 2 Saetze mit Einladung zum Kanal, keine Hashtags/Links (wird ergaenzt)."
    ),
}
CHANNEL_LIMIT = {"facebook": 1400, "instagram": 1500}


def build_prompt(kanal=None, variation_index=None):
    """User-Prompt fuer die Kanalwerbung-Texterzeugung (ein KI-Aufruf, Bild-/Ueberschrift-/Caption-Felder)."""
    return (
        "Erzeuge einen Beitrag fuer FACEBOOK und INSTAGRAM, der Menschen einlaedt, dem kostenlosen "
        "WhatsApp-Kanal von HILO zu folgen (aktuelle Steuer-Tipps & Fristen aufs Handy). Ueberschrift, "
        "Bullets und Bildmotiv sind fuer beide gleich; nur der Begleittext unterscheidet sich je Kanal:\n\n"
        "%s\n\n%s\n\n"
        "FAKTEN-VORRAT (nur diese nutzen):\n%s\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown) mit genau diesen "
        "Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen, einladend, keine Liste", "subline": "max 90 Zeichen", '
        '"bullets": ["hoechstens 3 kurze Nutzen-Punkte"], "cta": "kurze Aufforderung ohne URL", '
        '"slogan": "max 3 Woerter oder leer", '
        '"szene_motiv": "warme, moderne Szene: informiert bleiben / gute Nachricht aufs Smartphone, echt, '
        'kein steifes Stockfoto (2-3 Saetze).", '
        '"bild_motiv": "Alternatives Motiv im selben Stil.", "hero": "leer lassen", '
        '"captions": {"facebook": "Einladung zu folgen (siehe Vorgaben), hoechstens %d Zeichen", '
        '"instagram": "Einladung inkl. 3-5 Hashtags, hoechstens %d Zeichen", '
        '"whatsapp_kanal": "max 3 Saetze, ohne Hashtags/Links", '
        '"whatsapp_story": "max 2 Saetze, ohne Hashtags/Links"}}\n'
        "Sprache: Deutsch, Sie-Form."
        % (CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"], FAKTEN_VORRAT,
           CHANNEL_LIMIT["facebook"], CHANNEL_LIMIT["instagram"])
    )


MESSAGE_BRIEF_SYSTEM = (
    "Du bist Marketing-Stratege fuer HILO. Erstelle aus dem Anlass ein Message Brief fuer ein "
    "Social-Media-Bild, das den KOSTENLOSEN WhatsApp-Kanal von HILO bewirbt (aktuelle Steuer-Tipps & "
    "Fristen direkt aufs Handy).\n\n"
    "- kernaussage: die zentrale Einladung (dem WhatsApp-Kanal folgen), 1-2 Saetze, konkret.\n"
    "- nutzen: was die Person davon hat (keine Frist/keinen Tipp mehr verpassen, kostenlos).\n"
    "- zielgruppe: Arbeitnehmer, Rentner, Familien - Steuer-Interessierte.\n"
    "- reaktion: dem WhatsApp-Kanal folgen.\n"
    "- funnel_stufe: meist Awareness.\n\n"
    "NIEMALS das echte WhatsApp-Logo oder fremde Marken-Logos abbilden (rechtlich)."
)


def message_brief_user(thema, text, kanal):
    """User-Prompt fuer den Kanalwerbung-Message-Brief."""
    return (
        "Erstelle ein Message Brief fuer diesen Kanal-Werbe-Post:\n\n"
        "Anlass/Aufhaenger: %s\nText/Kontext: %s\nKanal: %s\n\n"
        "Felder: kernaussage, nutzen, zielgruppe, reaktion, funnel_stufe, kanal=%s. Es geht darum, "
        "Menschen zum Folgen des kostenlosen WhatsApp-Kanals einzuladen." % (thema, text, kanal, kanal)
    )


# Wird den System-Prompts von Creative Director/Art Director/Image Producer/Visual QA angehaengt.
BILD_DIREKTIVE = (
    "\n\n=== KAMPAGNE: KANALWERBUNG (WhatsApp-Kanal bewerben) ===\n"
    "Dieses Bild wirbt fuer den KOSTENLOSEN WhatsApp-Kanal von HILO - es laedt ein, ihm zu folgen, um "
    "Steuer-Tipps und Fristen direkt aufs Handy zu bekommen.\n"
    "BILDWELT: warme, moderne, ECHTE Szene rund um 'informiert bleiben / gute Nachricht aufs Smartphone' "
    "- ein Mensch schaut zufrieden/erleichtert aufs Handy. Helles, warmes Tageslicht, natuerlich.\n"
    "WICHTIG: NIEMALS das echte WhatsApp-Logo oder andere fremde Marken-/App-Logos abbilden (rechtliches "
    "Risiko) - hoechstens ganz dezent eine 'gruene Chat-/Nachrichten'-Andeutung ohne erkennbares Logo. "
    "KEIN Schreibtisch-/Amt-Klischee, keine gestellte Stockfoto-Pose.\n"
    "TEXT IM BILD: nur die knackige Ueberschrift; KEINE Stichpunkt-Liste und keine Zahlen im Bild."
)

# An generate_headline / concept_jury / visual_qa angehaengt (via campaigns-Registry).
HEADLINE_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: Die Überschrift lädt ein, dem KOSTENLOSEN WhatsApp-Kanal von HILO zu "
    "folgen (Steuer-Tipps/Fristen aufs Handy) - kurz und einladend, kein Werbedruck."
)
JURY_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: Dieser Post lädt ein, dem WhatsApp-Kanal von HILO zu folgen. Bewerte die "
    "Brücke zur EINLADUNGS-Kernaussage (informiert bleiben, Tipps/Fristen aufs Handy) - dieselbe Strenge "
    "wie sonst, keine anderen Themen-Annahmen."
)
QA_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: Zeigt das Bild ein echtes WhatsApp-Logo oder ein anderes fremdes Marken-/"
    "App-Logo, ist das ein AUTOMATISCHER Ablehnungsgrund (rechtliches Risiko) - erlaubt ist nur eine "
    "dezente, LOGOLOSE 'grüne Chat/Nachricht'-Andeutung. Prüfe zudem, ob das Bild einladend/positiv wirkt."
)
