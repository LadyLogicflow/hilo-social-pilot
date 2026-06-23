# -*- coding: utf-8 -*-
"""Test fuer Pool Phase 3 (Issue #127): Kanal-Verfuegbarkeit je Stelle, WhatsApp-Anbindung,
Frequenz- und Wochenend-Regeln.

Beweist:
  1. Kanal-Verfuegbarkeit: Stelle ohne IG-Konto bekommt keine Instagram-Ziehung; Stelle ohne
     WhatsApp-Konfiguration bekommt keine WhatsApp-Ziehung (kein pool_nutzung-Verbrauch dort).
  2. Frequenz: whatsapp_status wird taeglich gezogen, whatsapp_kanal nur an konfigurierten
     Wochentagen (an einem nicht-konfigurierten Tag: keine Kanal-Ziehung).
  3. Wochenend-Regel: am Wochenende werden nur 'leichte' Beitraege (Wissens-Serie) gezogen.
  4. WhatsApp-Posten laeuft ueber _wa_call (gemockt - kein echter Netzwerkruf) und schreibt einen
     posts-Eintrag; ein nicht erreichbarer Dienst fuehrt zu status='fehler', nicht zum Crash.
  5. Der bestehende FB/IG-Pool-Fluss und der Einmal-Posten-Fluss bleiben unberuehrt.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_pool_phase3.py
"""
import os, sys, random, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _seed(conn):
    """Drei aktive Stellen mit unterschiedlicher Kanal-Ausstattung:
      - Stelle 1: fb_seite mit IG-Konto, WhatsApp-Status + WhatsApp-Kanal.
      - Stelle 2: fb_seite OHNE IG-Konto, KEINE WhatsApp-Konfiguration.
      - Stelle 3: fb_seite mit IG-Konto, nur WhatsApp-Status (kein Kanal).
    Pool: Wissens-Beitraege (Wochenende erlaubt) + ein Fristen-Beitrag (Wochenende verboten)."""
    conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv, wa_status_aktiv, wa_kanal_invite) "
                 "VALUES ('Stelle 1','Ort 1','fb_1',1,1,'https://whatsapp.com/channel/AAA')")
    conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv, wa_status_aktiv, wa_kanal_invite) "
                 "VALUES ('Stelle 2','Ort 2','fb_2',1,0,NULL)")
    conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv, wa_status_aktiv, wa_kanal_invite) "
                 "VALUES ('Stelle 3','Ort 3','fb_3',1,1,NULL)")
    # Themen mit Quelle (fuer Stream-/Wochenend-Zuordnung).
    t_wissen, t_frist = [], None
    for i in range(1, 7):
        cur = conn.execute("INSERT INTO themen(quelle, titel, status) VALUES ('wissen',?, 'ausgewaehlt')",
                           ("Wissen %d" % i,))
        t_wissen.append(cur.lastrowid)
    cur = conn.execute("INSERT INTO themen(quelle, titel, status) VALUES ('frist','Frist 1','ausgewaehlt')")
    t_frist = cur.lastrowid
    wissen_eids, frist_eid = [], None
    for ti in t_wissen:
        cur = conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status) VALUES (?,?,?, 'pool')",
                           (ti, 'facebook', '{"ueberschrift":"Wissen","caption":"Wissens-Text"}'))
        eid = cur.lastrowid
        wissen_eids.append(eid)
        conn.execute("INSERT INTO pool(entwurf_id, aktiv) VALUES (?,1)", (eid,))
    cur = conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status) VALUES (?,?,?, 'pool')",
                       (t_frist, 'facebook', '{"ueberschrift":"Frist","caption":"Frist-Text"}'))
    frist_eid = cur.lastrowid
    conn.execute("INSERT INTO pool(entwurf_id, aktiv) VALUES (?,1)", (frist_eid,))
    conn.commit()
    return wissen_eids, frist_eid


