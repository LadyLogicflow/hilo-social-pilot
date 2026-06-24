# -*- coding: utf-8 -*-
"""Anlass-Tage: erzeugt zu besonderen Tagen (mit Steuer-Aufhaenger) automatisch einen
Beitrag - z.B. Tag des Bieres -> Biersteuer. Faellt der Tag auf ein Wochenende,
erscheint der Beitrag am Freitag davor. Texte via Claude (faktentreu, HILO-Stil)."""
import datetime, hashlib, json, logging

log = logging.getLogger("hilo.anlass")

def _post_tag(mmdd, jahr):
    """Tatsaechlicher Veroeffentlichungstag im Jahr: Anlass-Datum, bei Wochenende auf Freitag davor."""
    try:
        m, d = (int(x) for x in mmdd.split("-"))
        tag = datetime.date(jahr, m, d)
    except Exception:
        return None
    if tag.weekday() == 5:        # Samstag -> Freitag
        tag -= datetime.timedelta(days=1)
    elif tag.weekday() == 6:      # Sonntag -> Freitag
        tag -= datetime.timedelta(days=2)
    return tag

def faellige(heute):
    from db import get_conn
    with get_conn() as conn:
        tage = conn.execute("SELECT datum, anlass, steuer_hook FROM anlasstage WHERE aktiv=1").fetchall()
    return [a for a in tage if _post_tag(a["datum"], heute.year) == heute]

def erzeuge_anlass_posts(heute=None):
    """Legt fuer heute faellige Anlass-Beitraege als Entwurf an (auf den Tag geplant).
    Idempotent (Dublettenschutz via hash). Benoetigt anthropic_api_key (sonst uebersprungen)."""
    from db import get_conn
    from secrets_store import get_secret
    import textgen
    heute = heute or datetime.date.today()
    posten = faellige(heute)
    if not posten:
        return 0
    if not get_secret("anthropic_api_key"):
        log.info("Anlass-Tage uebersprungen: kein 'anthropic_api_key' hinterlegt.")
        return 0
    created = 0
    for a in posten:
        marke = "anlass|%s|%d" % (a["anlass"], heute.year)
        h = hashlib.sha256(marke.encode("utf-8")).hexdigest()
        with get_conn() as conn:
            if conn.execute("SELECT 1 FROM themen WHERE hash=?", (h,)).fetchone():
                continue
        thema = {"titel": a["anlass"],
                 "volltext": "Anlass: %s. Steuerlicher Aufhaenger: %s" % (a["anlass"], a["steuer_hook"] or "")}
        try:
            fields = textgen.generate(thema, "facebook")
        except Exception as ex:
            log.warning("Anlass-Text fehlgeschlagen (%s): %s", a["anlass"], ex)
            continue
        with get_conn() as conn:
            cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                               "VALUES('anlass', ?, 'erledigt', ?, ?)", (a["anlass"], a["steuer_hook"], h))
            # #140: Schauplatz EINMAL waehlen. Anlass-Datum (MM-DD) mitgeben -> ziel_jahreszeit kann
            # einen saisonalen Anlass (z.B. 12-24 Heiligabend) auf die Winter-Schauplaetze lenken.
            import schauplatz
            fields["anlass_datum"] = a["datum"]
            schauplatz.zuweisen_falls_fehlt(conn, fields, datum=heute)
            # #142: Traeger (Device der Botschaft) EINMAL waehlen, stabil in fields['traeger'].
            # Robust: fehlt die Tabelle (alte DB) -> No-Op.
            try:
                import traeger
                traeger.zuweisen_traeger_falls_fehlt(conn, fields, datum=heute)
            except Exception as ex:
                log.warning("Traeger-Zuweisung uebersprungen: %s", ex)
            conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer) "
                         "VALUES (?, 'facebook', ?, 'entwurf', ?)",
                         (cur.lastrowid, json.dumps(fields, ensure_ascii=False), heute.isoformat()))
            conn.commit()
        created += 1
        log.info("Anlass-Beitrag erzeugt: %s (geplant fuer %s).", a["anlass"], heute.isoformat())
    return created
