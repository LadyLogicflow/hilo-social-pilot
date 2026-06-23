# -*- coding: utf-8 -*-
"""Test fuer die Pool-Sammelaktion (Issue #128): mehrere Entwuerfe mit einem Klick in den Pool.

Beweist:
  1. POST /pool-aufnehmen-alle poolt ALLE Entwuerfe mit status='entwurf'
     (status -> 'pool', je ein pool-Eintrag mit aktiv=1, je ein audit_log).
  2. Die Aktion ist idempotent: ein zweiter Lauf nimmt 0 neue auf (nichts mehr im Status 'entwurf').
  3. Bereits freigegebene/veroeffentlichte/verworfene/gepoolte Beitraege werden NICHT angefasst.
  4. Die Stufe-2-Seite (/entwuerfe) rendert den Bulk-Button "Alle in den Pool", solange Entwuerfe da sind.

Ausfuehrung (HILO_DATA_DIR muss VOR dem Import gesetzt sein):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_pool_bulk.py
"""
import os, sys

# Projektwurzel in den Pfad (Test liegt in tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _seed(conn):
    """Entwuerfe in verschiedenen Status anlegen. Nur die mit status='entwurf' duerfen gepoolt werden."""
    eids = {}
    # 3 offene Entwuerfe (sollen gepoolt werden)
    for i in range(1, 4):
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook',?, 'entwurf')",
                           ('{"ueberschrift": "Entwurf %d"}' % i,))
        eids["entwurf_%d" % i] = cur.lastrowid
    # je ein Entwurf in jedem anderen Status (duerfen NICHT angefasst werden)
    for st in ("freigegeben", "veroeffentlicht", "verworfen"):
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook',?, ?)",
                           ('{"ueberschrift": "%s"}' % st, st))
        eids[st] = cur.lastrowid
    # ein bereits gepoolter Beitrag (status='pool' + pool-Eintrag aktiv=1)
    cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook','{\"ueberschrift\":\"schon im Pool\"}', 'pool')")
    eids["pool"] = cur.lastrowid
    conn.execute("INSERT INTO pool(entwurf_id, aktiv) VALUES (?, 1)", (eids["pool"],))
    conn.commit()
    return eids


def _client():
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"
        sess["rolle"] = "freigeber"
    return c


