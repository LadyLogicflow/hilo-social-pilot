# -*- coding: utf-8 -*-
"""Themen-Radar: RSS-Feeds + HTML-Scraper-Quellen, Relevanzfilter, Speicherung."""
import hashlib, logging
from db import get_conn
from sources import configured_sources
from relevance import classify

log = logging.getLogger("hilo.radar")

def _hash(quelle, url, titel):
    return hashlib.sha256(("%s|%s|%s" % (quelle, url or "", titel)).encode("utf-8")).hexdigest()

def fetch(url):
    import feedparser  # lazy
    parsed = feedparser.parse(url)
    items = []
    for e in parsed.entries:
        items.append({
            "titel": (e.get("title") or "").strip(),
            "url": e.get("link") or "",
            "datum": e.get("published") or e.get("updated") or "",
            "zusammenfassung": (e.get("summary") or e.get("description") or "").strip(),
        })
    return items

# Diese Quellen ueberspringen Stufe 1 (Themenauswahl) und gehen direkt in die
# Texterstellung (Stufe 2): BVL-Pressemeldungen (muessen social-media-tauglich
# umgeschrieben werden) und die HILO-eigenen Steuertipps (bereits kuratiert).
DIREKT_QUELLEN = {"bvl_pm", "bvl_dpa", "hilo"}

