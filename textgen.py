# -*- coding: utf-8 -*-
"""M3 - Texterstellung mit Claude. Erzeugt aus einem Thema einen HILO-Beitrag (strukturiert)."""
import json, logging, os
from secrets_store import get_secret

log = logging.getLogger("hilo.textgen")

SYSTEM = (
    "Du bist Social-Media-Redakteur fuer den Lohnsteuerhilfeverein HILO.\n\n"
    "ZIELGRUPPE: Steuerliche Laien - Arbeitnehmer, Rentner, Familien mit Kindern, private Vermieter.\n\n"
    "TONALITAET: Klar, direkt, menschlich - durchgehend in der Sie-Form (gesiezt). Nicht belehrend, "
    "nicht trocken. Schreibe mit PEP und Aufmerksamkeit, wie ein wertvoller Tipp unter guten Bekannten. "
    "Sei konkret, lebendig und neugierig machend statt allgemein und langweilig.\n\n"
    "SPRACHE: Alle Begriffe vollstaendig ausschreiben - KEINE Abkuerzungen (auch nicht im Bild oder in "
    "Bullets). Beispiel: 'Arbeitnehmer' statt 'AN', 'zum Beispiel' statt 'z.B.', 'Werbungskosten' statt 'WK'.\n\n"
    "UMLAUTE (SEHR WICHTIG): Schreibe AUSNAHMSLOS mit echten deutschen Umlauten und Eszett "
    "(ä, ö, ü, Ä, Ö, Ü, ß). Verwende NIEMALS die ASCII-Ersatzschreibweisen ae, oe, ue, Ae, Oe, Ue oder ss. "
    "Das gilt fuer JEDES Feld (Ueberschrift, Caption, Bullets, CTA). "
    "Richtig: 'für', 'Überschrift', 'persönlich', 'Grüße', 'Steuererklärung'. "
    "Falsch: 'fuer', 'Ueberschrift', 'persoenlich', 'Gruesse', 'Steuererklaerung'.\n\n"
    "AUFBAU JEDES BEITRAGS:\n"
    "1) UEBERSCHRIFT (erscheint gross auf dem Bild): kurze, knackige Schlagzeile mit Hook-Charakter, die "
    "sofort neugierig macht - kein allgemeiner Einstieg. Hoechstens 60 Zeichen.\n"
    "2) CAPTION (Begleittext unter dem Bild): Der ERSTE SATZ ist der Hook - HOECHSTENS 10 Woerter, "
    "ueberraschend und direkt (NICHT 'Die Steuererklaerung ist wichtig', sondern z.B. 'Viele verschenken "
    "jedes Jahr hunderte Euro.'). Nutze - WENN das Thema ihn hergibt - einen konkreten Fakt, eine Frist "
    "oder ein Gerichtsurteil als Aufhaenger und nenne die Quelle als TEXT, NIE als Link (z.B. 'Laut "
    "Bundesfinanzhof ...', 'Laut Bundesfinanzministerium ...'). Erklaere das Thema knapp, nutzenorientiert "
    "und OHNE Fachchinesisch, sprich konkrete Alltagssituationen an. Stelle direkt VOR dem Handlungsaufruf "
    "eine kurze INTERAKTIONSFRAGE (regt zum Kommentieren an). Ende mit einem klaren Handlungsaufruf und "
    "weise dezent auf die persoenliche HILO-Beratung hin. Emojis SPARSAM (Anzahl/Hashtags je Kanal siehe "
    "Plattform-Vorgaben).\n"
    "3) BULLETS (erscheinen als Text auf dem Bild): hoechstens 5 Woerter je Bullet, stichpunktartig, keine "
    "vollstaendigen Saetze, nur gesicherte Aussagen.\n"
    "4) CTA (erscheint auf dem Bild): kurze Handlungsaufforderung OHNE erfundene Webadresse, zum Beispiel "
    "'Jetzt Beratungsstelle in Ihrer Naehe finden'.\n"
    "5) SLOGAN: sehr kurzer, einpraegsamer HILO-Slogan, hoechstens 3 Woerter (oder leer fuer Standard).\n"
    "6) SZENE_MOTIV (NEU, wichtigstes Bildfeld): eine kurze Beschreibung einer emotionalen, "
    "authentischen Szene MIT Umgebung fuer ein vollflaechiges Magazin-/Editorial-Foto (KEIN "
    "freigestelltes Motiv). Verbinde JAHRESZEIT + GEFUEHL + einen dezenten THEMENBEZUG, z.B. "
    "'warmer Spaetsommer-Nachmittag, eine entspannte Familie am Kuechentisch sortiert gemeinsam "
    "Unterlagen, Erleichterung und Vertrauen' oder 'goldenes Herbstlicht, ein aelteres Paar laechelt "
    "beim Blick auf einen Brief, Geborgenheit'. Warmes, weiches Tageslicht, natuerlich, keine steifen "
    "Posen. KEIN Text/Logo im Bild. Kurz (ein Satz).\n"
    "7) BILD_MOTIV: kurzes Ersatzmotiv (Fallback) im selben Stil wie szene_motiv - wird genutzt, falls "
    "szene_motiv fehlt. Ebenfalls eine warme, authentische Szene mit Umgebung.\n"
    "8) HERO (OPTIONAL): ein KURZER, echter Zahl-/Datums-/Betrags-Wert aus dem Inhalt, der sich als "
    "grosser Blickfang eignet (z.B. '1.230 Euro', '31. Juli', '35 %'). NUR ausfuellen, wenn im Thema/"
    "Inhalt eine solche Zahl TATSAECHLICH vorkommt. Gibt es keine echte Zahl: LEER lassen ('') - "
    "NIEMALS eine Zahl, Frist oder einen Betrag erfinden.\n\n"
    "WICHTIG:\n"
    "- Erfinde NIEMALS Gerichtsurteile, Aktenzeichen, Zahlen, Fristen, Quellen, URLs, Adressen oder "
    "Telefonnummern - nutze AUSSCHLIESSLICH, was im Thema steht. Gibt das Thema keinen Fakt/kein Urteil "
    "her, dann nenne auch keins (lieber allgemeiner formulieren als etwas erfinden).\n"
    "- Der HOOK entscheidet, ob jemand weiterliest - hier maximale Sorgfalt.\n"
    "- DURCHGEHEND die Sie-Form: die Leser werden IMMER gesiezt (Sie/Ihr/Ihnen), NIEMALS geduzt - "
    "auch nicht im Hook, in der Interaktionsfrage oder im Handlungsaufruf. Kein Wechsel zwischen Du und Sie.\n"
    "- Emojis NUR in der Caption verwenden. Ueberschrift, Bullets und CTA werden als Text auf das Bild "
    "gezeichnet - dort KEINE Emojis und keine Sonderzeichen, die eine Standard-Schrift nicht darstellen kann."
)