def main():
    db.init_db()
    with db.get_conn() as conn:
        eids = _seed(conn)

    client = _client()

    # --- Lauf 1: alle offenen Entwuerfe poolen ---
    r = client.post("/pool-aufnehmen-alle", follow_redirects=False)
    if r.status_code not in (302, 303):
        _fail("Erwartete Redirect nach /pool, bekam HTTP %d" % r.status_code)
    if "/pool" not in r.headers.get("Location", ""):
        _fail("Redirect-Ziel ist nicht /pool: %r" % r.headers.get("Location"))

    with db.get_conn() as conn:
        # (1) Die 3 offenen Entwuerfe sind jetzt 'pool' mit aktivem pool-Eintrag.
        for key in ("entwurf_1", "entwurf_2", "entwurf_3"):
            eid = eids[key]
            st = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid,)).fetchone()[0]
            if st != "pool":
                _fail("%s (id %d) wurde nicht gepoolt, Status=%s" % (key, eid, st))
            p = conn.execute("SELECT aktiv FROM pool WHERE entwurf_id=?", (eid,)).fetchone()
            if not p or p[0] != 1:
                _fail("%s (id %d) hat keinen aktiven pool-Eintrag" % (key, eid))
            audit = conn.execute("SELECT COUNT(*) FROM audit WHERE entwurf_id=? AND aktion='pool_aufgenommen'",
                                 (eid,)).fetchone()[0]
            if audit < 1:
                _fail("%s (id %d): kein audit_log 'pool_aufgenommen'" % (key, eid))

        # (3) Andere Status unveraendert.
        for st_erwartet in ("freigegeben", "veroeffentlicht", "verworfen"):
            eid = eids[st_erwartet]
            st = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid,)).fetchone()[0]
            if st != st_erwartet:
                _fail("Status '%s' (id %d) wurde faelschlich auf '%s' geaendert" % (st_erwartet, eid, st))
            inpool = conn.execute("SELECT COUNT(*) FROM pool WHERE entwurf_id=?", (eid,)).fetchone()[0]
            if inpool:
                _fail("Status '%s' (id %d) wurde faelschlich in den Pool aufgenommen" % (st_erwartet, eid))

        # Der vorher schon gepoolte Beitrag bleibt 'pool' mit genau EINEM pool-Eintrag (idempotent durch INSERT OR IGNORE).
        eid_pool = eids["pool"]
        st = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid_pool,)).fetchone()[0]
        if st != "pool":
            _fail("Vorher gepoolter Beitrag (id %d) hat Status '%s' statt 'pool'" % (eid_pool, st))
        n_pool_eintrag = conn.execute("SELECT COUNT(*) FROM pool WHERE entwurf_id=?", (eid_pool,)).fetchone()[0]
        if n_pool_eintrag != 1:
            _fail("Vorher gepoolter Beitrag (id %d) hat %d pool-Eintraege statt 1" % (eid_pool, n_pool_eintrag))

        offen_nach_1 = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status='entwurf'").fetchone()[0]
        if offen_nach_1 != 0:
            _fail("Nach Lauf 1 sind noch %d Entwuerfe offen (erwartet 0)" % offen_nach_1)

        gepoolt_gesamt = conn.execute("SELECT COUNT(*) FROM pool WHERE aktiv=1").fetchone()[0]
        # 3 neue + 1 vorher schon vorhanden = 4
        if gepoolt_gesamt != 4:
            _fail("Erwartete 4 aktive pool-Eintraege, fand %d" % gepoolt_gesamt)

    # --- Lauf 2: idempotent, 0 neue ---
    audit_vor = None
    with db.get_conn() as conn:
        audit_vor = conn.execute("SELECT COUNT(*) FROM audit WHERE aktion='pool_aufgenommen'").fetchone()[0]
    client.post("/pool-aufnehmen-alle", follow_redirects=False)
    with db.get_conn() as conn:
        audit_nach = conn.execute("SELECT COUNT(*) FROM audit WHERE aktion='pool_aufgenommen'").fetchone()[0]
        if audit_nach != audit_vor:
            _fail("Zweiter Lauf nicht idempotent: %d neue audit_log-Eintraege" % (audit_nach - audit_vor))
        offen_nach_2 = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status='entwurf'").fetchone()[0]
        if offen_nach_2 != 0:
            _fail("Nach Lauf 2 sind %d Entwuerfe offen (erwartet 0)" % offen_nach_2)

    # --- (4) Button-Render: mit Entwuerfen erscheint der Bulk-Button ---
    with db.get_conn() as conn:
        conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook','{\"ueberschrift\":\"neu\"}', 'entwurf')")
        conn.commit()
    html = client.get("/entwuerfe").get_data(as_text=True)
    if "/pool-aufnehmen-alle" not in html:
        _fail("Bulk-Button (action /pool-aufnehmen-alle) fehlt auf der /entwuerfe-Seite")
    if "Alle in den Pool" not in html:
        _fail("Bulk-Button-Beschriftung 'Alle in den Pool' fehlt auf der /entwuerfe-Seite")

    print("OK: alle Pool-Sammelaktion-Pruefungen bestanden")
    print("  Lauf 1: 3 Entwuerfe -> 'pool' (+ pool-Eintrag + audit_log), andere Status unangetastet")
    print("  Lauf 2: idempotent (0 neue), vorher gepoolter Beitrag mit genau 1 pool-Eintrag")
    print("  /entwuerfe rendert den Button 'Alle in den Pool'")


if __name__ == "__main__":
    main()
