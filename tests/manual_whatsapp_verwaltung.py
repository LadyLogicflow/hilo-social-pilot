# -*- coding: utf-8 -*-
"""Tests fuer die per-Stelle WhatsApp-Verbindung DIREKT in der Beratungsstellen-Verwaltung.

Beweist die VERDRAHTUNG (KEIN echter Node-/Baileys-Dienst, kein Netz - _wa_call ist gemockt):

  1. /verwaltung?bereich=stellen (admin) rendert je aktiver Stelle den WhatsApp-Status:
     connected -> "verbunden", qr -> QR-Bild + "QR bereit".
  2. Faellt der WhatsApp-Dienst aus (_wa_call liefert Fehler), bricht die Verwaltung NICHT
     (Status 200) und zeigt den dezenten Hinweis "WhatsApp-Dienst nicht erreichbar".
  3. Auto-Refresh: bei state=qr ist genau dann <meta http-equiv=refresh> gesetzt.
  4. whatsapp_connect / whatsapp_logout mit hidden zurueck=verwaltung -> Redirect zurueck in die
     Beratungsstellen-Verwaltung; ohne/anders -> weiter zur bestehenden /whatsapp-Uebersicht.

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/wa-verw-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/manual_whatsapp_verwaltung.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web


_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


def _client(rolle="admin", login=True):
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    if login:
        with c.session_transaction() as sess:
            sess["user"] = "tester"
            sess["rolle"] = rolle
    return c


def _seed_stelle(name, aktiv=1):
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO beratungsstellen(name, ort, aktiv) VALUES (?,?,?)",
            (name, "Teststadt", aktiv))
        conn.commit()
        return cur.lastrowid


class _PatchWaCall:
    """Kontextmanager: ersetzt web._wa_call durch eine Fake-Funktion (daten, fehler)."""

    def __init__(self, fake):
        self.fake = fake
        self.orig = None

    def __enter__(self):
        self.orig = web._wa_call
        web._wa_call = self.fake
        return self

    def __exit__(self, *a):
        web._wa_call = self.orig


# ---------------------------------------------------------------------------
def test_1_verwaltung_zeigt_status_pro_stelle():
    """connected + qr: Verwaltung zeigt je Stelle den passenden Status, QR-Bild bei qr."""
    sid_conn = _seed_stelle("Stelle-Connected")
    sid_qr = _seed_stelle("Stelle-QR")

    def _fake(path, method="GET", payload=None, timeout=6, session=None):
        if int(session) == sid_conn:
            return {"state": "connected", "qr": None, "me": "4915100000000",
                    "error": None, "contacts": 7}, None
        return {"state": "qr", "qr": "data:image/png;base64,ABC123",
                "me": None, "error": None, "contacts": 0}, None

    with _PatchWaCall(_fake):
        c = _client(rolle="admin")
        resp = c.get("/verwaltung?bereich=stellen")
    if resp.status_code != 200:
        _fail("Verwaltung/stellen Status %s" % resp.status_code)
    body = resp.get_data(as_text=True)
    if "verbunden" not in body:
        _fail("Status 'verbunden' fehlt fuer die connected-Stelle")
    if "QR bereit" not in body or "data:image/png;base64,ABC123" not in body:
        _fail("QR-Status/QR-Bild fehlt fuer die qr-Stelle")
    # Auto-Refresh muss bei einem ausstehenden QR aktiv sein.
    if "http-equiv=refresh" not in body:
        _fail("Auto-Refresh (meta refresh) fehlt, obwohl eine Stelle im QR-Zustand ist")
    # Ruecksp-Marker fuer die Verwaltung muss in den Formularen stecken.
    if 'name=zurueck value=verwaltung' not in body:
        _fail("hidden zurueck=verwaltung fehlt in den Verwaltungs-WhatsApp-Formularen")
    _ok("Verwaltung/stellen: connected+qr korrekt, QR-Bild, Auto-Refresh, zurueck-Marker")


def test_2_dienst_aus_bricht_nicht():
    """_wa_call-Fehler: Verwaltung bleibt 200 und zeigt den dezenten Nicht-erreichbar-Hinweis."""
    _seed_stelle("Stelle-Dienst-Aus")

    def _fake(path, method="GET", payload=None, timeout=6, session=None):
        return None, "Dienst nicht erreichbar (Connection refused)"

    with _PatchWaCall(_fake):
        c = _client(rolle="admin")
        resp = c.get("/verwaltung?bereich=stellen")
    if resp.status_code != 200:
        _fail("Verwaltung bricht bei Dienst-Ausfall (Status %s statt 200)" % resp.status_code)
    body = resp.get_data(as_text=True)
    if "WhatsApp-Dienst nicht erreichbar" not in body:
        _fail("Dezenter Hinweis 'WhatsApp-Dienst nicht erreichbar' fehlt")
    # Kein Refresh, wenn nichts im QR-/init-/closed-Zustand pending ist.
    if "http-equiv=refresh" in body:
        _fail("Auto-Refresh faelschlich aktiv, obwohl keine Stelle pending ist")
    _ok("Dienst aus: Verwaltung bleibt 200 mit Hinweis, kein Auto-Refresh")


def test_3_wa_call_exception_bricht_nicht():
    """Wirft _wa_call eine Exception, faengt die Verwaltung sie ab (Status 200)."""
    _seed_stelle("Stelle-Exception")

    def _fake(path, method="GET", payload=None, timeout=6, session=None):
        raise RuntimeError("Boom im WhatsApp-Client")

    with _PatchWaCall(_fake):
        c = _client(rolle="admin")
        resp = c.get("/verwaltung?bereich=stellen")
    if resp.status_code != 200:
        _fail("Verwaltung bricht bei _wa_call-Exception (Status %s)" % resp.status_code)
    if "WhatsApp-Dienst nicht erreichbar" not in resp.get_data(as_text=True):
        _fail("Hinweis fehlt trotz _wa_call-Exception")
    _ok("_wa_call-Exception: Verwaltung robust (200 + Hinweis)")


def test_4_redirect_zurueck_verwaltung():
    """connect/logout mit zurueck=verwaltung -> Verwaltung; ohne/anders -> /whatsapp."""
    sid = _seed_stelle("Stelle-Redirect")

    def _fake(path, method="GET", payload=None, timeout=6, session=None):
        return {"state": "init"}, None

    with _PatchWaCall(_fake):
        c = _client(rolle="admin")
        # a) connect mit zurueck=verwaltung
        r = c.post("/whatsapp/connect/%d" % sid, data={"zurueck": "verwaltung"})
        if r.status_code != 302 or "bereich=stellen" not in r.headers.get("Location", ""):
            _fail("connect zurueck=verwaltung -> falsches Ziel: %s / %s"
                  % (r.status_code, r.headers.get("Location")))
        # b) logout mit zurueck=verwaltung
        r = c.post("/whatsapp/logout/%d" % sid, data={"zurueck": "verwaltung"})
        if r.status_code != 302 or "bereich=stellen" not in r.headers.get("Location", ""):
            _fail("logout zurueck=verwaltung -> falsches Ziel: %s / %s"
                  % (r.status_code, r.headers.get("Location")))
        # c) connect OHNE zurueck -> /whatsapp
        r = c.post("/whatsapp/connect/%d" % sid, data={})
        loc = r.headers.get("Location", "")
        if r.status_code != 302 or not loc.endswith("/whatsapp") or "bereich=stellen" in loc:
            _fail("connect ohne zurueck -> nicht /whatsapp: %s / %s" % (r.status_code, loc))
        # d) logout mit anderem zurueck-Wert -> /whatsapp
        r = c.post("/whatsapp/logout/%d" % sid, data={"zurueck": "sonstwo"})
        loc = r.headers.get("Location", "")
        if r.status_code != 302 or not loc.endswith("/whatsapp"):
            _fail("logout mit fremdem zurueck -> nicht /whatsapp: %s / %s" % (r.status_code, loc))
    _ok("connect/logout: zurueck=verwaltung -> Verwaltung, sonst -> /whatsapp")


def test_5_whatsapp_uebersicht_unveraendert():
    """Die bestehende /whatsapp-Uebersicht rendert weiterhin (200)."""
    _seed_stelle("Stelle-Uebersicht")

    def _fake(path, method="GET", payload=None, timeout=6, session=None):
        return {"state": "nicht_verbunden", "qr": None, "me": None,
                "error": None, "contacts": 0}, None

    with _PatchWaCall(_fake):
        c = _client(rolle="admin")
        resp = c.get("/whatsapp")
    if resp.status_code != 200:
        _fail("/whatsapp-Uebersicht Status %s" % resp.status_code)
    _ok("/whatsapp-Uebersicht bleibt funktionsfaehig (200)")


def main():
    db.init_db()
    test_1_verwaltung_zeigt_status_pro_stelle()
    test_2_dienst_aus_bricht_nicht()
    test_3_wa_call_exception_bricht_nicht()
    test_4_redirect_zurueck_verwaltung()
    test_5_whatsapp_uebersicht_unveraendert()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