CHANNEL_LIMIT = {"google": 1400, "linkedin": 1300, "instagram": 1500, "facebook": 1400}

# Plattformspezifische Vorgaben fuer die Caption (Ton, Laenge, Hashtags) - werden in den
# Auftrags-Prompt eingesetzt, damit jeder Kanal seinen passenden Stil bekommt.
CHANNEL_GUIDE = {
    "facebook": (
        "PLATTFORM FACEBOOK (Hauptkanal): Freundlich, persoenlich, etwas ausfuehrlicher - Zielgruppe hier "
        "am staerksten (Rentner, Familien). HOECHSTENS 150 Woerter. HOECHSTENS 2 Emojis. KEIN Link und "
        "KEIN Verweis auf einen Link im Text (ein Termin-Hinweis wird automatisch ergaenzt). Beende mit "
        "4 bis 5 thematisch passenden Hashtags, #HILO als LETZTEN."
    ),
    "instagram": (
        "PLATTFORM INSTAGRAM (Hauptkanal): Moderner, visuell gedacht - das Bild traegt die Hauptlast. "
        "HOECHSTENS 100 Woerter. HOECHSTENS 2 Emojis. Der Hook MUSS in die ersten 125 Zeichen passen. "
        "Gestalte den Inhalt so, dass man ihn gern weitersendet (praktischer Tipp oder Ueberraschungseffekt). "
        "KEINE URL und KEIN Verweis auf einen Link im Text (ein Bio-Hinweis wird automatisch ergaenzt). "
        "Beende mit 3 bis 5 thematisch gebuendelten Hashtags, #HILO als LETZTEN."
    ),
    "linkedin": (
        "PLATTFORM LINKEDIN: Sachlich-informativer Ton, Fachsprache erlaubt, KEIN Werbeton."
    ),
    "google": (
        "PLATTFORM GOOGLE BUSINESS: Kurz, lokal und suchrelevant - Ort und Leistung prominent."
    ),
    "whatsapp_kanal": (
        "WHATSAPP-KANAL: HOECHSTENS 3 Saetze, sofortiger Mehrwert (praktischer Tipp), KEIN Werbeton, "
        "KEINE Hashtags. KEINE Links im Text (Quell- und Buchungslink werden automatisch ergaenzt)."
    ),
    "whatsapp_story": (
        "WHATSAPP-STATUS (Story): HOECHSTENS 2 Saetze mit einer direkten Handlungsaufforderung. "
        "KEINE Hashtags, KEINE Links im Text (werden automatisch ergaenzt)."
    ),
}

def _model():
    return os.environ.get("HILO_CLAUDE_MODEL", "claude-sonnet-4-6")

# --- #143: Art-Director-Schritt (NUR im Bild-Stil 'kreativ') -----------------------------------
# Zweistufig: NACH der Texterzeugung erzeugt die Text-KI (Claude) ZUSAETZLICH ein konkretes
# Szene-Motiv (fields['kreativ_motiv']) fuer ein kinoreifes Foto OHNE Text. Exakter deutscher
# Wortlaut (echte Umlaute). Dieser Schritt laeuft AUSSCHLIESSLICH im kreativ-Modus, damit in den
# Stilen standard/ki_tafel KEIN zusaetzlicher KI-Aufruf (kein zusaetzlicher Token-Verbrauch) anfaellt.
ART_DIRECTOR_SYSTEM = (
    "Du bist ein preisgekrönter Art Director und Social-Media-Marketing-Experte."
)

def _art_director_prompt(fields):
    """Baut die Art-Director-Anweisung (#143) aus dem fertigen Beitrag (Überschrift + Caption +
    Bullets). Exakter, deutscher Wortlaut mit echten Umlauten. Die KI liefert NUR die Bildszene
    (1-3 Sätze) zurück - daraus wird fields['kreativ_motiv']."""
    f = fields if isinstance(fields, dict) else {}
    ueberschrift = (f.get("ueberschrift") or "").strip()
    caption = (f.get("caption") or "").strip()
    if not caption:
        caps = f.get("captions") if isinstance(f.get("captions"), dict) else {}
        caption = (caps.get("facebook") or caps.get("instagram") or "").strip()
    bullets_raw = f.get("bullets")
    bullets = ""
    if isinstance(bullets_raw, (list, tuple)):
        bullets = "; ".join((str(b) if b is not None else "").strip()
                            for b in bullets_raw if b is not None and str(b).strip())
    beitrag = ("Überschrift: %s\n\nBeitragstext: %s\n\nStichpunkte: %s"
               % (ueberschrift or "-", caption or "-", bullets or "-"))
    return (
        "Du bist ein preisgekrönter Art Director und Social-Media-Marketing-Experte. Lies den "
        "folgenden Beitragstext. Finde die EINE überraschendste, kontraintuitivste Erkenntnis. "
        "Entwirf dann eine fotorealistische, kinoreif beleuchtete Bildszene, auf die eine "
        "Top-Kreativagentur stolz wäre - KEINE Stockfoto-Ästhetik, KEINE Klischees (keine "
        "Taschenrechner, keine Ordner, keine Händedrücke). Visualisiere die emotionale oder "
        "finanzielle KONSEQUENZ über echte Objekte, echte Menschen, echte Situationen. Nutze "
        "visuellen Kontrast, Spannung oder Ironie für Stopping Power. KEIN Text im Bild. Gib NUR "
        "die konkrete Bildszene-Beschreibung zurück (1-3 Sätze).\n\n%s" % beitrag
    )