def _patch_pages():
    # Nur Stelle 1 (fb_1) und Stelle 3 (fb_3) haben ein verknuepftes IG-Konto; Stelle 2 (fb_2) nicht.
    web._pages = lambda force=False: (
        [{"id": "fb_1", "name": "S1", "ig_id": "ig_1", "ig_username": "s1"},
         {"id": "fb_2", "name": "S2", "ig_id": None, "ig_username": None},
         {"id": "fb_3", "name": "S3", "ig_id": "ig_3", "ig_username": "s3"}], None)


def test_kanal_verfuegbarkeit():
    """Werktag (Montag): FB fuer alle, IG nur fuer Stelle 1+3, WA-Status fuer 1+3, WA-Kanal nur fuer 1.
    Montag ist kein WA-Kanal-Tag im Default {Di,Fr} -> ueber Env erzwingen wir Montag als Kanal-Tag."""
    os.environ["HILO_WA_KANAL_TAGE"] = "0"   # Montag als WhatsApp-Kanal-Tag
    montag = "2026-06-22"  # ein Montag
    with db.get_conn() as conn:
        n = web._pool_tagesziehung(conn, datum=montag, rng=random.Random(7))
    with db.get_conn() as conn:
        rows = conn.execute("SELECT stelle_id, kanal FROM geplante_posts WHERE pool=1 AND geplant_am LIKE ?",
                            (montag + "T%",)).fetchall()
    paare = {(r["stelle_id"], r["kanal"]) for r in rows}
    erwartet = {
        (1, "facebook"), (2, "facebook"), (3, "facebook"),
        (1, "instagram"), (3, "instagram"),
        (1, "whatsapp_status"), (3, "whatsapp_status"),
        (1, "whatsapp_kanal"),
    }
    if paare != erwartet:
        _fail("Kanal-Verfuegbarkeit falsch.\n  bekam:    %r\n  erwartet: %r" % (sorted(paare), sorted(erwartet)))
    # Stelle 2 darf KEINE IG-/WA-Ziehung haben -> auch kein pool_nutzung-Verbrauch dort.
    with db.get_conn() as conn:
        s2 = {(r[0], r[1]) for r in conn.execute(
            "SELECT stelle_id, kanal FROM pool_nutzung WHERE stelle_id=2")}
    if any(k in ("instagram", "whatsapp_status", "whatsapp_kanal") for _, k in s2):
        _fail("Stelle 2 (ohne IG/WA) hat unerlaubten pool_nutzung-Verbrauch: %r" % sorted(s2))
    print("  [1] Kanal-Verfuegbarkeit je Stelle: OK (8 Einplanungen, Stelle 2 nur Facebook)")


def test_frequenz():
    """whatsapp_status taeglich, whatsapp_kanal nur an konfigurierten Wochentagen."""
    # _kanal_heute_faellig direkt pruefen (unabhaengig vom DB-Zustand).
    os.environ["HILO_WA_KANAL_TAGE"] = "1,4"   # Di, Fr
    if not web._kanal_heute_faellig("whatsapp_status", 0):
        _fail("whatsapp_status muss taeglich faellig sein (Montag)")
    if not web._kanal_heute_faellig("whatsapp_status", 6):
        _fail("whatsapp_status muss taeglich faellig sein (Sonntag)")
    if web._kanal_heute_faellig("whatsapp_kanal", 0):  # Montag
        _fail("whatsapp_kanal darf am Montag NICHT faellig sein (nur Di/Fr)")
    if not web._kanal_heute_faellig("whatsapp_kanal", 1):  # Dienstag
        _fail("whatsapp_kanal muss am Dienstag faellig sein")
    if not web._kanal_heute_faellig("whatsapp_kanal", 4):  # Freitag
        _fail("whatsapp_kanal muss am Freitag faellig sein")
    if not web._kanal_heute_faellig("facebook", 3):
        _fail("facebook muss taeglich faellig sein")
    print("  [2] Frequenz je Kanal: OK (Status taeglich, Kanal nur Di/Fr)")


