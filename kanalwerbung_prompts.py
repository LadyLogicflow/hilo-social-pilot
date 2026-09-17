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
    "folgen. Variiere Einstieg und Form von Post zu Post; beginne NICHT jedes Mal mit den Fristen oder "
    "'Nie wieder ...'. Die Beispiele sind NUR Stilreferenz, NIEMALS woertlich uebernehmen (z.B. "
    "'Steuer-Tipps aufs Handy.' / 'Bleiben Sie informiert.' / 'Nichts Wichtiges mehr verpassen.' / "
    "'Ihr Draht zur Steuer.'). Hoechstens 60 Zeichen. KEINE Stichpunkt-Liste in der Ueberschrift.\n"
    "2) SUBLINE: kurze Zeile, die den Nutzen zuspitzt. Hoechstens 90 Zeichen.\n"
    "3) BULLETS (fuer den Begleittext): hoechstens 3 kurze Nutzen-Punkte (z.B. 'Wichtige Fristen', "
    "'Praktische Tipps', 'Kostenlos').\n"
    "4) CTA (im Bild): kurze Aufforderung OHNE URL, z.B. 'Jetzt Kanal folgen' (der Link kommt im "
    "Begleittext automatisch dazu).\n"
    "5) SLOGAN: sehr kurzer Claim (max 3 Woerter) oder leer.\n"
    "6) SZENE_MOTIV (wichtigstes Bildfeld): PFLICHT ist ein echter Mensch der Zielgruppe (Arbeitnehmer, "
    "Rentnerin, Familie) bei einer KONKRETEN, KLEINEN ALLTAGS-HANDLUNG, die den Nutzen des Kanals SELBST "
    "erzaehlt - also 'informiert bleiben / Frist & Tipp im Blick'. Genau DAS ist der visuelle Anker; die "
    "Handlung traegt die Botschaft, nicht die Ueberschrift allein. Gute Beispiele (variieren, nicht "
    "woertlich): einen Termin/eine Frist im Kalender oder Handy-Kalender markieren; einen Reminder-Zettel "
    "an Pinnwand/Kuehlschrank heften; kurz konzentriert einen Tipp auf dem Handy lesen (als HANDLUNG, "
    "beilaeufig, ohne sichtbares Display/UI); etwas in einen Planer/Notizblock eintragen; einen "
    "Kalendertag mit Stift einkreisen. Warme, moderne Alltagsumgebung, weiches Tageslicht, echt.\n"
    "   STRENG VERBOTEN: (a) ein 'generisch erleichterter/gluecklicher Mensch' als Botschaftstraeger "
    "(seliges Laecheln, Arme hoch, Familien-Wohlfuehl-Stock ohne Bezug) - das sagt NICHTS ueber Steuer; "
    "(b) ein abstraktes Objekt als Held (Ball, Papierflieger/Origami, schwebende Symbole/Pins/Netze/Icons/"
    "Sprechblasen, ein blosser Gegenstand in HILO-Gruen); (c) stumpfes Aufs-Handy-Starren oder dekoratives "
    "Posieren. Das Handy/UI/App-Symbolik NIE als Hauptmotiv. Ein Satz mit der konkreten Handlung.\n"
    "7) BILD_MOTIV: kurzes Ersatzmotiv im selben Prinzip - echter Mensch bei einer ANDEREN konkreten "
    "Alltags-Handlung, die 'Frist/Tipp im Blick' zeigt. KEIN erleichtertes Wohlfuehl-Gesicht, KEIN "
    "abstraktes Objekt, KEIN Geraet als Held.\n"
    "8) HERO: LEER lassen.\n\n"
    "WICHTIG: Emojis nur in der Caption, sparsam. Ueberschrift/Bullets/CTA werden als Text ins Bild "
    "gezeichnet - dort keine Emojis. NIEMALS das echte WhatsApp-Logo, fremde Marken-/App-Logos ODER "
    "WhatsApp-aehnliche gruene Sprechblasen/Chat-Symbole abbilden (rechtlich + verwaesert die Marke)."
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
    """User-Prompt fuer die Kanalwerbung-Texterzeugung (ein KI-Aufruf, Bild-/Ueberschrift-/Caption-Felder).
    variation_index (0..n) rotiert den BLICKWINKEL/Aufhaenger, damit nicht jeder Beitrag mit derselben Zeile
    ('Nie wieder eine Frist verpassen') beginnt."""
    blickwinkel = [
        "aktuelle Steuer-Tipps, die man sonst leicht uebersieht",
        "Neuigkeiten und Aenderungen rund um die Steuer",
        "dass alles kostenlos, unverbindlich und jederzeit abbestellbar ist",
        "die Bequemlichkeit - alles Wichtige direkt aufs Handy, ohne selbst suchen zu muessen",
        "wichtige Fristen rechtzeitig im Blick behalten",
    ]
    if isinstance(variation_index, int):
        w = blickwinkel[variation_index % len(blickwinkel)]
        fokus = ("SCHWERPUNKT DIESES POSTS: Ueberschrift und Aufhaenger drehen sich um %s. Beginne NICHT "
                 "mit 'Nie wieder eine Frist verpassen' und nicht mit den Fristen - waehle einen frischen "
                 "Einstieg passend zu diesem Schwerpunkt." % w)
    else:
        fokus = "Variiere Ueberschrift und Einstieg von Post zu Post - NICHT immer mit den Fristen beginnen."
    return (
        "Erzeuge einen Beitrag fuer FACEBOOK und INSTAGRAM, der Menschen einlaedt, dem kostenlosen "
        "WhatsApp-Kanal von HILO zu folgen (aktuelle Steuer-Tipps & Fristen aufs Handy). Ueberschrift, "
        "Bullets und Bildmotiv sind fuer beide gleich; nur der Begleittext unterscheidet sich je Kanal:\n\n"
        "%s\n\n%s\n\n%s\n\n"
        "FAKTEN-VORRAT (nur diese nutzen):\n%s\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown) mit genau diesen "
        "Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen, einladend, keine Liste", "subline": "max 90 Zeichen", '
        '"bullets": ["hoechstens 3 kurze Nutzen-Punkte"], "cta": "kurze Aufforderung ohne URL", '
        '"slogan": "max 3 Woerter oder leer", '
        '"szene_motiv": "PFLICHT: echter Mensch der Zielgruppe bei einer KONKRETEN kleinen Alltags-Handlung, '
        'die den Nutzen SELBST erzaehlt (Frist/Tipp im Blick): z.B. Termin im Kalender markieren, '
        'Reminder-Zettel anheften, kurz einen Tipp aufs Handy lesen (als Handlung, beilaeufig, kein UI), '
        'etwas in einen Planer eintragen. Warm, echt. VERBOTEN: generisch erleichtertes/gluecklickes '
        'Wohlfuehl-Gesicht ohne Steuerbezug, abstrakte Objekte (Ball/Origami/Pin/Symbol), stumpfes '
        'Handy-Starren, Geraet/UI als Held (2-3 Saetze).", '
        '"bild_motiv": "Alternative Alltags-Handlung im selben Prinzip (andere konkrete Handlung); kein '
        'erleichtertes Wohlfuehl-Gesicht, kein abstraktes Objekt, kein Geraet als Held.", '
        '"hero": "leer lassen", '
        '"captions": {"facebook": "Einladung zu folgen (siehe Vorgaben), hoechstens %d Zeichen", '
        '"instagram": "Einladung inkl. 3-5 Hashtags, hoechstens %d Zeichen", '
        '"whatsapp_kanal": "max 3 Saetze, ohne Hashtags/Links", '
        '"whatsapp_story": "max 2 Saetze, ohne Hashtags/Links"}}\n'
        "Sprache: Deutsch, Sie-Form."
        % (CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"], fokus, FAKTEN_VORRAT,
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
    "BILDWELT (PFLICHT): ein echter Mensch der Zielgruppe (Arbeitnehmer, Rentnerin, Familie) bei einer "
    "KONKRETEN, KLEINEN ALLTAGS-HANDLUNG, die den Nutzen des Kanals SELBST erzaehlt - 'Frist/Tipp im "
    "Blick, direkt aufs Handy'. Die HANDLUNG traegt die Botschaft, nicht die Ueberschrift. Gute "
    "Beispiele (variieren, nicht 1:1): einen Termin/eine Frist im Kalender (Wand-, Tisch- oder "
    "Handy-Kalender) markieren; einen Reminder-Zettel an Pinnwand/Kuehlschrank heften; kurz konzentriert "
    "einen Tipp auf dem Handy lesen (als Handlung, beilaeufig, KEIN sichtbares Display/UI); etwas in "
    "einen Planer/Notizblock eintragen; einen Kalendertag einkreisen. Warme, moderne Alltagsumgebung, "
    "helles weiches Tageslicht, natuerlich.\n"
    "STRENG VERBOTEN (wurde wiederholt abgelehnt): (a) ein 'generisch erleichterter/gluecklicher Mensch' "
    "als Botschaftstraeger (seliges Laecheln, Arme hoch, Familien-Wohlfuehl-Stock ohne Steuerbezug) - das "
    "sagt NICHTS ueber Steuer/Kanal; (b) ein abstraktes Objekt als Held (Ball, Papierflieger/Origami, "
    "schwebende Symbole/Pins/Icons/Netze/Sprechblasen, ein blosser Gegenstand in HILO-Gruen); (c) stumpfes "
    "Aufs-Handy-Starren oder dekoratives Posieren. Handy/UI/App-Symbolik NIE als Hero-Motiv. Wenn keine "
    "konkrete, themenbezogene Handlung im Bild ist, ist das Bild FALSCH.\n"
    "WICHTIG: NIEMALS das echte WhatsApp-Logo, fremde Marken-/App-Logos ODER WhatsApp-aehnliche gruene "
    "Sprechblasen/Chat-Symbole abbilden (rechtlich + verwaesert die Marke). KEIN Schreibtisch-/Amt-"
    "Klischee, keine gestellte Stockfoto-Pose.\n"
    "TEXT IM BILD: nur die knackige Ueberschrift; KEINE Stichpunkt-Liste und keine Zahlen im Bild."
)

# An generate_headline / concept_jury / visual_qa angehaengt (via campaigns-Registry).
HEADLINE_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: Die Überschrift lädt ein, dem KOSTENLOSEN WhatsApp-Kanal von HILO zu "
    "folgen (Steuer-Tipps/Fristen aufs Handy) - kurz und einladend, kein Werbedruck."
)
JURY_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: Dieser Post lädt ein, dem WhatsApp-Kanal von HILO zu folgen. Bewerte streng "
    "die BRÜCKE zwischen BILD und Botschaft: Trägt eine konkrete Alltags-HANDLUNG im Bild den Nutzen "
    "(Frist/Tipp im Blick, informiert bleiben)? Ein bloß emotional schönes Wohlfühl-/Familienbild OHNE "
    "erkennbaren Steuer-/Informiert-Bezug ist SCHWACH (Botschaftsklarheit niedrig) - auch wenn es "
    "handwerklich gut ist. Belohne Motive, bei denen man ohne Überschrift erahnt, worum es geht."
)
QA_HINT = (
    "\n\nKAMPAGNE KANALWERBUNG: AUTOMATISCHE Ablehnungsgründe: (1) ein echtes WhatsApp-Logo, ein anderes "
    "fremdes Marken-/App-Logo ODER eine WhatsApp-ähnliche grüne Sprechblase/Chat-Symbolik (rechtlich). "
    "(2) Eine abstrakte Objekt-Metapher als Held (Ball/Papierflieger/Origami, schwebender Pin/Symbol, "
    "Netz, Icon, Sprechblase, bloßer Gegenstand in HILO-Grün). (3) Ein 'generisch erleichterter/"
    "glücklicher Mensch' bzw. reines Familien-Wohlfühl-Stock OHNE erkennbaren Bezug zu Steuer/Informiert-"
    "sein (das Bild könnte für jedes Produkt stehen). (4) Stumpfes Aufs-Handy-Starren oder rein "
    "dekoratives Posieren; UI/Chatblasen/App-Symbolik als Hauptmotiv. Gut ist eine konkrete, "
    "themenbezogene Alltags-HANDLUNG (Kalender/Frist markieren, Reminder anheften, Tipp lesen)."
)
