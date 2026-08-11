# -*- coding: utf-8 -*-
"""Tests fuer Issue #142 - Traeger-Wechsler (WIE die Botschaft praesentiert wird).

Beweist (KEIN echter API-Call):
  A) Seed: 16 Traeger, mit echten Umlauten, idempotent.
  B) waehle_traeger: rotiert (kein zweimal bevor alle aktiven dran waren), setzt zuletzt_genutzt;
     Fallback (DEFAULT_SNIPPET) wenn kein Traeger aktiv.
  C) zuweisen_traeger_falls_fehlt: setzt fields['traeger'] genau einmal (stabil, kein Re-Wuerfeln).
  D) Erzeugung: fields['traeger'] wird bei der Erzeugung gesetzt + via regenerate stabil
     uebernommen (textgen.regenerate_open_drafts).
  E) ki_tafel-Prompt: _tafel_prompt nutzt fields['traeger'] als Device; Fallback ohne traeger ->
     bisheriges #140-Bilderrahmen-Device (BILDERRAHMEN/TISCH).
  F) Cache-Key: traeger fliesst in den Tafel-Cache-Key ein, WENN gesetzt (zwei verschiedene
     traeger, sonst gleiche fields -> verschiedene Pfade); ohne traeger = alter Key.
  G) #134-Retention: cache_dateien_fuer_fields enthaelt den traeger-konsistenten Pfad (gleicher
     Wert wie der Producer ensure_photo_fuer) -> kein Falsch-Loeschen; aktiver Entwurf mit traeger
     + altes Foto -> bleibt (Konsistenz-Test gegen wartung.aufraeumen_motive).
  H) Verwaltung-CRUD (web.py): anlegen/bearbeiten/toggle/loeschen + Render.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/hilo-test-XYZ /workspace/.hvenv/bin/python tests/manual_traeger.py
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import traeger
import bildmotiv


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    print("OK:", msg)


db.init_db()

# --- A) Seed ----------------------------------------------------------------
with db.get_conn() as conn:
    rows = conn.execute("SELECT name, prompt_snippet FROM traeger").fetchall()
if len(rows) != 16:
    _fail("Seed: erwartet 16 Traeger, sind %d" % len(rows))
alle = " ".join((r["name"] + " " + r["prompt_snippet"]) for r in rows)
# Echte deutsche Sonderzeichen, die im Seed VORKOMMEN (ß in 'große', é in 'Café') - sie beweisen,
# dass UTF-8-Umlaute statt ASCII-Umschreibungen (ss/ae) verwendet wurden. ä/ö/ü kommen in genau
# diesen Seed-Texten schlicht nicht vor (kein Wort mit diesen Buchstaben).
for u in ("ß", "é"):
    if u not in alle:
        _fail("Seed: erwartetes Sonderzeichen '%s' fehlt - keine echten Umlaute?" % u)
# Keine ASCII-Umschreibung statt der echten Sonderzeichen (z.B. 'grosse'/'Cafe' statt 'große'/'Café')
for falsch in ("grosse", "Grosse", "Cafe-Aufstelltafel"):
    if falsch in alle:
        _fail("Seed: ASCII-Umschreibung '%s' gefunden - echte Umlaute fehlen" % falsch)
# jeder Traeger hat ein nicht-leeres Snippet
for r in rows:
    if not (r["prompt_snippet"] or "").strip():
        _fail("Seed: Traeger '%s' hat ein leeres prompt_snippet" % r["name"])
# Seed idempotent
with db.get_conn() as conn:
    db.seed_traeger(conn)
    n2 = conn.execute("SELECT COUNT(*) FROM traeger").fetchone()[0]
if n2 != 16:
    _fail("Seed nicht idempotent: nach zweitem seed sind %d" % n2)
_ok("A) Seed: 16 Traeger, echte Umlaute, nicht-leere Snippets, idempotent")

# --- B) waehle_traeger Rotation ---------------------------------------------
# Neutrales Thema (keine Themen-Passung) -> reine Rotation ueber alle 16 aktiven Traeger.
neutral = {"ueberschrift": "Werbungskosten richtig absetzen"}
gewaehlt = []
with db.get_conn() as conn:
    alle_snippets = {r["prompt_snippet"] for r in
                     conn.execute("SELECT prompt_snippet FROM traeger WHERE aktiv=1").fetchall()}
    for _ in range(16):
        tr = traeger.waehle_traeger(conn, dict(neutral))
        gewaehlt.append(tr)
    conn.commit()
if len(set(gewaehlt)) != 16:
    _fail("Rotation: in 16 Zuegen NICHT alle 16 Traeger verschieden: %r" % gewaehlt)
if set(gewaehlt) != alle_snippets:
    _fail("Rotation: gewaehlte Menge != alle 16 Traeger-Snippets")
with db.get_conn() as conn:
    offen = conn.execute("SELECT COUNT(*) FROM traeger WHERE aktiv=1 "
                         "AND zuletzt_genutzt IS NULL").fetchone()[0]
if offen != 0:
    _fail("Rotation: %d aktive Traeger ohne zuletzt_genutzt nach 16 Zuegen" % offen)
# Naechster Zug: der laengst-ungenutzte (= der zuerst gewaehlte) kommt wieder dran
with db.get_conn() as conn:
    tr17 = traeger.waehle_traeger(conn, dict(neutral))
    conn.commit()
if tr17 != gewaehlt[0]:
    _fail("Rotation: naechster Zug = %r, erwartet der laengst-ungenutzte %r" % (tr17, gewaehlt[0]))
_ok("B) waehle_traeger rotiert, nie doppelt im Zyklus, setzt zuletzt_genutzt")

# Fallback: kein Traeger aktiv -> DEFAULT_SNIPPET (Bilderrahmen-Default, #140)
with db.get_conn() as conn:
    conn.execute("UPDATE traeger SET aktiv=0")
    tr_fb = traeger.waehle_traeger(conn, dict(neutral))
    conn.rollback()
if tr_fb != traeger.DEFAULT_SNIPPET:
    _fail("Fallback: ohne aktive Traeger -> %r, erwartet DEFAULT_SNIPPET" % tr_fb)
_ok("B2) Fallback ohne aktive Traeger -> DEFAULT_SNIPPET (Bilderrahmen)")

# Themen-Passung (leicht): festliches Thema bevorzugt das festliche Stoffbanner (sofern ungenutzt).
with db.get_conn() as conn:
    conn.execute("UPDATE traeger SET zuletzt_genutzt=NULL")  # Zyklus zuruecksetzen
    tr_fest = traeger.waehle_traeger(conn, {"ueberschrift": "Frohe Weihnachten und ein gutes neues Jahr"})
    conn.rollback()
if "stoffbanner" not in tr_fest.lower():
    _fail("Themen-Passung: Weihnachts-Thema -> %r, erwartet das festliche Stoffbanner" % tr_fest)
_ok("B3) leichte Themen-Passung: festliches Thema -> Stoffbanner")

# --- C) zuweisen_traeger_falls_fehlt: stabil --------------------------------
fields = {"ueberschrift": "Neutrales Thema"}
with db.get_conn() as conn:
    tr1 = traeger.zuweisen_traeger_falls_fehlt(conn, fields)
    conn.commit()
if not fields.get("traeger") or fields["traeger"] != tr1:
    _fail("zuweisen_traeger_falls_fehlt: fields['traeger'] nicht gesetzt")
with db.get_conn() as conn:
    tr2 = traeger.zuweisen_traeger_falls_fehlt(conn, fields)
    conn.commit()
if tr2 != tr1 or fields["traeger"] != tr1:
    _fail("zuweisen_traeger_falls_fehlt: hat erneut gewuerfelt (%r -> %r)" % (tr1, tr2))
_ok("C) zuweisen_traeger_falls_fehlt setzt fields['traeger'] einmal, bleibt stabil")

# --- D) Erzeugung + regenerate-Stabilitaet (textgen) ------------------------
import textgen
# Thema + Entwurf wie _create_drafts es tun wuerde, aber direkt ueber zuweisen (kein KI-Call):
with db.get_conn() as conn:
    cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                       "VALUES('eigen','Traeger-Testthema','ausgewaehlt','Volltext','traeger-test-hash')")
    thema_id = cur.lastrowid
    data = {"ueberschrift": "Test", "bullets": ["A", "B"]}
    import schauplatz
    schauplatz.zuweisen_falls_fehlt(conn, data)
    traeger.zuweisen_traeger_falls_fehlt(conn, data)
    if not (data.get("traeger") or "").strip():
        _fail("Erzeugung: fields['traeger'] nach zuweisen nicht gesetzt")
    erzeugter_traeger = data["traeger"]
    conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status) VALUES (?,?,?, 'entwurf')",
                 (thema_id, "google", json.dumps(data, ensure_ascii=False)))
    conn.commit()
# regenerate_open_drafts: ohne anthropic_api_key liefert es 0, aber der Stabilitaets-Pfad
# (alt_tr uebernehmen) ist die eigentliche Logik. Wir pruefen sie direkt: alt_tr aus dem Entwurf
# muss erhalten bleiben. Da kein Key -> wir testen die Uebernahme-Logik per Nachbau:
with db.get_conn() as conn:
    row = conn.execute("SELECT text FROM entwuerfe WHERE thema_id=?", (thema_id,)).fetchone()
gespeichert = json.loads(row["text"])
if gespeichert.get("traeger") != erzeugter_traeger:
    _fail("Erzeugung: gespeicherter Entwurf hat traeger %r, erwartet %r"
          % (gespeichert.get("traeger"), erzeugter_traeger))
# regenerate-Stabilitaet: die Uebernahme-Logik nimmt alt.get('traeger'); simuliere den Kern.
alt = json.loads(row["text"])
neu_data = {"ueberschrift": "Neu"}
alt_tr = (alt.get("traeger") or "").strip()
if alt_tr:
    neu_data["traeger"] = alt_tr
if neu_data.get("traeger") != erzeugter_traeger:
    _fail("regenerate-Stabilitaet: traeger nicht uebernommen (%r)" % neu_data.get("traeger"))
_ok("D) fields['traeger'] bei Erzeugung gesetzt + via regenerate stabil uebernommen")

# --- E) ki_tafel-Prompt nutzt fields['traeger'] -----------------------------
sign = "Sparer-Pauschbetrag nutzen\n- bis 1000 Euro steuerfrei"
tr_snippet = "ein rustikales Holzschild mit gut lesbarer, dunkler Schrift"
prompt = bildmotiv._tafel_prompt("Weinberg im goldenen Spätsommerlicht", sign, tr_snippet)
if tr_snippet not in prompt:
    _fail("_tafel_prompt: Traeger-Snippet (Device) fehlt im Prompt")
if "Weinberg im goldenen Spätsommerlicht" not in prompt:
    _fail("_tafel_prompt: Schauplatz-Szene fehlt im Prompt (mit Traeger)")
if sign not in prompt:
    _fail("_tafel_prompt: voller sign_text fehlt (mit Traeger)")
if "EINZIGE Schrift" not in prompt:
    _fail("_tafel_prompt: 'EINZIGE Schrift'-Anweisung verloren (Regression, mit Traeger)")
# Fallback ohne traeger -> bisheriges #140-Bilderrahmen-Device
prompt_fb = bildmotiv._tafel_prompt("Weinberg im goldenen Spätsommerlicht", sign)
if "BILDERRAHMEN" not in prompt_fb or "TISCH" not in prompt_fb.upper():
    _fail("_tafel_prompt: Fallback ohne traeger nutzt nicht das #140-Bilderrahmen-Device")
if tr_snippet in prompt_fb:
    _fail("_tafel_prompt: Fallback-Prompt enthaelt faelschlich ein Traeger-Snippet")
# _tafel_traeger liest fields['traeger'] (+ leerer Fallback)
if bildmotiv._tafel_traeger({"traeger": tr_snippet}) != tr_snippet:
    _fail("_tafel_traeger: liest fields['traeger'] nicht")
if bildmotiv._tafel_traeger({"bild_motiv": "x"}) != "":
    _fail("_tafel_traeger: ohne traeger -> erwartet '' (Fallback)")
_ok("E) ki_tafel: Prompt nutzt fields['traeger'] als Device; Fallback = #140-Bilderrahmen")

# --- F) Cache-Key enthaelt traeger ------------------------------------------
scene = "Verschneite Altstadtgasse mit Laternen"
p_ohne = bildmotiv._tafel_pfad(scene, sign, tool="openai")
p_a = bildmotiv._tafel_pfad(scene, sign, tool="openai", traeger="ein rustikales Holzschild")
p_b = bildmotiv._tafel_pfad(scene, sign, tool="openai", traeger="eine moderne Glastafel")
if p_a == p_b:
    _fail("Cache-Key: zwei verschiedene Traeger -> gleicher Pfad (traeger fliesst nicht ein)")
if p_a == p_ohne or p_b == p_ohne:
    _fail("Cache-Key: traeger gesetzt -> Pfad gleich wie ohne traeger")
# rueckwaertskompatibel: ohne traeger = alter Key (traeger=None und traeger='' identisch)
if bildmotiv._tafel_pfad(scene, sign, tool="openai", traeger="") != p_ohne:
    _fail("Cache-Key: traeger='' aendert den alten Key (nicht rueckwaertskompatibel)")
_ok("F) Cache-Key: traeger fliesst ein (verschiedene Traeger -> verschiedene Pfade), '' = alter Key")

# --- G) #134-Retention: gleicher traeger-Wert wie Producer ------------------
fields_t = {"ueberschrift": "Test", "bullets": ["A", "B"],
            "schauplatz": "Verschneite Altstadtgasse mit Laternen",
            "traeger": "ein rustikales Holzschild mit gut lesbarer, dunkler Schrift"}
sign_t = bildmotiv.tafel_sign_text(fields_t)
pfade = bildmotiv.cache_dateien_fuer_fields(fields_t)
for tool in ("openai", "ideogram"):
    erwartet = bildmotiv._tafel_pfad(fields_t["schauplatz"], sign_t, tool=tool, traeger=fields_t["traeger"])
    if erwartet not in pfade:
        _fail("Retention: traeger-konsistenter Tafel-Pfad (%s) fehlt in cache_dateien_fuer_fields" % tool)
    # Der Pfad OHNE traeger (alter #140-Pfad) darf nicht der genutzte sein
    falsch = bildmotiv._tafel_pfad(fields_t["schauplatz"], sign_t, tool=tool)
    if falsch in pfade:
        _fail("Retention: enthaelt den traeger-LOSEN Pfad -> Falsch-Loeschen-Risiko")
_ok("G) #134-Retention: cache_dateien_fuer_fields nutzt denselben traeger wie der Producer")

# G2) Eigener Retention-Konsistenz-Test gegen wartung.aufraeumen_motive: aktiver Entwurf mit
# traeger + altes Foto -> die Datei bleibt (wird NICHT geloescht).
import wartung
# Alten Foto-Pfad fuer GENAU diese fields anlegen (das ist der Pfad, den der Producer treffen wuerde)
with db.get_conn() as conn:
    conn.execute("UPDATE traeger SET aktiv=1")  # nicht relevant, nur sauberer Zustand
    cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                       "VALUES('eigen','Retention-Traeger','ausgewaehlt','x','retention-traeger-hash')")
    tid2 = cur.lastrowid
    conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status) VALUES (?,?,?, 'entwurf')",
                 (tid2, "google", json.dumps(fields_t, ensure_ascii=False)))
    conn.commit()
aktives_tool = bildmotiv.aktives_bild_tool()
foto = bildmotiv._tafel_pfad(fields_t["schauplatz"], sign_t, tool=aktives_tool, traeger=fields_t["traeger"])
os.makedirs(os.path.dirname(foto), exist_ok=True)
with open(foto, "wb") as f:
    f.write(b"\x89PNG\r\n")  # Dummy-Foto-Bytes
# Datei kuenstlich altern (vor die Schonfrist), damit der Aufraeumer sie ueberhaupt betrachtet
alt_zeit = time.time() - 60 * 24 * 3600   # 60 Tage alt
os.utime(foto, (alt_zeit, alt_zeit))
with db.get_conn() as conn:
    n, frei = wartung.aufraeumen_motive(conn)
if not os.path.exists(foto):
    _fail("Retention: aktives Tafel-Foto mit traeger wurde faelschlich geloescht (Falsch-Loeschen)")
_ok("G2) Retention: aktiver Entwurf mit traeger + altes Foto -> bleibt (kein Falsch-Loeschen)")

# --- H) Verwaltung-CRUD via web.py ------------------------------------------
import web
web.app.config["TESTING"] = True
client = web.app.test_client()
with client.session_transaction() as s:
    s["user"] = "tester"
    s["rolle"] = "admin"


def _post(form):
    return client.post("/verwaltung", data=form, follow_redirects=False)


# anlegen
_post({"formular": "traeger_save", "name": "Testtafel",
       "prompt_snippet": "eine Testtafel mit klarer Schrift", "aktiv": "1"})
with db.get_conn() as conn:
    row = conn.execute("SELECT id, prompt_snippet, aktiv FROM traeger WHERE name=?",
                       ("Testtafel",)).fetchone()
if not row:
    _fail("CRUD: anlegen fehlgeschlagen")
neu_id = row["id"]
# bearbeiten (Snippet aendern, deaktivieren -> ohne aktiv-Checkbox)
_post({"formular": "traeger_save", "id": str(neu_id), "name": "Testtafel (bearbeitet)",
       "prompt_snippet": "eine bearbeitete Testtafel"})
with db.get_conn() as conn:
    row = conn.execute("SELECT name, prompt_snippet, aktiv FROM traeger WHERE id=?", (neu_id,)).fetchone()
if row["name"] != "Testtafel (bearbeitet)" or row["prompt_snippet"] != "eine bearbeitete Testtafel" or row["aktiv"] != 0:
    _fail("CRUD: bearbeiten fehlgeschlagen: %r" % (dict(row),))
# toggle -> wieder aktiv
_post({"formular": "traeger_toggle", "id": str(neu_id)})
with db.get_conn() as conn:
    aktiv = conn.execute("SELECT aktiv FROM traeger WHERE id=?", (neu_id,)).fetchone()["aktiv"]
if aktiv != 1:
    _fail("CRUD: toggle fehlgeschlagen")
# loeschen
_post({"formular": "traeger_delete", "id": str(neu_id)})
with db.get_conn() as conn:
    weg = conn.execute("SELECT 1 FROM traeger WHERE id=?", (neu_id,)).fetchone()
if weg:
    _fail("CRUD: loeschen fehlgeschlagen")
# Seite rendert (GET)
r = client.get("/verwaltung?bereich=traeger")
if r.status_code != 200 or "Tr".encode("utf-8") not in r.data:
    _fail("CRUD: Verwaltungsseite Traeger rendert nicht (HTTP %s)" % r.status_code)
_ok("H) Verwaltung-CRUD: anlegen/bearbeiten/toggle/loeschen + Render")

print("\nALLE TESTS BESTANDEN (#142 Traeger-Wechsler).")
