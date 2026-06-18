# -*- coding: utf-8 -*-
"""M3 - Texterstellung mit Claude. Erzeugt aus einem Thema einen HILO-Beitrag (strukturiert)."""
import json, logging, os
from secrets_store import get_secret

log = logging.getLogger("hilo.textgen")

SYSTEM = (
    "Du bist Social-Media-Redakteur fuer den Lohnsteuerhilfeverein HILO.\n\n"
    "ZIELGRUPPE: Steuerliche Laien - Arbeitnehmer, Rentner, Familien mit Kindern, private Vermieter.\n\n"
    "TONALITAET: Klar, direkt, menschlich - in der Sie-Form. Nicht belehrend, nicht trocken. "
    "Schreibe mit PEP und Aufmerksamkeit, als wuerdest du einem Freund einen wertvollen Tipp geben. "
    "Sei konkret, lebendig und neugierig machend statt allgemein und langweilig.\n\n"
    "SPRACHE: Alle Begriffe vollstaendig ausschreiben - KEINE Abkuerzungen (auch nicht im Bild oder in "
    "Bullets). Beispiel: 'Arbeitnehmer' statt 'AN', 'zum Beispiel' statt 'z.B.', 'Werbungskosten' statt 'WK'.\n\n"
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
    "6) BILD_MOTIV: warme, positive Szene - eine sympathische HILO-Beraterin oder ein Berater im "
    "freundlichen Gespraech mit Mandanten, die zum Thema passen. FREIGESTELLT, ohne Tisch oder Raum im "
    "Hintergrund. Mappe oder Unterlagen in der Hand, gerne eine Kaffeetasse dabei - laechelnd, zugewandt, "
    "aktiv (KEINE nachdenklichen Gesichter, keine Einzelportraits). Passe die Mandanten ans Thema an, z.B. "
    "'Beraterin und junge Familie im Gespraech mit Unterlagen', 'Berater und aelteres Ehepaar, Kaffeetasse "
    "in der Hand', 'Beraterin zeigt einem Rentnerpaar etwas in einer Mappe'.\n"
    "7) BILD_MOTIV_THEMA: ein zum Thema passendes, GEGENSTAENDLICHES Motiv OHNE Personen - einzelne, klar "
    "erkennbare Gegenstaende oder eine kleine Stillleben-Szene (z.B. fuer 'Gaertner absetzen' Gartengeraete "
    "wie Heckenschere, Rechen und ein paar Pflanzen; fuer 'Homeoffice' ein aufgeraeumter Schreibtisch mit "
    "Laptop und Notizblock; fuer 'Handwerkerleistungen' Werkzeug). Freigestellt, OHNE Raum/Hintergrund, "
    "KEINE Menschen, KEIN Text. Kurze Beschreibung.\n"
    "8) BILD_TYP: empfiehl den passenden Bildtyp - 'thema' wenn das Thema ein konkretes, bildstarkes Objekt "
    "oder eine Szene nahelegt (z.B. Gaertner, Handwerker, Homeoffice, Umzug, Pendeln), sonst 'person'.\n\n"
    "WICHTIG:\n"
    "- Erfinde NIEMALS Gerichtsurteile, Aktenzeichen, Zahlen, Fristen, Quellen, URLs, Adressen oder "
    "Telefonnummern - nutze AUSSCHLIESSLICH, was im Thema steht. Gibt das Thema keinen Fakt/kein Urteil "
    "her, dann nenne auch keins (lieber allgemeiner formulieren als etwas erfinden).\n"
    "- Der HOOK entscheidet, ob jemand weiterliest - hier maximale Sorgfalt.\n"
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
}

def _model():
    return os.environ.get("HILO_CLAUDE_MODEL", "claude-sonnet-4-6")

