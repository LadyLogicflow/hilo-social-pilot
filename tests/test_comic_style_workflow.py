# -*- coding: utf-8 -*-
"""Tests fuer den Comic-Stil-Workflow (Entkopplung Text/Bild + neuer Comic-Stil).

Beweist die VERDRAHTUNG (keine echten externen KI-/Bild-APIs - alles gemockt):

  1. ENTKOPPELN: Die drei Text-Gen-Launcher rufen main.py OHNE '--render' auf; der
     /eigener-Pfad rendert NICHT mehr (bild_pfad bleibt NULL nach der Erzeugung).
  2. /bild-generieren OHNE/leerem bild_stil -> flash "Bitte einen Stil wählen.", bild_pfad NULL.
  3. /bild-generieren mit bild_stil=comic (KI gemockt) -> data['bild_stil']=='comic' im text-JSON,
     Render-Pfad wird aufgerufen, bild_pfad gesetzt.
  4. ensure_comic_bild: der an erzeuge_bild uebergebene Prompt enthaelt STIL_A_BLOCK UND die Szene
     (+ FINANZAMT_BLOCK nur bei finanzamt_figur True).
  5. stilwahl: STILE enthaelt "comic"; aktiver_stil({'bild_stil':'comic'})=="comic".
  6. /entwuerfe und /pool HTML: Optionen Comic/Tafel/Kreativ vorhanden; 'selected' NUR auf der
     leeren "– Stil wählen –"-Option (keine echte Vorauswahl).

Ausfuehrung (HILO_DATA_DIR VOR dem Import setzen):
  HILO_DATA_DIR=/tmp/comic-XYZ BELEGSORT_SKIP_BACKEND=1 \
    /workspace/.hvenv/bin/python tests/test_comic_style_workflow.py
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import web
import stilwahl
import bildmotiv
import textgen
import bildgen


_PASS = []


def _fail(msg):
    print("FEHLGESCHLAGEN:", msg)
    sys.exit(1)


def _ok(msg):
    _PASS.append(msg)
    print("  OK:", msg)


def _client():
    web.app.config["TESTING"] = True
    web.app.secret_key = web.app.secret_key or "test"
    c = web.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"
        sess["rolle"] = "freigeber"
    return c


def _seed_entwurf(status="entwurf", fields=None):
    payload = json.dumps(fields or {"ueberschrift": "Test-Beitrag", "slogan": "",
                                    "captions": {"facebook": "Text"}, "caption": "Text"},
                         ensure_ascii=False)
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO entwuerfe(kanal, text, status) VALUES ('facebook',?,?)",
                           (payload, status))
        conn.commit()
        return cur.lastrowid


def _bild_pfad(eid):
    with db.get_conn() as conn:
        return conn.execute("SELECT bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()["bild_pfad"]


def _text_json(eid):
    with db.get_conn() as conn:
        return json.loads(conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()["text"])


# ---------------------------------------------------------------------------
def test_1_entkoppeln_launchers_kein_render():
    """Die drei Launcher spawnen main.py OHNE '--render'."""
    captured = []

    class _FakeProc:
        def poll(self):
            return 0

    def _fake_popen(argv, *a, **k):
        captured.append(list(argv))
        return _FakeProc()

    orig = web.subprocess.Popen
    web.subprocess.Popen = _fake_popen
    try:
        web._start_generation(2)
        web._start_generation_ids([1, 2])
        web._start_regenerate()
    finally:
        web.subprocess.Popen = orig

    if len(captured) != 3:
        _fail("Erwartete 3 Popen-Aufrufe, bekam %d" % len(captured))
    for argv in captured:
        if "--render" in argv:
            _fail("Launcher enthaelt noch '--render': %s" % argv)
    # Sanity: der Text-Gen-Modus ist noch da
    if not any("--generate" in a for a in captured[0]):
        _fail("Erster Launcher ist nicht mehr der Text-Generator: %s" % captured[0])
    _ok("Entkoppeln: kein Launcher uebergibt '--render'")


def test_2_eigener_rendert_nicht():
    """/eigener erzeugt nur Text; render_drafts wird NICHT aufgerufen, bild_pfad bleibt NULL."""
    render_called = {"n": 0}

    def _fake_generate(thema, kanal=None):
        return {"ueberschrift": "Eigenes Thema", "captions": {"facebook": "x"}, "caption": "x",
                "szene_motiv": "eine ruhige Szene", "bullets": []}

    def _fake_render_drafts():
        render_called["n"] += 1
        return 0

    orig_gen = textgen.generate
    orig_rd = bildgen.render_drafts
    textgen.generate = _fake_generate
    bildgen.render_drafts = _fake_render_drafts
    try:
        client = _client()
        # Datum sicher in der Zukunft
        import datetime
        datum = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        r = client.post("/eigener", data={"thema": "Kinderbetreuungskosten", "datum": datum},
                        follow_redirects=False)
        if r.status_code not in (302, 303):
            _fail("/eigener: erwarteter Redirect, bekam HTTP %d" % r.status_code)
    finally:
        textgen.generate = orig_gen
        bildgen.render_drafts = orig_rd

    if render_called["n"] != 0:
        _fail("/eigener hat render_drafts aufgerufen (Bild sollte entkoppelt sein)")
    # Der neu erzeugte Entwurf (juengste ID) muss bild_pfad NULL haben
    with db.get_conn() as conn:
        row = conn.execute("SELECT id, bild_pfad FROM entwuerfe WHERE status='entwurf' "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        _fail("/eigener hat keinen Entwurf angelegt")
    if row["bild_pfad"] not in (None, ""):
        _fail("/eigener: bild_pfad ist nicht NULL (%r)" % row["bild_pfad"])
    _ok("Entkoppeln: /eigener rendert nicht, bild_pfad bleibt NULL")


def test_3_bild_generieren_ohne_stil():
    """POST /bild-generieren ohne bild_stil -> flash, bild_pfad bleibt NULL."""
    eid = _seed_entwurf()
    client = _client()
    r = client.post("/bild-generieren/%d" % eid, data={"zurueck": "entwuerfe"},
                    follow_redirects=True)
    body = r.get_data(as_text=True)
    if "Bitte einen Stil wählen." not in body:
        _fail("Erwartete Flash 'Bitte einen Stil wählen.' fehlt")
    if _bild_pfad(eid) not in (None, ""):
        _fail("bild_pfad wurde trotz fehlendem Stil gesetzt")
    # auch explizit leerer Wert
    r2 = client.post("/bild-generieren/%d" % eid, data={"bild_stil": "", "zurueck": "pool"},
                     follow_redirects=True)
    if "Bitte einen Stil wählen." not in r2.get_data(as_text=True):
        _fail("Leerer bild_stil: Flash fehlt")
    if _bild_pfad(eid) not in (None, ""):
        _fail("bild_pfad gesetzt bei leerem bild_stil")
    _ok("/bild-generieren ohne/leerem Stil: Flash + bild_pfad NULL")


def test_4_bild_generieren_comic():
    """POST /bild-generieren mit comic (KI gemockt): bild_stil persistiert, render aufgerufen,
    bild_pfad gesetzt."""
    eid = _seed_entwurf()
    calls = {"comic_brief": 0, "render": 0, "ensure_photo": 0}

    def _fake_comic_brief(data, client=None):
        calls["comic_brief"] += 1
        data["comic_brief"] = {"stimmung": "positiv", "szene": "Familie am Tisch",
                               "hook": "", "finanzamt_figur": False}
        return data

    def _fake_ensure_photo(fields):
        calls["ensure_photo"] += 1
        return None   # kein echtes Foto noetig, render ist gemockt

    def _fake_render(fields, photo, slogan, out_path, portrait=None):
        calls["render"] += 1
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(b"PNG")
        return out_path

    orig_cb = textgen.comic_brief
    orig_ep = bildmotiv.ensure_photo_fuer
    orig_rn = bildgen.render
    textgen.comic_brief = _fake_comic_brief
    bildmotiv.ensure_photo_fuer = _fake_ensure_photo
    bildgen.render = _fake_render
    try:
        client = _client()
        r = client.post("/bild-generieren/%d" % eid,
                        data={"bild_stil": "comic", "zurueck": "entwuerfe"},
                        follow_redirects=True)
        if r.status_code != 200:
            _fail("/bild-generieren comic: HTTP %d" % r.status_code)
    finally:
        textgen.comic_brief = orig_cb
        bildmotiv.ensure_photo_fuer = orig_ep
        bildgen.render = orig_rn

    if calls["comic_brief"] != 1:
        _fail("comic_brief wurde nicht (genau einmal) aufgerufen: %d" % calls["comic_brief"])
    if calls["render"] != 1:
        _fail("bildgen.render wurde nicht aufgerufen: %d" % calls["render"])
    data = _text_json(eid)
    if data.get("bild_stil") != "comic":
        _fail("bild_stil nicht als 'comic' persistiert: %r" % data.get("bild_stil"))
    if not isinstance(data.get("comic_brief"), dict):
        _fail("comic_brief nicht im text-JSON persistiert")
    bp = _bild_pfad(eid)
    if not bp or not os.path.exists(bp):
        _fail("bild_pfad nicht gesetzt/Datei fehlt: %r" % bp)
    _ok("/bild-generieren comic: bild_stil persistiert, render aufgerufen, bild_pfad gesetzt")


def test_5_ensure_comic_bild_prompt():
    """ensure_comic_bild uebergibt STIL_A_BLOCK + Szene (+ FINANZAMT_BLOCK nur bei finanzamt_figur)."""
    captured = {"prompt": None}

    def _fake_erzeuge(prompt, tool=None):
        captured["prompt"] = prompt
        return b"PNGDATA"

    orig = bildmotiv.erzeuge_bild
    bildmotiv.erzeuge_bild = _fake_erzeuge
    try:
        # a) MIT Finanzamt-Figur
        fields = {"ueberschrift": "Bescheid abgelehnt",
                  "comic_brief": {"stimmung": "humor", "szene": "Buerger staunt ueber Post",
                                  "hook": "Aha!", "finanzamt_figur": True}}
        path = bildmotiv.ensure_comic_bild(fields)
        p = captured["prompt"]
        if p is None:
            _fail("ensure_comic_bild hat erzeuge_bild nicht aufgerufen")
        if bildmotiv.STIL_A_BLOCK not in p:
            _fail("Prompt enthaelt STIL_A_BLOCK nicht")
        if "Buerger staunt ueber Post" not in p:
            _fail("Prompt enthaelt die Szene nicht")
        if bildmotiv.FINANZAMT_BLOCK not in p:
            _fail("Prompt enthaelt FINANZAMT_BLOCK nicht (obwohl finanzamt_figur True)")
        if "Aha!" not in p:
            _fail("Prompt enthaelt den Hook nicht")
        if not path or not os.path.exists(path):
            _fail("ensure_comic_bild lieferte keinen gueltigen Cache-Pfad")

        # b) OHNE Finanzamt-Figur -> KEIN FINANZAMT_BLOCK
        captured["prompt"] = None
        fields2 = {"ueberschrift": "Pauschale nutzen",
                   "comic_brief": {"stimmung": "positiv", "szene": "Paar freut sich",
                                   "hook": "", "finanzamt_figur": False}}
        bildmotiv.ensure_comic_bild(fields2)
        p2 = captured["prompt"]
        if bildmotiv.STIL_A_BLOCK not in p2 or "Paar freut sich" not in p2:
            _fail("Prompt (ohne Finanzamt) unvollstaendig")
        if bildmotiv.FINANZAMT_BLOCK in p2:
            _fail("FINANZAMT_BLOCK erscheint, obwohl finanzamt_figur False")
    finally:
        bildmotiv.erzeuge_bild = orig
    _ok("ensure_comic_bild: Prompt = STIL_A_BLOCK + Szene (+ Finanzamt nur wenn gefordert)")


def test_6_stilwahl_comic():
    if "comic" not in stilwahl.STILE:
        _fail("stilwahl.STILE enthaelt 'comic' nicht: %r" % (stilwahl.STILE,))
    if stilwahl.aktiver_stil({"bild_stil": "comic"}) != "comic":
        _fail("aktiver_stil({'bild_stil':'comic'}) != 'comic'")
    # standard bleibt erhalten (Rueckwaertskompat)
    if "standard" not in stilwahl.STILE:
        _fail("'standard' wurde aus STILE entfernt")
    _ok("stilwahl: 'comic' registriert, aktiver_stil erkennt ihn, 'standard' erhalten")


def _assert_picker(body, seite):
    for val, label in (("comic", "Comic"), ("ki_tafel", "Tafel"), ("kreativ", "Kreativ")):
        if ('value="%s">%s' % (val, label)) not in body:
            _fail("%s: Option %s/%s fehlt" % (seite, val, label))
        # keine echte Vorauswahl: die Stil-Option traegt kein 'selected'
        if ('value="%s" selected' % val) in body or ('value="%s"  selected' % val) in body:
            _fail("%s: Stil-Option %s ist faelschlich vorausgewaehlt" % (seite, val))
    if '<option value="" disabled selected>' not in body:
        _fail("%s: leere '– Stil wählen –'-Option ist nicht 'selected'" % seite)


def test_7_entwuerfe_und_pool_html():
    # /entwuerfe
    _seed_entwurf()
    client = _client()
    r = client.get("/entwuerfe")
    if r.status_code != 200:
        _fail("/entwuerfe HTTP %d" % r.status_code)
    _assert_picker(r.get_data(as_text=True), "/entwuerfe")
    _ok("/entwuerfe: Stil-Picker mit Comic/Tafel/Kreativ, keine Vorauswahl")

    # /pool: einen Pool-Beitrag anlegen
    peid = _seed_entwurf(status="pool")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO pool(entwurf_id, aktiv) VALUES (?,1)", (peid,))
        conn.commit()
    r2 = client.get("/pool")
    if r2.status_code != 200:
        _fail("/pool HTTP %d" % r2.status_code)
    _assert_picker(r2.get_data(as_text=True), "/pool")
    _ok("/pool: Stil-Picker mit Comic/Tafel/Kreativ, keine Vorauswahl")


class _FakePublish:
    """Minimaler Publish-Stub: zeichnet die an publish_facebook uebergebenen Bilder auf, damit der
    Test beweisen kann, dass NIE ein None/NULL-Pfad an den echten Post geht."""
    def __init__(self):
        self.fb_bilder = []       # jeder an publish_facebook uebergebene Bild-Pfad
        self.fb_carousel = []

    def publish_facebook(self, seite, bild, caption, place=None):
        self.fb_bilder.append(bild)
        return True, "fbpost_1"

    def publish_facebook_carousel(self, seite, bilder, caption, place=None):
        self.fb_carousel.append(list(bilder))
        return True, "fbcar_1"

    def comment_facebook(self, *a, **k):
        return True, "comment_1"


def test_8_publish_guard_no_stelle_nie_bildlos_und_stelle_bleibt_null():
    """Fix 1/2: (a) no-stelle Einzelbild-Feed -> publish_facebook bekommt NIE None (entweder ein
    gerendertes Bild oder ok=False 'Kein Bild vorhanden'); (b) per-STELLE veroeffentlicht ->
    entwuerfe.bild_pfad bleibt DANACH NULL (kein generisches 'Notbild' persistiert)."""
    import personalisierung

    # --- (a) no-stelle Einzelbild-Feed: bild_pfad NULL, Render gemockt -> Post bekommt echtes Bild ---
    eid = _seed_entwurf(status="freigegeben",
                        fields={"ueberschrift": "Ohne Stelle", "captions": {"facebook": "fb"},
                                "caption": "fb", "slogan": "", "bullets": []})
    rendered = {"n": 0}

    def _fake_ensure_photo(fields):
        return None

    def _fake_render(fields, photo, slogan, out_path, portrait=None):
        rendered["n"] += 1
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(b"PNG")
        return out_path

    orig_ep = bildmotiv.ensure_photo_fuer
    orig_rn = bildgen.render
    bildmotiv.ensure_photo_fuer = _fake_ensure_photo
    bildgen.render = _fake_render
    fake_pub = _FakePublish()
    try:
        with db.get_conn() as conn:
            e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
            f = json.loads(e["text"])
            web._veroeffentliche_ziel(conn, e, eid, f, "einzelbild", "einzelbild", "facebook",
                                      None, "PAGE_1", "tester", fake_pub, story=False, story_fb=False)
    finally:
        bildmotiv.ensure_photo_fuer = orig_ep
        bildgen.render = orig_rn

    if not fake_pub.fb_bilder:
        _fail("(a) publish_facebook wurde nicht aufgerufen")
    for b in fake_pub.fb_bilder:
        if b is None or not (isinstance(b, str) and os.path.exists(b)):
            _fail("(a) publish_facebook bekam ein NULL/nicht-existentes Bild: %r" % b)
    if rendered["n"] < 1:
        _fail("(a) On-demand-Render wurde im no-stelle-Feed nicht ausgeloest")
    _ok("(a) no-stelle Feed: publish_facebook bekommt nie ein NULL-Bild (on-demand gerendert)")

    # --- (b) per-STELLE: bild_pfad NULL bleibt NULL (kein generisches Bild persistiert) ---
    eid2 = _seed_entwurf(status="freigegeben",
                         fields={"ueberschrift": "Mit Stelle", "captions": {"facebook": "fb"},
                                 "caption": "fb", "slogan": "", "bullets": []})
    with db.get_conn() as conn:
        conn.execute("INSERT INTO beratungsstellen(name, ort, fb_seite, buchungs_url, aktiv) "
                     "VALUES ('Teststelle', 'Testort', 'fbseite_1', '', 1)")
        conn.commit()
        stelle = conn.execute("SELECT * FROM beratungsstellen WHERE name='Teststelle'").fetchone()

    def _fake_render_fuer_stelle(fields, st, out, *a, **k):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(b"PNG")
        return "portrait", out

    def _fake_caption_fuer_stelle(fields, st, k):
        return "personalisierter Text"

    def _fake_buchungslink(st):
        return ""

    # Guard-Wachhund: _ensure_bild_pfad darf im Stelle-Pfad NICHT aufgerufen werden.
    guard = {"calls": 0}
    orig_ensure = web._ensure_bild_pfad

    def _spy_ensure(conn, eid_, fields):
        guard["calls"] += 1
        return orig_ensure(conn, eid_, fields)

    orig_rfs = personalisierung.render_fuer_stelle
    orig_cfs = personalisierung.caption_fuer_stelle
    orig_bl = personalisierung.buchungslink
    personalisierung.render_fuer_stelle = _fake_render_fuer_stelle
    personalisierung.caption_fuer_stelle = _fake_caption_fuer_stelle
    personalisierung.buchungslink = _fake_buchungslink
    web._ensure_bild_pfad = _spy_ensure
    fake_pub2 = _FakePublish()
    try:
        with db.get_conn() as conn:
            e2 = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid2,)).fetchone()
            f2 = json.loads(e2["text"])
            web._veroeffentliche_ziel(conn, e2, eid2, f2, "einzelbild", "einzelbild", "facebook",
                                      stelle, None, "tester", fake_pub2, story=False, story_fb=False)
    finally:
        personalisierung.render_fuer_stelle = orig_rfs
        personalisierung.caption_fuer_stelle = orig_cfs
        personalisierung.buchungslink = orig_bl
        web._ensure_bild_pfad = orig_ensure

    if guard["calls"] != 0:
        _fail("(b) _ensure_bild_pfad wurde im Stelle-Pfad aufgerufen (darf nicht)")
    if _bild_pfad(eid2) not in (None, ""):
        _fail("(b) bild_pfad wurde im Stelle-Pfad gesetzt (generisches Notbild persistiert): %r"
              % _bild_pfad(eid2))
    if not fake_pub2.fb_bilder:
        _fail("(b) publish_facebook (Stelle) wurde nicht aufgerufen")
    _ok("(b) per-Stelle Veroeffentlichung: bild_pfad bleibt NULL, kein _ensure_bild_pfad")


def main():
    db.init_db()
    test_1_entkoppeln_launchers_kein_render()
    test_2_eigener_rendert_nicht()
    test_3_bild_generieren_ohne_stil()
    test_4_bild_generieren_comic()
    test_5_ensure_comic_bild_prompt()
    test_6_stilwahl_comic()
    test_7_entwuerfe_und_pool_html()
    test_8_publish_guard_no_stelle_nie_bildlos_und_stelle_bleibt_null()
    print("\nALLE TESTS BESTANDEN (%d Checks)." % len(_PASS))


if __name__ == "__main__":
    main()
