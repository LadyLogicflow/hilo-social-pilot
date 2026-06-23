# -*- coding: utf-8 -*-
"""Tests fuer Issue #134 - sicheres, orphan-basiertes Aufraeumen des KI-Foto-Caches
(DATA_DIR/motive/) + Speicher-Status.

Beweist:
  A) bildmotiv.cache_dateien_fuer_fields: liefert die KORREKTEN Cache-Pfade
     (Standard-Szene UND KI-Tafel) fuer einen Entwurf; die gekapselte Hash-Formel ist
     IDENTISCH zur bestehenden ensure_photo/ensure_photo_tafel-Pfadbildung (Regression).
  B) wartung.aufraeumen_motive (Sicherheit zuerst):
     - aktiver Entwurf (entwurf/freigegeben) -> Foto bleibt, auch wenn ALT.
     - Pool-Entwurf -> Foto bleibt IMMER (auch alt).
     - verworfener/veroeffentlichter Entwurf (nicht im Pool, keine aktive Einplanung) mit
       Foto-mtime > 14 Tage -> Foto WIRD geloescht.
     - frisch erzeugtes verwaistes Foto (mtime < 14 Tage) -> bleibt (Schonfrist).
     - icon_-Datei -> wird NIE geloescht.
     - per geplante_posts (geplant/laeuft) referenzierter Entwurf -> Foto bleibt.
  C) Speicher-Helfer: motive_ordner_groesse, freier_speicher (disk_usage), menschlich.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/test_cache_retention.py
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import bildmotiv
import wartung
from bildmotiv import MOTIV_DIR


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _touch(pfad, alter_tage=0.0):
    """Legt eine kleine PNG-Dummy-Datei an und setzt ihre mtime auf 'alter_tage' Tage in der
    Vergangenheit (os.utime), um echte Schonfrist-Pruefung zu simulieren."""
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    if alter_tage:
        t = time.time() - alter_tage * 86400
        os.utime(pfad, (t, t))
    return pfad


def _entwurf(conn, status, fields):
    cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES (?,?,?)",
                       ("facebook", json.dumps(fields, ensure_ascii=False), status))
    return cur.lastrowid


# --- Vorbereitung -----------------------------------------------------------
db.init_db()
os.makedirs(MOTIV_DIR, exist_ok=True)

# --- A) Helfer-Pfade + Regression gegen bestehende Formel -------------------
fields = {"szene_motiv": "Ein warmer Herbstmoment am Kuechentisch", "ueberschrift": "Steuer leicht gemacht"}
pfade = bildmotiv.cache_dateien_fuer_fields(fields)

# Erwarteter Standard-Szene-Pfad (BESTEHENDE Formel, unveraendert)
motiv = fields["szene_motiv"]
h_szene = hashlib.sha256(("szene:" + motiv).lower().encode("utf-8")).hexdigest()[:16]
erwartet_szene = os.path.join(MOTIV_DIR, h_szene + ".png")
# Erwarteter Tafel-Pfad (BESTEHENDE Formel via tafel_cache_key)
key = bildmotiv.tafel_cache_key(motiv, fields["ueberschrift"])
h_tafel = hashlib.sha256(key.lower().encode("utf-8")).hexdigest()[:16]
erwartet_tafel = os.path.join(MOTIV_DIR, "tafel_" + h_tafel + ".png")

if erwartet_szene not in pfade:
    _fail("Helfer liefert nicht den erwarteten Standard-Szene-Pfad.")
if erwartet_tafel not in pfade:
    _fail("Helfer liefert nicht den erwarteten KI-Tafel-Pfad.")
# icon-Fall: nur der icon_-Pfad
ipfade = bildmotiv.cache_dateien_fuer_fields({"szene_motiv": "icon:kalender", "ueberschrift": "X"})
if ipfade != {os.path.join(MOTIV_DIR, "icon_kalender.png")}:
    _fail("Helfer liefert fuer 'icon:'-Motiv nicht exakt den icon_-Pfad: %r" % ipfade)
# defekte/leere fields -> leeres set, kein Crash
if bildmotiv.cache_dateien_fuer_fields(None) != set():
    _fail("Helfer crasht/liefert falsch fuer None.")
print("A) Helfer-Pfade + Regression: OK")

# --- B) Aufraeum-Szenarien --------------------------------------------------
with db.get_conn() as conn:
    # 1) Aktiver Entwurf (entwurf) mit ALTEM Foto -> bleibt
    f_aktiv = {"szene_motiv": "Aktive Szene am Morgen", "ueberschrift": "Bleibt"}
    _entwurf(conn, "entwurf", f_aktiv)
    p_aktiv = list(bildmotiv.cache_dateien_fuer_fields(f_aktiv))[0]

    # 2) Freigegebener Entwurf mit ALTEM Foto -> bleibt
    f_frei = {"szene_motiv": "Freigegebene Szene", "ueberschrift": "Bleibt2"}
    _entwurf(conn, "freigegeben", f_frei)

    # 3) Pool-Entwurf mit ALTEM Foto -> bleibt IMMER
    f_pool = {"szene_motiv": "Pool Szene zeitlos", "ueberschrift": "Pool"}
    _entwurf(conn, "pool", f_pool)

    # 4) Verworfener Entwurf mit ALTEM Foto (>14 Tage) -> WIRD geloescht
    f_verworfen = {"szene_motiv": "Verworfene alte Szene", "ueberschrift": "Weg"}
    _entwurf(conn, "verworfen", f_verworfen)

    # 5) Veroeffentlichter Entwurf, NICHT im Pool, keine aktive Einplanung, ALTES Foto -> geloescht
    f_veroeff = {"szene_motiv": "Veroeffentlichte alte Szene", "ueberschrift": "Auch weg"}
    _entwurf(conn, "veroeffentlicht", f_veroeff)

    # 6) Veroeffentlichter Entwurf, ABER per geplante_posts (status 'geplant') referenziert -> bleibt
    f_geplant = {"szene_motiv": "Eingeplante Szene", "ueberschrift": "Eingeplant"}
    eid_geplant = _entwurf(conn, "veroeffentlicht", f_geplant)
    conn.execute("INSERT INTO geplante_posts(entwurf_id, kanal, geplant_am, status) VALUES (?,?,?,?)",
                 (eid_geplant, "facebook", "2099-01-01T09:00", "geplant"))
    conn.commit()

    # Dateien anlegen: Standard-Szene-Pfade, alle ALT (40 Tage), ausser dem frischen Waisen-Foto.
    for f in (f_aktiv, f_frei, f_pool, f_verworfen, f_veroeff, f_geplant):
        for p in bildmotiv.cache_dateien_fuer_fields(f):
            # nur Standard-Szene-Datei anlegen (kein .startswith icon_), tafel-Pfad ebenfalls anlegen
            _touch(p, alter_tage=40)

    # 7) frisch erzeugtes verwaistes Foto (kein Entwurf, mtime 1 Tag) -> bleibt (Schonfrist)
    p_frisch = _touch(os.path.join(MOTIV_DIR, "deadbeefdeadbeef.png"), alter_tage=1)

    # 8) altes verwaistes Foto ohne jeden Entwurf (>14 Tage) -> wird geloescht
    p_waise_alt = _touch(os.path.join(MOTIV_DIR, "0000111122223333.png"), alter_tage=40)

    # 9) icon_-Datei, ALT, verwaist -> wird NIE geloescht
    p_icon = _touch(os.path.join(MOTIV_DIR, "icon_kalender.png"), alter_tage=99)

    geloescht, frei = wartung.aufraeumen_motive(conn, schonfrist_tage=14)

# Pruefungen
def _muss_da(p, was):
    if not os.path.exists(p):
        _fail("%s sollte ERHALTEN bleiben, wurde aber geloescht: %s" % (was, p))

def _muss_weg(p, was):
    if os.path.exists(p):
        _fail("%s sollte GELOESCHT sein, existiert aber noch: %s" % (was, p))

for f, name in ((f_aktiv, "aktiver Entwurf (entwurf)"), (f_frei, "freigegebener Entwurf"),
                (f_pool, "POOL-Entwurf"), (f_geplant, "eingeplanter Entwurf (geplante_posts)")):
    for p in bildmotiv.cache_dateien_fuer_fields(f):
        _muss_da(p, name + "-Foto")

# verworfen/veroeffentlicht -> die Standard-Szene-Datei muss weg sein
for f, name in ((f_verworfen, "verworfener Entwurf"), (f_veroeff, "veroeffentlichter Entwurf")):
    szene = bildmotiv._szene_pfad(f["szene_motiv"])
    _muss_weg(szene, name + "-Foto (verwaist, alt)")

_muss_da(p_frisch, "frisches verwaistes Foto (Schonfrist)")
_muss_weg(p_waise_alt, "altes verwaistes Foto")
_muss_da(p_icon, "icon_-Datei")

if geloescht < 1:
    _fail("Es haette mindestens 1 Datei geloescht werden muessen, war %d." % geloescht)
if frei <= 0:
    _fail("freigegebene Bytes sollten > 0 sein.")
print("B) Aufraeum-Szenarien (Pool/aktiv bleiben, alte Waisen weg, Schonfrist, icon_): OK (%d geloescht, %d Bytes)"
      % (geloescht, frei))

# --- C) Speicher-Helfer -----------------------------------------------------
groesse = wartung.motive_ordner_groesse()
if groesse <= 0:
    _fail("motive_ordner_groesse sollte > 0 sein (Dateien vorhanden).")
frei_b, gesamt_b = wartung.freier_speicher(__file__)
if gesamt_b <= 0 or frei_b <= 0 or frei_b > gesamt_b:
    _fail("freier_speicher liefert unplausible Werte: frei=%d gesamt=%d" % (frei_b, gesamt_b))
if wartung.menschlich(0) != "0 B":
    _fail("menschlich(0) falsch: %r" % wartung.menschlich(0))
if wartung.menschlich(1536) != "1,5 KB":
    _fail("menschlich(1536) falsch: %r" % wartung.menschlich(1536))
if not wartung.menschlich(5 * 1024 * 1024 * 1024).endswith("GB"):
    _fail("menschlich(5GB) sollte GB-Einheit liefern: %r" % wartung.menschlich(5 * 1024 * 1024 * 1024))
print("C) Speicher-Helfer (Groesse/disk_usage/menschlich): OK")

print("ALLE TESTS GRUEN (#134)")