def art_director_motiv(fields, client=None):
    """#143: Setzt fields['kreativ_motiv'] - das konkrete Szene-Motiv fuer ein kinoreifes Foto OHNE
    Text - per Art-Director-Schritt (zusaetzlicher Claude-Aufruf). Eigenschaften:

    - NUR im Bild-Stil 'kreativ' aktiv: bei jedem anderen Stil wird KEIN KI-Aufruf gemacht und
      fields unveraendert zurueckgegeben (kein zusaetzlicher Token-Verbrauch).
    - STABIL: ist fields['kreativ_motiv'] bereits gesetzt (Re-Render/Regenerate), bleibt es
      UNVERAENDERT (kein neuer KI-Aufruf) - nur wenn leer wird es gesetzt.
    - ROBUST: jeder Fehler (kein Key, KI-/Parse-Fehler) wird abgefangen; fields bleibt dann ohne
      kreativ_motiv (Fallback: ensure_photo_fuer/_kreativ_scene nutzt szene_motiv/bild_motiv).

    'client' kann ein bereits erzeugter anthropic-Client sein (spart einen zweiten Verbindungs-
    aufbau im selben Erzeugungslauf); fehlt er, wird bei Bedarf einer erzeugt. Mockbar: Tests
    koennen client durch ein Objekt mit messages.create(...) ersetzen (kein echter KI-Aufruf)."""
    if not isinstance(fields, dict):
        return fields
    # #144: kreativ-Gate PRO BEITRAG. Der Kosten-/Token-Schutz bleibt erhalten - der Art-Director-
    # Aufruf erfolgt NUR, wenn der fuer DIESEN Beitrag gewaehlte Stil 'kreativ' ist
    # (fields['bild_stil']), nicht mehr anhand der globalen Einstellung. Fallback (kein
    # fields['bild_stil']): globale Einstellung/'standard' via stilwahl.aktiver_stil.
    try:
        import stilwahl
        stil = stilwahl.aktiver_stil(fields)
    except Exception:
        stil = "standard"
    if stil != "kreativ":
        return fields
    # Stabil: bereits gesetztes Motiv NICHT ueberschreiben (kein neuer KI-Aufruf).
    if (fields.get("kreativ_motiv") or "").strip():
        return fields
    try:
        if client is None:
            key = get_secret("anthropic_api_key")
            if not key:
                log.info("Art-Director-Schritt uebersprungen: kein 'anthropic_api_key' hinterlegt.")
                return fields
            import anthropic  # lazy
            client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=_model(), max_tokens=400, system=ART_DIRECTOR_SYSTEM,
            messages=[{"role": "user", "content": _art_director_prompt(fields)}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        if raw:
            fields["kreativ_motiv"] = raw[:600]
            log.info("Art-Director-Motiv erzeugt (#143): %s", raw[:60])
    except Exception as ex:
        log.warning("Art-Director-Schritt fehlgeschlagen (#143): %s", ex)
    return fields

# --- Comic-Stil: Bild-Brief-Schritt (NUR im Bild-Stil 'comic') -----------------------------------
# Analog zu art_director_motiv: NACH der Texterzeugung liefert die Text-KI (Claude) einen kompakten
# "Bild-Brief" (fields['comic_brief']) fuer eine Comic-Illustration. Das Bild soll NICHT das
# Steuerthema woertlich illustrieren, sondern die STIMMUNG + ein greifbares Alltagsmotiv.
COMIC_BRIEF_SYSTEM = (
    "Du bist Bildredakteur und Comic-Art-Director fuer einen serioesen Lohnsteuerhilfeverein."
)

def _comic_brief_prompt(fields):
    """Baut die Comic-Brief-Anweisung aus dem fertigen Beitrag (Ueberschrift + Caption + Bullets).
    Exakter deutscher Wortlaut mit echten Umlauten. Die KI liefert NUR ein JSON-Objekt zurueck -
    daraus wird fields['comic_brief']."""
    f = fields if isinstance(fields, dict) else {}
    ueberschrift = (f.get("ueberschrift") or "").strip()
    caption = (f.get("caption") or "").strip()
    if not caption:
        caps = f.get("captions") if isinstance(f.get("captions"), dict) else {}
        caption = (caps.get("facebook") or caps.get("instagram") or "").strip()
    bullets_raw = f.get("bullets")
    bullets = ""
    if isinstance(bullets_raw, (list, tuple)):
        bullets = "; ".join((str(b) if b is not None else "").strip()
                            for b in bullets_raw if b is not None and str(b).strip())
    beitrag = ("Ueberschrift: %s\n\nBeitragstext: %s\n\nStichpunkte: %s"
               % (ueberschrift or "-", caption or "-", bullets or "-"))
    return (
        "Lies den folgenden HILO-Steuerbeitrag und erfinde den BILD-EINFALL fuer EINE clevere "
        "Comic-Illustration. Ziel ist ein WITZIGES, ueberraschendes Bild, das man sich merkt - "
        "NICHT eine brave, austauschbare Szene.\n\n"
        "REGELN:\n"
        "- VERBOTEN ist die langweilige Standardloesung 'eine sorgenvolle/nachdenkliche Person am "
        "Tisch mit einem Brief'. Finde stattdessen einen echten EINFALL - waehle einen dieser Wege:\n"
        "  * KUNST-/KULTUR-ANSPIELUNG passend zum Thema (z.B. bei Auslands-/Laenderbezug ein "
        "beruehmter Maler oder ein Wahrzeichen des Landes; bei Zeit/Frist eine surreale schmelzende "
        "Uhr im Dali-Stil), ODER\n"
        "  * visuelle METAPHER / Wortwitz (z.B. Geld, das jemandem unbemerkt aus der Tasche faellt; "
        "eine Falle, die zuschnappt; ein Regenschirm, der nicht schuetzt; eine Tuer, die aufgeht), ODER\n"
        "  * die wiederkehrende FINANZAMT-FIGUR (ein leicht ueberkorrekter, stempel-verliebter "
        "Beamter mit Riesenstempel), die dem Buerger einen Strich durch die Rechnung macht.\n"
        "- Das Bild illustriert also NICHT den Paragraphen, sondern bringt Thema + Stimmung mit einem "
        "Augenzwinkern auf den Punkt.\n"
        "- AUSNAHME Ton: bei Pflege, Krankheit, Tod, Trauer oder Familie in Not KEIN Humor. Dann "
        "stimmung='wuerdevoll' und ein STILLES, kuenstlerisches Motiv (z.B. zwei Haende, alt und jung, "
        "die sich halten) - poetisch, wuerdevoll, ohne Gag und ohne Finanzamt-Figur.\n"
        "- 'finanzamt_figur' nur true, wenn ein klarer 'Buerger-gegen-Finanzamt'-Dreh passt (Falle, "
        "Ablehnung, Bescheid, gestrichen) UND stimmung != 'wuerdevoll'.\n"
        "- WICHTIG - Themen-Treue: Alle Bild-Elemente muessen zum TATSAECHLICHEN Thema passen. Keine "
        "Symbole, die dem Thema widersprechen - insbesondere KEIN 'GESTRICHEN'-Stempel, wenn es NICHT "
        "um eine Ablehnung/Streichung geht (z.B. bei 'Steuersatz steigt / Progressionsvorbehalt' zeigt "
        "die Szene die Mehrbelastung bzw. das Steigen, NICHT eine Streichung). Der Finanzamt-Beamte "
        "darf auftreten, tut aber etwas Themen-Passendes - nicht automatisch stempeln.\n"
        "- Bei GUTER Nachricht (steuerfrei, Vorteil, 'das Finanzamt bekommt nichts') ist ein starker "
        "Dreh: der Buerger bzw. die Familie profitiert sichtbar und freut sich, waehrend der "
        "Finanzamt-Beamte LEER AUSGEHT (leere Hand, zieht enttaeuscht ab). So wird die gute Nachricht "
        "zum Bild - nicht nur eine woertliche Szene.\n\n"
        "BEISPIELE (Thema -> szene):\n"
        "- 'Rente aus den Niederlanden, Aerger mit dem Finanzamt' -> 'Eine Karikatur von Vincent van "
        "Gogh (Strohhut, roter Bart) haelt ratlos einen deutschen Finanzamt-Brief in den Haenden.'\n"
        "- 'Frist verpasst, Brief kam zu spaet' -> 'Eine schmelzende Taschenuhr im Dali-Stil, ueber "
        "deren Rand ein amtlicher Briefumschlag zerlaeuft, daneben ein Wandkalender.'\n"
        "- 'Steuer-App verschenkt Geld' -> 'Eine Person tippt begeistert aufs Handy, waehrend ihr "
        "unbemerkt Euro-Muenzen aus der Hosentasche kullern.'\n"
        "- 'Abfindung/Erbe steuerfrei - das Finanzamt bekommt nichts' -> 'Eine Familie haelt zufrieden "
        "und laechelnd ein Geldbuendel fest, waehrend der Finanzamt-Beamte daneben mit leeren Haenden "
        "entaeuscht abzieht.'\n\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown):\n"
        '{"stimmung": "humor|positiv|wuerdevoll|sachlich", '
        '"szene": "ein bis zwei Saetze, der konkrete visuelle Einfall MIT Umgebung/Hintergrund '
        '(Figur + Ort + ein zwei atmosphaerische Details), bildreich, deutsch", '
        '"hook": "kurzer Bild-Hook oder leerer String", '
        '"finanzamt_figur": true oder false}\n\n%s' % beitrag
    )

def _comic_brief_fallback(fields):
    """Robuster Fallback, wenn der Comic-Brief-Aufruf/das Parsen fehlschlaegt: neutrale, sachliche
    Stimmung; Szene aus der Ueberschrift; kein Hook, keine Finanzamt-Figur."""
    f = fields if isinstance(fields, dict) else {}
    ueberschrift = (f.get("ueberschrift") or "").strip()
    return {"stimmung": "sachlich",
            "szene": (ueberschrift or "eine ruhige Alltagsszene am Kuechentisch")[:200],
            "hook": "", "finanzamt_figur": False}

def comic_brief(fields, client=None):
    """Setzt fields['comic_brief'] - einen kompakten Bild-Brief (Stimmung + Alltagsszene) fuer die
    Comic-Illustration - per zusaetzlichem Claude-Aufruf. Eigenschaften analog art_director_motiv:

    - STABIL: ist fields['comic_brief'] bereits ein dict, bleibt es UNVERAENDERT (kein neuer Aufruf).
    - ROBUST: jeder Fehler (kein Key, KI-/Parse-Fehler) faellt auf _comic_brief_fallback zurueck -
      fields['comic_brief'] ist danach IMMER ein gueltiges dict (nie None).

    'client' kann ein bereits erzeugter anthropic-Client sein (mockbar in Tests). Rueckgabe: fields.
    Anders als art_director_motiv gibt es hier KEIN Stil-Gate: der Aufrufer (Bild-Generieren-Route)
    ruft comic_brief NUR im Comic-Fall auf - so bleibt der Token-Verbrauch on-demand."""
    if not isinstance(fields, dict):
        return fields
    if isinstance(fields.get("comic_brief"), dict) and fields["comic_brief"]:
        return fields
    brief = None
    try:
        if client is None:
            key = get_secret("anthropic_api_key")
            if not key:
                log.info("Comic-Brief uebersprungen: kein 'anthropic_api_key' hinterlegt.")
                fields["comic_brief"] = _comic_brief_fallback(fields)
                return fields
            import anthropic  # lazy
            client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=_model(), max_tokens=400, system=COMIC_BRIEF_SYSTEM,
            messages=[{"role": "user", "content": _comic_brief_prompt(fields)}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content)
        data = _parse_json(raw)
        if isinstance(data, dict):
            stimmung = str(data.get("stimmung") or "sachlich").strip().lower()
            if stimmung not in ("humor", "positiv", "wuerdevoll", "sachlich"):
                stimmung = "sachlich"
            szene = (str(data.get("szene") or "").strip()
                     or _comic_brief_fallback(fields)["szene"])
            hook = str(data.get("hook") or "").strip()
            finanzamt = bool(data.get("finanzamt_figur"))
            # Sicherung: bei wuerdevoller Stimmung NIE die (comic-hafte) Finanzamt-Figur.
            if stimmung == "wuerdevoll":
                finanzamt = False
            brief = {"stimmung": stimmung, "szene": szene[:400],
                     "hook": hook[:200], "finanzamt_figur": finanzamt}
            log.info("Comic-Brief erzeugt: %s / %s", stimmung, szene[:50])
    except Exception as ex:
        log.warning("Comic-Brief fehlgeschlagen: %s", ex)
        brief = None
    fields["comic_brief"] = brief or _comic_brief_fallback(fields)
    return fields

# --- Comic-Strip v2 (#155): Archetyp-/Varianten-Vorauswahl (leichter Text-KI-Schritt) -----------
# Claude liest den fertigen Beitrag und liefert eine VORAUSWAHL fuer das Bild-2-Dropdown:
#   {"archetyp": "vorteil"|"warnung", "variant_index": int}
# 'vorteil' = gute Nachricht, HILO bringt einen Vorteil (trauriger Aermelschoner - jemand WAR bei
# HILO). 'warnung' = ohne HILO Nachteil / Finanzamt lehnt ab (schadenfroher Aermelschoner - jemand
# war NICHT bei HILO). Nur Text-Tokens, kein zusaetzliches Bild; der Aufrufer ruft die Funktion NUR
# im Comic-Strip-Fall auf. Menschliche Freigabe bleibt (Redakteurin kann die Wahl aendern).
COMIC_STRIP_VORAUSWAHL_SYSTEM = (
    "Du bist Bildredakteur fuer einen serioesen Lohnsteuerhilfeverein (HILO)."
)


def _comic_strip_vorauswahl_fallback(fields):
    """Robuster Fallback ohne Key/bei Fehlern: leitet den Archetyp aus einem evtl. vorhandenen
    comic_brief ab (Stimmung/finanzamt_figur). Steht keine Info bereit -> Default 'vorteil', Index 0
    (bisheriges v1-Verhalten). Liefert IMMER ein gueltiges dict."""
    f = fields if isinstance(fields, dict) else {}
    brief = f.get("comic_brief") if isinstance(f.get("comic_brief"), dict) else {}
    stimmung = str(brief.get("stimmung") or "").strip().lower()
    finanzamt = bool(brief.get("finanzamt_figur"))
    # Nur wenn die Finanzamt-Figur einen 'Buerger-gegen-Finanzamt'-Dreh signalisiert UND die
    # Stimmung nicht ausdruecklich positiv/wuerdevoll ist, deuten wir es als 'warnung'. Sonst
    # bleibt es beim Default 'vorteil'.
    archetyp = "warnung" if (finanzamt and stimmung not in ("positiv", "wuerdevoll")) else "vorteil"
    return {"archetyp": archetyp, "variant_index": 0}


def _comic_strip_vorauswahl_prompt(fields):
    """Baut die Vorauswahl-Anweisung aus dem fertigen Beitrag + den konkreten Bild-2-Varianten
    (aus bildmotiv.COMIC_STRIP_VARIANTEN, lazy importiert), damit Claude einen gueltigen
    variant_index waehlen kann. Exakter deutscher Wortlaut mit echten Umlauten."""
    f = fields if isinstance(fields, dict) else {}
    ueberschrift = (f.get("ueberschrift") or "").strip()
    caption = (f.get("caption") or "").strip()
    if not caption:
        caps = f.get("captions") if isinstance(f.get("captions"), dict) else {}
        caption = (caps.get("facebook") or caps.get("instagram") or "").strip()
    beitrag = "Ueberschrift: %s\n\nBeitragstext: %s" % (ueberschrift or "-", caption or "-")
    try:
        import bildmotiv
        varianten = bildmotiv.COMIC_STRIP_VARIANTEN
    except Exception:
        varianten = {"vorteil": [], "warnung": []}
    def _liste(key):
        return "\n".join("  [%d] %s" % (i, v) for i, v in enumerate(varianten.get(key, [])))
    return (
        "Fuer einen dreiteiligen HILO-Comic-Strip gibt es zwei Story-Archetypen. Waehle anhand des "
        "folgenden Beitrags den PASSENDEN Archetyp und die passendste Bild-2-Aussage (Aermelschoner "
        "des Finanzamt-Beamten).\n\n"
        "- 'vorteil': gute Nachricht - jemand WAR bei HILO und spart Steuern; der Aermelschoner ist "
        "TRAURIG/geknickt. Waehle diesen Archetyp, wenn der Beitrag einen konkreten HILO-Vorteil, "
        "eine Ersparnis oder eine gute Nachricht vermittelt.\n"
        "- 'warnung': jemand war NICHT bei HILO und zahlt drauf / das Finanzamt lehnt ab; der "
        "Aermelschoner ist SCHADENFROH. Waehle diesen Archetyp, wenn der Beitrag vor einem Fehler, "
        "einer verpassten Chance oder einem Nachteil ohne Beratung warnt.\n\n"
        "Bild-2-Varianten 'vorteil' (traurig):\n%s\n\n"
        "Bild-2-Varianten 'warnung' (schadenfroh):\n%s\n\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown):\n"
        '{"archetyp": "vorteil|warnung", "variant_index": <0-basierter Index in der Liste des '
        'gewaehlten Archetyps>}\n\n%s' % (_liste("vorteil"), _liste("warnung"), beitrag)
    )


def comic_strip_vorauswahl(fields, client=None):
    """#155: Leichter Text-KI-Schritt. Liest den Beitrag und liefert eine VORAUSWAHL fuer den
    Comic-Strip: {'archetyp': 'vorteil'|'warnung', 'variant_index': int}. Eigenschaften:

    - ROBUST: jeder Fehler (kein Key, KI-/Parse-Fehler) faellt auf _comic_strip_vorauswahl_fallback
      zurueck (aus comic_brief abgeleitet bzw. Default vorteil/0). Es gibt NIE einen Crash und die
      Rueckgabe ist IMMER ein gueltiges dict.
    - variant_index wird gegen die tatsaechliche Variantenzahl des gewaehlten Archetyps geklemmt.

    'client' kann ein bereits erzeugter anthropic-Client sein (mockbar in Tests). Es wird KEIN
    fields mutiert - die Funktion liefert nur die Vorauswahl (der Aufrufer persistiert sie)."""
    f = fields if isinstance(fields, dict) else {}
    default = _comic_strip_vorauswahl_fallback(f)
    try:
        if client is None:
            key = get_secret("anthropic_api_key")
            if not key:
                log.info("Comic-Strip-Vorauswahl uebersprungen: kein 'anthropic_api_key' hinterlegt.")
                return default
            import anthropic  # lazy
            client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=_model(), max_tokens=200, system=COMIC_STRIP_VORAUSWAHL_SYSTEM,
            messages=[{"role": "user", "content": _comic_strip_vorauswahl_prompt(f)}],
        )
        raw = "".join(getattr(b, "text", "") for b in msg.content)
        data = _parse_json(raw)
        if isinstance(data, dict):
            archetyp = str(data.get("archetyp") or "").strip().lower()
            if archetyp not in ("vorteil", "warnung"):
                archetyp = default["archetyp"]
            try:
                idx = int(data.get("variant_index"))
            except Exception:
                idx = 0
            try:
                import bildmotiv
                n = len(bildmotiv.COMIC_STRIP_VARIANTEN.get(archetyp, []))
            except Exception:
                n = 0
            if n and not (0 <= idx < n):
                idx = 0
            elif idx < 0:
                idx = 0
            log.info("Comic-Strip-Vorauswahl: %s / %d", archetyp, idx)
            return {"archetyp": archetyp, "variant_index": idx}
    except Exception as ex:
        log.warning("Comic-Strip-Vorauswahl fehlgeschlagen: %s", ex)
    return default

