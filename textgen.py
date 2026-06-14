# -*- coding: utf-8 -*-
"""M3 - Texterstellung mit Claude. Erzeugt aus einem Thema einen HILO-Beitrag (strukturiert)."""
import json, logging, os
from secrets_store import get_secret

log = logging.getLogger("hilo.textgen")

SYSTEM = (
    "Du bist Social-Media-Redakteur fuer den Lohnsteuerhilfeverein HILO. "
    "Zielgruppe: Arbeitnehmer, Rentner, Familien mit Kindern und private Vermieter. "
    "Schreibe klar, freundlich, serioes und nutzenorientiert in der Sie-Form (gesietzt). "
    "Erfinde KEINE Zahlen, Fristen, URLs, Adressen oder Telefonnummern - nutze nur, was im Thema steht. "
    "Die Bullets muessen SEHR KURZ sein (hoechstens 5 Woerter, stichpunktartig) - sie erscheinen auf "
    "einem Bild; der ausfuehrliche Text gehoert in das Feld caption. Im CTA KEINE erfundene Webadresse, "
    "sondern eine allgemeine Aufforderung wie 'Jetzt Beratungsstelle in Ihrer Naehe finden'. "
    "Verweise dezent auf die HILO-Mitgliedschaft bzw. persoenliche Beratung. "
    "Gib zusaetzlich: 'slogan' = sehr kurzer, einpraegsamer HILO-Slogan (max 3 Woerter, passend zum Thema; oder leer fuer Standard). "
    "'bild_motiv' = kurze Beschreibung eines freigestellten, situativen Fotomotivs passend zum Thema "
    "(z.B. 'freundliches aelteres Ehepaar', 'junge Familie mit Kindern', 'Person mit Unterlagen am Laptop')."
)

CHANNEL_LIMIT = {"google": 1400, "linkedin": 1300, "instagram": 1500, "facebook": 1400}

def _model():
    return os.environ.get("HILO_CLAUDE_MODEL", "claude-sonnet-4-6")

def _build_prompt(thema, kanal):
    limit = CHANNEL_LIMIT.get(kanal, 1400)
    return (
        "Thema: %s\n"
        "Zusammenfassung/Inhalt: %s\n"
        "Kanal: %s\n\n"
        "Erzeuge daraus einen HILO-Beitrag. Antworte AUSSCHLIESSLICH als JSON-Objekt "
        "(keine Erklaerung, kein Markdown) mit genau diesen Feldern:\n"
        '{"ueberschrift": "max 60 Zeichen", "subline": "max 90 Zeichen", '
        '"bullets": ["3 sehr kurze Stichpunkte, je max 5 Woerter"], "cta": "kurze Handlungsaufforderung", '
        '"slogan": "max 3 Woerter oder leer", "bild_motiv": "kurzes freigestelltes Fotomotiv", '
        '"caption": "Fliesstext fuer den Kanal, hoechstens %d Zeichen"}\n'
        "Sprache: Deutsch, Sie-Form."
        % (thema.get("titel", ""), (thema.get("volltext") or "")[:1500], kanal, limit)
    )

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

def generate(thema, kanal="google"):
    key = get_secret("anthropic_api_key", required=True)
    import anthropic  # lazy
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=_model(), max_tokens=900, system=SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(thema, kanal)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    return _parse_json(raw)

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


def regenerate(thema, previous, feedback, kanal="google"):
    """Erzeugt eine ueberarbeitete Version eines Beitrags gemaess Aenderungswunsch."""
    import json as _json
    key = get_secret("anthropic_api_key", required=True)
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    prompt = (
        "Bisheriger Beitrag (JSON):\n%s\n\n"
        "Thema: %s\nInhalt: %s\nKanal: %s\n\n"
        "Aenderungswunsch des Nutzers: %s\n\n"
        "Erzeuge eine UEBERARBEITETE Version, die den Aenderungswunsch umsetzt. "
        "Antworte AUSSCHLIESSLICH als JSON mit denselben Feldern (ueberschrift, subline, "
        "bullets [3 sehr kurze Stichpunkte], cta, caption)."
        % (_json.dumps(previous, ensure_ascii=False), thema.get("titel", ""),
           (thema.get("volltext") or "")[:1500], kanal, feedback)
    )
    msg = client.messages.create(model=_model(), max_tokens=900, system=SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    return _parse_json(raw)
