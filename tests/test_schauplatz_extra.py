# -*- coding: utf-8 -*-
"""Tests fuer Issue #141 - 20 ZUSAETZLICHE Schauplaetze (additiver, idempotenter Seed).

Beweist (KEIN echter API-Call):
  1) Nach init_db: 40 Schauplaetze, genau 10 pro Jahreszeit, echte Umlaute.
  2) Zweiter init_db-Lauf -> weiterhin 40 (keine Duplikate, idempotent).
  3) Bestehende DB (erst nur die 20 aus #140, dann seed_schauplaetze_extra) -> 40.
  4) Ein manuell geloeschter NEUER Eintrag wird beim naechsten init_db NICHT wieder
     eingespielt (Sentinel verhindert Wiedereinspielen).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_schauplatz_extra.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    print("OK:", msg)


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM schauplaetze").fetchone()[0]


def _je_jahreszeit(conn):
    z = {}
    for r in conn.execute("SELECT jahreszeit FROM schauplaetze"):
        z[r["jahreszeit"]] = z.get(r["jahreszeit"], 0) + 1
    return z


# --- 1) init_db -> 40, 10/Jahreszeit, echte Umlaute ------------------------
db.init_db()
with db.get_conn() as conn:
    n = _count(conn)
    z = _je_jahreszeit(conn)
    alle = " ".join(r["beschreibung"] for r in
                    conn.execute("SELECT beschreibung FROM schauplaetze"))
if n != 40:
    _fail("init_db: erwartet 40 Schauplaetze, sind %d" % n)
for jz in ("fruehling", "sommer", "herbst", "winter"):
    if z.get(jz) != 10:
        _fail("init_db: Jahreszeit %s hat %s statt 10" % (jz, z.get(jz)))
for u in ("ä", "ö", "ü", "ß"):
    if u not in alle:
        _fail("Umlaut/ss '%s' fehlt - keine echten Umlaute im Extra-Seed?" % u)
_ok("1) init_db: 40 Schauplaetze, 10/Jahreszeit, echte Umlaute (inkl. ß)")

# --- 2) Zweiter init_db-Lauf -> weiterhin 40 (idempotent) ------------------
db.init_db()
with db.get_conn() as conn:
    n = _count(conn)
if n != 40:
    _fail("idempotent: nach zweitem init_db sind %d statt 40" % n)
_ok("2) Zweiter init_db-Lauf -> weiterhin 40 (idempotent)")

# --- 3) Bestehende DB: erst nur die 20 aus #140, dann extra -> 40 ----------
with db.get_conn() as conn:
    conn.execute("DELETE FROM schauplaetze")
    db.seed_schauplaetze(conn)            # nur die 20 aus #140 (leere Tabelle)
    n20 = _count(conn)
    db.seed_schauplaetze_extra(conn)      # zieht die 20 neuen nach
    n40 = _count(conn)
if n20 != 20:
    _fail("Simulation #140-DB: erwartet 20, sind %d" % n20)
if n40 != 40:
    _fail("Nachziehen in bestehende DB: erwartet 40, sind %d" % n40)
_ok("3) Bestehende #140-DB (20) -> seed_schauplaetze_extra -> 40")

# --- 4) Manuell geloeschter NEUER Eintrag wird NICHT wieder eingespielt ----
geloescht = db.SCHAUPLATZ_SEED_EXTRA[5][0]   # ein NICHT-Sentinel-Eintrag
with db.get_conn() as conn:
    conn.execute("DELETE FROM schauplaetze WHERE beschreibung=?", (geloescht,))
    rest = _count(conn)
if rest != 39:
    _fail("Loeschen: erwartet 39 nach Loeschen eines Eintrags, sind %d" % rest)
db.init_db()
with db.get_conn() as conn:
    n = _count(conn)
    wieder_da = conn.execute("SELECT 1 FROM schauplaetze WHERE beschreibung=?",
                             (geloescht,)).fetchone()
if wieder_da:
    _fail("Sentinel verletzt: geloeschter Eintrag '%s' wurde wieder eingespielt" % geloescht)
if n != 39:
    _fail("Sentinel: erwartet 39 nach init_db (geloeschter bleibt weg), sind %d" % n)
_ok("4) Manuell geloeschter neuer Eintrag bleibt geloescht (Sentinel)")

print("\nALLE TESTS BESTANDEN (#141)")
