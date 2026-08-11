# -*- coding: utf-8 -*-
"""Smoke-Test fuer Pool Phase 2 (Issue #126): taegliche Auto-Ziehung aus dem Zufalls-Pool.

Beweist:
  1. keine Doppelung je (Stelle, Kanal) - zweiter Lauf am selben Tag plant nichts nach,
  2. verschiedene Beitraege je Stelle am selben Tag,
  3. geplante_posts mit pool=1 entsteht,
  4. pool_nutzung wird geschrieben,
  5. bestehender 'freigegeben'-Fluss bleibt unveraendert (Status-Flip nur fuer Nicht-Pool).

Ausfuehrung (HILO_DATA_DIR muss VOR dem Import gesetzt sein, siehe Hinweis am Ende):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/manual_pool_phase2.py
"""
import os, sys, random, datetime

# Projektwurzel in den Pfad (Test liegt in tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web


def _seed(conn):
    """Drei aktive Beratungsstellen (mit Facebook-Seite) und drei Pool-Beitraege anlegen."""
    for i in range(1, 4):
        conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv) VALUES (?,?,?,1)",
                     ("Stelle %d" % i, "Ort %d" % i, "fbseite_%d" % i))
    # Eine inaktive Stelle und eine ohne fb_seite - duerfen NICHT gezogen werden.
    conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv) VALUES ('Inaktiv','X','fb_x',0)")
    conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, aktiv) VALUES ('OhneSeite','Y',NULL,1)")
    # Vier zeitlose Pool-Beitraege (mehr als Stellen, damit 'je Stelle ein anderer' moeglich ist).
    eids = []
    for i in range(1, 5):
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook',?, 'pool')",
                           ('{"ueberschrift": "Pool-Beitrag %d"}' % i,))
        eid = cur.lastrowid
        eids.append(eid)
        conn.execute("INSERT INTO pool(entwurf_id, aktiv) VALUES (?, 1)", (eid,))
    conn.commit()
    return eids


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def main():
    db.init_db()
    heute = datetime.date.today().isoformat()
    with db.get_conn() as conn:
        _seed(conn)

    # Pool Phase 3 (#127) gatet Instagram auf Stellen, deren fb_seite ein verknuepftes IG-Konto hat.
    # Damit der Phase-2-Fluss (FB+IG) hier unveraendert greift, geben wir die drei Seiten als
    # IG-faehig vor (kein echter Meta-Aufruf im Test).
    web._pages = lambda force=False: (
        [{"id": "fbseite_%d" % i, "name": "Seite %d" % i,
          "ig_id": "ig_%d" % i, "ig_username": "stelle%d" % i} for i in range(1, 4)], None)

    # --- Lauf 1: deterministischer rng ---
    with db.get_conn() as conn:
        n1 = web._pool_tagesziehung(conn, datum=heute, rng=random.Random(42))
    # 3 aktive postbare Stellen x 2 Kanaele (facebook, instagram) = 6 Einplanungen.
    if n1 != 6:
        _fail("Erster Lauf: erwartete 6 Einplanungen, bekam %d" % n1)

    # --- Lauf 2: muss idempotent sein (nichts Neues) ---
    with db.get_conn() as conn:
        n2 = web._pool_tagesziehung(conn, datum=heute, rng=random.Random(99))
    if n2 != 0:
        _fail("Zweiter Lauf nicht idempotent: %d zusaetzliche Einplanungen" % n2)

    with db.get_conn() as conn:
        # (1) keine Doppelung je (Stelle, Kanal): genau ein pool=1-Eintrag pro Kombination
        dubletten = conn.execute(
            "SELECT stelle_id, kanal, COUNT(*) c FROM geplante_posts WHERE pool=1 "
            "GROUP BY stelle_id, kanal HAVING c > 1").fetchall()
        if dubletten:
            _fail("Doppelung je (Stelle, Kanal) gefunden: %r" % [tuple(r) for r in dubletten])

        # (3) geplante_posts mit pool=1 entstanden
        anzahl_pool = conn.execute("SELECT COUNT(*) FROM geplante_posts WHERE pool=1").fetchone()[0]
        if anzahl_pool != 6:
            _fail("Erwartete 6 pool=1-Eintraege, fand %d" % anzahl_pool)

        # (2) verschiedene Beitraege je Stelle am selben Tag/Kanal
        for kanal in ("facebook", "instagram"):
            eids = [r[0] for r in conn.execute(
                "SELECT entwurf_id FROM geplante_posts WHERE pool=1 AND kanal=?", (kanal,))]
            if len(eids) != len(set(eids)):
                _fail("Kanal %s: nicht alle Stellen bekamen einen ANDEREN Beitrag (%r)" % (kanal, eids))

        # (4) pool_nutzung wurde geschrieben (genau ein Tripel je Einplanung)
        nutzung = conn.execute("SELECT COUNT(*) FROM pool_nutzung").fetchone()[0]
        if nutzung != 6:
            _fail("Erwartete 6 pool_nutzung-Eintraege, fand %d" % nutzung)

        # Nur aktive postbare Stellen (IDs 1-3) wurden bedient - nicht die inaktive/ohne-Seite.
        bediente = {r[0] for r in conn.execute("SELECT DISTINCT stelle_id FROM geplante_posts WHERE pool=1")}
        if bediente != {1, 2, 3}:
            _fail("Falsche Stellen bedient: %r (erwartet {1,2,3})" % bediente)

        # Pool-Entwuerfe haben weiterhin status 'pool' (KEIN Status-Flip durch Einplanung)
        offene_pool = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status='pool'").fetchone()[0]
        if offene_pool != 4:
            _fail("Pool-Entwuerfe duerfen 'pool' bleiben, fand nur %d von 4" % offene_pool)

    # --- (5) Bestehender 'freigegeben'-Fluss unveraendert: _publiziere_geplant flippt einen
    #         NICHT-Pool-freigegebenen Entwurf weiter auf 'veroeffentlicht'. Wir simulieren das
    #         Posten, indem _veroeffentliche_ziel gemockt wird (kein Netzwerk).
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook','{}', 'freigegeben')")
        feid = cur.lastrowid
        # geplant_am leicht in der Vergangenheit, damit der Verpasst-Schutz (>60 Min) nicht greift.
        jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
        cur = conn.execute("INSERT INTO geplante_posts(entwurf_id, stelle_id, kanal, geplant_am, status, pool) "
                           "VALUES (?,1,'facebook',?, 'geplant', 0)", (feid, jetzt))
        gpid_frei = cur.lastrowid
        conn.commit()

    # geplante Pool-Einplanung von oben (Stelle 1, facebook) holen, um den Pool-Pfad zu pruefen.
    with db.get_conn() as conn:
        gpid_pool = conn.execute("SELECT id FROM geplante_posts WHERE pool=1 AND stelle_id=1 AND kanal='facebook'"
                                 ).fetchone()[0]
        eid_pool = conn.execute("SELECT entwurf_id FROM geplante_posts WHERE id=?", (gpid_pool,)).fetchone()[0]
        # geplant_am der Pool-Einplanung in die juengste Vergangenheit ruecken (Verpasst-Schutz umgehen).
        conn.execute("UPDATE geplante_posts SET geplant_am=? WHERE id=?", (jetzt, gpid_pool)); conn.commit()

    # _veroeffentliche_ziel mocken: immer Erfolg, ohne Netz.
    orig = web._veroeffentliche_ziel
    web._veroeffentliche_ziel = lambda conn, e, eid, *a, **k: ("Mock", True, [("facebook", True, "ok")])
    try:
        web._publiziere_geplant(gpid_frei)
        web._publiziere_geplant(gpid_pool)
    finally:
        web._veroeffentliche_ziel = orig

    with db.get_conn() as conn:
        s_frei = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (feid,)).fetchone()[0]
        s_pool = conn.execute("SELECT status FROM entwuerfe WHERE id=?", (eid_pool,)).fetchone()[0]
        gp_frei_status = conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gpid_frei,)).fetchone()[0]
        gp_pool_status = conn.execute("SELECT status FROM geplante_posts WHERE id=?", (gpid_pool,)).fetchone()[0]

    if s_frei != "veroeffentlicht":
        _fail("Bestehender Fluss verletzt: freigegebener Entwurf wurde NICHT auf 'veroeffentlicht' geflippt (%s)" % s_frei)
    if s_pool != "pool":
        _fail("Pool-Beitrag wurde faelschlich geflippt: Status ist '%s' statt 'pool'" % s_pool)
    if gp_frei_status != "veroeffentlicht" or gp_pool_status != "veroeffentlicht":
        _fail("geplante_posts nicht korrekt auf 'veroeffentlicht' gesetzt (frei=%s, pool=%s)"
              % (gp_frei_status, gp_pool_status))

    print("OK: alle Pool-Phase-2-Pruefungen bestanden")
    print("  Lauf 1: 6 Einplanungen, Lauf 2 (idempotent): 0")
    print("  pool=1-Eintraege: 6, pool_nutzung: 6, je Stelle/Kanal verschiedene Beitraege")
    print("  freigegeben -> veroeffentlicht (Flip OK), pool bleibt 'pool' (kein Flip)")


if __name__ == "__main__":
    main()