def test_wochenende(wissen_eids, frist_eid):
    """Am Wochenende werden nur 'leichte' Beitraege (Wissens-Serie) gezogen - der Fristen-Beitrag nicht."""
    os.environ["HILO_POOL_WOCHENEND_FILTER"] = "1"
    samstag = "2026-06-20"  # ein Samstag
    with db.get_conn() as conn:
        web._pool_tagesziehung(conn, datum=samstag, rng=random.Random(3))
    with db.get_conn() as conn:
        gezogen = {r[0] for r in conn.execute(
            "SELECT DISTINCT entwurf_id FROM geplante_posts WHERE pool=1 AND geplant_am LIKE ?",
            (samstag + "T%",))}
    if frist_eid in gezogen:
        _fail("Wochenend-Regel verletzt: Fristen-Beitrag (%d) wurde am Samstag gezogen" % frist_eid)
    if not gezogen:
        _fail("Wochenend-Regel: am Samstag wurde gar nichts gezogen (erwartet Wissens-Beitraege)")
    if not gezogen.issubset(set(wissen_eids)):
        _fail("Wochenend-Regel: nicht nur Wissens-Beitraege gezogen: %r" % sorted(gezogen))
    print("  [3] Wochenend-Regel: OK (nur Wissens-Serie, kein Fristen-Beitrag)")


def test_whatsapp_posten():
    """WhatsApp-Veroeffentlichung ueber gemocktes _wa_call: Erfolg -> posts-Eintrag, Fehler -> status='fehler'."""
    # Eine geplante WhatsApp-Status-Einplanung (Stelle 1) aus test_kanal_verfuegbarkeit holen.
    with db.get_conn() as conn:
        gp = conn.execute("SELECT id, entwurf_id FROM geplante_posts WHERE pool=1 AND kanal='whatsapp_status' "
                          "AND stelle_id=1 LIMIT 1").fetchone()
    if not gp:
        _fail("Keine whatsapp_status-Einplanung fuer den Posten-Test vorhanden")
    gpid, eid = gp["id"], gp["entwurf_id"]
    jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    with db.get_conn() as conn:
        conn.execute("UPDATE geplante_posts SET geplant_am=?, status='geplant' WHERE id=?", (jetzt, gpid))
        conn.commit()

    calls = []
    def _mock_ok(path, method="GET", payload=None, timeout=6):
        calls.append((path, payload))
        return {"ok": True, "recipients": 5}, None
    # Bildrendering ueberspringen (kein Pillow/Portrait im Test) -> reiner Textpfad.
    orig_wa, orig_render, orig_status = web._wa_call, web._render_stelle_bild, web._status_hochkant
    web._wa_call = _mock_ok
    web._render_stelle_bild = lambda eid, sid: None
    web._status_hochkant = lambda a, b: None
    try:
        web._publiziere_geplant(gpid)
    finally:
        web._wa_call, web._render_stelle_bild, web._status_hochkant = orig_wa, orig_render, orig_status

    if not any(p == "/post-status" for p, _ in calls):
        _fail("WhatsApp-Status-Posten rief NICHT /post-status (calls=%r)" % calls)
    with db.get_conn() as conn:
        gp_status = conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gpid,)).fetchone()[0]
        post = conn.execute("SELECT status FROM posts WHERE entwurf_id=? AND kanal='whatsapp_status' "
                            "ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
        ent_status = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid,)).fetchone()[0]
    if gp_status != "veroeffentlicht":
        _fail("WhatsApp-Status: geplante_posts nicht auf 'veroeffentlicht' (%s)" % gp_status)
    if not post or post[0] != "veroeffentlicht":
        _fail("WhatsApp-Status: kein veroeffentlichter posts-Eintrag")
    if ent_status != "pool":
        _fail("WhatsApp-Pool-Beitrag wurde faelschlich geflippt: '%s' statt 'pool'" % ent_status)
    print("  [4a] WhatsApp-Posten (Erfolg): OK (/post-status, posts-Eintrag, kein Status-Flip)")

    # --- Fehlerfall: Dienst nicht erreichbar -> status='fehler', kein Crash ---
    with db.get_conn() as conn:
        gp2 = conn.execute("SELECT id, entwurf_id FROM geplante_posts WHERE pool=1 AND kanal='whatsapp_kanal' "
                           "AND stelle_id=1 LIMIT 1").fetchone()
    gpid2, eid2 = gp2["id"], gp2["entwurf_id"]
    with db.get_conn() as conn:
        conn.execute("UPDATE geplante_posts SET geplant_am=?, status='geplant' WHERE id=?", (jetzt, gpid2))
        conn.commit()
    def _mock_err(path, method="GET", payload=None, timeout=6):
        return None, "Dienst nicht erreichbar (Connection refused)"
    orig_wa = web._wa_call
    web._wa_call, web._render_stelle_bild = _mock_err, (lambda eid, sid: None)
    try:
        web._publiziere_geplant(gpid2)
    finally:
        web._wa_call, web._render_stelle_bild = orig_wa, orig_render
    with db.get_conn() as conn:
        gp2_status = conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gpid2,)).fetchone()[0]
        ent2_status = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid2,)).fetchone()[0]
    if gp2_status != "fehler":
        _fail("WhatsApp-Fehlerfall: geplante_posts nicht auf 'fehler' (%s)" % gp2_status)
    if ent2_status != "pool":
        _fail("WhatsApp-Fehlerfall: Pool-Beitrag darf 'pool' bleiben, ist '%s'" % ent2_status)
    print("  [4b] WhatsApp-Posten (Dienst nicht erreichbar): OK (status='fehler', kein Crash, kein Flip)")


