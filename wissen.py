# -*- coding: utf-8 -*-
"""Wissens-Serie (Evergreen): zeitlose Steuer-Themen, die leere Kalendertage fuellen.
Wenn der Vorrat an offenen Beitraegen unter eine Schwelle faellt, wird das am laengsten
nicht genutzte Wissens-Thema zu einem Beitrag gemacht (via Claude, faktentreu, HILO-Stil).
Diese Beitraege haben kein festes Datum und werden bei der Freigabe auf den naechsten
freien Werktag eingeplant."""
import datetime, hashlib, json, logging

log = logging.getLogger("hilo.wissen")

def auffuellen(heute=None, min_buffer=3):
    """Erzeugt bis zu 1 Evergreen-Beitrag, wenn weniger als min_buffer offene Beitraege
    (Entwurf oder freigegeben) vorhanden sind. Rueckgabe: Anzahl erzeugt (0 oder 1).
    Nutzt den 3-Stufen-Workflow (GPT-5.6 Terra + GPT Image 2 + Pillow-Text), daher
    'openai_api_key' statt 'anthropic_api_key' (Claude wird hier nicht mehr verwendet)."""
    from db import get_conn
    from secrets_store import get_secret
    import textgen
    heute = heute or datetime.date.today()
    with get_conn() as conn:
        offen = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status IN ('entwurf','freigegeben')").fetchone()[0]
    if offen >= min_buffer:
        return 0
    if not get_secret("openai_api_key"):
        log.info("Wissens-Serie uebersprungen: kein 'openai_api_key' hinterlegt.")
        return 0
    with get_conn() as conn:
        # am laengsten nicht genutztes aktives Thema (nie genutzte zuerst)
        topic = conn.execute("SELECT id, titel, hook FROM wissensthemen WHERE aktiv=1 "
                            "ORDER BY zuletzt IS NOT NULL, zuletzt, id LIMIT 1").fetchone()
    if not topic:
        return 0
    thema = {"titel": topic["titel"], "volltext": topic["hook"] or ""}
    try:
        fields = textgen.generate_with_campaign(thema, "facebook")
    except Exception as ex:
        log.warning("Wissens-Text/Bild fehlgeschlagen (%s): %s", topic["titel"], ex)
        return 0
    h = hashlib.sha256(("wissen|%s|%s" % (topic["titel"], heute.isoformat())).encode("utf-8")).hexdigest()
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                           "VALUES('wissen', ?, 'erledigt', ?, ?)", (topic["titel"], topic["hook"], h))
        conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, bild_pfad) "
                     "VALUES (?, 'facebook', ?, 'entwurf', ?)",
                     (cur.lastrowid, json.dumps(fields, ensure_ascii=False), fields.get("bild_pfad")))
        conn.execute("UPDATE wissensthemen SET zuletzt=? WHERE id=?", (heute.isoformat(), topic["id"]))
        conn.commit()
    log.info("Wissens-Beitrag erzeugt: %s", topic["titel"])
    return 1
