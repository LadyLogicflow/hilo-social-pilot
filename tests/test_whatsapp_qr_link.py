"""Tests fuer den login-freien, 48h gueltigen WhatsApp-QR-Link pro Beratungsstelle (#10069,
catrin 08.10.2026)."""
import os, tempfile, shutil
from datetime import datetime, timedelta

import pytest

import db
import web


@pytest.fixture
def setup():
    tmp_dir = tempfile.mkdtemp(prefix="hilo-test-qrlink-")
    original_db_path = db.DB_PATH
    db.DB_PATH = os.path.join(tmp_dir, "test.db")
    db.init_db()

    with web.get_conn() as conn:
        conn.execute(
            "INSERT INTO beratungsstellen(name, ort, aktiv) VALUES (?,?,1)",
            ("Teststelle QR", "Teststadt"))
        stelle_id = conn.execute(
            "SELECT id FROM beratungsstellen WHERE name=?", ("Teststelle QR",)).fetchone()["id"]

    web.app.config["TESTING"] = True
    admin_client = web.app.test_client()
    with admin_client.session_transaction() as sess:
        sess["user"] = "test-admin"
        sess["rolle"] = "admin"

    anon_client = web.app.test_client()  # KEIN Login -- genau der zu testende Fall

    yield stelle_id, admin_client, anon_client

    db.DB_PATH = original_db_path
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_qr_link_erzeugen_erfordert_login(setup):
    stelle_id, admin_client, anon_client = setup
    r = anon_client.post("/whatsapp/qr-link/%d" % stelle_id)
    # login_required leitet auf /login um, erzeugt KEINEN Token
    assert r.status_code in (302, 401, 403)
    with web.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM wa_qr_links").fetchone()["c"]
    assert count == 0


def test_qr_link_erzeugen_legt_token_an(setup):
    stelle_id, admin_client, anon_client = setup
    r = admin_client.post("/whatsapp/qr-link/%d" % stelle_id, follow_redirects=False)
    assert r.status_code in (200, 302)
    with web.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM wa_qr_links WHERE stelle_id=?", (stelle_id,)).fetchone()
    assert row is not None
    assert row["laeuft_ab"] > datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def test_oeffentliche_qr_seite_ohne_login_erreichbar(setup):
    stelle_id, admin_client, anon_client = setup
    with web.get_conn() as conn:
        conn.execute(
            "INSERT INTO wa_qr_links(token, stelle_id, laeuft_ab) VALUES (?,?,?)",
            ("gueltiger-token", stelle_id,
             (datetime.utcnow() + timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")))

    r = anon_client.get("/whatsapp/qr/gueltiger-token")
    assert r.status_code == 200
    assert b"Teststelle QR" in r.data


def test_oeffentliche_qr_seite_abgelaufener_token(setup):
    stelle_id, admin_client, anon_client = setup
    with web.get_conn() as conn:
        conn.execute(
            "INSERT INTO wa_qr_links(token, stelle_id, laeuft_ab) VALUES (?,?,?)",
            ("abgelaufener-token", stelle_id,
             (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))

    r = anon_client.get("/whatsapp/qr/abgelaufener-token")
    assert r.status_code == 200
    assert "abgelaufen".encode() in r.data


def test_oeffentliche_qr_seite_unbekannter_token(setup):
    stelle_id, admin_client, anon_client = setup
    r = anon_client.get("/whatsapp/qr/kompletter-unsinn")
    assert r.status_code == 200
    assert "ungültig".encode() in r.data