def test_fbig_fluss_unveraendert():
    """Der bestehende FB/IG-Einmal-Posten-Fluss bleibt: ein NICHT-Pool freigegebener Entwurf wird
    von _publiziere_geplant ueber den (gemockten) _veroeffentliche_ziel-Pfad auf 'veroeffentlicht'
    geflippt. WhatsApp-Pfad wird dafuer NICHT angefasst."""
    jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook','{}', 'freigegeben')")
        feid = cur.lastrowid
        cur = conn.execute("INSERT INTO geplante_posts(entwurf_id, stelle_id, kanal, geplant_am, status, pool) "
                           "VALUES (?,1,'facebook',?, 'geplant', 0)", (feid, jetzt))
        gpid = cur.lastrowid
        conn.commit()
    orig = web._veroeffentliche_ziel
    web._veroeffentliche_ziel = lambda conn, e, eid, *a, **k: ("Mock", True, [("facebook", True, "ok")])
    try:
        web._publiziere_geplant(gpid)
    finally:
        web._veroeffentliche_ziel = orig
    with db.get_conn() as conn:
        s = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (feid,)).fetchone()[0]
        gps = conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gpid,)).fetchone()[0]
    if s != "veroeffentlicht" or gps != "veroeffentlicht":
        _fail("FB/IG-Einmal-Fluss verletzt (entwurf=%s, gp=%s)" % (s, gps))
    print("  [5] Bestehender FB/IG-Einmal-Posten-Fluss: OK (Flip auf 'veroeffentlicht')")


def main():
    db.init_db()
    _patch_pages()
    with db.get_conn() as conn:
        wissen_eids, frist_eid = _seed(conn)

    test_kanal_verfuegbarkeit()
    test_frequenz()
    test_whatsapp_posten()
    test_wochenende(wissen_eids, frist_eid)
    test_fbig_fluss_unveraendert()

    print("OK: alle Pool-Phase-3-Pruefungen bestanden (#127)")


if __name__ == "__main__":
    main()