def _build_prompt(thema, kanal=None):
    """Ein Auftrag erzeugt den Beitrag fuer Facebook UND Instagram in einem Rutsch: Bild, Ueberschrift
    und Stichpunkte sind fuer beide Kanaele gleich; NUR der Begleittext (caption) unterscheidet sich je
    Kanal nach den plattformspezifischen Vorgaben. So bleibt es bei einem einzigen KI-Aufruf."""
    return (
        "Thema: %s\n"
        "Zusammenfassung/Inhalt: %s\n\n"
        "Erzeuge daraus einen HILO-Beitrag fuer FACEBOOK UND INSTAGRAM. Bild, Ueberschrift und "
        "Stichpunkte sind fuer beide Kanaele identisch; NUR der Begleittext (caption) unterscheidet sich "
        "je Kanal nach diesen Vorgaben:\n\n%s\n\n%s\n\n"
        "Antworte AUSSCHLIESSLICH als JSON-Objekt (keine Erklaerung, kein Markdown) mit genau diesen "
        "Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen", "subline": "max 90 Zeichen", '
        '"bullets": ["3 sehr kurze Stichpunkte, je max 5 Woerter"], "cta": "kurze Handlungsaufforderung", '
        '"slogan": "max 3 Woerter oder leer", "bild_motiv": "kurzes freigestelltes Personen-Fotomotiv", '
        '"bild_motiv_thema": "kurzes gegenstaendliches Motiv ohne Personen", '
        '"bild_typ": "person oder thema", '
        '"captions": {"facebook": "Begleittext fuer Facebook inkl. Hashtags am Ende, hoechstens %d '
        'Zeichen", "instagram": "Begleittext fuer Instagram inkl. Hashtags am Ende, hoechstens %d '
        'Zeichen"}}\n'
        "Sprache: Deutsch, Sie-Form."
        % (thema.get("titel", ""), (thema.get("volltext") or "")[:1500],
           CHANNEL_GUIDE["facebook"], CHANNEL_GUIDE["instagram"],
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
    data["captions"] = {"facebook": fb, "instagram": ig}
    data["caption"] = fb
    return data

def caption_fuer(fields, kanal):
    """Liefert den kanalspezifischen Begleittext (Fallback: gemeinsame 'caption')."""
    caps = fields.get("captions") if isinstance(fields.get("captions"), dict) else {}
    return (caps.get(kanal) or fields.get("caption") or "").strip()

def _normalize_bild(data):
    """Stellt bild_typ ('person'|'thema', Default 'person') und ein vorhandenes bild_motiv_thema sicher.
    Faellt auf 'person' zurueck, wenn kein gegenstaendliches Motiv geliefert wurde."""
    if not isinstance(data, dict):
        return data
    typ = (data.get("bild_typ") or "").strip().lower()
    thema_motiv = (data.get("bild_motiv_thema") or "").strip()
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

def _create_drafts(rows, kanal):
    """Erzeugt fuer die uebergebenen Themen-Zeilen je einen Entwurf (Claude). Rueckgabe: Anzahl."""
    from db import get_conn
    created = 0
    for r in rows:
        try:
            data = generate({"titel": r["titel"], "volltext": r["volltext"], "url": r["url"]}, kanal)
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO entwuerfe(thema_id, kanal, text, status) VALUES (?,?,?, 'entwurf')",
                    (r["id"], kanal, json.dumps(data, ensure_ascii=False)))
            created += 1
            log.info("Entwurf erzeugt: Thema %s - %s", r["id"], (r["titel"] or "")[:60])
        except Exception as ex:
            log.warning("Texterzeugung fehlgeschlagen (Thema %s): %s", r["id"], ex)
    return created

def generate_drafts(limit=3, kanal="google"):
    from db import get_conn
    if not get_secret("anthropic_api_key"):
        log.info("Texterzeugung uebersprungen: kein 'anthropic_api_key' hinterlegt (secrets.json).")
        return 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titel, url, volltext FROM themen t WHERE status='ausgewaehlt' "
            "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=t.id AND e.kanal=?) "
            "ORDER BY erkannt_am DESC LIMIT ?", (kanal, limit)).fetchall()
    return _create_drafts(rows, kanal)

def generate_for_ids(ids, kanal="google"):
    """Erzeugt Entwuerfe NUR fuer die ausgewaehlten Thema-IDs (status 'ausgewaehlt', noch ohne
    Entwurf in diesem Kanal). Rueckgabe: Anzahl erzeugter Entwuerfe."""
    from db import get_conn
    ids = [int(i) for i in ids if str(i).strip().isdigit()]
    if not ids:
        return 0
    if not get_secret("anthropic_api_key"):
        log.info("Texterzeugung uebersprungen: kein 'anthropic_api_key' hinterlegt (secrets.json).")
        return 0
    ph = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titel, url, volltext FROM themen WHERE id IN (%s) AND status='ausgewaehlt' "
            "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=themen.id AND e.kanal=?)" % ph,
            ids + [kanal]).fetchall()
    return _create_drafts(rows, kanal)


def regenerate_open_drafts(kanal="google"):
    """Erzeugt fuer ALLE noch nicht freigegebenen Entwuerfe (status 'entwurf') den Text NEU
    gemaess den aktuellen Vorgaben (bewusst voller KI-Lauf). Setzt danach das Bild aller offenen
    Entwuerfe zurueck, damit sie mit dem aktuellen Layout/Motiv neu gerendert werden.
    Nur Entwuerfe mit hinterlegtem Thema bekommen neuen Text; die uebrigen behalten ihren Text,
    werden aber ebenfalls neu gerendert. Rueckgabe: Anzahl neu erzeugter Texte."""
    from db import get_conn
    if not get_secret("anthropic_api_key"):
        log.info("Neu-Erzeugung uebersprungen: kein 'anthropic_api_key' hinterlegt (secrets.json).")
        return 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.id AS eid, e.kanal AS kanal, t.titel AS titel, t.url AS url, t.volltext AS volltext "
            "FROM entwuerfe e JOIN themen t ON t.id = e.thema_id WHERE e.status='entwurf'").fetchall()
    neu = 0
    for r in rows:
        try:
            data = generate({"titel": r["titel"], "volltext": r["volltext"], "url": r["url"]},
                            r["kanal"] or kanal)
            with get_conn() as conn:
                conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=NULL WHERE id=?",
                             (json.dumps(data, ensure_ascii=False), r["eid"]))
            neu += 1
            log.info("Entwurf neu erzeugt: %s - %s", r["eid"], (r["titel"] or "")[:60])
        except Exception as ex:
            log.warning("Neu-Erzeugung fehlgeschlagen (Entwurf %s): %s", r["eid"], ex)
    # auch Entwuerfe ohne Text-Neuerzeugung (z.B. Countdowns) neu rendern -> neues Bild-Layout
    with get_conn() as conn:
        conn.execute("UPDATE entwuerfe SET bild_pfad=NULL WHERE status='entwurf'")
    return neu


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