def _store(conn, quelle, items):
    neu = relevant = 0
    for e in items:
        if not e.get("titel"):
            continue
        h = _hash(quelle, e.get("url"), e["titel"])
        # Stufe 1: relevante Themen werden 'vorgeschlagen' (warten auf erste Freigabe).
        # Ausnahme BVL: direkt 'ausgewaehlt' -> ueberspringt Stufe 1, geht in die Texterstellung.
        roh = classify(e["titel"] + " " + e.get("zusammenfassung", ""))
        if roh == "ausgewaehlt":
            status = "ausgewaehlt" if quelle in DIREKT_QUELLEN else "vorgeschlagen"
        else:
            status = roh
        try:
            conn.execute(
                "INSERT INTO themen(quelle, titel, url, veroeffentlicht_am, status, volltext, hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (quelle, e["titel"], e.get("url"), e.get("datum", ""), status, e.get("zusammenfassung", ""), h))
            neu += 1
            if status in ("vorgeschlagen", "ausgewaehlt"):
                relevant += 1
        except Exception:
            pass  # Dublette
    return neu, relevant

_STOP = {"steuer", "steuern", "fuer", "und", "der", "die", "das", "den", "mit", "von",
         "bei", "ist", "werden", "koennen", "wird", "auch", "eine", "einen", "einer"}
# lange, aber GENERISCHE Begriffe: ein einzelnes davon reicht NICHT als Themen-Match
_GENERIC = {"steuererklaerung", "steuererklärung", "einkommensteuer", "lohnsteuer",
            "finanzamt", "steuerzahler", "steuerpflichtige", "steuerpflichtiger",
            "steuerbescheid", "steuertipp", "steuertipps", "beratungsstelle",
            "steuerberater", "arbeitnehmer", "steuerlich", "steuerliche"}

def _signifikante(text):
    """Lange, aussagekraeftige Woerter (>=6 Zeichen) eines Titels - fuer Aehnlichkeitsabgleich."""
    import re
    woerter = re.findall(r"[a-zaeoeuessäöüß]+", (text or "").lower())
    return {w for w in woerter if len(w) >= 6 and w not in _STOP}

def _aehnlich(a, b):
    """True, wenn zwei Titel dasselbe Thema behandeln (Wortueberschneidung)."""
    sa, sb = _signifikante(a), _signifikante(b)
    if not sa or not sb:
        return False
    gemeinsam = sa & sb
    if not gemeinsam:
        return False
    # ein einzelnes geteiltes, distinktives Kompositum (lang, nicht generisch) reicht
    distinktiv = {w for w in gemeinsam if len(w) >= 8 and w not in _GENERIC}
    if distinktiv:
        return True
    if len(gemeinsam) >= 2:
        return True
    return len(gemeinsam) / len(sa | sb) >= 0.4

def _dedupe_hilo_bvl(conn):
    """Abgleich HILO <-> BVL ueber den GESAMTEN Bestand (auch zurueckliegende Themen):
      - Beide noch offen, gleiches Thema -> HILO gewinnt, BVL -> 'dublette'.
      - Das Gegenstueck wurde schon verarbeitet/veroeffentlicht (BVL war schneller
        oder HILO war zuerst) -> das spaetere, offene Thema -> 'erledigt', kein Text.
    Markiert werden nur noch OFFENE Themen (status='ausgewaehlt')."""
    def _txt(r):
        return (r["titel"] or "") + " " + (r["volltext"] or "")

    def _verarbeitet(tid):
        # Thema gilt als verarbeitet, wenn ein nicht-verworfener Entwurf existiert
        return conn.execute("SELECT 1 FROM entwuerfe WHERE thema_id=? AND status!='verworfen' LIMIT 1",
                            (tid,)).fetchone() is not None

    hilo = conn.execute("SELECT id, titel, volltext, status FROM themen WHERE quelle='hilo'").fetchall()
    bvl = conn.execute("SELECT id, titel, volltext, status FROM themen "
                       "WHERE quelle IN ('bvl_pm','bvl_dpa')").fetchall()
    dubletten = erledigt = 0

    def _offen(x):  # noch nicht verarbeitet und zur Generierung vorgemerkt
        return x["status"] == "ausgewaehlt" and not _verarbeitet(x["id"])

    # Offene BVL-Themen gegen ALLE HILO-Themen pruefen
    for b in (x for x in bvl if _offen(x)):
        for h in hilo:
            if not _aehnlich(_txt(b), _txt(h)):
                continue
            if _verarbeitet(h["id"]) or h["status"] == "veroeffentlicht":
                conn.execute("UPDATE themen SET status='erledigt' WHERE id=?", (b["id"],)); erledigt += 1
            else:  # beide offen -> HILO gewinnt
                conn.execute("UPDATE themen SET status='dublette' WHERE id=?", (b["id"],)); dubletten += 1
            break

    # Offene HILO-Themen gegen ALLE BVL-Themen pruefen (BVL war evtl. schneller)
    for h in (x for x in hilo if _offen(x)):
        for b in bvl:
            if not _aehnlich(_txt(h), _txt(b)):
                continue
            if _verarbeitet(b["id"]) or b["status"] == "veroeffentlicht":
                conn.execute("UPDATE themen SET status='erledigt' WHERE id=?", (h["id"],)); erledigt += 1
                break  # nur erledigen, wenn BVL bereits raus war; sonst gewinnt HILO (offen lassen)

    if dubletten or erledigt:
        log.info("HILO/BVL-Abgleich: %d BVL-Dubletten (HILO gewinnt), %d als 'erledigt' markiert.",
                 dubletten, erledigt)
    return dubletten + erledigt

def run():
    rss = configured_sources()
    try:
        from config import SCRAPE_SOURCES
    except Exception:
        SCRAPE_SOURCES = {}
    if not rss and not SCRAPE_SOURCES:
        log.info("Themen-Radar: keine Quellen konfiguriert - uebersprungen.")
        return 0
    neu = relevant = 0
    with get_conn() as conn:
        for quelle, url in rss.items():
            try:
                n, r = _store(conn, quelle, fetch(url)); neu += n; relevant += r
            except Exception as ex:
                log.warning("Quelle '%s' (RSS) fehlgeschlagen: %s", quelle, ex)
        if SCRAPE_SOURCES:
            import scraper
            for quelle, url in SCRAPE_SOURCES.items():
                if not url:
                    continue
                try:
                    n, r = _store(conn, quelle, scraper.scrape(url)); neu += n; relevant += r
                except Exception as ex:
                    log.warning("Quelle '%s' (Scraper) fehlgeschlagen: %s", quelle, ex)
        try:
            _dedupe_hilo_bvl(conn)
        except Exception as ex:
            log.warning("HILO/BVL-Abgleich fehlgeschlagen: %s", ex)
    log.info("Themen-Radar: %d neue Themen (%d als relevant vorausgewaehlt).", neu, relevant)
    return neu