def _build_prompt(thema, kanal=None):
    """Ein Auftrag erzeugt den Beitrag fuer Facebook UND Instagram in einem Rutsch: Bild, Ueberschrift
    und Stichpunkte sind fuer beide Kanaele gleich; NUR der Begleittext (caption) unterscheidet sich je
    Kanal nach den plattformspezifischen Vorgaben. So bleibt es bei einem einzigen KI-Aufruf."""
    return (
        "Thema: %s\n"
        "Zusammenfassung/Inhalt: %s\n\n"
        "Erzeuge daraus einen HILO-Beitrag fuer FACEBOOK, INSTAGRAM und WHATSAPP (Kanal + Status). Bild, "
        "Ueberschrift und Stichpunkte sind fuer alle gleich; NUR der Begleittext unterscheidet sich je "
        "Kanal nach diesen Vorgaben:\n\n%s\n\n%s\n\n%s\n\n%s\n\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown) mit genau diesen "
        "Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen", "subline": "max 90 Zeichen", '
        '"bullets": ["3 sehr kurze Stichpunkte, je max 5 Woerter"], "cta": "kurze Handlungsaufforderung", '
        '"slogan": "max 3 Woerter oder leer", '
        '"szene_motiv": "INSZENIERTE Still-Life-Szene mit Objekten/Gegenstaenden - KEINE Personen! Symbolische Objekte zum Thema: Aktenordner, Kalender, Muenzen, Sparschwein, Taschenrechner, Dokumente, Stifte, Stempel, etc. Beschreibe AUSFUEHRLICH (2-3 Saetze): (1) Welche Objekte, (2) Wie arrangiert/inszeniert, (3) Licht/Atmosphaere/Farben. Sei KONKRET und DETAILLIERT - das Motiv ist die Grundlage fuer ein hochwertiges Foto.", '
        '"bild_motiv": "Alternatives Still-Life-Motiv - NUR Objekte, keine Menschen. Kurz beschreiben.", '
        '"hero": "kurze ECHTE Zahl/Datum/Betrag aus dem Inhalt oder leer", '
        '"captions": {"facebook": "Begleittext fuer Facebook inkl. Hashtags am Ende, hoechstens %d '
        'Zeichen", "instagram": "Begleittext fuer Instagram inkl. Hashtags am Ende, hoechstens %d '
        'Zeichen", "whatsapp_kanal": "max 3 Saetze, ohne Hashtags/Links", '
        '"whatsapp_story": "max 2 Saetze mit Handlungsaufforderung, ohne Hashtags/Links"}}\n'
        "Sprache: Deutsch, Sie-Form."
        % (thema.get("titel", ""), (thema.get("volltext") or "")[:1500],
           CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"],
           CHANNEL_GUIDE["whatsapp_kanal"], CHANNEL_GUIDE["whatsapp_story"],
           CHANNEL_LIMIT["facebook"], CHANNEL_LIMIT["instagram"])
    )

