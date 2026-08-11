# -*- coding: utf-8 -*-
"""Tests fuer Issue #140 - Schauplaetze-Bibliothek (saisonale Umgebungen mit Bilderrahmen-Botschaft).

Beweist (KEIN echter API-Call):
  A) Seed: 20 Schauplaetze, genau 5 pro Jahreszeit, mit echten Umlauten.
  B) schauplatz.aktuelle_jahreszeit: korrekt je Monat (3-5 fruehling, 6-8 sommer, 9-11 herbst, 12/1/2 winter).
  C) schauplatz.ziel_jahreszeit:
       - Sommer-Thema im Winter -> sommer
       - Weihnachts-Thema -> winter
       - Anlass-Datum (MM-DD) -> Jahreszeit dieses Datums
       - kein Themenbezug -> Kalender-Jahreszeit (datum-abhaengig)
  D) waehle_schauplatz: rotiert (kein zweimal dasselbe, bis alle der Jahreszeit dran waren),
     setzt zuletzt_genutzt, respektiert aktiv=0.
  E) zuweisen_falls_fehlt setzt fields['schauplatz'] genau einmal (stabil, kein Re-Wuerfeln).
  F) bildmotiv ki_tafel: _tafel_scene nutzt fields['schauplatz'] als Szene + Fallback;
     _tafel_prompt nutzt scene + Bilderrahmen/Tisch-Aufsteller-Device + vollen sign_text.
  G) #134-Retention: cache_dateien_fuer_fields enthaelt den Schauplatz-Tafel-Pfad (gleicher
     scene-Wert wie der Producer ensure_photo_fuer) -> kein Falsch-Loeschen.
  H) Verwaltung-CRUD (web.py): anlegen/bearbeiten/toggle/loeschen.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/manual_schauplatz.py
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import schauplatz
import bildmotiv


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    print("OK:", msg)


db.init_db()

# --- A) Seed ----------------------------------------------------------------
with db.get_conn() as conn:
    rows = conn.execute("SELECT beschreibung, jahreszeit FROM schauplaetze").fetchall()
if len(rows) != 40:
    _fail("Seed: erwartet 40 Schauplaetze, sind %d" % len(rows))
zaehl = {}
for r in rows:
    zaehl[r["jahreszeit"]] = zaehl.get(r["jahreszeit"], 0) + 1
for jz in schauplatz.JAHRESZEITEN:
    if zaehl.get(jz) != 10:
        _fail("Seed: Jahreszeit %s hat %s statt 10 Schauplaetze" % (jz, zaehl.get(jz)))
# echte Umlaute im Seed (z.B. Café, München, Dünen, Kürbissen, Rottönen)
alle = " ".join(r["beschreibung"] for r in rows)
for u in ("ä", "ö", "ü", "é"):
    if u not in alle:
        _fail("Seed: erwartetes Umlaut/Sonderzeichen '%s' fehlt - keine echten Umlaute?" % u)
# Seed idempotent: zweiter Aufruf legt nichts dazu
with db.get_conn() as conn:
    db.seed_schauplaetze(conn)
    db.seed_schauplaetze_extra(conn)
    n2 = conn.execute("SELECT COUNT(*) FROM schauplaetze").fetchone()[0]
if n2 != 40:
    _fail("Seed nicht idempotent: nach zweitem seed sind %d" % n2)
_ok("A) Seed: 40 Schauplaetze, 10/Jahreszeit, echte Umlaute, idempotent")

# --- B) aktuelle_jahreszeit -------------------------------------------------
erwartet = {1: "winter", 2: "winter", 3: "fruehling", 4: "fruehling", 5: "fruehling",
            6: "sommer", 7: "sommer", 8: "sommer", 9: "herbst", 10: "herbst", 11: "herbst",
            12: "winter"}
for m, jz in erwartet.items():
    got = schauplatz.aktuelle_jahreszeit(m)
    if got != jz:
        _fail("aktuelle_jahreszeit(%d) = %s, erwartet %s" % (m, got, jz))
_ok("B) aktuelle_jahreszeit korrekt fuer alle 12 Monate")

# --- C) ziel_jahreszeit -----------------------------------------------------
winter_tag = datetime.date(2026, 1, 15)   # tatsaechlich Winter
# Sommer-Thema im Winter -> sommer (Thema schlaegt Kalender)
jz = schauplatz.ziel_jahreszeit({"ueberschrift": "Tipps für den Sommerurlaub am Strand"}, winter_tag)
if jz != "sommer":
    _fail("ziel_jahreszeit: Sommer-Thema im Winter -> %s, erwartet sommer" % jz)
# Weihnachts-Thema -> winter
jz = schauplatz.ziel_jahreszeit({"titel": "Spenden zu Weihnachten absetzen"}, datetime.date(2026, 7, 1))
if jz != "winter":
    _fail("ziel_jahreszeit: Weihnachts-Thema -> %s, erwartet winter" % jz)
# Anlass-Datum (MM-DD) -> Jahreszeit des Datums (10-31 -> herbst)
jz = schauplatz.ziel_jahreszeit({"anlass_datum": "10-31"}, datetime.date(2026, 1, 1))
if jz != "herbst":
    _fail("ziel_jahreszeit: Anlass-Datum 10-31 -> %s, erwartet herbst" % jz)
# kein Themenbezug -> Kalender-Jahreszeit
jz = schauplatz.ziel_jahreszeit({"ueberschrift": "Werbungskosten richtig absetzen"}, winter_tag)
if jz != "winter":
    _fail("ziel_jahreszeit: ohne Themenbezug im Winter -> %s, erwartet winter" % jz)
jz = schauplatz.ziel_jahreszeit({"ueberschrift": "Werbungskosten"}, datetime.date(2026, 6, 1))
if jz != "sommer":
    _fail("ziel_jahreszeit: ohne Themenbezug im Juni -> %s, erwartet sommer" % jz)
_ok("C) ziel_jahreszeit: Thema schlaegt Kalender, Anlass-Datum, Fallback auf Kalender")

# --- D) waehle_schauplatz Rotation -----------------------------------------
# Erzwinge Sommer (kein Themenbezug, Datum im Sommer); es gibt genau 10 Sommer-Schauplaetze.
sommer_tag = datetime.date(2026, 7, 15)
gewaehlt = []
with db.get_conn() as conn:
    sommer_namen = {r["beschreibung"] for r in
                    conn.execute("SELECT beschreibung FROM schauplaetze WHERE jahreszeit='sommer'").fetchall()}
    for _ in range(10):
        sp = schauplatz.waehle_schauplatz(conn, {"ueberschrift": "Neutrales Thema"}, sommer_tag)
        gewaehlt.append(sp)
    conn.commit()
if len(set(gewaehlt)) != 10:
    _fail("Rotation: in 10 Zuegen NICHT alle 10 Sommer-Schauplaetze verschieden: %r" % gewaehlt)
if set(gewaehlt) != sommer_namen:
    _fail("Rotation: gewaehlte Menge != die 10 Sommer-Schauplaetze")
# zuletzt_genutzt ist nun fuer alle Sommer-Schauplaetze gesetzt
with db.get_conn() as conn:
    offen = conn.execute("SELECT COUNT(*) FROM schauplaetze WHERE jahreszeit='sommer' "
                         "AND zuletzt_genutzt IS NULL").fetchone()[0]
if offen != 0:
    _fail("Rotation: %d Sommer-Schauplaetze ohne zuletzt_genutzt nach 5 Zuegen" % offen)
# Naechster Zug: der am laengsten nicht genutzte (= der zuerst gewaehlte) kommt wieder dran
with db.get_conn() as conn:
    sp6 = schauplatz.waehle_schauplatz(conn, {"ueberschrift": "Neutral"}, sommer_tag)
    conn.commit()
if sp6 != gewaehlt[0]:
    _fail("Rotation: naechster Zug = %r, erwartet der laengst-ungenutzte %r" % (sp6, gewaehlt[0]))
_ok("D) waehle_schauplatz rotiert, nie doppelt im Zyklus, setzt zuletzt_genutzt")

# aktiv=0 wird uebersprungen: alle Sommer auf inaktiv -> Fallback auf andere aktive Jahreszeit
with db.get_conn() as conn:
    conn.execute("UPDATE schauplaetze SET aktiv=0 WHERE jahreszeit='sommer'")
    sp = schauplatz.waehle_schauplatz(conn, {"ueberschrift": "Neutral"}, sommer_tag)
    conn.rollback()   # Aenderung nicht behalten
if not sp or sp in sommer_namen:
    _fail("Fallback: bei inaktivem Sommer wurde dennoch ein Sommer-Schauplatz gewaehlt: %r" % sp)
_ok("D2) inaktive Jahreszeit -> Fallback auf anderen aktiven Schauplatz")

# --- E) zuweisen_falls_fehlt: stabil ---------------------------------------
fields = {"ueberschrift": "Neutrales Thema"}
with db.get_conn() as conn:
    sp1 = schauplatz.zuweisen_falls_fehlt(conn, fields, datetime.date(2026, 4, 1))
    conn.commit()
if not fields.get("schauplatz") or fields["schauplatz"] != sp1:
    _fail("zuweisen_falls_fehlt: fields['schauplatz'] nicht gesetzt")
# erneuter Aufruf darf NICHT neu wuerfeln (Stabilitaet)
with db.get_conn() as conn:
    sp2 = schauplatz.zuweisen_falls_fehlt(conn, fields, datetime.date(2026, 4, 1))
    conn.commit()
if sp2 != sp1 or fields["schauplatz"] != sp1:
    _fail("zuweisen_falls_fehlt: hat erneut gewuerfelt (%r -> %r), erwartet stabil" % (sp1, sp2))
_ok("E) zuweisen_falls_fehlt setzt fields['schauplatz'] einmal, bleibt stabil")

# --- F) ki_tafel-Szene + Prompt --------------------------------------------
scene = bildmotiv._tafel_scene({"schauplatz": "Weinberg im goldenen Spätsommerlicht",
                                "bild_motiv": "Buero"})
if scene != "Weinberg im goldenen Spätsommerlicht":
    _fail("_tafel_scene: nutzt nicht den Schauplatz, sondern %r" % scene)
# Fallback auf Motiv, wenn kein Schauplatz
scene_fb = bildmotiv._tafel_scene({"bild_motiv": "Buero-Szene"})
if scene_fb != "Buero-Szene":
    _fail("_tafel_scene: Fallback auf Motiv falsch: %r" % scene_fb)
# Prompt nutzt scene + Bilderrahmen-Device + vollen sign_text
sign = "Sparer-Pauschbetrag nutzen\n- bis 1000 Euro steuerfrei\n- Freistellungsauftrag stellen"
prompt = bildmotiv._tafel_prompt("Weinberg im goldenen Spätsommerlicht", sign)
if "Weinberg im goldenen Spätsommerlicht" not in prompt:
    _fail("_tafel_prompt: Schauplatz-Szene fehlt im Prompt")
if "BILDERRAHMEN" not in prompt or "TISCH" not in prompt.upper():
    _fail("_tafel_prompt: Bilderrahmen/Tisch-Aufsteller-Device fehlt")
if sign not in prompt:
    _fail("_tafel_prompt: voller sign_text (Ueberschrift + Stichpunkte) fehlt")
if "EINZIGE Schrift" not in prompt:
    _fail("_tafel_prompt: 'EINZIGE Schrift'-Anweisung verloren (Regression)")
_ok("F) ki_tafel: scene=Schauplatz (+Fallback), Bilderrahmen-Device, voller sign_text")

# --- G) #134-Retention: gleicher scene-Wert wie Producer --------------------
fields_t = {"ueberschrift": "Test", "bullets": ["A", "B"],
            "schauplatz": "Verschneite Altstadtgasse mit Laternen", "bild_motiv": "Anderes Motiv"}
sign_t = bildmotiv.tafel_sign_text(fields_t)
pfade = bildmotiv.cache_dateien_fuer_fields(fields_t)
for tool in ("openai", "ideogram"):
    erwartet_pfad = bildmotiv._tafel_pfad("Verschneite Altstadtgasse mit Laternen", sign_t, tool=tool)
    if erwartet_pfad not in pfade:
        _fail("Retention: Tafel-Pfad mit Schauplatz-Szene (%s) fehlt in cache_dateien_fuer_fields" % tool)
    # FALSCHER Pfad (mit Motiv statt Schauplatz) darf NICHT der einzige sein -> Konsistenz-Check:
    falsch = bildmotiv._tafel_pfad("Anderes Motiv", sign_t, tool=tool)
    if falsch in pfade and erwartet_pfad not in pfade:
        _fail("Retention: zeigt auf Motiv- statt Schauplatz-Pfad -> Falsch-Loeschen-Risiko")
_ok("G) #134-Retention: cache_dateien_fuer_fields nutzt denselben Schauplatz-scene wie der Producer")

# --- H) Verwaltung-CRUD via web.py -----------------------------------------
import web
web.app.config["TESTING"] = True
client = web.app.test_client()
with client.session_transaction() as s:
    s["user"] = "tester"
    s["rolle"] = "admin"


def _post(form):
    return client.post("/verwaltung", data=form, follow_redirects=False)


# anlegen
_post({"formular": "schauplatz_save", "beschreibung": "Testkulisse am Hafen",
       "jahreszeit": "sommer", "aktiv": "1"})
with db.get_conn() as conn:
    row = conn.execute("SELECT id, jahreszeit, aktiv FROM schauplaetze WHERE beschreibung=?",
                       ("Testkulisse am Hafen",)).fetchone()
if not row:
    _fail("CRUD: anlegen fehlgeschlagen")
neu_id = row["id"]
# bearbeiten (Jahreszeit aendern, deaktivieren)
_post({"formular": "schauplatz_save", "id": str(neu_id), "beschreibung": "Testkulisse am Hafen (Herbst)",
       "jahreszeit": "herbst"})   # ohne aktiv-checkbox -> aktiv=0
with db.get_conn() as conn:
    row = conn.execute("SELECT beschreibung, jahreszeit, aktiv FROM schauplaetze WHERE id=?", (neu_id,)).fetchone()
if row["jahreszeit"] != "herbst" or row["beschreibung"] != "Testkulisse am Hafen (Herbst)" or row["aktiv"] != 0:
    _fail("CRUD: bearbeiten fehlgeschlagen: %r" % (dict(row),))
# toggle -> wieder aktiv
_post({"formular": "schauplatz_toggle", "id": str(neu_id)})
with db.get_conn() as conn:
    aktiv = conn.execute("SELECT aktiv FROM schauplaetze WHERE id=?", (neu_id,)).fetchone()["aktiv"]
if aktiv != 1:
    _fail("CRUD: toggle fehlgeschlagen")
# loeschen
_post({"formular": "schauplatz_delete", "id": str(neu_id)})
with db.get_conn() as conn:
    weg = conn.execute("SELECT 1 FROM schauplaetze WHERE id=?", (neu_id,)).fetchone()
if weg:
    _fail("CRUD: loeschen fehlgeschlagen")
# Seite rendert (GET)
r = client.get("/verwaltung?bereich=schauplatz")
if r.status_code != 200 or "Schaupl".encode("utf-8") not in r.data:
    _fail("CRUD: Verwaltungsseite Schauplaetze rendert nicht (HTTP %s)" % r.status_code)
_ok("H) Verwaltung-CRUD: anlegen/bearbeiten/toggle/loeschen + Render")

print("\nALLE TESTS BESTANDEN (#140 Schauplaetze).")
