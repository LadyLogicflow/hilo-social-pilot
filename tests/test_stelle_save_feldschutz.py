"""Regressionstest: stelle_save darf bestehende Werte nicht loeschen, wenn ein Formularfeld
leer gelassen wird (Bug gefunden 08.10.2026, catrin live auf ShareNext).

db.DB_PATH wird in der Fixture direkt gepatcht (nicht nur die HILO_DATA_DIR-Umgebungsvariable),
weil config.DB_PATH eine Modul-Import-Zeit-Konstante ist -- wird db/web bereits von einer
anderen Testdatei vor dieser hier importiert (Reihenfolge nicht garantiert), wirkt ein spaeteres
os.environ-Setzen nicht mehr. Ein direkter Patch von db.DB_PATH ist unabhaengig davon sicher."""
import os, tempfile, shutil

import pytest

import db
import web


@pytest.fixture
def client():
    tmp_dir = tempfile.mkdtemp(prefix="hilo-test-stelle-")
    original_db_path = db.DB_PATH
    db.DB_PATH = os.path.join(tmp_dir, "test.db")
    db.init_db()

    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "test-admin"
        sess["rolle"] = "admin"
    yield c

    db.DB_PATH = original_db_path
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_stelle_save_neuanlage_setzt_alle_felder(client):
    r = client.post("/verwaltung?bereich=stellen", data={
        "formular": "stelle_save", "name": "Teststelle", "ort": "Teststadt",
        "leitung": "Erika Mustermann", "fb_seite": "123456",
        "homepage_url": "https://teststelle.de", "buchungs_url": "https://teststelle.de/termin",
    })
    assert r.status_code in (200, 302)

    row = web.get_conn().execute(
        "SELECT * FROM beratungsstellen WHERE name=?", ("Teststelle",)).fetchone()
    assert row["homepage_url"] == "https://teststelle.de"
    assert row["buchungs_url"] == "https://teststelle.de/termin"
    assert row["leitung"] == "Erika Mustermann"
    assert row["fb_seite"] == "123456"


def test_stelle_save_leeres_feld_behaelt_bestehenden_wert(client):
    client.post("/verwaltung?bereich=stellen", data={
        "formular": "stelle_save", "name": "Teststelle", "ort": "Teststadt",
        "leitung": "Erika Mustermann", "fb_seite": "123456",
        "homepage_url": "https://teststelle.de", "buchungs_url": "https://teststelle.de/termin",
    })

    r2 = client.post("/verwaltung?bereich=stellen", data={
        "formular": "stelle_save", "name": "Teststelle", "ort": "Teststadt",
        "leitung": "", "fb_seite": "", "homepage_url": "",
        "buchungs_url": "https://teststelle.de/neuer-termin",
    })
    assert r2.status_code in (200, 302)

    row = web.get_conn().execute(
        "SELECT * FROM beratungsstellen WHERE name=?", ("Teststelle",)).fetchone()
    assert row["buchungs_url"] == "https://teststelle.de/neuer-termin"
    assert row["homepage_url"] == "https://teststelle.de"
    assert row["leitung"] == "Erika Mustermann"
    assert row["fb_seite"] == "123456"
