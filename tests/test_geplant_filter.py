"""Regressionstest: /geplant kann nach Beratungsstelle gefiltert werden (catrin, 12.10.2026,
#10374) -- Dropdown ueber Query-Parameter ?stelle=<ziel-label>."""
import os, tempfile, shutil

import pytest

import db
import web


@pytest.fixture
def client():
    tmp_dir = tempfile.mkdtemp(prefix="hilo-test-geplant-")
    original_db_path = db.DB_PATH
    db.DB_PATH = os.path.join(tmp_dir, "test.db")
    db.init_db()

    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(id,name,ort,aktiv) VALUES (1,'HILO Neuss','Neuss',1)")
        conn.execute("INSERT INTO beratungsstellen(id,name,ort,aktiv) VALUES (2,'HILO Tuebingen','Tuebingen',1)")
        conn.execute("INSERT INTO entwuerfe(id,text) VALUES (1,'{\"ueberschrift\":\"Beitrag Neuss\"}')")
        conn.execute("INSERT INTO entwuerfe(id,text) VALUES (2,'{\"ueberschrift\":\"Beitrag Tuebingen\"}')")
        conn.execute(
            "INSERT INTO geplante_posts(id,entwurf_id,stelle_id,kanal,format,geplant_am,status) "
            "VALUES (1,1,1,'facebook','einzelbild','2026-10-20T10:00:00','geplant')")
        conn.execute(
            "INSERT INTO geplante_posts(id,entwurf_id,stelle_id,kanal,format,geplant_am,status) "
            "VALUES (2,2,2,'facebook','einzelbild','2026-10-20T11:00:00','geplant')")

    web.app.config["TESTING"] = True
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "test-admin"
        sess["rolle"] = "admin"
    yield c

    db.DB_PATH = original_db_path
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_ungefiltert_zeigt_alle_beratungsstellen(client):
    r = client.get("/geplant")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Beitrag Neuss" in body
    assert "Beitrag Tuebingen" in body
    assert "name=stelle" in body


def test_filter_zeigt_nur_gewaehlte_beratungsstelle(client):
    r = client.get("/geplant?stelle=HILO+Neuss+%C2%B7+Neuss")
    body = r.get_data(as_text=True)
    assert "Beitrag Neuss" in body
    assert "Beitrag Tuebingen" not in body


def test_filter_ohne_treffer_zeigt_hinweis(client):
    r = client.get("/geplant?stelle=Unbekannte+Stelle")
    body = r.get_data(as_text=True)
    assert "Keine geplanten Ver" in body
    assert "Unbekannte Stelle" in body