def _normalize_captions(data):
    """Stellt sicher, dass data['captions'] beide Kanaele (facebook, instagram) enthaelt und setzt
    data['caption'] als Rueckwaerts-Fallback (= Facebook). Faengt aeltere Antworten mit nur 'caption' ab."""
    if not isinstance(data, dict):
        return data
    caps = data.get("captions") if isinstance(data.get("captions"), dict) else {}
    single = (data.get("caption") or "").strip()
    fb = (caps.get("facebook") or "").strip() or single
    ig = (caps.get("instagram") or "").strip() or single
    fb = fb or ig
    ig = ig or fb
    # WhatsApp-Varianten - Fallback auf den Facebook-Text, falls (z.B. bei aelteren Entwuerfen) nicht erzeugt.
    wa_k = (caps.get("whatsapp_kanal") or "").strip() or fb
    wa_s = (caps.get("whatsapp_story") or "").strip() or wa_k
    data["captions"] = {"facebook": fb, "instagram": ig, "whatsapp_kanal": wa_k, "whatsapp_story": wa_s}
    data["caption"] = fb
    return data

def caption_fuer(fields, kanal):
    """Liefert den kanalspezifischen Begleittext (Fallback: gemeinsame 'caption')."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    return (caps.get(kanal) or fields.get("caption") or "").strip()

def _normalize_bild(data):
    """Sichert die Bildfelder fuer das Magazin-Layout:
    - szene_motiv (neues Hauptfeld): Fallback auf bild_motiv bzw. (fuer alte Entwuerfe) bild_motiv_thema.
    - hero (optional): nur uebernehmen, wenn die KI eine echte Zahl/Frist/Betrag geliefert hat
      (wird hier NICHT erfunden) - sonst leer, dann greift im Bild der Ueberschrift-Hingucker.
    - bild_typ / bild_motiv_thema bleiben aus Rueckwaerts-Kompatibilitaet erhalten."""
    if not isinstance(data, dict):
        return data
    szene = (data.get("szene_motiv") or "").strip()
    bild_motiv = (data.get("bild_motiv") or "").strip()
    thema_motiv = (data.get("bild_motiv_thema") or "").strip()
    data["szene_motiv"] = szene or bild_motiv or thema_motiv
    data["hero"] = (data.get("hero") or "").strip()
    # Altfelder unveraendert erhalten, damit bestehende Entwuerfe/Render-Pfade weiter funktionieren
    typ = (data.get("bild_typ") or "").strip().lower()
    data["bild_motiv_thema"] = thema_motiv
    data["bild_typ"] = "thema" if (typ == "thema" and thema_motiv) else "person"
    return data

def _parse_json(raw):
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    return json.loads(s)

def _parse_json_array(raw):
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    a, b = s.find("["), s.rfind("]")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    data = json.loads(s)
    return data if isinstance(data, list) else []

def extract_topics(volltext, quelle_titel=""):
    """Zerlegt einen laengeren Text (PDF/Webseite) in einzelne, eigenstaendige Themen.
    Rueckgabe: Liste von {"titel":..., "inhalt":...}. Leer, wenn kein Key hinterlegt ist."""
    key = get_secret("anthropic_api_key")
    if not key:
        log.info("Themen-Extraktion uebersprungen: kein 'anthropic_api_key' hinterlegt.")
        return []
    import anthropic  # lazy
    client = anthropic.Anthropic(api_key=key)
    prompt = (
        "Zerlege den folgenden Fachtext in die EINZELNEN behandelten Themen. "
        "Gib nur Themen aus, die fuer die HILO-Zielgruppe relevant sind "
        "(Arbeitnehmer, Rentner, Familien mit Kindern, private Vermieter). "
        "Erfinde nichts - nutze ausschliesslich den Textinhalt. "
        "Antworte AUSSCHLIESSLICH als JSON-Array (keine Erklaerung, kein Markdown), "
        'jedes Element: {"titel": "praegnanter Titel, max 80 Zeichen", '
        '"inhalt": "die zum Thema gehoerenden Fakten aus dem Text, 2-5 Saetze"}. '
        "Wenn nur EIN Thema behandelt wird, gib ein Array mit genau einem Element zurueck. "
        "Quelle: %s\n\nText:\n%s" % (quelle_titel or "-", (volltext or "")[:8000])
    )
    msg = client.messages.create(
        model=_model(), max_tokens=1500,
        system="Du analysierst deutsche Steuer-Fachtexte und zerlegst sie sauber in einzelne Themen.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    try:
        topics = _parse_json_array(raw)
    except Exception as ex:
        log.warning("Themen-Extraktion: Antwort nicht lesbar (%s).", ex)
        return []
    out = []
    for t in topics:
        if isinstance(t, dict) and t.get("titel"):
            out.append({"titel": str(t["titel"])[:300], "inhalt": str(t.get("inhalt", ""))})
    return out

def generate(thema, kanal=None):
    key = get_secret("anthropic_api_key", required=True)
    import anthropic  # lazy
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=_model(), max_tokens=1600, system=SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(thema)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    return _normalize_bild(_normalize_captions(_parse_json(raw)))


def generate_with_campaign(thema, kanal=None, test_mode=False):
    """Neuer 3-Stufen-Workflow mit GPT-5.6 Terra + GPT Image 2 + QA.

    Statt Anthropic Claude verwenden wir den kampagne.run_campaign() Workflow:
    1. GPT-5.6 Terra: Kampagnenplanung
    2. GPT Image 2: Grafik-Generierung (mit Text im Bild!)
    3. GPT-5.6 Terra: Qualitätskontrolle (Retry bei Fehlern)

    Args:
        thema: Dict mit {titel, volltext, url} oder String
        kanal: Ziel-Kanal (für CTA)
        test_mode: True = low quality für Tests, False = high quality

    Returns:
        Dict mit fields + bild_pfad + qa_status

    Raises:
        Exception: Bei Fehlern in der Kampagnen-Generierung
    """
    import kampagne
    import os
    from config import DATA_DIR

    # Thema zu Text konvertieren
    if isinstance(thema, dict):
        article = f"{thema.get('titel', '')}\n\n{thema.get('volltext', '')}"
    else:
        article = str(thema)

    # CTA basierend auf Kanal
    cta = "Jetzt Beratungsstelle finden"
    if kanal == "facebook":
        cta = "Mehr erfahren"
    elif kanal == "instagram":
        cta = "Link in Bio"

    # 3-Stufen-Workflow ausführen
    log.info("3-Stufen-Workflow wird ausgeführt (test_mode=%s)...", test_mode)
    plan, image_path, review, motiv_path = kampagne.run_campaign(
        article=article,
        cta=cta,
        test_mode=test_mode,
    )

    # Bild in das Standard-Verzeichnis kopieren + Logo-Kreise drüberlegen
    import shutil
    import time
    import uuid
    import bildgen
    from pathlib import Path
    final_image_dir = os.path.join(DATA_DIR, "bilder")
    os.makedirs(final_image_dir, exist_ok=True)

    # Eindeutiger Dateiname (timestamp + UUID gegen Race Condition)
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:12]
    final_image_path = os.path.join(final_image_dir, f"campaign_{timestamp}_{unique_id}.png")

    # Logo-Kreise drüberlegen (wie bei bildgen.render() für v5.x Bilder)
    slogan = bildgen.pick_slogan(None)
    bildgen.add_logo_circles(image_path, slogan, final_image_path, pos="diagonal2")

    # Fields zusammenstellen (kompatibel mit bestehendem Format)
    fields = {
        "ueberschrift": plan.headline,
        "subline": plan.core_message,  # Kernaussage als Subline
        "bullets": plan.supporting_points,
        "cta": plan.cta,
        "caption": plan.caption,  # Begleittext ✅
        "bild_motiv": plan.visual_concept,  # Für Dokumentation
        "bild_stil": "standard",  # v5.x wird automatisch erkannt
        "bild_pfad": final_image_path,  # Bild ist BEREITS erstellt!
        "qa_approved": review.approved,  # QA-Status
        "qa_problems": review.problems if not review.approved else [],
        # NEU: rohes Motiv + Layout fuer personalisierung.render_fuer_stelle - damit die
        # Personalisierung je Beratungsstelle (anderer CTA-Text IM Bild) den Text per Pillow
        # neu drauf rendern kann, OHNE nochmal GPT Image 2 aufzurufen (#Kostenschutz).
        "kampagne_motiv_pfad": str(motiv_path),
        "kampagne_layout_template": plan.layout_template,
        "highlight_words": plan.highlight_words,
    }

    log.info("3-Stufen-Workflow abgeschlossen: %s (QA: %s)",
             plan.headline, "✅" if review.approved else "❌")

    return fields


def _create_drafts(rows, kanal, use_campaign=False, test_mode=False):
    """Erzeugt fuer die uebergebenen Themen-Zeilen je einen Entwurf.

    Args:
        rows: Themen-Zeilen aus der DB
        kanal: Ziel-Kanal (google, facebook, instagram)
        use_campaign: True = 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2 + QA)
                      False = Anthropic Claude (bisheriger Workflow)
        test_mode: True = low quality für Tests (nur bei use_campaign=True)

    Returns:
        Anzahl erzeugter Entwuerfe

    Note:
        Alle Bilder werden NUR NOCH mit ShareNext Premium generiert!
    """
    from db import get_conn
    created = 0
    for r in rows:
        try:
            # WAHL: 3-Stufen-Workflow oder bisheriger Claude-Workflow
            if use_campaign:
                data = generate_with_campaign(
                    {"titel": r["titel"], "volltext": r["volltext"], "url": r["url"]},
                    kanal,
                    test_mode=test_mode
                )
            else:
                data = generate({"titel": r["titel"], "volltext": r["volltext"], "url": r["url"]}, kanal)
            with get_conn() as conn:
                # #144: Bild-Stil EINMAL zufaellig aus den aktiven Stilen waehlen und in
                # fields['bild_stil'] ablegen (stabil ueber Re-Renders). Robust gegen Fehler.
                try:
                    import stilwahl
                    stilwahl.zuweisen_stil_falls_fehlt(conn, data)
                except Exception as ex:
                    log.warning("Stil-Zuweisung uebersprungen: %s", ex)
                # #143/#144: NUR wenn der PRO-BEITRAG-Stil 'kreativ' ist, ein zusaetzliches
                # Art-Director-Motiv erzeugen (stabil, nur-wenn-leer). Sonst No-Op (kein KI-Aufruf).
                art_director_motiv(data)
                # #140: Schauplatz EINMAL bei der Erzeugung waehlen und in fields['schauplatz']
                # ablegen (stabil ueber Re-Renders/Personalisierung; KI-Tafel nutzt ihn als Szene).
                import schauplatz
                schauplatz.zuweisen_falls_fehlt(conn, data)
                # #142: zusaetzlich den Traeger (Device der Botschaft) EINMAL waehlen, ebenfalls
                # stabil in fields['traeger']. Robust: fehlt die Tabelle (alte DB) -> No-Op.
                try:
                    import traeger
                    traeger.zuweisen_traeger_falls_fehlt(conn, data)
                except Exception as ex:
                    log.warning("Traeger-Zuweisung uebersprungen: %s", ex)
                cursor = conn.execute(
                    "INSERT INTO entwuerfe(thema_id, kanal, text, status, bild_pfad) VALUES (?,?,?, 'entwurf', ?)",
                    (r["id"], kanal, json.dumps(data, ensure_ascii=False), data.get("bild_pfad")))
                entwurf_id = cursor.lastrowid

                # ShareNext Premium-Bilder generieren (IMMER!)
                try:
                    log.info("Generiere ShareNext Bild für Entwurf %s...", entwurf_id)
                    from sharenext_pipeline import run_sharenext_pipeline
                    import tempfile, os as _os
                    import bildgen as _bildgen

                    # ShareNext Pipeline ausführen - MIT headline vom Campaign Plan!
                    result = run_sharenext_pipeline(
                        stream="radar",
                        thema=data.get("ueberschrift", r["titel"]),
                        text="\n".join(data.get("bullets", [])),
                        kanal=kanal.capitalize(),
                        headline=data.get("ueberschrift", ""),
                        size="1024x1024",
                        quality="medium"
                    )

                    # Nur Logo-Kreise hinzufügen (GPT schreibt Text schon ins Bild!)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_raw:
                        result.image.save(tmp_raw.name, "PNG")
                        slogan = _bildgen.pick_slogan("")

                        from config import DATA_DIR as _DATA_DIR
                        _os.makedirs(_DATA_DIR, exist_ok=True)

                        # ShareNext Bild als Hauptbild speichern
                        bild_pfad = _os.path.join(_DATA_DIR, f"entwurf_{entwurf_id}.png")
                        _bildgen.add_logo_circles(tmp_raw.name, slogan, bild_pfad, pos="unten")

                        # WICHTIG: bild_pfad + alt_text in DB Spalte UND im JSON setzen!
                        # render_fuer_stelle() liest aus dem JSON, nicht aus der DB Spalte!
                        data["bild_pfad"] = bild_pfad
                        data["alt_text"] = result.production_brief.alt_text or ""
                        conn.execute("UPDATE entwuerfe SET bild_pfad=?, text=? WHERE id=?",
                                   (bild_pfad, json.dumps(data, ensure_ascii=False), entwurf_id))
                        log.info("✓ ShareNext Bild generiert: %s", bild_pfad)
                        if result.production_brief.alt_text:
                            log.info("✓ Alt-Text: %s", result.production_brief.alt_text[:80])

                        _os.unlink(tmp_raw.name)

                except Exception as ex:
                    log.error("ShareNext Bildgenerierung fehlgeschlagen (Entwurf %s): %s", entwurf_id, ex)
                    # Kein Fallback mehr - ShareNext ist einzige Option!

            created += 1
            log.info("Entwurf erzeugt: Thema %s - %s", r["id"], (r["titel"] or "")[:60])
        except Exception as ex:
            log.warning("Texterzeugung fehlgeschlagen (Thema %s): %s", r["id"], ex)
    return created

def generate_drafts(limit=3, kanal="google", use_campaign=False, test_mode=False):
    """Erzeugt Entwuerfe fuer ausgewaehlte Themen.

    Args:
        limit: Max. Anzahl Entwuerfe
        kanal: Ziel-Kanal (google, facebook, instagram)
        use_campaign: True = 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2 + QA)
                      False = Anthropic Claude (bisheriger Workflow)
        test_mode: True = low quality für Tests (nur bei use_campaign=True)

    Returns:
        Anzahl erzeugter Entwuerfe
    """
    from db import get_conn
    if not use_campaign and not get_secret("anthropic_api_key"):
        log.info("Texterzeugung uebersprungen: kein 'anthropic_api_key' hinterlegt (secrets.json).")
        return 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titel, url, volltext FROM themen t WHERE status='ausgewaehlt' "
            "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=t.id AND e.kanal=?) "
            "ORDER BY erkannt_am DESC LIMIT ?", (kanal, limit)).fetchall()
    return _create_drafts(rows, kanal, use_campaign=use_campaign, test_mode=test_mode)

def generate_for_ids(ids, kanal="google", use_campaign=False, test_mode=False, premium_images=False, both_images=False):
    """Erzeugt Entwuerfe NUR fuer die ausgewaehlten Thema-IDs.

    Args:
        ids: Liste von Thema-IDs
        kanal: Ziel-Kanal (google, facebook, instagram)
        use_campaign: True = 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2 + QA)
                      False = Anthropic Claude (bisheriger Workflow)
        test_mode: True = low quality für Tests (nur bei use_campaign=True)
        premium_images: DEPRECATED - wird ignoriert (immer ShareNext!)
        both_images: DEPRECATED - wird ignoriert (immer ShareNext!)

    Returns:
        Anzahl erzeugter Entwuerfe

    Note:
        Alle Bilder werden NUR NOCH mit ShareNext Premium generiert!
        Die Parameter premium_images und both_images werden aus Kompatibilitätsgründen
        noch akzeptiert, aber ignoriert.
    """
    from db import get_conn
    ids = [int(i) for i in ids if str(i).strip().isdigit()]
    if not ids:
        return 0
    if not use_campaign and not get_secret("anthropic_api_key"):
        log.info("Texterzeugung uebersprungen: kein 'anthropic_api_key' hinterlegt (secrets.json).")
        return 0
    ph = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titel, url, volltext FROM themen WHERE id IN (%s) AND status='ausgewaehlt' "
            "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=themen.id AND e.kanal=?)" % ph,
            ids + [kanal]).fetchall()
    # premium_images und both_images werden ignoriert - immer ShareNext!
    return _create_drafts(rows, kanal, use_campaign=use_campaign, test_mode=test_mode)


def regenerate(thema, previous, feedback, kanal="google"):
    """Erzeugt eine ueberarbeitete Version eines Beitrags gemaess Aenderungswunsch."""
    import json as _json
    key = get_secret("anthropic_api_key", required=True)
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    prompt = (
        "Bisheriger Beitrag (JSON):\n%s\n\n"
        "Thema: %s\nInhalt: %s\n\n"
        "Begleittext-Vorgaben je Kanal:\n%s\n\n%s\n\n"
        "Aenderungswunsch des Nutzers: %s\n\n"
        "Erzeuge eine UEBERARBEITETE Version, die den Aenderungswunsch umsetzt. Bild, Ueberschrift und "
        "Stichpunkte sind fuer beide Kanaele gleich; NUR der Begleittext unterscheidet sich je Kanal. "
        "Antworte AUSSCHLIESSLICH als JSON mit denselben Feldern (ueberschrift, subline, "
        "bullets [3 sehr kurze Stichpunkte], cta, captions {facebook, instagram})."
        % (_json.dumps(previous, ensure_ascii=False), thema.get("titel", ""),
           (thema.get("volltext") or "")[:1500],
           CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"], feedback)
    )
    msg = client.messages.create(model=_model(), max_tokens=1600, system=SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    return _normalize_captions(_parse_json(raw))
