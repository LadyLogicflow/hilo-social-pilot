# -*- coding: utf-8 -*-
"""HISOME - HILO Social Media Tool. Kachel-Dashboard (Flask):
Startseite mit Workflow-Kacheln, Stufe 1 (Themenauswahl), Texte/Bilder erzeugen,
Stufe 2 (Entwuerfe freigeben), Einplanung/Veroeffentlichung, eigene Quellen,
Admin-Verwaltung (Benutzer + Beratungsstellen). Taeglicher Radar-Lauf um 7 Uhr."""
import json, os, time, sys, subprocess, threading, functools, logging
from flask import (Flask, request, redirect, url_for, session, send_file,
                   render_template_string, flash, abort)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from db import get_conn, init_db, audit_log
from secrets_store import get_secret
from config import BASE_DIR, DATA_DIR, WHATSAPP_URL
import textgen, bildgen

app = Flask(__name__)
log = logging.getLogger("hilo.web")

def _flask_secret():
    sk = get_secret("flask_secret") or os.environ.get("HILO_FLASK_SECRET")
    if not sk:
        # einmalig erzeugen und persistent ablegen, damit Sessions Neustarts ueberleben
        import secrets as _secrets
        from secrets_store import set_secret
        sk = _secrets.token_hex(32)
        try:
            set_secret("flask_secret", sk)
        except Exception:
            pass
    return sk

app.secret_key = _flask_secret()
# Upload-Groesse begrenzen (Pi-Speicher schuetzen)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

def _under_portraits(path):
    """True nur, wenn der (aufgeloeste) Pfad innerhalb von DATA_DIR/portraits liegt.
    Schutz davor, dass ein manipulierter DB-Wert eine fremde Datei ausliefert/loescht."""
    try:
        base = os.path.realpath(os.path.join(DATA_DIR, "portraits"))
        rp = os.path.realpath(path)
        return rp == base or rp.startswith(base + os.sep)
    except Exception:
        return False

# --- Facebook-Seiten (gecacht) ---------------------------------------------
_pages_cache = {"ts": 0, "data": None, "err": None}

def _pages(force=False):
    if not force and _pages_cache["data"] is not None and (time.time() - _pages_cache["ts"] < 300):
        return _pages_cache["data"], _pages_cache["err"]
    try:
        import publish
        data = publish.list_pages()
        _pages_cache.update(ts=time.time(), data=data, err=None)
    except Exception as ex:
        _pages_cache.update(ts=time.time(), data=[], err=str(ex))
    return _pages_cache["data"], _pages_cache["err"]

_KANAL_DE = {"facebook": "Facebook", "instagram": "Instagram", "beide": "Facebook + Instagram"}

def _kanal_fuer(prefix, tid):
    """Liest den je Ziel gewaehlten Kanal aus dem Formular (kanal_s<id> bzw. kanal_p<id>).
    Default: facebook. So kann jede Beratungsstelle/Seite einen eigenen Kanal haben."""
    k = (request.form.get("kanal_%s%s" % (prefix, tid)) or "facebook").strip()
    return k if k in ("facebook", "instagram", "beide") else "facebook"

def _format(name, default="einzelbild"):
    """Liest ein Bildformat aus dem Formular (einzelbild|karussell), Default sonst."""
    v = (request.form.get(name) or "").strip()
    return v if v in ("einzelbild", "karussell") else default

_QUELLE_LABELS = {
    "bvl_pm": "BVL-Pressemitteilungen", "bvl_dpa": "BVL / dpa-Themen", "hilo": "HILO-Meldungen",
    "bmf": "BMF (Steuern)", "bfh": "Bundesfinanzhof", "bfh_news": "Bundesfinanzhof News", "haufe": "Haufe",
    "pdf": "Eigenes PDF", "link": "Eigener Link", "eigen": "Eigener Beitrag",
    "anlass": "Anlass-Tage", "wissen": "Wissens-Serie", "frist": "Fristen-Countdown",
}

def _quelle_label(q):
    """Freundlicher Anzeigename fuer einen Quelle-Code (Fallback: Code lesbar gemacht)."""
    return _QUELLE_LABELS.get(q, (q or "Sonstige").replace("_", " ").title())

# --- Auswertung "Was funktioniert" (Insights) -------------------------------
_STREAM_NEWS = {"bvl_pm", "bvl_dpa", "hilo", "bmf", "bfh", "bfh_news", "haufe"}
_WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

def _stream(quelle):
    """Ordnet eine Themen-Quelle einem der Content-Streams zu."""
    m = {"frist": "Fristen-Countdown", "anlass": "Anlass-Tage", "wissen": "Wissens-Serie"}
    if quelle in m:
        return m[quelle]
    if quelle in _STREAM_NEWS:
        return "Radar (News)"
    if quelle in ("pdf", "link", "eigen"):
        return "Eigene Beiträge"
    return "Sonstige"

def _lokal(wann):
    """Wandelt den gespeicherten UTC-Zeitstempel ('YYYY-MM-DD HH:MM:SS') in deutsche Lokalzeit
    (Europe/Berlin, mit Sommerzeit) um, damit Uhrzeit-/Wochentag-Auswertung stimmt. None bei Fehler."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        dt = datetime.strptime(str(wann)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        return None

def _zeitfenster(wann):
    """Grobes Tagesfenster in deutscher Lokalzeit."""
    dt = _lokal(wann)
    if dt is None:
        return None
    h = dt.hour
    if h < 9:
        return "Früh (bis 9 Uhr)"
    if h < 12:
        return "Vormittag (9-12 Uhr)"
    if h < 15:
        return "Mittag (12-15 Uhr)"
    if h < 18:
        return "Nachmittag (15-18 Uhr)"
    return "Abend (ab 18 Uhr)"

def _wochentag(wann):
    dt = _lokal(wann)
    return _WOCHENTAGE[dt.weekday()] if dt is not None else None

def _rang(items, keyfn):
    """Gruppiert Posts nach keyfn und liefert je Gruppe die durchschnittliche Reichweite,
    absteigend sortiert. Leere/None-Schluessel werden uebersprungen."""
    from collections import defaultdict
    g = defaultdict(list)
    for it in items:
        k = keyfn(it)
        if k:
            g[k].append(it["reichweite"])
    rows = [{"label": k, "schnitt": round(sum(v) / len(v)), "anzahl": len(v)}
            for k, v in g.items() if v]
    return sorted(rows, key=lambda x: (-x["schnitt"], x["label"]))

def _insights_aktualisieren():
    """Ruft fuer alle veroeffentlichten Posts mit Plattform-ID die aktuellen Insights ab und
    speichert Reichweite + Interaktionen. Rueckgabe: (aktualisiert, fehlgeschlagen)."""
    import publish
    with get_conn() as conn:
        # seite IS NOT NULL: nur Posts mit hinterlegter Seiten-ID - das Seiten-Token kann die
        # Insights lesen. Alte Posts ohne Seiten-ID werden uebersprungen (kein Fehl-Call).
        rows = conn.execute("SELECT id, kanal, plattform_post_id, seite FROM posts "
                            "WHERE status='veroeffentlicht' AND plattform_post_id IS NOT NULL "
                            "AND plattform_post_id!='' AND seite IS NOT NULL AND seite!=''").fetchall()
    ok, fehler = 0, 0
    for r in rows:
        try:
            reichweite, interakt = publish.post_insights(r["kanal"], r["plattform_post_id"], r["seite"])
            with get_conn() as conn:
                conn.execute("UPDATE posts SET reichweite=?, interaktionen=?, "
                             "insights_am=datetime('now') WHERE id=?", (reichweite, interakt, r["id"]))
                conn.commit()
            ok += 1
        except Exception as ex:
            log.warning("Insights-Abruf fehlgeschlagen (Post %s): %s", r["id"], ex)
            fehler += 1
    return ok, fehler

def _vorschlag_zeit(belegt=(), min_m=7 * 60):
    """Schlaegt eine gestreute Uhrzeit zwischen 07:00 und 19:00 vor (deutsche Zeit), die moeglichst
    nicht mit bereits vergebenen kollidiert - damit die Beitraege individuell gepostet wirken.
    min_m = fruehest moegliche Minute (fuer 'heute' = jetzt + Puffer, damit die Zeit in der Zukunft liegt)."""
    import random
    lo = min(max(7 * 60, min_m), 19 * 60)
    hi = 19 * 60
    if lo > hi:
        lo = hi
    m = lo
    for _ in range(40):
        m = random.randint(lo, hi)
        hhmm = "%02d:%02d" % (m // 60, m % 60)
        if all(abs(m - (int(b[:2]) * 60 + int(b[3:5]))) >= 7 for b in belegt):  # >= 7 Min Abstand
            return hhmm
    return "%02d:%02d" % (m // 60, m % 60)

# --- Hintergrund-Erzeugung als eigener Prozess -----------------------------
_gen = {"proc": None}
_gen_lock = threading.Lock()   # schuetzt Pruefen+Starten gegen Doppelklick/parallele Tabs

def _generation_running():
    p = _gen["proc"]
    return p is not None and p.poll() is None

def _start_generation(anzahl):
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"), "--generate", str(anzahl), "--render"],
        cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)

def _start_generation_ids(ids):
    """Hintergrund-Erzeugung nur fuer die ausgewaehlten Thema-IDs (+ Bilder)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"),
         "--generate-ids", ",".join(str(i) for i in ids), "--render"],
        cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)

def _start_regenerate():
    """Hintergrund: alle offenen Entwuerfe nach aktuellen Vorgaben neu erzeugen (+ Bilder neu)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"), "--regenerate-drafts", "--render"],
        cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)

# --- Taeglicher Radar-Lauf (7 Uhr), als Subprozess -------------------------
def _daily_scheduler():
    import datetime
    marker = os.path.join(DATA_DIR, "last_radar.txt")
    while True:
        try:
            now = datetime.datetime.now()
            heute = now.strftime("%Y-%m-%d")
            last = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else ""
            if now.hour >= 7 and last != heute:
                os.makedirs(DATA_DIR, exist_ok=True)
                logf = open(os.path.join(DATA_DIR, "radar.log"), "a", encoding="utf-8")
                subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "main.py"), "--daily"],
                                 cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
                open(marker, "w", encoding="utf-8").write(heute)
        except Exception:
            pass
        time.sleep(120)

# --- Automatische Veroeffentlichung zur geplanten Uhrzeit (deutsche Pi-Zeit) ----
def _publiziere_geplant(gpid):
    """Veroeffentlicht EINEN faelligen geplanten Post. Claim per status='laeuft' (kein Doppel-Post)."""
    import publish, datetime
    with get_conn() as conn:
        cur = conn.execute("UPDATE geplante_posts SET status='laeuft' WHERE id=? AND status='geplant'", (gpid,))
        conn.commit()
        if cur.rowcount == 0:
            return  # bereits von einem anderen Durchlauf uebernommen
        gp = conn.execute("SELECT * FROM geplante_posts WHERE id=?", (gpid,)).fetchone()
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (gp["entwurf_id"],)).fetchone()
    # Nur FREIGEGEBENE Beitraege automatisch posten (zurueckgezogene/geloeschte NICHT).
    if not e or e["status"] != "freigegeben":
        with get_conn() as conn:
            conn.execute("UPDATE geplante_posts SET status='fehler', info=? WHERE id=?",
                         ("Beitrag nicht mehr freigegeben/vorhanden", gpid)); conn.commit()
        return
    # Verpasst-Schutz: war der Pi laenger aus, NICHT zur falschen Tageszeit nachposten.
    try:
        geplant_dt = datetime.datetime.strptime((gp["geplant_am"] or "")[:16], "%Y-%m-%dT%H:%M")
    except Exception:
        geplant_dt = None
    if geplant_dt and (datetime.datetime.now() - geplant_dt).total_seconds() > 60 * 60:
        with get_conn() as conn:
            conn.execute("UPDATE geplante_posts SET status='fehler', info=? WHERE id=?",
                         ("Zeitpunkt verpasst (>60 Min) – Pi war evtl. aus; bitte neu einplanen", gpid))
            conn.commit()
        return
    try:
        f = json.loads(e["text"])
    except Exception:
        f = {}
    fmt_fb = gp["format_fb"] or gp["format"] or "einzelbild"
    fmt_ig = gp["format_ig"] or gp["format"] or "karussell"
    kanal = gp["kanal"] or "facebook"
    ziel_name = "?"
    with get_conn() as conn:
        stelle = conn.execute("SELECT * FROM beratungsstellen WHERE id=?", (gp["stelle_id"],)).fetchone() \
            if gp["stelle_id"] else None
        try:
            ziel_name, erfolg, ergebnisse = _veroeffentliche_ziel(
                conn, e, gp["entwurf_id"], f, fmt_fb, fmt_ig, kanal, stelle, gp["page_id"], "scheduler", publish)
        except Exception as ex:
            erfolg, ergebnisse = False, [("-", False, str(ex))]
        info = " | ".join("%s: %s" % (k, ("OK" if ok else "Fehler – %s" % i)) for k, ok, i in ergebnisse)
        conn.execute("UPDATE geplante_posts SET status=?, info=? WHERE id=?",
                     ("veroeffentlicht" if erfolg else "fehler", info[:500], gpid))
        offen = conn.execute("SELECT COUNT(*) FROM geplante_posts WHERE entwurf_id=? AND status IN "
                             "('geplant','laeuft')", (gp["entwurf_id"],)).fetchone()[0]
        if erfolg and offen == 0:
            conn.execute("UPDATE entwuerfe SET status='veroeffentlicht' WHERE id=? AND status='freigegeben'",
                         (gp["entwurf_id"],))
        conn.commit()
    log.info("Auto-Veroeffentlichung Beitrag %s (%s): %s", gp["entwurf_id"], ziel_name, info)

def _publish_scheduler():
    """Prueft minuetlich faellige geplante Veroeffentlichungen (geplant_am <= jetzt) und postet sie."""
    import datetime
    # Beim Start: haengende 'laeuft'-Eintraege (aus einem abgebrochenen Lauf) als Fehler markieren -
    # bewusst NICHT erneut posten (sonst Doppel-Post-Risiko), sondern sichtbar machen.
    try:
        with get_conn() as conn:
            conn.execute("UPDATE geplante_posts SET status='fehler', "
                         "info='unterbrochen (Neustart) – bitte pruefen' WHERE status='laeuft'")
            conn.commit()
    except Exception:
        log.exception("Auto-Veroeffentlichung: Aufraeumen beim Start fehlgeschlagen")
    while True:
        try:
            now_iso = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
            with get_conn() as conn:
                due = conn.execute("SELECT id FROM geplante_posts WHERE status='geplant' AND geplant_am <= ? "
                                   "ORDER BY geplant_am", (now_iso,)).fetchall()
            for row in due:
                _publiziere_geplant(row["id"])
        except Exception:
            log.exception("Auto-Veroeffentlichung: Scheduler-Fehler")
        time.sleep(45)

# --- Zugriffsschutz ---------------------------------------------------------
def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*a, **k)
    return w

def admin_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if not session.get("user"):
            return redirect(url_for("login"))
        if session.get("rolle") != "admin":
            abort(403)
        return f(*a, **k)
    return w

def rolle_required(*rollen):
    """Erlaubt nur bestimmte Rollen (admin ist immer erlaubt)."""
    def deco(f):
        @functools.wraps(f)
        def w(*a, **k):
            if not session.get("user"):
                return redirect(url_for("login"))
            if session.get("rolle") not in rollen and session.get("rolle") != "admin":
                abort(403)
            return f(*a, **k)
        return w
    return deco

# --- Stilvorlagen -----------------------------------------------------------
_STYLE = """body{font-family:Arial,Helvetica,sans-serif;background:#eef1f4;padding:20px;margin:0;color:#15336e}
.box{max-width:920px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:22px}
h2{color:#1f428d;margin-top:0}h3{color:#15336e}a{color:#1f428d;text-decoration:none}
table{width:100%;border-collapse:collapse;margin:12px 0}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left;font-size:14px}
th{color:#4c7b2d}input,select{padding:9px;border:1px solid #ccd3df;border-radius:8px;margin:4px 6px 4px 0}
button{background:#1f428d;color:#fff;border:0;padding:9px 14px;border-radius:8px;cursor:pointer}
.flash{color:#1f428d;margin:8px 0;font-weight:bold}.hint{color:#777;font-size:13px}"""

_NAV = """<div class=top><div><b style="color:#1f428d;font-size:20px">HISOME</b> <span style="color:#60a33c;font-size:13px">HILO Social Media Tool</span></div>
<div><a href="/whatsapp">WhatsApp</a> &middot; <a href="/quellen">Eigene Quellen</a> &middot; {% if rolle=='admin' %}<a href="/verwaltung">Verwaltung</a> &middot; {% endif %}{{user}} &middot; <a href="/logout">Abmelden</a></div></div>"""

LOGIN = """<!doctype html><meta charset=utf-8><title>HISOME - HILO Social Media Tool</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#1f428d 0%,#60a33c 100%)}
.box{background:#fff;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.25);width:330px;overflow:hidden}
.head{padding:28px 26px 4px;text-align:center}.head img{height:46px}
.head h1{color:#1f428d;font-size:22px;margin:14px 0 2px}.head p{color:#60a33c;font-size:13px;margin:0;font-weight:bold;letter-spacing:.5px}
.body{padding:10px 26px 26px}
input{display:block;width:100%;box-sizing:border-box;margin:9px 0;padding:11px;border:1px solid #ccd3df;border-radius:9px}
button{width:100%;background:#1f428d;color:#fff;border:0;padding:12px;border-radius:9px;font-weight:bold;cursor:pointer;margin-top:6px}
.err{color:#b00020;font-size:13px;text-align:center}
</style>
<div class=box><div class=head><img src="/logo.png" alt="HILO"><h1>HISOME</h1><p>HILO Social Media Tool</p></div>
<div class=body>
{% with m=get_flashed_messages() %}{% if m %}<p class=err>{{m[0]}}</p>{% endif %}{% endwith %}
<form method=post><input name=name placeholder="Benutzer" autofocus><input name=passwort type=password placeholder="Passwort"><button>Anmelden</button></form>
</div></div>"""

_TOP = """body{font-family:Arial,Helvetica,sans-serif;background:#eef1f4;margin:0;padding:18px;color:#15336e}
.top{display:flex;justify-content:space-between;align-items:center;max-width:1040px;margin:0 auto 14px}
.top a{color:#1f428d;text-decoration:none}
.flash{max-width:1040px;margin:0 auto 12px;color:#1f428d;font-weight:bold}"""

HOME = """<!doctype html><meta charset=utf-8><title>HISOME</title>
<style>""" + _TOP + """
.info{max-width:1040px;margin:0 auto 16px;background:#e6eef6;border-radius:10px;padding:11px 16px;color:#1f428d;font-weight:bold;font-size:14px}
.grid{max-width:1040px;margin:0 auto;display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.tile{display:block;background:#fff;border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:18px;position:relative;border-top:5px solid #1f428d;min-height:150px;color:inherit;text-decoration:none}
.tile:hover{transform:translateY(-3px);box-shadow:0 10px 26px rgba(0,0,0,.14);transition:.15s}
.tile.action{border-top-color:#4c7b2d;background:linear-gradient(180deg,#f6faf2,#fff)}
.tile h3{color:#1f428d;margin:6px 0 4px;font-size:16px}.tile p{color:#6b7280;font-size:13px;margin:0}
.badge{position:absolute;bottom:14px;right:16px;background:#1f428d;color:#fff;border-radius:18px;padding:2px 11px;font-weight:bold;font-size:14px}
.badge.g{background:#4c7b2d}
.tile form{margin:10px 0 0}.tile button{background:#4c7b2d;color:#fff;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;font-size:13px}
.run{color:#4c7b2d;font-weight:bold;font-size:13px;margin-top:8px}</style>
""" + _NAV + """
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=info>&#x1F552; Themen werden täglich um 7:00 Uhr automatisch aus allen Quellen geholt.</div>
<div class=grid>
  <a class=tile href="/themen">{% if themen_offen %}<span class=badge>{{themen_offen}}</span>{% endif %}<h3>1. Freigabe: Themen</h3><p>Themen für die Kampagne auswählen (Stufe 1).</p></a>
  <a class=tile href="/erzeugen">{% if bereit %}<span class="badge g">{{bereit}}</span>{% endif %}<h3>2. Texte &amp; Bilder erzeugen</h3><p>Themen anhaken und für die ausgewählten Themen Beiträge erstellen.{% if gen_running %} <b>(läuft gerade &hellip;)</b>{% endif %}</p></a>
  <a class=tile href="/entwuerfe">{% if entwuerfe_offen %}<span class=badge>{{entwuerfe_offen}}</span>{% endif %}<h3>3. Freigabe: Texte &amp; Bilder</h3><p>Entwürfe prüfen, überarbeiten, freigeben (Stufe 2).</p></a>
  <a class=tile href="/einplanung">{% if freigegeben_offen %}<span class="badge g">{{freigegeben_offen}}</span>{% endif %}<h3>4. Einplanung Veröffentlichung</h3><p>Freigegebene Beiträge veröffentlichen.</p></a>
</div>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4c7b2d" href="/eigener"><h3>&#x270F;&#xFE0F; Eigenen Beitrag erstellen</h3><p>Thema und Tag angeben – das Tool erstellt einen Entwurf, den du freigibst und der dann fest für diesen Tag eingeplant wird.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4c7b2d" href="/kalender"><h3>&#x1F4C5; Content-Kalender</h3><p>Monatsübersicht: geplante Beiträge und besondere Tage (Anlass-Tage, Fristen) auf einen Blick.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4c7b2d" href="/auswertung"><h3>&#x1F4CA; Was funktioniert</h3><p>Auswertung der veröffentlichten Beiträge nach Reichweite – welcher Stream, welches Bild und welche Uhrzeit am besten ankommen.</p></a>"""

ERZEUGEN = """<!doctype html><meta charset=utf-8><title>Themen auswählen</title><style>""" + _STYLE + """
.bar{max-width:920px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#1f428d;color:#fff;padding:7px 13px;border-radius:8px}
.allrow{display:flex;align-items:center;gap:8px;background:#dfe7f3;color:#1f428d;padding:9px 11px;border-radius:8px;font-weight:bold;cursor:pointer}
.qgroup{border:1px solid #e3e7ee;border-radius:10px;margin:10px 0;overflow:hidden}
.qhead{display:flex;align-items:center;gap:8px;background:#eef2f8;color:#1f428d;padding:9px 11px;cursor:pointer;margin:0}
.qrow{display:flex;gap:11px;align-items:flex-start;padding:10px 11px;border-top:1px solid #eef1f4;cursor:pointer;margin:0}
.qrow:hover{background:#f6f8fb}
.qhead input{margin:0}.qrow input{margin:3px 0 0}
.ti{font-weight:bold;color:#15336e}.meta{font-size:12px;color:#7a8694}
.delbtn{background:#b00020;color:#fff;border:0;border-radius:7px;padding:5px 10px;cursor:pointer;font-size:12px;margin-left:auto;align-self:center}</style>
<div class=bar><h2 style="margin:0">Themen auswählen &amp; erzeugen</h2><a href="/">&larr; Startseite</a></div>
<div class=box>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if laeuft %}<div class=flash>&#x23F3; Eine Erzeugung läuft gerade im Hintergrund – bitte in ein bis zwei Minuten die Startseite neu laden.</div>{% endif %}
{% if themen %}
<p class=hint>Hake die Themen an, für die jetzt Texte &amp; Bilder erzeugt werden sollen. Für jedes angehakte Thema entsteht ein Entwurf, den du danach unter „3. Freigabe: Texte &amp; Bilder" prüfst.</p>
<form method=post onsubmit="return chk(this)">
  <label class=allrow><input type=checkbox onclick="toggleAll(this)"> Alle auswählen ({{themen|length}})</label>
  {% for g in gruppen %}{% set gi = loop.index %}
  <div class=qgroup>
    <label class=qhead><input type=checkbox onclick="toggleGroup(this,{{gi}})"> <b>{{g.label}}</b>&nbsp;<span class=meta>({{g.themen|length}})</span></label>
    {% for t in g.themen %}<label class=qrow><input type=checkbox name=thema_id value="{{t.id}}" data-grp="{{gi}}">
      <span><span class=ti>{{t.titel}}</span>{% if t.erkannt_am %}<br><span class=meta>erkannt {{t.erkannt_am[:10]}}</span>{% endif %}</span>
      <button type=button class=delbtn onclick="event.preventDefault();event.stopPropagation();loeschThema({{t.id}},'erzeugen')">Löschen</button></label>{% endfor %}
  </div>
  {% endfor %}
  <div style="margin-top:16px;display:flex;justify-content:space-between;align-items:center">
    <span class=hint><b id=cnt>0</b> ausgewählt</span>
    <button{% if laeuft %} disabled title="Es läuft bereits eine Erzeugung"{% endif %}>Ausgewählte erzeugen</button>
  </div>
</form>
<script>
function upd(){document.getElementById('cnt').textContent=document.querySelectorAll('input[name=thema_id]:checked').length;}
function toggleAll(c){document.querySelectorAll('input[name=thema_id]').forEach(function(b){b.checked=c.checked;});upd();}
function toggleGroup(c,gi){document.querySelectorAll('input[name=thema_id][data-grp="'+gi+'"]').forEach(function(b){b.checked=c.checked;});upd();}
function chk(f){if(f.querySelectorAll('input[name=thema_id]:checked').length===0){alert('Bitte mindestens ein Thema anhaken.');return false;}return true;}
function loeschThema(id,z){if(!confirm('Dieses Thema wirklich löschen?'))return;var f=document.createElement('form');f.method='post';f.action='/thema-loeschen/'+id;var i=document.createElement('input');i.type='hidden';i.name='zurueck';i.value=z;f.appendChild(i);document.body.appendChild(f);f.submit();}
document.addEventListener('change',function(e){if(e.target&&e.target.name==='thema_id')upd();});
</script>
{% else %}
<p class=hint>Aktuell sind keine freigegebenen Themen offen. Wähle zuerst unter „1. Freigabe: Themen" Themen für die Kampagne aus – danach erscheinen sie hier zur Erzeugung.</p>
<p><a href="/themen">&rarr; Zu „1. Freigabe: Themen"</a></p>
{% endif %}
</div>"""

EIGENER = """<!doctype html><meta charset=utf-8><title>Eigenen Beitrag erstellen</title>
<style>""" + _TOP + """
.card{max-width:680px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:22px}
label{display:block;font-weight:bold;color:#15336e;margin:16px 0 4px}
textarea,input[type=date]{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ccd3df;border-radius:8px;font-size:15px}
textarea{min-height:84px;resize:vertical}
button{margin-top:18px;background:#4c7b2d;color:#fff;border:0;border-radius:8px;padding:11px 18px;cursor:pointer;font-weight:bold}</style>
<div class=top><h2 style="margin:0;color:#1f428d">Eigenen Beitrag erstellen</h2><a href="/">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=card>
  <p class=hint>Gib ein <b>Thema</b> und einen <b>Tag</b> an. Das Tool erstellt daraus einen Entwurf (Text&nbsp;+&nbsp;Bild) wie bei den automatischen Themen. Nach deiner Freigabe unter „3. Freigabe: Texte &amp; Bilder" wird er fest für den gewählten Tag eingeplant.</p>
  <form method=post>
    <label>Thema des Beitrags</label>
    <textarea name=thema placeholder="z. B. Urlaub ist steuerlich nicht abzugsfähig" required>{{ vorgabe_thema }}</textarea>
    <label>Veröffentlichen am</label>
    <input type=date name=datum value="{{ vorgabe_datum }}" required>
    <button>Entwurf erstellen</button>
  </form>
</div>"""

ENTWUERFE = """<!doctype html><meta charset=utf-8><title>Freigabe: Texte & Bilder</title>
<style>""" + _TOP + """
.card{display:flex;gap:18px;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:16px;max-width:1040px;margin:0 auto 18px}
.card img{width:340px;height:340px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.t{flex:1}.t h3{color:#15336e;margin:.2em 0}.sub{color:#4c7b2d;font-weight:bold}
.cta{display:inline-block;background:#1f428d;color:#fff;padding:5px 10px;border-radius:14px;font-size:13px}
textarea{width:100%;min-height:54px;margin:8px 0;border:1px solid #ccd;border-radius:8px;padding:8px}
button{border:0;border-radius:8px;padding:9px 14px;cursor:pointer;margin-right:6px;color:#fff}
.ok{background:#2e7d32}.no{background:#9aa0a6}.re{background:#1f428d}.del{background:#b00020}</style>
<div class=top><h2 style="margin:0;color:#1f428d">Freigabe: Texte &amp; Bilder (Stufe 2)</h2><a href="/">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if entwuerfe %}<div style="max-width:1040px;margin:0 auto 14px;display:flex;justify-content:space-between;align-items:center">
  <span style="color:#6b7280;font-size:13px">Tipp: Nach geänderten Vorgaben (Bildstil, keine Abkürzungen …) kannst du alle offenen Entwürfe neu erzeugen lassen.</span>
  <form method=post action="/entwuerfe-neu" onsubmit="return confirm('Alle offenen Entwürfe nach den neuen Vorgaben NEU erzeugen? Das ersetzt die aktuellen Text- und Bildvorschläge und kostet KI-Tokens.')">
    <button class=re{% if gen_running %} disabled title="Es läuft bereits eine Erzeugung"{% endif %}>&#x21BB; Alle nach neuen Vorgaben neu erzeugen</button>
  </form></div>{% endif %}
{% for e in entwuerfe %}
<div class=card><img src="/bild/{{e.id}}" alt="Vorschau">
  <div class=t><h3>{{e.f.ueberschrift}}</h3><p class=sub>{{e.f.subline}}</p>
    <ul>{% for b in e.f.bullets %}<li>{{b}}</li>{% endfor %}</ul>
    <p><span class=cta>{{e.f.cta}}</span></p>
    <details><summary>Begleittext anzeigen</summary><p>{{e.f.caption}}</p></details>
    <form method=post action="/aktion/{{e.id}}">
      <textarea name=feedback placeholder="Änderungswunsch (z.B. 'Bild freundlicher') &ndash; dann 'Überarbeiten'"></textarea>
      <button class=ok name=aktion value=freigeben>Freigeben</button>
      <button class=re name=aktion value=ueberarbeiten>Überarbeiten</button>
      <button class=no name=aktion value=verwerfen>Verwerfen</button>
      <button class=del name=aktion value=loeschen onclick="return confirm('Diesen Entwurf wirklich löschen? Das kann nicht rückgängig gemacht werden.')">Löschen</button>
    </form>
    <form method=post action="/bild-neu/{{e.id}}" style="margin-top:6px" onsubmit="return confirm('Nur das Bild neu erzeugen? Der Text bleibt unverändert.')">
      <input type=hidden name=zurueck value=entwuerfe>
      <button style="background:#6b7280" title="Nur das Bild neu rendern (kostenlos), Text bleibt">&#x21BB; Nur Bild neu</button></form>
  </div></div>
{% else %}<p style="text-align:center">Keine offenen Entwürfe. Erst Themen auswählen und Beiträge erzeugen.</p>{% endfor %}"""

EINPLANUNG = """<!doctype html><meta charset=utf-8><title>Einplanung Veröffentlichung</title>
<style>""" + _TOP + """
.card{display:flex;gap:18px;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:16px;max-width:1040px;margin:0 auto 18px}
.card img{width:240px;height:240px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.t{flex:1}.t h3{color:#15336e;margin:.2em 0}.sub{color:#4c7b2d;font-weight:bold}
select,button{padding:9px;border-radius:8px;margin:4px 6px 4px 0}
button{border:0;background:#2e7d32;color:#fff;cursor:pointer}
.checks{margin:6px 0;display:flex;flex-wrap:wrap;gap:8px 14px}
.checks label{font-size:14px;background:#eef2f8;padding:4px 10px;border-radius:7px;cursor:pointer}
.checks .stelle{display:flex;align-items:center;gap:6px;background:#eef2f8;padding:4px 8px;border-radius:7px}
.checks .stelle label{background:none;padding:0}
.checks .stelle select{padding:4px 6px;margin:0;font-size:13px;border-radius:6px}
.fmt{font-size:13px;color:#15336e;margin-right:6px}.fmt select{font-size:13px;padding:6px}</style>
<script>function need(f,n,m){return f.querySelectorAll('input[name='+n+']:checked').length>0||(alert(m),false);}</script>
<div class=top><h2 style="margin:0;color:#1f428d">Einplanung Veröffentlichung</h2><div><a href="/geplant">&#x23F0; Geplante Veröffentlichungen</a> &middot; <a href="/">Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<p class=hint style="max-width:1040px;margin:0 auto 12px">Neu freigegebene Beiträge sind zunächst <b>„Noch nicht geplant"</b>. Das Tool schlägt den nächsten freien <b>Werktag nach der letzten Einplanung</b> vor (max. 1 pro Tag, Sa+So frei) – mit einem Klick bestätigen. Termin bleibt jederzeit anpassbar.</p>
{% if pages_err %}<div class=flash style="color:#b00020">Facebook-Seiten konnten nicht geladen werden: {{pages_err}}</div>{% endif %}
{% for e in freigegeben %}
<div class=card><img src="/bild/{{e.id}}" alt="Vorschau">
  <div class=t><h3>{{e.f.ueberschrift}}</h3><p class=sub>{{e.f.subline}}</p>
    <p>{% if e.geplant_fuer %}<b style="color:#1f428d">&#x1F4C5; Geplant: {{e.geplant_de}}</b>
       <form method=post action="/umplanen/{{e.id}}" style="display:inline;margin-left:8px">
         <input type=date name=geplant_fuer value="{{e.geplant_fuer}}" style="padding:5px">
         <button style="background:#1f428d;padding:6px 10px">Termin ändern</button></form>
       {% else %}<span style="display:inline-block;background:#b00020;color:#fff;font-size:16px;font-weight:bold;padding:10px 16px;border-radius:8px">&#x26A0;&#xFE0F; Noch nicht geplant</span>
       <form method=post action="/umplanen/{{e.id}}" style="display:inline;margin-left:10px">
         <span class=hint>Vorschlag: <b>{{e.vorschlag_de}}</b></span>
         <input type=date name=geplant_fuer value="{{e.vorschlag}}" style="padding:5px;margin-left:4px">
         <button style="background:#2e7d32;color:#fff;padding:8px 13px;border-radius:8px;font-weight:bold">Für diesen Tag einplanen</button></form>
       {% endif %}
       <form method=post action="/beitrag-neu/{{e.id}}" style="display:inline;margin-left:6px" onsubmit="return confirm('Diesen Beitrag nach den aktuellen Vorgaben neu erzeugen (Text + Bild)? Der geplante Termin bleibt erhalten.')">
         <button style="background:#4c7b2d;padding:6px 10px" title="Text und Bild nach aktuellen Vorgaben neu erzeugen">&#x21BB; Neu erzeugen</button></form>
       <form method=post action="/bild-neu/{{e.id}}" style="display:inline;margin-left:6px" onsubmit="return confirm('Nur das Bild neu erzeugen? Text und Termin bleiben unverändert.')">
         <input type=hidden name=zurueck value=einplanung>
         <button style="background:#6b7280;padding:6px 10px" title="Nur das Bild neu rendern (kostenlos), Text bleibt">&#x21BB; Nur Bild neu</button></form></p>
    <form method=post action="/text-neu/{{e.id}}" style="margin:4px 0 8px" onsubmit="if(!this.feedback.value.trim()){alert('Bitte kurz angeben, was am Text geändert werden soll.');return false}return confirm('Nur den Text mit Ihrem Hinweis überarbeiten? Das nutzt die Text-KI; das Bild wird kostenlos an den neuen Text angepasst. Termin bleibt.')">
      <input type=hidden name=zurueck value=einplanung>
      <input name=feedback placeholder="Was am Text stört (z.B. „kürzer", „weniger werblich")" style="padding:6px;width:330px;border:1px solid #ccd3df;border-radius:6px">
      <button style="background:#1f428d;padding:6px 10px" title="Nur den Text mit Ihrem Hinweis überarbeiten; Bild wird an den neuen Text angepasst (Text-KI, Bild kostenlos)">&#x270E; Text überarbeiten</button></form>
    <details><summary>Begleittext anzeigen</summary><p>{{e.f.caption}}</p></details>
    <p><a href="/beitrag/{{e.id}}" style="color:#1f428d;font-weight:bold;text-decoration:none">{% if e.format=='karussell' %}&#x1F5BC;&#xFE0F; Komplettes Karussell ansehen{% else %}&#x1F50D; Beitrag ansehen{% endif %} &amp; für WhatsApp &rarr;</a></p>
    {% if stellen %}
    <form method=post action="/vorschau/{{e.id}}" onsubmit="return need(this,'stelle_id','Bitte mindestens eine Beratungsstelle auswählen.')">
      <div class=checks>{% for s in stellen %}<span class=stelle><label><input type=checkbox name=stelle_id value="{{s.id}}"> {{s.name}}{% if s.ort %} ({{s.ort}}){% endif %}</label>
        <select name="kanal_s{{s.id}}" title="Kanal für diese Beratungsstelle">
          <option value="facebook"{% if (s.fb_seite|string) not in ig_seiten %} selected{% endif %}>Facebook</option>
          <option value="instagram">Instagram</option>
          <option value="beide"{% if (s.fb_seite|string) in ig_seiten %} selected{% endif %}>Facebook + Instagram</option></select></span>{% endfor %}</div>
      <span class=fmt>Facebook: <select name=format_fb title="Bildformat für Facebook">
        <option value="einzelbild" selected>Einzelbild</option>
        <option value="karussell">Karussell</option></select></span>
      <span class=fmt>Instagram: <select name=format_ig title="Bildformat für Instagram">
        <option value="einzelbild">Einzelbild</option>
        <option value="karussell" selected>Karussell</option></select></span>
      <label class=fmt style="font-weight:normal"><input type=checkbox name=story_ig value="1" checked> Bei Instagram zusätzlich als Story posten</label>
      <button>Vorschau ansehen</button>
      <button formaction="/auto-einplanen/{{e.id}}" style="background:#1f428d" title="Zur vorgeschlagenen Uhrzeit automatisch veröffentlichen">&#x23F0; Automatisch einplanen</button>
      <button formaction="/veroeffentlichen/{{e.id}}" onclick="return confirm('Ohne Vorschau direkt für die gewählten Beratungsstellen veröffentlichen?')" style="background:#6b7280">Direkt veröffentlichen</button>
    </form>
    <p class=hint>Bild-CTA und Begleittext werden automatisch auf die Beratungsstelle angepasst. Der <b>Kanal ist je Beratungsstelle wählbar</b> (ohne Instagram-Konto automatisch nur Facebook). <b>„Automatisch einplanen"</b> postet zur vorgeschlagenen Uhrzeit (gestreut 07–19 Uhr, anpassbar unter <a href="/geplant">Geplante Veröffentlichungen</a>).</p>
    {% elif pages %}
    <form method=post action="/vorschau/{{e.id}}" onsubmit="return need(this,'page_id','Bitte mindestens eine Facebook-Seite auswählen.')">
      <div class=checks>{% for p in pages %}<span class=stelle><label><input type=checkbox name=page_id value="{{p.id}}"> {{p.name}}</label>
        <select name="kanal_p{{p.id}}" title="Kanal für diese Seite">
          <option value="facebook"{% if not p.ig_username %} selected{% endif %}>Facebook</option>
          <option value="instagram">Instagram</option>
          <option value="beide"{% if p.ig_username %} selected{% endif %}>Facebook + Instagram</option></select></span>{% endfor %}</div>
      <span class=fmt>Facebook: <select name=format_fb title="Bildformat für Facebook">
        <option value="einzelbild" selected>Einzelbild</option>
        <option value="karussell">Karussell</option></select></span>
      <span class=fmt>Instagram: <select name=format_ig title="Bildformat für Instagram">
        <option value="einzelbild">Einzelbild</option>
        <option value="karussell" selected>Karussell</option></select></span>
      <label class=fmt style="font-weight:normal"><input type=checkbox name=story_ig value="1" checked> Bei Instagram zusätzlich als Story posten</label>
      <button>Vorschau ansehen</button>
      <button formaction="/auto-einplanen/{{e.id}}" style="background:#1f428d" title="Zur vorgeschlagenen Uhrzeit automatisch veröffentlichen">&#x23F0; Automatisch einplanen</button>
      <button formaction="/veroeffentlichen/{{e.id}}" onclick="return confirm('Ohne Vorschau direkt auf den gewählten Facebook-Seiten veröffentlichen?')" style="background:#6b7280">Direkt veröffentlichen</button>
    </form>
    <p class=hint>Tipp: Lege in der Verwaltung Beratungsstellen mit Facebook-Seite an, dann werden Beiträge automatisch personalisiert.</p>
    {% else %}<p class=sub>Kein Facebook-Zugang/keine Beratungsstelle aktiv.</p>{% endif %}
  </div></div>
{% else %}<p style="text-align:center">Keine freigegebenen Beiträge zur Einplanung.</p>{% endfor %}"""

VORSCHAU = """<!doctype html><meta charset=utf-8><title>Vorschau vor Veröffentlichung</title><style>""" + _STYLE + """
.bar{max-width:1200px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#1f428d;color:#fff;padding:7px 13px;border-radius:8px}
.pv{display:flex;flex-wrap:wrap;gap:18px;justify-content:center}
.pvc{background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:12px;width:340px}
.pvc img{width:316px;height:316px;object-fit:cover;border-radius:8px;border:1px solid #eef1f4}
.pvh{font-weight:bold;color:#15336e;margin-bottom:8px}
.pvc details{margin-top:8px}.pvc summary{cursor:pointer;color:#1f428d;font-size:13px}
.pvc .cap{font-size:13px;color:#444;margin:6px 0 0}
.foot{max-width:1200px;margin:16px auto 0;display:flex;justify-content:space-between;align-items:center;background:#fff;border-radius:12px;padding:14px}</style>
<div class=bar><h2 style="margin:0">Vorschau vor Veröffentlichung</h2><a href="/einplanung">&larr; Einplanung</a></div>
<div style="max-width:1200px;margin:0 auto 12px">
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<p class=hint>Prüfe für jede Beratungsstelle, ob <b>Porträt-Kreis, Name, Ort und Begleittext</b> stimmen. Erst wenn alles passt, unten auf „Jetzt veröffentlichen" klicken.<br><i>Format &ndash; Facebook: {{'Karussell' if fmt_fb=='karussell' else 'Einzelbild'}}, Instagram: {{'Karussell' if fmt_ig=='karussell' else 'Einzelbild'}}. Die Vorschau zeigt die personalisierte Bildvariante; ein Karussell enthält beim Posten zusätzlich mehrere Slides.</i></p>
</div>
<div class=pv>
{% for it in items %}
  <div class=pvc>
    <div class=pvh>{{it.label}}{% if not it.ok %} <span style="color:#b00020">– Vorschau-Fehler</span>{% endif %}</div>
    <div style="font-size:12px;color:#4c7b2d;font-weight:bold;margin-bottom:6px">Kanal: {{it.kanal_de}}</div>
    {% if it.ok %}<img src="{{it.url}}" alt="Vorschau {{it.label}}">{% else %}<p class=cap style="color:#b00020">{{it.caption}}</p>{% endif %}
    {% if it.ok %}{% for kn, cap in it.caps %}<details{% if loop.first %} open{% endif %}><summary>Begleittext {{kn}}</summary><p class=cap style="white-space:pre-wrap">{{cap}}</p></details>{% endfor %}{% endif %}
  </div>
{% endfor %}
</div>
<form method=post action="/veroeffentlichen/{{eid}}" onsubmit="return confirm('Jetzt an die {{ziel_count}} gültigen Ziele veröffentlichen?')">
  {% for s in stelle_ids %}<input type=hidden name=stelle_id value="{{s}}"><input type=hidden name="kanal_s{{s}}" value="{{kanal_map.get('s'+s,'facebook')}}">{% endfor %}
  {% for p in page_ids %}<input type=hidden name=page_id value="{{p}}"><input type=hidden name="kanal_p{{p}}" value="{{kanal_map.get('p'+p,'facebook')}}">{% endfor %}
  <input type=hidden name=format_fb value="{{fmt_fb}}"><input type=hidden name=format_ig value="{{fmt_ig}}">{% if story_ig %}<input type=hidden name=story_ig value="1">{% endif %}
  <div class=foot><a href="/einplanung">&larr; Auswahl ändern</a>
    <span class=hint>{{ziel_count}} Ziel(e) – Kanal je Beratungsstelle wie oben angezeigt</span>
    <button{% if not ziel_count %} disabled{% endif %}>Jetzt veröffentlichen</button></div>
</form>"""

GEPLANT = """<!doctype html><meta charset=utf-8><title>Geplante Veröffentlichungen</title><style>""" + _STYLE + """
.bar{max-width:1120px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#1f428d;color:#fff;padding:7px 13px;border-radius:8px}
table.gp{max-width:1120px;margin:0 auto;width:100%}
.gp td,.gp th{font-size:13px;vertical-align:middle}
.st{font-weight:bold;font-size:12px;border-radius:6px;padding:2px 8px}
.st.geplant{background:#eaf0fa;color:#1f428d}.st.veroeffentlicht{background:#e3efe0;color:#3c6322}
.st.fehler{background:#fdeaea;color:#b00020}.st.laeuft{background:#fff3e0;color:#9a6a00}
.gp input{padding:4px 6px;margin:0}.gp form button{padding:5px 9px;margin:0}</style>
<div class=bar><h2 style="margin:0;color:#1f428d">Geplante Veröffentlichungen</h2><a href="/einplanung">&larr; Einplanung</a></div>
<div class=box style="max-width:1120px">
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if posts %}
<p class=hint>Diese Beiträge werden <b>automatisch zur angegebenen Uhrzeit</b> (deutsche Zeit) veröffentlicht – der Pi muss dafür laufen. Uhrzeit/Datum unten anpassbar; Eintrag entfernbar.</p>
<table class=gp><tr><th>Beitrag</th><th>Ziel</th><th>Kanal</th><th>Format</th><th>Wann (deutsche Zeit)</th><th>Status</th><th></th></tr>
{% for p in posts %}<tr>
  <td><a href="/beitrag/{{p.eid}}">{{p.titel}}</a></td>
  <td>{{p.ziel}}</td><td>{{p.kanal}}</td><td>{{p.format}}</td>
  <td>{% if p.status in ['geplant','laeuft'] %}<form method=post action="/geplant-aendern/{{p.id}}" style="margin:0;display:flex;gap:5px;align-items:center">
        <input type=date name=datum value="{{p.datum}}"><input type=time name=zeit value="{{p.zeit}}"><button>OK</button></form>
      {% else %}{{p.geplant_de}}, {{p.zeit}} Uhr{% endif %}</td>
  <td><span class="st {{p.status}}">{{p.status}}</span>{% if p.info %} <span class=hint title="{{p.info}}">&#9432;</span>{% endif %}</td>
  <td>{% if p.status in ['geplant','laeuft'] %}<form method=post action="/geplant-loeschen/{{p.id}}" style="margin:0" onsubmit="return confirm('Diese geplante Veröffentlichung entfernen?')"><button style="background:#b00020">&times;</button></form>{% endif %}</td>
</tr>{% endfor %}</table>
{% else %}<p style="text-align:center">Keine geplanten Veröffentlichungen. Auf der Einplanungs-Seite „<b>Automatisch einplanen</b>" wählen.</p>{% endif %}
</div>"""

KALENDER = """<!doctype html><meta charset=utf-8><title>Content-Kalender</title>
<style>""" + _TOP + """
.kbar{max-width:1120px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.kbar a{background:#1f428d;color:#fff;padding:7px 13px;border-radius:8px;text-decoration:none}
table.kal{max-width:1120px;margin:0 auto;border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.kal th{background:#1f428d;color:#fff;padding:8px;font-size:13px}
.kal td{border:1px solid #eef1f4;vertical-align:top;height:98px;width:14.28%;padding:4px 6px;font-size:12px}
.kal td.out{background:#f6f7f9;color:#c2c8d0}
.kal td.we{background:#fafbfc}
.kal td.heute{outline:3px solid #4c7b2d;outline-offset:-3px}
.kt{font-weight:bold;color:#1f428d}
.anl{display:block;background:#eaf3e2;color:#3c6322;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.frist{display:block;background:#fdeaea;color:#b00020;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post{display:block;background:#eaf0fa;color:#15336e;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post.pub{background:#e3efe0;color:#3c6322}
a.anl{text-decoration:none;cursor:pointer}a.anl:hover{filter:brightness(.94)}
a.post{text-decoration:none;cursor:pointer}a.post:hover{filter:brightness(.94)}
.addpost{display:inline-block;margin-top:4px;color:#4c7b2d;font-size:11px;font-weight:bold;text-decoration:none}
.addpost:hover{text-decoration:underline}</style>
""" + _NAV + """
<div style="max-width:1120px;margin:0 auto 10px"><a href="/" style="color:#1f428d;text-decoration:none;font-weight:bold">&larr; Startseite</a></div>
<div class=kbar>
  <a href="/kalender?jahr={{prev.year}}&monat={{prev.month}}">&larr; {{prev_name}}</a>
  <h2 style="margin:0;color:#1f428d">{{monatname}} {{jahr}}</h2>
  <a href="/kalender?jahr={{nxt.year}}&monat={{nxt.month}}">{{nxt_name}} &rarr;</a>
</div>
<table class=kal><tr>{% for d in ['Mo','Di','Mi','Do','Fr','Sa','So'] %}<th>{{d}}</th>{% endfor %}</tr>
{% for woche in wochen %}<tr>
{% for c in woche %}<td class="{% if not c.im_monat %}out{% elif c.we %}we{% endif %}{% if c.heute %} heute{% endif %}">
<span class=kt>{{c.tag}}</span>
{% for b in c.besondere %}{% if 'Fristende' in b %}<span class=frist title="{{b}}">{{b}}</span>{% elif c.im_monat and not c.past %}<a class=anl href="/eigener?datum={{c.iso}}&anlass={{b|urlencode}}" title="Beitrag zu „{{b}}“ erstellen">{{b}}</a>{% else %}<span class=anl title="{{b}}">{{b}}</span>{% endif %}{% endfor %}
{% for p in c.posts %}<a class="post{% if p.status=='veroeffentlicht' %} pub{% endif %}" href="/beitrag/{{p.id}}" title="{{p.titel}}{% if p.format=='karussell' %} – Karussell ansehen{% else %} – Beitrag ansehen{% endif %}">{% if p.format=='karussell' %}&#x1F5BC;&#xFE0F; {% endif %}{{p.titel}}</a>{% endfor %}
{% if c.im_monat and not c.past %}<a class=addpost href="/eigener?datum={{c.iso}}" title="Beitrag für diesen Tag erstellen">+ Beitrag</a>{% endif %}
</td>{% endfor %}
</tr>{% endfor %}
</table>
<p class=hint style="max-width:1120px;margin:10px auto;text-align:center">Grün = besonderer Tag &middot; Rot = Fristende &middot; Blau = geplanter Beitrag (grün = bereits veröffentlicht)<br>Tipp: Auf einen Tag „+ Beitrag" klicken (oder direkt auf einen grünen Anlass-Tag) erstellt einen Beitrag für diesen Tag. Auf einen <b>blauen Beitrag</b> klicken zeigt ihn komplett (bei Karussells alle Slides).</p>"""

BEITRAG = """<!doctype html><meta charset=utf-8><title>Beitrag-Detail</title><style>""" + _STYLE + """
.bar{max-width:1000px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#1f428d;color:#fff;padding:7px 13px;border-radius:8px;margin-left:6px}
.slides{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin:6px 0}
.slides figure{margin:0}
.slides img,.single img{width:300px;height:300px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.slides figcaption{text-align:center;font-size:12px;color:#7a8694;margin-top:3px}
.single{text-align:center;margin:6px 0}.meta{color:#4c7b2d;font-weight:bold}
.wa{margin-top:18px;border-top:1px solid #eef1f4;padding-top:14px}
.wa textarea{width:100%;box-sizing:border-box;min-height:90px;border:1px solid #ccd3df;border-radius:8px;padding:8px;font:inherit}
.wa .row{margin-top:8px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.wa a.dl,.wa button{background:#1f428d;color:#fff;border:0;border-radius:8px;padding:8px 13px;text-decoration:none;cursor:pointer;font-size:14px}
.wa a.dl.gn{background:#25638f}</style>
<script>function copyId(id,b){navigator.clipboard.writeText(document.getElementById(id).value).then(function(){var t=b.textContent;b.textContent='✓ Kopiert';setTimeout(function(){b.textContent=t;},1500);});}</script>
<div class=bar><h2 style="margin:0;color:#1f428d">Geplanter Beitrag</h2><div><a href="/kalender">&larr; Kalender</a><a href="/einplanung">Alle geplanten</a></div></div>
<div class=box style="max-width:1000px">
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<h3 style="margin-top:0">{{e.f.ueberschrift}}</h3>
<p class=meta>{{e.f.subline}}</p>
<p><b style="color:#1f428d">&#x1F4C5; Geplant: {{e.geplant_de}}</b> &middot; <span class=hint>{% if fmt=='karussell' %}Karussell ({{n_slides}} Slides){% else %}Einzelbild{% endif %} &middot; Status: {{status}}</span></p>
{% if fmt=='karussell' and n_slides %}
<div class=slides>{% for i in range(n_slides) %}<figure><img src="/beitrag-slide/{{e.id}}/{{i}}" alt="Slide {{i+1}}"><figcaption>Slide {{i+1}} von {{n_slides}}</figcaption></figure>{% endfor %}</div>
{% elif fmt=='karussell' %}
<p class=hint>Die Karussell-Slides konnten gerade nicht erzeugt werden – bitte später erneut öffnen.</p>
{% else %}
<div class=single><img src="/bild/{{e.id}}" alt="Beitragsbild"></div>
{% endif %}
<ul>{% for b in e.f.bullets %}<li>{{b}}</li>{% endfor %}</ul>
<p><b>Aufruf:</b> {{e.f.cta}}</p>
{% if status in ('entwurf','freigegeben') %}
<div style="border:1px solid #e3e7ee;border-radius:10px;padding:10px;margin:10px 0;background:#f7f9fc">
  <b style="color:#15336e">Bildtyp:</b>
  {% if e.f.bild_typ=='thema' %}Themenbild (Gegenstände){% else %}Personenbild (Beratungsszene){% endif %}
  {% if e.f.bild_motiv_thema %}
    <form method=post action="/bild-typ/{{e.id}}" style="display:inline;margin-left:8px"
          onsubmit="return confirm({% if e.f.bild_typ=='thema' %}'Zur Personenszene zurückwechseln? Das Bild wird neu zusammengesetzt.'{% else %}'Auf ein Themenbild (ohne Personen) umstellen? Beim ersten Mal wird dafür ein neues Bild erzeugt (kostet ein paar Cent bei der Bild-KI).'{% endif %})">
      <input type=hidden name=zurueck value=beitrag>
      <input type=hidden name=typ value="{% if e.f.bild_typ=='thema' %}person{% else %}thema{% endif %}">
      <button>{% if e.f.bild_typ=='thema' %}&#x21BA; Personenbild verwenden{% else %}&#x1F33F; Themenbild verwenden{% endif %}</button>
    </form>
  {% else %}
    <span class=hint style="margin-left:8px">Kein Themenbild hinterlegt &ndash; über „Neu erzeugen" wird eines miterstellt.</span>
  {% endif %}
</div>
{% endif %}
<details open><summary>Begleittext Facebook</summary><p style="white-space:pre-wrap">{{ e.f.captions.facebook if e.f.captions else e.f.caption }}</p></details>
<details><summary>Begleittext Instagram</summary><p style="white-space:pre-wrap">{{ e.f.captions.instagram if e.f.captions else e.f.caption }}</p></details>
<div class=wa>
  <h3 style="margin:.2em 0">&#x1F4F2; Für WhatsApp (Kanal / Status)</h3>
  <p class=hint>WhatsApp lässt sich nicht automatisch befüllen – hier alles zum schnellen <b>manuellen</b> Posten: Text kopieren, Bild herunterladen, fertig.</p>
  <p style="margin:.2em 0;font-weight:bold;color:#15336e">Allgemein (ohne Beratungsstelle)</p>
  <div class=hint>Kanal-Text (höchstens 3 Sätze, mit Quell-/Buchungslink)</div>
  <textarea id=watext_k readonly>{{wa_allg_kanal}}</textarea>
  <div class=row><button type=button onclick="copyId('watext_k',this)">Kanal-Text kopieren</button></div>
  <div class=hint style="margin-top:6px">Status-Text (höchstens 2 Sätze)</div>
  <textarea id=watext_s readonly>{{wa_allg_story}}</textarea>
  <div class=row>
    <button type=button onclick="copyId('watext_s',this)">Status-Text kopieren</button>
    {% if fmt=='karussell' and n_slides %}{% for i in range(n_slides) %}<a class=dl href="/beitrag-slide/{{e.id}}/{{i}}" download="hilo_{{e.id}}_slide{{i+1}}.png">Slide {{i+1}} laden</a>{% endfor %}{% else %}<a class=dl href="/bild/{{e.id}}" download="hilo_{{e.id}}.png">Bild herunterladen</a>{% endif %}
    <a class="dl gn" href="/bild-status/{{e.id}}" title="Hochkant 9:16, ideal für Status/Story">Status-Version (hochkant) laden</a>
  </div>
  {% if wa_stellen %}
  <p style="margin:16px 0 .2em;font-weight:bold;color:#15336e">Personalisiert je Beratungsstelle <span class=hint style="font-weight:normal">(mit Porträt-Kreis und Ort)</span></p>
  {% for w in wa_stellen %}
  <div style="border:1px solid #e3e7ee;border-radius:10px;padding:10px;margin:8px 0">
    <b style="color:#1f428d">{{w.name}}{% if w.ort %} &middot; {{w.ort}}{% endif %}</b>
    <div class=hint style="margin-top:6px">Kanal-Text</div>
    <textarea id="watext_k_{{w.id}}" readonly>{{w.kanal}}</textarea>
    <div class=row><button type=button onclick="copyId('watext_k_{{w.id}}',this)">Kanal-Text kopieren</button></div>
    <div class=hint style="margin-top:6px">Status-Text</div>
    <textarea id="watext_s_{{w.id}}" readonly>{{w.story}}</textarea>
    <div class=row>
      <button type=button onclick="copyId('watext_s_{{w.id}}',this)">Status-Text kopieren</button>
      <a class=dl href="/bild-stelle/{{e.id}}/{{w.id}}">Bild (personalisiert)</a>
      <a class="dl gn" href="/bild-status-stelle/{{e.id}}/{{w.id}}">Status-Version (hochkant)</a>
    </div>
  </div>
  {% endfor %}
  {% endif %}
</div>
</div>"""

THEMEN = """<!doctype html><meta charset=utf-8><title>Freigabe: Themen</title><style>""" + _STYLE + """
.q{display:inline-block;background:#eaf0fa;color:#1f428d;border-radius:10px;padding:1px 8px;font-size:12px;font-weight:bold}
.delbtn{background:#b00020;color:#fff;border:0;border-radius:7px;padding:5px 10px;cursor:pointer;font-size:12px}</style>
<script>function loeschThema(id,z){if(!confirm('Dieses Thema wirklich löschen?'))return;var f=document.createElement('form');f.method='post';f.action='/thema-loeschen/'+id;var i=document.createElement('input');i.type='hidden';i.name='zurueck';i.value=z;f.appendChild(i);document.body.appendChild(f);f.submit();}</script>
<div class=box style="max-width:980px">
<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">Freigabe: Themen (Stufe 1)</h2><a href="/">&larr; Startseite</a></div>
<p class=hint>Wähle die Themen aus, die in die Kampagne sollen. Erst für <b>ausgewählte</b> Themen werden danach Text und Bild erzeugt (spart Token).</p>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if themen %}
<form method=post>
<p><label><input type=checkbox onclick="for(var c of document.querySelectorAll('input[name=thema_ids]'))c.checked=this.checked"> <b>Alle markieren</b></label>
&nbsp;&nbsp;<button name=aktion value=auswaehlen>Markierte freigeben &rarr; Stufe 2</button>
<button name=aktion value=verwerfen style="background:#9aa0a6">Markierte verwerfen</button></p>
<table><tr><th></th><th>Quelle</th><th>Titel</th><th></th></tr>
{% for t in themen %}<tr><td><input type=checkbox name=thema_ids value="{{t.id}}"></td>
<td><span class=q>{{t.quelle}}</span></td>
<td>{% if t.url %}<a href="{{t.url}}" target=_blank rel=noopener>{{t.titel}}</a>{% else %}{{t.titel}}{% endif %}</td>
<td><button type=button class=delbtn onclick="loeschThema({{t.id}},'themen')">Löschen</button></td></tr>{% endfor %}
</table>
<p><button name=aktion value=auswaehlen>Markierte freigeben &rarr; Stufe 2</button></p>
</form>
{% else %}<p>Keine offenen Themen. Der tägliche 7-Uhr-Lauf füllt diese Liste automatisch.</p>{% endif %}
</div>"""

QUELLEN = """<!doctype html><meta charset=utf-8><title>Eigene Quellen</title><style>""" + _STYLE + """
.q{display:inline-block;background:#eaf0fa;color:#1f428d;border-radius:10px;padding:1px 8px;font-size:12px;font-weight:bold}
.drop{border:2px dashed #ccd3df;border-radius:12px;padding:18px;margin:8px 0;background:#fafbfc}</style>
<div class=box>
<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">Eigene Quellen einwerfen</h2><a href="/">&larr; Startseite</a></div>
<p class=hint>Wirf hier ein <b>PDF</b> oder einen <b>Link</b> ein. HISOME liest den Inhalt, <b>zerlegt ihn in die einzelnen Themen</b> und merkt jedes direkt zur Texterstellung vor. <b>Wichtig:</b> Nur öffentliche/unkritische Inhalte &ndash; keine Mandantendaten.</p>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=drop><h3>PDF hochladen</h3>
<form method=post enctype=multipart/form-data><input type=file name=pdf accept="application/pdf,.pdf" required>
<button>PDF analysieren</button></form></div>
<div class=drop><h3>Link analysieren</h3>
<form method=post><input name=url type=url placeholder="https://..." style="width:60%" required>
<button>Link analysieren</button></form></div>
{% if quellen %}<h3>Zuletzt eingeworfen</h3>
<table><tr><th>Art</th><th>Titel</th><th>Status</th></tr>
{% for q in quellen %}<tr><td><span class=q>{{q.quelle}}</span></td>
<td>{% if q.url %}<a href="{{q.url}}" target=_blank rel=noopener>{{q.titel}}</a>{% else %}{{q.titel}}{% endif %}</td>
<td>{{q.status}}</td></tr>{% endfor %}</table>{% endif %}
</div>"""

VERWALTUNG_HOME = """<!doctype html><meta charset=utf-8><title>Verwaltung</title>
<style>""" + _TOP + """
.grid{max-width:1040px;margin:0 auto;display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.tile{display:block;background:#fff;border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:20px;border-top:5px solid #1f428d;color:inherit;text-decoration:none;min-height:92px}
.tile:hover{transform:translateY(-3px);box-shadow:0 10px 26px rgba(0,0,0,.14);transition:.15s}
.tile h3{color:#1f428d;margin:4px 0 4px;font-size:17px}.tile p{color:#6b7280;font-size:13px;margin:0}</style>
<div class=top><h2 style="margin:0;color:#1f428d">Verwaltung</h2><a href="/" style="color:#1f428d;text-decoration:none">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=grid>
  <a class=tile href="/verwaltung?bereich=benutzer"><h3>&#x1F465; Benutzer</h3><p>Konten anlegen, Rollen vergeben, aktivieren oder deaktivieren.</p></a>
  <a class=tile href="/verwaltung?bereich=stellen"><h3>&#x1F3E2; Beratungsstellen</h3><p>Stellen mit Ort, Facebook-Seite und Buchungslink pflegen.</p></a>
  <a class=tile href="/verwaltung?bereich=anlass"><h3>&#x1F4C5; Anlass-Tage</h3><p>Besondere Tage mit Steuer-Aufh&auml;nger verwalten.</p></a>
  <a class=tile href="/verwaltung?bereich=wissen"><h3>&#x1F4A1; Wissens-Serie</h3><p>Zeitlose Themen, die leere Kalendertage f&uuml;llen.</p></a>
</div>"""

VERWALTUNG = """<!doctype html><meta charset=utf-8><title>{{bereich_titel}} - Verwaltung</title><style>""" + _STYLE + """
.filebtn{display:inline-block;background:#eef2f8;border:1px solid #cfd8e6;border-radius:7px;padding:6px 11px;cursor:pointer;font-size:13px;color:#1f428d;white-space:nowrap}
.filebtn:hover{background:#e2e9f4}
button:disabled{opacity:.45;cursor:not-allowed}
.wide{max-width:1480px}
.scrollx{overflow-x:auto}
.vtab td,.vtab th{padding:11px 13px}
.nw{white-space:nowrap}
.stcards{max-width:840px;margin:0 auto}
.stcard{background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:14px 16px;margin:0 0 12px;box-shadow:0 2px 6px rgba(0,0,0,.05)}
.sthead{font-size:16px;color:#1f428d;margin-bottom:10px}
.stgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.stfield>label{display:block;font-size:12px;font-weight:bold;color:#5a6472;margin-bottom:4px}
.stfield select,.stfield .oid{width:100%;box-sizing:border-box;padding:7px;border:1px solid #ccd3df;border-radius:6px}
.stfield form{margin:0}.oidrow{display:flex;gap:6px;align-items:center}.oidrow .oid{flex:1}</style>
<div class=box><div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">{{bereich_titel}}</h2><div><a href="/verwaltung">&larr; Verwaltung</a> &middot; <a href="/">Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}

{% if bereich=='benutzer' %}
<table><tr><th>Name</th><th>Rolle</th><th>Aktiv</th><th></th></tr>
{% for u in users %}<tr><td>{{u.name}}</td><td>{{u.rolle}}</td><td>{{'ja' if u.aktiv else 'nein'}}</td>
<td><form method=post style=display:inline><input type=hidden name=formular value=benutzer_toggle><input type=hidden name=name value="{{u.name}}"><button>{{'Deaktivieren' if u.aktiv else 'Aktivieren'}}</button></form></td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=benutzer_add>
<input name=name placeholder="Name" required>
<input name=passwort type=password placeholder="Passwort" required>
<select name=rolle><option value=redakteur>Redakteur</option><option value=freigeber>Freigeber</option><option value=admin>Admin</option></select>
<button>Benutzer anlegen</button></form>
{% endif %}

{% if bereich=='stellen' %}
{% if pages_err %}<p class=hint style="color:#b00020">Facebook-Seiten konnten nicht geladen werden: {{pages_err}} – du kannst die Seiten-ID solange manuell eintragen.</p>{% endif %}
<div class=stcards>
{% for b in stellen %}
<div class=stcard>
  <div class=sthead><b>{{b.name}}</b>{% if b.ort %} &middot; {{b.ort}}{% endif %}{% if b.leitung %} <span class=hint style="font-weight:normal">Leitung: {{b.leitung}}</span>{% endif %}</div>
  <div class=stgrid>
    <div class=stfield><label>Facebook-Seite</label>
      {% if pages %}<form method=post><input type=hidden name=formular value=stelle_fb><input type=hidden name=stelle_id value="{{b.id}}">
        <select name=fb_seite onchange="this.form.submit()">
          <option value="">— keine —</option>
          {% if b.fb_seite and (b.fb_seite|string) not in page_id_set %}<option value="{{b.fb_seite}}" selected>{{b.fb_seite}} (alt)</option>{% endif %}
          {% for p in pages %}<option value="{{p.id}}"{% if (b.fb_seite|string)==(p.id|string) %} selected{% endif %}>{{p.name}}{% if p.ig_username %} / @{{p.ig_username}}{% endif %}</option>{% endfor %}
        </select></form>{% else %}<div class=hint>{{fb_name.get(b.fb_seite|string, b.fb_seite) or '—'}}</div>{% endif %}
    </div>
    <div class=stfield><label>Orts-ID (Facebook &amp; Instagram-Geotag)</label>
      <form method=post class=oidrow><input type=hidden name=formular value=stelle_ort_id><input type=hidden name=stelle_id value="{{b.id}}">
        <input class=oid name=ort_id value="{{b.ort_id or ''}}" placeholder="Facebook-Orts-ID" inputmode=numeric title="Facebook-Orts-ID (nur Ziffern) - markiert Facebook- und Instagram-Beiträge mit dem Ort">
        <button style="padding:7px 13px">OK</button></form>
    </div>
    <div class=stfield><label>Buchungslink</label><div class=hint style="word-break:break-all">{{b.buchungs_url or '—'}}</div></div>
    <div class=stfield><label>Porträt (Kreis)</label>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        {% if b.portrait_pfad %}<img src="/portrait/{{b.id}}?v={{b.id}}" alt="Porträt" style="width:44px;height:44px;border-radius:50%;object-fit:cover">{% endif %}
        <form method=post enctype="multipart/form-data" style="margin:0;display:flex;align-items:center;gap:7px">
          <input type=hidden name=formular value=stelle_portrait><input type=hidden name=stelle_id value="{{b.id}}">
          <label class=filebtn>{% if b.portrait_pfad %}Anderes Bild …{% else %}Bild wählen …{% endif %}
            <input type=file name=portrait accept="image/*" style="display:none"
                   onchange="var f=this.files[0];this.form.querySelector('.fn').textContent=f?f.name:'';this.form.querySelector('.up').disabled=!f"></label>
          <span class=fn style="font-size:12px;color:#5a6472;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
          <button class=up style="padding:6px 12px" disabled>Hochladen</button>
        </form>
        {% if b.portrait_pfad %}<form method=post style="margin:0" onsubmit="return confirm('Porträt entfernen? Dann erscheint wieder der blaue Punkt.')"><input type=hidden name=formular value=stelle_portrait_del><input type=hidden name=stelle_id value="{{b.id}}"><button title="Porträt entfernen" style="background:#b00020;padding:6px 11px">×</button></form>{% endif %}
      </div>
    </div>
  </div>
</div>
{% endfor %}
</div>
<form method=post><input type=hidden name=formular value=stelle_save>
<input name=name placeholder="Name der Beratungsstelle" required>
<input name=ort placeholder="Ort (z.B. Neuss)" required>
<input name=leitung placeholder="Name der Leitung">
{% if pages %}<select name=fb_seite><option value="">— Facebook-Seite wählen —</option>{% for p in pages %}<option value="{{p.id}}">{{p.name}}{% if p.ig_username %} / @{{p.ig_username}}{% endif %}</option>{% endfor %}</select>
{% else %}<input name=fb_seite placeholder="Facebook-Seite (ID)">{% endif %}
<input name=homepage_url placeholder="Link Homepage">
<input name=buchungs_url placeholder="Link Buchungskalender">
<button>Beratungsstelle speichern</button></form>
<p class=hint>Die Facebook-Seite verknüpft die Stelle für personalisierte Beiträge und die richtige Veröffentlichung. Bei bestehenden Stellen oben direkt im Dropdown wählen – wird sofort gespeichert.</p>
{% endif %}

{% if bereich=='anlass' %}
<p class=hint>Besondere Tage mit Steuer-Aufhänger. Datum als MM-TT (z.B. 04-23). Fällt der Tag aufs Wochenende, erscheint der Beitrag am Freitag davor.</p>
<table><tr><th>Datum</th><th>Anlass</th><th>Steuer-Aufhänger</th><th>Aktiv</th><th></th></tr>
{% for a in anlasstage %}<tr><td>{{a.datum}}</td><td>{{a.anlass}}</td><td>{{a.steuer_hook}}</td><td>{{'ja' if a.aktiv else 'nein'}}</td>
<td><form method=post style=display:inline><input type=hidden name=formular value=anlass_toggle><input type=hidden name=anlass value="{{a.anlass}}"><button>{{'Aus' if a.aktiv else 'Ein'}}</button></form></td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=anlass_save>
<input name=datum placeholder="MM-TT" size=6 required>
<input name=anlass placeholder="Anlass (z.B. Tag des Bieres)" required>
<input name=steuer_hook placeholder="Steuer-Aufhänger" style="width:40%">
<button>Anlass-Tag speichern</button></form>
{% endif %}

{% if bereich=='wissen' %}
<p class=hint>Diese Themen füllen leere Kalendertage, wenn sonst nichts ansteht.</p>
<table><tr><th>Thema</th><th>Aufhänger</th><th>Aktiv</th><th></th></tr>
{% for w in wissen %}<tr><td>{{w.titel}}</td><td>{{w.hook}}</td><td>{{'ja' if w.aktiv else 'nein'}}</td>
<td><form method=post style=display:inline><input type=hidden name=formular value=wissen_toggle><input type=hidden name=titel value="{{w.titel}}"><button>{{'Aus' if w.aktiv else 'Ein'}}</button></form></td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=wissen_save>
<input name=titel placeholder="Thema (z.B. Wer muss abgeben?)" required style="width:35%">
<input name=hook placeholder="Kurzer Aufhänger" style="width:40%">
<button>Wissens-Thema speichern</button></form>
{% endif %}
</div>"""

# --- Hilfsfunktionen --------------------------------------------------------
def _parse(e):
    try:
        f = json.loads(e["text"])
    except Exception:
        f = {"ueberschrift": "(fehlerhafter Entwurf)", "subline": "", "bullets": [], "cta": "", "caption": ""}
    row = {"id": e["id"], "f": f}
    if "format" in e.keys():
        row["format"] = e["format"] or "einzelbild"
    if "geplant_fuer" in e.keys():
        row["geplant_fuer"] = e["geplant_fuer"]
        row["geplant_de"] = _de_datum(e["geplant_fuer"])
    return row

def _de_datum(iso):
    import datetime
    try:
        d = datetime.date.fromisoformat(iso)
        wt = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.weekday()]
        return "%s, %02d.%02d.%04d" % (wt, d.day, d.month, d.year)
    except Exception:
        return iso or "-"

def _vorschlag_termin(belegt):
    """Terminvorschlag: ein Werktag NACH der letzten Einplanung (Sa/So uebersprungen,
    max 1 Beitrag pro Tag). `belegt` = Menge bereits vergebener ISO-Daten. Ist (zukuenftig)
    noch nichts geplant, faengt es beim naechsten Werktag ab heute an."""
    import datetime
    heute = datetime.date.today()
    zukunft = [datetime.date.fromisoformat(x) for x in belegt
               if datetime.date.fromisoformat(x) >= heute]
    if zukunft:
        d = max(zukunft)  # letzte Einplanung -> ein Werktag danach
        for _ in range(400):
            d += datetime.timedelta(days=1)
            if d.weekday() < 5 and d.isoformat() not in belegt:
                return d.isoformat()
        return d.isoformat()
    d = heute  # nichts geplant -> erster freier Werktag ab heute
    for _ in range(400):
        if d.weekday() < 5 and d.isoformat() not in belegt:
            return d.isoformat()
        d += datetime.timedelta(days=1)
    return d.isoformat()

def _naechster_freier_werktag(conn, ausser_id=None):
    """Terminvorschlag fuer EINEN Beitrag anhand der bereits geplanten Beitraege."""
    belegt = {r[0] for r in conn.execute(
        "SELECT geplant_fuer FROM entwuerfe WHERE status='freigegeben' "
        "AND geplant_fuer IS NOT NULL AND id != ?", (ausser_id or -1,))}
    return _vorschlag_termin(belegt)

def _ctx(**kw):
    kw.setdefault("user", session.get("user"))
    kw.setdefault("rolle", session.get("rolle"))
    return kw

# --- Routen -----------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pw = request.form.get("passwort", "")
        with get_conn() as conn:
            u = conn.execute("SELECT * FROM benutzer WHERE name=? AND aktiv=1", (name,)).fetchone()
        if u and check_password_hash(u["passwort_hash"], pw):
            session["user"] = name
            session["rolle"] = u["rolle"]
            return redirect(url_for("index"))
        flash("Anmeldung fehlgeschlagen.")
    return render_template_string(LOGIN)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    with get_conn() as conn:
        themen_offen = conn.execute("SELECT COUNT(*) FROM themen WHERE status='vorgeschlagen'").fetchone()[0]
        bereit = conn.execute("SELECT COUNT(*) FROM themen t WHERE t.status='ausgewaehlt' "
                              "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=t.id)").fetchone()[0]
        entwuerfe_offen = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status='entwurf'").fetchone()[0]
        freigegeben_offen = conn.execute("SELECT COUNT(*) FROM entwuerfe WHERE status='freigegeben'").fetchone()[0]
    return render_template_string(HOME, **_ctx(themen_offen=themen_offen, bereit=bereit,
                                  entwuerfe_offen=entwuerfe_offen, freigegeben_offen=freigegeben_offen,
                                  gen_running=_generation_running()))

@app.route("/entwuerfe")
@login_required
def entwuerfe():
    rows = []
    with get_conn() as conn:
        for e in conn.execute("SELECT id, text FROM entwuerfe WHERE status='entwurf' ORDER BY id DESC"):
            rows.append(_parse(e))
    return render_template_string(ENTWUERFE, **_ctx(entwuerfe=rows, gen_running=_generation_running()))

@app.route("/entwuerfe-neu", methods=["POST"])
@rolle_required("freigeber")
def entwuerfe_neu():
    """Erzeugt alle noch nicht freigegebenen Entwuerfe nach aktuellen Vorgaben neu (Hintergrund)."""
    with _gen_lock:
        if _generation_running():
            flash("Es läuft bereits eine Erzeugung - einen Moment, dann die Seite neu laden.")
        else:
            try:
                _start_regenerate()
                flash("Alle offenen Entwürfe werden nach den neuen Vorgaben neu erzeugt - läuft im "
                      "Hintergrund. In ein bis zwei Minuten die Seite neu laden.")
            except Exception as ex:
                flash("Neu-Erzeugung konnte nicht gestartet werden: %s" % ex)
    return redirect(url_for("entwuerfe"))

@app.route("/einplanung")
@login_required
def einplanung():
    rows = []
    with get_conn() as conn:
        for e in conn.execute("SELECT id, text, geplant_fuer, format FROM entwuerfe WHERE status='freigegeben' "
                              "ORDER BY geplant_fuer IS NULL, geplant_fuer, id"):
            rows.append(_parse(e))
        # Fuer noch nicht geplante Beitraege je einen fortlaufenden Werktags-Vorschlag berechnen
        # (jeder Vorschlag belegt den Tag fuer den naechsten ungeplanten Beitrag).
        belegt = {r["geplant_fuer"] for r in rows if r.get("geplant_fuer")}
        for r in rows:
            if not r.get("geplant_fuer"):
                v = _vorschlag_termin(belegt)
                r["vorschlag"] = v
                r["vorschlag_de"] = _de_datum(v)
                belegt.add(v)
        stellen = conn.execute("SELECT id, name, ort, fb_seite, buchungs_url FROM beratungsstellen "
                              "WHERE aktiv=1 AND fb_seite IS NOT NULL AND fb_seite!='' ORDER BY ort").fetchall()
    pages, pages_err = (_pages() if rows and not stellen else ([], None))
    # IG-Verknuepfung je Facebook-Seite -> Kanal-Vorauswahl: mit IG 'beide', ohne IG nur 'Facebook'
    ig_seiten = set()
    if rows and stellen:
        pg, _ = _pages()
        ig_seiten = {str(p["id"]) for p in (pg or []) if p.get("ig_id")}
    return render_template_string(EINPLANUNG, **_ctx(freigegeben=rows, stellen=stellen,
                                  pages=pages, pages_err=pages_err, ig_seiten=ig_seiten))

@app.route("/umplanen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def umplanen(eid):
    datum = request.form.get("geplant_fuer", "").strip()
    with get_conn() as conn:
        if datum:
            conn.execute("UPDATE entwuerfe SET geplant_fuer=? WHERE id=? AND status='freigegeben'", (datum, eid))
            audit_log(conn, session["user"], "umgeplant", eid, datum)
            flash("Beitrag %d auf %s umgeplant." % (eid, _de_datum(datum)))
            conn.commit()
    return redirect(url_for("einplanung"))

@app.route("/beitrag-neu/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def beitrag_neu(eid):
    """Erzeugt einen (auch bereits freigegebenen) Beitrag nach aktuellen Vorgaben neu - Text + Bild.
    Status und geplanter Termin bleiben erhalten (render_drafts() nimmt nur Entwuerfe, daher hier direkt)."""
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        if e["status"] not in ("freigegeben", "entwurf"):
            flash("Beitrag %d kann nicht neu erzeugt werden (Status: %s)." % (eid, e["status"]))
            return redirect(url_for("einplanung"))
        thema = conn.execute("SELECT titel, url, volltext FROM themen WHERE id=?",
                             (e["thema_id"],)).fetchone() if e["thema_id"] else None
        kanal = e["kanal"] or "google"
    # Text neu (falls ein Thema hinterlegt ist), sonst bestehenden Text beibehalten
    try:
        if thema:
            data = textgen.generate({"titel": thema["titel"], "volltext": thema["volltext"],
                                     "url": thema["url"]}, kanal)
        else:
            data = json.loads(e["text"])
    except Exception as ex:
        flash("Neu-Erzeugung fehlgeschlagen (Text): %s" % ex); return redirect(url_for("einplanung"))
    # Bild direkt neu rendern (unabhaengig vom Status)
    out = None
    try:
        import bildmotiv
        photo = bildmotiv.ensure_photo_fuer(data)
        slogan = bildgen.pick_slogan(data.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(data, photo, slogan, out)
    except Exception as ex:
        out = None
        flash("Hinweis: Bild konnte nicht neu erzeugt werden (%s) - der Text wurde aktualisiert." % ex)
    with get_conn() as conn:
        if out:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), out, eid))
        else:
            # Bild fehlgeschlagen: neuer Text wuerde nicht zum alten Bild passen -> nicht freigegeben/
            # geplant mit Mismatch stehen lassen, sondern zurueck in die Entwurfs-Pruefung (Termin bleibt).
            conn.execute("UPDATE entwuerfe SET text=?, status='entwurf' WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), eid))
        audit_log(conn, session["user"], "beitrag_neu_erzeugt", eid)
        conn.commit()
    if out:
        flash("Beitrag %d nach den aktuellen Vorgaben neu erzeugt - bitte vor dem Veröffentlichen prüfen." % eid)
    else:
        flash("Beitrag %d: Text aktualisiert, aber das Bild schlug fehl - der Beitrag liegt jetzt wieder "
              "unter „3. Freigabe: Texte & Bilder“ zur Prüfung." % eid)
    return redirect(url_for("einplanung"))

@app.route("/text-neu/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def text_neu(eid):
    """Ueberarbeitet NUR den Text gemaess einem Aenderungswunsch (Text-KI) und passt das Bild an den
    neuen Text an (Motiv aus dem Cache -> keine Bild-KI-Kosten). Status und Termin bleiben."""
    zurueck = request.form.get("zurueck", "einplanung")
    ziel = url_for("entwuerfe") if zurueck == "entwuerfe" else url_for("einplanung")
    feedback = request.form.get("feedback", "").strip()
    if not feedback:
        flash("Bitte kurz angeben, was am Text geändert werden soll."); return redirect(ziel)
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        if e["status"] not in ("freigegeben", "entwurf"):
            flash("Text von Beitrag %d kann nicht überarbeitet werden (Status: %s)." % (eid, e["status"]))
            return redirect(ziel)
        thema = conn.execute("SELECT titel, volltext FROM themen WHERE id=?", (e["thema_id"],)).fetchone() \
            if e["thema_id"] else None
        kanal = e["kanal"] or "google"
    try:
        prev = json.loads(e["text"])
    except Exception:
        prev = {}
    try:
        th = {"titel": thema["titel"] if thema else "", "volltext": (thema["volltext"] if thema else "") or ""}
        neu = textgen.regenerate(th, prev, feedback, kanal)
        # Slogan und Bild-Felder aus dem vorherigen Beitrag uebernehmen (regenerate liefert sie nicht)
        for k, dflt in (("slogan", ""), ("bild_motiv", ""), ("bild_motiv_thema", ""), ("bild_typ", "person")):
            neu.setdefault(k, prev.get(k, dflt))
        import bildmotiv
        photo = bildmotiv.ensure_photo_fuer(neu)   # Motiv aus Cache -> keine Bild-KI-Kosten
        slogan = bildgen.pick_slogan(neu.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(neu, photo, slogan, out)
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(neu, ensure_ascii=False), out, eid))
            audit_log(conn, session["user"], "text_ueberarbeitet", eid, feedback)
            conn.commit()
        flash("Text von Beitrag %d überarbeitet (Bild an den neuen Text angepasst) - bitte prüfen." % eid)
    except Exception as ex:
        flash("Text-Überarbeitung fehlgeschlagen: %s" % ex)
    return redirect(ziel)

@app.route("/bild-neu/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def bild_neu(eid):
    """Rendert NUR das Bild eines Beitrags neu (aktuelles Layout, bestehendes Motiv aus dem Cache) -
    ohne Text- oder Motiv-Neuerzeugung, also ohne KI-Kosten. Text, Status und Termin bleiben."""
    zurueck = request.form.get("zurueck", "einplanung")
    ziel = url_for("entwuerfe") if zurueck == "entwuerfe" else url_for("einplanung")
    with get_conn() as conn:
        e = conn.execute("SELECT id, text, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    if e["status"] not in ("freigegeben", "entwurf"):
        flash("Bild von Beitrag %d kann nicht neu erzeugt werden (Status: %s)." % (eid, e["status"]))
        return redirect(ziel)
    try:
        import bildmotiv
        data = json.loads(e["text"])
        photo = bildmotiv.ensure_photo_fuer(data)   # Cache -> kein neuer KI-Aufruf
        slogan = bildgen.pick_slogan(data.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(data, photo, slogan, out)
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (out, eid))
            audit_log(conn, session["user"], "bild_neu_erzeugt", eid)
            conn.commit()
        flash("Bild von Beitrag %d neu erzeugt (Text unverändert)." % eid)
    except Exception as ex:
        flash("Bild konnte nicht neu erzeugt werden: %s" % ex)
    return redirect(ziel)

@app.route("/bild-typ/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def bild_typ(eid):
    """Stellt den Bildtyp eines Beitrags um: 'person' (Beratungsszene) <-> 'thema' (gegenstaendliches
    Themenbild) und rendert das Bild entsprechend neu. Beim Wechsel auf 'thema' wird ggf. ein neues
    Themenbild bei der Bild-KI erzeugt (Kosten); 'person' nutzt i.d.R. das gecachte Motiv."""
    zurueck = request.form.get("zurueck", "beitrag")
    ziel = (url_for("entwuerfe") if zurueck == "entwuerfe"
            else url_for("einplanung") if zurueck == "einplanung"
            else url_for("beitrag", eid=eid))
    neuer_typ = "thema" if request.form.get("typ") == "thema" else "person"
    with get_conn() as conn:
        e = conn.execute("SELECT id, text, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    if e["status"] not in ("freigegeben", "entwurf"):
        flash("Bildtyp von Beitrag %d kann nicht geändert werden (Status: %s)." % (eid, e["status"]))
        return redirect(ziel)
    try:
        import bildmotiv
        data = json.loads(e["text"])
        if neuer_typ == "thema" and not (data.get("bild_motiv_thema") or "").strip():
            flash("Für Beitrag %d gibt es kein Themenbild-Motiv. Bitte den Beitrag einmal neu erzeugen, "
                  "dann steht das Themenbild zur Verfügung." % eid)
            return redirect(ziel)
        data["bild_typ"] = neuer_typ
        photo = bildmotiv.ensure_photo_fuer(data)
        slogan = bildgen.pick_slogan(data.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(data, photo, slogan, out)
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), out, eid))
            audit_log(conn, session["user"], "bild_typ_%s" % neuer_typ, eid)
            conn.commit()
        flash("Beitrag %d nutzt jetzt das %s." % (eid, "Themenbild" if neuer_typ == "thema" else "Personenbild"))
    except Exception as ex:
        flash("Bildtyp konnte nicht umgestellt werden: %s" % ex)
    return redirect(ziel)

AUSWERTUNG = """<!doctype html><meta charset=utf-8><title>Was funktioniert</title><style>""" + _STYLE + """
.awbox{max-width:780px;margin:0 auto 14px}
table.aw{width:100%;border-collapse:collapse}
table.aw td{padding:4px 0;vertical-align:middle}
.bar{background:#e7edf6;border-radius:6px;overflow:hidden}
.bar>div{background:#1f428d;height:18px;border-radius:6px}
</style>
<div style="max-width:780px;margin:0 auto 10px"><div class=top><h2 style="margin:0;color:#1f428d">&#x1F4CA; Was funktioniert</h2><a href="/" style="color:#1f428d;text-decoration:none;font-weight:bold">&larr; Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div style="max-width:780px;margin:0 auto"><div class=flash>{{m[0]}}</div></div>{% endif %}{% endwith %}
<div class=awbox>
<p class=hint>Ausgewertet nach <b>Reichweite</b> – wie viele Personen den Beitrag gesehen haben. {% if stand %}Letzter Abruf: {{stand}} (UTC).{% endif %}</p>
<form method=post action="/insights-abrufen"><button>Zahlen jetzt aktualisieren</button>{% if offen %} <span class=hint>&nbsp;{{offen}} Beitrag(e) noch ohne Zahlen</span>{% endif %}</form>
</div>
{% if not gesamt %}
<div class="box awbox"><p>Noch keine ausgewerteten Beiträge. Sobald Beiträge veröffentlicht sind, hier auf <b>„Zahlen jetzt aktualisieren"</b> klicken – dann holt das Tool die Reichweite von Facebook und Instagram.</p>
<p class=hint>Aussagekräftig wird die Auswertung erst nach einigen Wochen mit genügend Beiträgen – am Anfang sind es nur Tendenzen.</p></div>
{% else %}
<div class=awbox><p class=hint>{{gesamt}} ausgewertete Veröffentlichung(en). Längerer Balken = höhere durchschnittliche Reichweite.</p></div>
{% macro rang(titel, rows) %}
<div class="box awbox"><h3 style="margin:.1em 0 .4em">{{titel}}</h3>
{% if not rows %}<p class=hint>Noch keine Daten.</p>{% else %}{% set maxv = rows[0].schnitt or 1 %}
<table class=aw>{% for r in rows %}<tr>
<td style="white-space:nowrap;padding-right:10px">{{r.label}}</td>
<td style="width:100%"><div class=bar><div style="width:{{ (r.schnitt*100//maxv) if maxv else 0 }}%"></div></div></td>
<td style="white-space:nowrap;padding-left:10px"><b>{{r.schnitt}}</b> <span class=hint>(Schnitt aus {{r.anzahl}})</span></td>
</tr>{% endfor %}</table>{% endif %}</div>
{% endmacro %}
{{ rang("Nach Content-Stream", nach_stream) }}
{{ rang("Nach Uhrzeit", nach_zeit) }}
{{ rang("Nach Bildtyp", nach_bildtyp) }}
{{ rang("Nach Kanal", nach_kanal) }}
{{ rang("Nach Wochentag", nach_wochentag) }}
<div class="box awbox"><h3 style="margin:.1em 0 .4em">Top-Beiträge nach Reichweite</h3>
<table class=aw><tr><th style="text-align:left">Titel</th><th>Kanal</th><th>Reichweite</th><th>Interaktionen</th></tr>
{% for t in top %}<tr><td>{{t.titel or '(ohne Titel)'}}</td><td style="text-align:center">{{t.kanal}}</td><td style="text-align:center"><b>{{t.reichweite}}</b></td><td style="text-align:center">{{t.interaktionen}}</td></tr>{% endfor %}</table></div>
{% endif %}"""

@app.route("/insights-abrufen", methods=["POST"])
@rolle_required("freigeber")
def insights_abrufen():
    """Holt die aktuellen Reichweiten-/Interaktionszahlen aller veroeffentlichten Beitraege."""
    try:
        ok, fehler = _insights_aktualisieren()
        if ok or fehler:
            flash("Zahlen aktualisiert: %d Beitrag/Beitraege abgerufen%s."
                  % (ok, (", %d fehlgeschlagen" % fehler) if fehler else ""))
        else:
            flash("Keine veröffentlichten Beiträge mit Plattform-ID zum Abrufen gefunden.")
    except Exception as ex:
        flash("Abruf fehlgeschlagen: %s" % ex)
    return redirect(url_for("auswertung"))

@app.route("/auswertung")
@login_required
def auswertung():
    """Dashboard 'Was funktioniert' - Reichweiten-Auswertung der veroeffentlichten Beitraege."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.reichweite AS reichweite, p.interaktionen AS interaktionen, p.kanal AS kanal, "
            "p.veroeffentlicht_am AS wann, p.insights_am AS insights_am, e.text AS etext, t.quelle AS quelle "
            "FROM posts p LEFT JOIN entwuerfe e ON e.id=p.entwurf_id LEFT JOIN themen t ON t.id=e.thema_id "
            "WHERE p.status='veroeffentlicht' AND p.reichweite IS NOT NULL "
            "ORDER BY p.reichweite DESC").fetchall()
        offen = conn.execute("SELECT COUNT(*) FROM posts WHERE status='veroeffentlicht' "
                             "AND plattform_post_id IS NOT NULL AND plattform_post_id!='' "
                             "AND seite IS NOT NULL AND seite!='' AND reichweite IS NULL").fetchone()[0]
    items = []
    for r in rows:
        bildtyp, titel = "Personenbild", ""
        try:
            f = json.loads(r["etext"]) if r["etext"] else {}
            bildtyp = "Themenbild" if f.get("bild_typ") == "thema" else "Personenbild"
            titel = f.get("ueberschrift") or ""
        except Exception:
            pass
        items.append({"reichweite": r["reichweite"] or 0, "interaktionen": r["interaktionen"] or 0,
                      "kanal": _KANAL_DE.get(r["kanal"], r["kanal"]), "wann": r["wann"],
                      "stream": _stream(r["quelle"]), "bildtyp": bildtyp, "titel": titel})
    stand = max([r["insights_am"] for r in rows if r["insights_am"]], default=None)
    return render_template_string(AUSWERTUNG, **_ctx(
        gesamt=len(items), offen=offen, stand=stand, top=items[:8],
        nach_stream=_rang(items, lambda it: it["stream"]),
        nach_kanal=_rang(items, lambda it: it["kanal"]),
        nach_bildtyp=_rang(items, lambda it: it["bildtyp"]),
        nach_zeit=_rang(items, lambda it: _zeitfenster(it["wann"])),
        nach_wochentag=_rang(items, lambda it: _wochentag(it["wann"]))))

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

@app.route("/kalender")
@login_required
def kalender():
    import calendar as _cal, datetime
    heute = datetime.date.today()
    try:
        jahr = min(2100, max(2000, int(request.args.get("jahr", heute.year))))
        monat = min(12, max(1, int(request.args.get("monat", heute.month))))
    except (ValueError, TypeError):
        jahr, monat = heute.year, heute.month
    praefix = "%04d-%02d-" % (jahr, monat)
    posts, besondere = {}, {}
    with get_conn() as conn:
        for e in conn.execute("SELECT id, text, geplant_fuer, status, format FROM entwuerfe "
                             "WHERE geplant_fuer LIKE ?", (praefix + "%",)):
            try:
                titel = (json.loads(e["text"]).get("ueberschrift") or "Beitrag")
            except Exception:
                titel = "Beitrag"
            posts.setdefault(e["geplant_fuer"], []).append(
                {"id": e["id"], "titel": titel, "status": e["status"], "format": e["format"] or "einzelbild"})
        anlass_rows = conn.execute("SELECT datum, anlass FROM anlasstage WHERE aktiv=1").fetchall()
    import anlass as _anl, fristen
    for a in anlass_rows:
        pt = _anl._post_tag(a["datum"], jahr)
        if pt and pt.month == monat and pt.year == jahr:
            besondere.setdefault(pt.isoformat(), []).append(a["anlass"])
    for fr in fristen.FRISTEN:
        fd = fristen._frist_datum(fr)
        if fd.month == monat and fd.year == jahr:
            besondere.setdefault(fd.isoformat(), []).append("Fristende: " + fr["name"])
    wochen = []
    for woche in _cal.Calendar(firstweekday=0).monthdatescalendar(jahr, monat):
        zeile = []
        for d in woche:
            iso = d.isoformat()
            zeile.append({"tag": d.day, "iso": iso, "im_monat": d.month == monat, "we": d.weekday() >= 5,
                          "heute": d == heute, "past": d < heute, "posts": posts.get(iso, []),
                          "besondere": besondere.get(iso, [])})
        wochen.append(zeile)
    erster = datetime.date(jahr, monat, 1)
    prev = (erster - datetime.timedelta(days=1)).replace(day=1)
    nxt = (erster + datetime.timedelta(days=31)).replace(day=1)
    return render_template_string(KALENDER, **_ctx(
        wochen=wochen, jahr=jahr, monat=monat, monatname=MONATE[monat],
        prev=prev, nxt=nxt, prev_name=MONATE[prev.month], nxt_name=MONATE[nxt.month]))

@app.route("/beitrag/<int:eid>")
@login_required
def beitrag(eid):
    """Detailansicht eines Beitrags - bei Karussell werden ALLE Slides gezeigt (kein Blackbox)."""
    with get_conn() as conn:
        e = conn.execute("SELECT id, text, geplant_fuer, status, format, thema_id FROM entwuerfe WHERE id=?",
                         (eid,)).fetchone()
        if not e:
            abort(404)
        quelle_url = ""
        if e["thema_id"]:
            t = conn.execute("SELECT url FROM themen WHERE id=?", (e["thema_id"],)).fetchone()
            quelle_url = (t["url"] or "").strip() if t else ""
    row = _parse(e)
    fmt = row.get("format", "einzelbild")
    n_slides = 0
    if fmt == "karussell":
        try:
            import bildmotiv
            data = row["f"]
            photo = bildmotiv.ensure_photo_fuer(data)   # Cache -> kein neuer KI-Aufruf
            slogan = bildgen.pick_slogan(data.get("slogan"))
            out_dir = os.path.join(DATA_DIR, "preview", "karussell_%d" % eid)
            n_slides = len(bildgen.render_slides(data, photo, slogan, out_dir, "slide"))
        except Exception as ex:
            log.warning("Karussell-Vorschau fehlgeschlagen (Beitrag %s): %s", eid, ex)
            n_slides = 0
    # WhatsApp-Varianten: eigener Kanal-Text (max 3 Saetze) + Status-Text (max 2 Saetze),
    # je mit eingebettetem Quell-/Buchungslink. Allgemein + personalisiert je Beratungsstelle.
    import personalisierung
    wa_allg_kanal, wa_allg_story = personalisierung.whatsapp_texte(row["f"], None, quelle_url)
    wa_stellen = []
    try:
        with get_conn() as conn:
            stellen = conn.execute("SELECT * FROM beratungsstellen WHERE aktiv=1 AND fb_seite IS NOT NULL "
                                   "AND fb_seite!='' ORDER BY ort").fetchall()
        for st in stellen:
            wk, ws = personalisierung.whatsapp_texte(row["f"], st, quelle_url)
            wa_stellen.append({"id": st["id"], "name": st["name"], "ort": st["ort"] or "",
                               "kanal": wk, "story": ws})
    except Exception:
        log.exception("WhatsApp-Stellen-Varianten fehlgeschlagen (Beitrag %s)", eid)
        wa_stellen = []
    return render_template_string(BEITRAG, **_ctx(e=row, fmt=fmt, status=e["status"], n_slides=n_slides,
                                  wa_stellen=wa_stellen, wa_allg_kanal=wa_allg_kanal, wa_allg_story=wa_allg_story))

@app.route("/beitrag-slide/<int:eid>/<int:idx>")
@login_required
def beitrag_slide(eid, idx):
    base = os.path.realpath(os.path.join(DATA_DIR, "preview", "karussell_%d" % eid))
    p = os.path.realpath(os.path.join(base, "slide_%02d.png" % (idx + 1)))
    if not (p == base or p.startswith(base + os.sep)) or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png", max_age=0)

def _status_hochkant(square_path, out_path):
    """Komponiert ein quadratisches Bild zentriert auf einen HILO-Verlauf (9:16, 1080x1920) -
    fuer WhatsApp-Status / Instagram-Story. Liefert out_path."""
    from PIL import Image
    W, H = 1080, 1920
    top, bot = (31, 66, 141), (96, 163, 60)
    grad = Image.new("RGB", (1, H)); gp = grad.load()
    for y in range(H):
        t = y / (H - 1)
        gp[0, y] = (int(top[0] + (bot[0]-top[0])*t), int(top[1] + (bot[1]-top[1])*t),
                    int(top[2] + (bot[2]-top[2])*t))
    canvas = grad.resize((W, H), Image.BILINEAR)
    sq = Image.open(square_path).convert("RGB").resize((W, W), Image.LANCZOS)
    canvas.paste(sq, (0, (H - W) // 2))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas.save(out_path)
    return out_path

def _render_stelle_bild(eid, sid):
    """Rendert das PERSONALISIERTE Einzelbild fuer (Beitrag, Beratungsstelle) - mit Portraet-Kreis,
    Ort und personalisiertem CTA. Liefert den Pfad oder None."""
    with get_conn() as conn:
        e = conn.execute("SELECT id, text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        st = conn.execute("SELECT * FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
    if not e or not st:
        return None
    import personalisierung
    data = json.loads(e["text"])
    out = os.path.join(DATA_DIR, "preview", "wa_e%d_stelle_%d.png" % (eid, int(st["id"])))
    personalisierung.render_fuer_stelle(data, st, out)
    return out

@app.route("/bild-status/<int:eid>")
@login_required
def bild_status(eid):
    """Hochkant-Version (9:16) des allgemeinen Beitragsbildes fuer WhatsApp-Status / Story."""
    with get_conn() as conn:
        e = conn.execute("SELECT id, bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e or not e["bild_pfad"] or not os.path.exists(e["bild_pfad"]):
        abort(404)
    out = _status_hochkant(e["bild_pfad"], os.path.join(DATA_DIR, "preview", "status_%d.png" % eid))
    return send_file(out, mimetype="image/png", max_age=0,
                     as_attachment=True, download_name="hilo_status_%d.png" % eid)

@app.route("/bild-stelle/<int:eid>/<int:sid>")
@login_required
def bild_stelle(eid, sid):
    """Personalisiertes Einzelbild (Portraet-Kreis + Ort) der Beratungsstelle zum Download."""
    try:
        p = _render_stelle_bild(eid, sid)
    except Exception:
        log.exception("WhatsApp-Bild (Stelle) fehlgeschlagen (Beitrag %s, Stelle %s)", eid, sid); p = None
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png", max_age=0,
                     as_attachment=True, download_name="hilo_%d_stelle_%d.png" % (eid, sid))

@app.route("/bild-status-stelle/<int:eid>/<int:sid>")
@login_required
def bild_status_stelle(eid, sid):
    """Hochkant-Status-Version des PERSONALISIERTEN Bildes der Beratungsstelle."""
    try:
        p = _render_stelle_bild(eid, sid)
    except Exception:
        log.exception("WhatsApp-Status (Stelle) fehlgeschlagen (Beitrag %s, Stelle %s)", eid, sid); p = None
    if not p or not os.path.exists(p):
        abort(404)
    out = _status_hochkant(p, os.path.join(DATA_DIR, "preview", "wa_status_e%d_stelle_%d.png" % (eid, sid)))
    return send_file(out, mimetype="image/png", max_age=0,
                     as_attachment=True, download_name="hilo_status_%d_stelle_%d.png" % (eid, sid))

@app.route("/themen", methods=["GET", "POST"])
@login_required
def themen():
    with get_conn() as conn:
        if request.method == "POST":
            ids = request.form.getlist("thema_ids")
            aktion = request.form.get("aktion")
            if ids and aktion in ("auswaehlen", "verwerfen"):
                ziel = "ausgewaehlt" if aktion == "auswaehlen" else "verworfen"
                q = "UPDATE themen SET status=? WHERE id IN (%s) AND status='vorgeschlagen'" % ",".join("?" * len(ids))
                conn.execute(q, [ziel] + ids)
                audit_log(conn, session["user"], "themen_" + aktion, None, "%d Themen" % len(ids))
                conn.commit()
                if ziel == "ausgewaehlt":
                    flash("%d Themen freigegeben. Auf der Startseite 'Texte & Bilder erzeugen' klicken." % len(ids))
                else:
                    flash("%d Themen verworfen." % len(ids))
            else:
                flash("Bitte mindestens ein Thema markieren.")
        rows = conn.execute("SELECT id, quelle, titel, url FROM themen WHERE status='vorgeschlagen' "
                            "ORDER BY quelle, id DESC").fetchall()
    return render_template_string(THEMEN, **_ctx(themen=rows))

@app.route("/thema-loeschen/<int:tid>", methods=["POST"])
@login_required
def thema_loeschen(tid):
    """Markiert ein einzelnes Thema als geloescht (aus Themen-Liste oder Erzeugen-Uebersicht).

    Soft-Delete: Die Zeile (und ihr UNIQUE-hash) bleibt erhalten, damit der Themen-Radar das
    bereits gepruefte Thema beim naechsten Lauf nicht erneut als 'neu' einliest - sonst kaeme
    es nach dem Loeschen wieder zurueck. Aus den Listen verschwindet es trotzdem, weil diese
    nur 'vorgeschlagen'/'ausgewaehlt' anzeigen (analog zum 'verworfen'-Status)."""
    zurueck = request.form.get("zurueck", "themen")
    with get_conn() as conn:
        # Soft-Delete nur, solange das Thema KEINEN Entwurf hat (schliesst das Zeitfenster zwischen
        # Anzeige und Klick - kein verwaister entwuerfe-Eintrag, da SQLite hier keine FK erzwingt)
        cur = conn.execute("UPDATE themen SET status='geloescht' WHERE id=? AND status!='geloescht' "
                           "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=themen.id)", (tid,))
        if cur.rowcount > 0:
            audit_log(conn, session["user"], "thema_geloescht", None, "Thema %d" % tid)
            flash("Thema gelöscht.")
        else:
            flash("Thema wurde nicht gelöscht (es hat bereits einen Entwurf oder existiert nicht mehr).")
        conn.commit()
    return redirect(url_for("erzeugen") if zurueck == "erzeugen" else url_for("themen"))

@app.route("/quellen", methods=["GET", "POST"])
@login_required
def quellen():
    import ingest
    if request.method == "POST":
        f = request.files.get("pdf")
        url = request.form.get("url", "").strip()
        try:
            if f and f.filename:
                if not f.filename.lower().endswith(".pdf"):
                    flash("Bitte eine PDF-Datei waehlen."); return redirect(url_for("quellen"))
                updir = os.path.join(DATA_DIR, "uploads"); os.makedirs(updir, exist_ok=True)
                dest = os.path.join(updir, secure_filename(f.filename)); f.save(dest)
                n = ingest.add_pdf(dest)
                with get_conn() as conn:
                    audit_log(conn, session["user"], "quelle_pdf", None, "%s (%d Themen)" % (os.path.basename(dest), n)); conn.commit()
                flash("PDF analysiert: %d Thema/Themen erkannt und zur Texterstellung vorgemerkt." % n)
            elif url:
                n = ingest.add_url(url)
                with get_conn() as conn:
                    audit_log(conn, session["user"], "quelle_link", None, "%s (%d Themen)" % (url, n)); conn.commit()
                flash("Link analysiert: %d Thema/Themen erkannt und zur Texterstellung vorgemerkt." % n)
            else:
                flash("Bitte ein PDF hochladen oder einen Link angeben.")
        except Exception as ex:
            flash("Analyse fehlgeschlagen: %s" % ex)
        return redirect(url_for("quellen"))
    with get_conn() as conn:
        rows = conn.execute("SELECT quelle, titel, url, status FROM themen "
                            "WHERE quelle IN ('pdf','link') ORDER BY id DESC LIMIT 20").fetchall()
    return render_template_string(QUELLEN, **_ctx(quellen=rows))

@app.route("/radar", methods=["POST"])
@login_required
def radar_starten():
    try:
        import radar
        neu = radar.run()
        flash("Themen aktualisiert: %d neue Themen aus den Quellen." % neu)
    except Exception as ex:
        flash("Radar fehlgeschlagen: %s" % ex)
    return redirect(url_for("themen"))

@app.route("/generieren", methods=["POST"])
@login_required
def generieren():
    with _gen_lock:   # gleicher Lock wie /erzeugen - kein paralleler Start ueber beide Wege
        if _generation_running():
            flash("Erzeugung läuft bereits - einen Moment, dann Seite neu laden.")
        else:
            with get_conn() as conn:
                offen = conn.execute("SELECT COUNT(*) FROM themen t WHERE t.status='ausgewaehlt' "
                                     "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=t.id)").fetchone()[0]
            if not offen:
                flash("Keine ausgewählten Themen offen. Erst unter 'Freigabe: Themen' Themen freigeben.")
            else:
                try:
                    anzahl = int(request.form.get("anzahl", offen))
                except (TypeError, ValueError):
                    anzahl = offen
                anzahl = max(1, min(anzahl, offen))   # auf die verfügbaren Themen begrenzen
                try:
                    _start_generation(anzahl)
                    flash("Erzeugung für %d von %d Themen gestartet - läuft im Hintergrund. "
                          "In ein bis zwei Minuten die Seite neu laden." % (anzahl, offen))
                except Exception as ex:
                    flash("Erzeugung konnte nicht gestartet werden: %s" % ex)
    return redirect(url_for("index"))

@app.route("/erzeugen", methods=["GET", "POST"])
@login_required
def erzeugen():
    if request.method == "POST":
        ids = [i for i in request.form.getlist("thema_id") if i.strip().isdigit()]
        if not ids:
            flash("Bitte mindestens ein Thema anhaken."); return redirect(url_for("erzeugen"))
        with _gen_lock:   # Pruefen+Starten atomar, sonst koennten zwei Klicks zwei Prozesse starten
            if _generation_running():
                flash("Erzeugung läuft bereits - einen Moment, dann die Startseite neu laden.")
                return redirect(url_for("index"))
            try:
                _start_generation_ids(ids)
                flash("Erzeugung für %d ausgewählte Thema/Themen gestartet - läuft im Hintergrund. "
                      "In ein bis zwei Minuten die Startseite neu laden." % len(ids))
            except Exception as ex:
                flash("Erzeugung konnte nicht gestartet werden: %s" % ex)
        return redirect(url_for("index"))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, titel, quelle, erkannt_am FROM themen t WHERE status='ausgewaehlt' "
            "AND NOT EXISTS (SELECT 1 FROM entwuerfe e WHERE e.thema_id=t.id) "
            "ORDER BY erkannt_am DESC").fetchall()
    # nach Quelle gruppieren (Unterkacheln) - uebersichtlicher als eine flache Liste
    gruppen_map = {}
    for r in rows:
        gruppen_map.setdefault(r["quelle"] or "", []).append(r)
    gruppen = [{"quelle": q, "label": _quelle_label(q), "themen": ts}
               for q, ts in sorted(gruppen_map.items(), key=lambda kv: _quelle_label(kv[0]).lower())]
    return render_template_string(ERZEUGEN, **_ctx(themen=rows, gruppen=gruppen, laeuft=_generation_running()))

@app.route("/eigener", methods=["GET", "POST"])
@rolle_required("freigeber")
def eigener():
    if request.method == "POST":
        import datetime, hashlib
        thema_txt = request.form.get("thema", "").strip()
        datum = request.form.get("datum", "").strip()
        if not thema_txt or not datum:
            flash("Bitte Thema und Tag angeben."); return redirect(url_for("eigener"))
        try:
            d = datetime.date.fromisoformat(datum)
        except ValueError:
            flash("Ungültiges Datum."); return redirect(url_for("eigener"))
        if d < datetime.date.today():
            flash("Der Tag liegt in der Vergangenheit – bitte einen Tag ab heute wählen.")
            return redirect(url_for("eigener"))
        # Zuerst den Beitrag erzeugen (Claude) - noch KEIN DB-Schreiben, falls es fehlschlaegt
        try:
            data = textgen.generate({"titel": thema_txt, "volltext": thema_txt, "url": None}, "google")
        except Exception as ex:
            flash("Erstellung fehlgeschlagen (Texterzeugung): %s" % ex)
            return redirect(url_for("eigener"))
        # Thema + Entwurf in EINER Transaktion (kein verwaistes Thema, kein Race mit /generieren,
        # das ein 'ausgewaehlt'-Thema ohne Entwurf doppelt aufgreifen koennte)
        h = hashlib.sha256(("eigen:%s:%s:%s" % (thema_txt, datum,
                            datetime.datetime.now().isoformat())).encode("utf-8")).hexdigest()
        with get_conn() as conn:
            cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                               "VALUES ('eigen', ?, 'ausgewaehlt', ?, ?)", (thema_txt[:300], thema_txt, h))
            thema_id = cur.lastrowid
            conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer) "
                         "VALUES (?, 'google', ?, 'entwurf', ?)",
                         (thema_id, json.dumps(data, ensure_ascii=False), datum))
            audit_log(conn, session["user"], "eigener_beitrag", None, "Thema '%s' fuer %s" % (thema_txt[:60], datum))
            conn.commit()
        try:
            bildgen.render_drafts()
        except Exception:
            pass   # Bild wird sonst beim naechsten Lauf nachgerendert; Entwurf existiert bereits
        flash("Beitrag-Entwurf zum Thema „%s“ für %s erstellt – jetzt unter „3. Freigabe: Texte & Bilder“ "
              "prüfen und freigeben." % (thema_txt[:60], _de_datum(datum)))
        return redirect(url_for("entwuerfe"))
    # GET: Vorgaben aus dem Kalender-Klick (Datum, optional Thema aus einem Anlass-Tag)
    vorgabe_datum = request.args.get("datum", "").strip()
    vorgabe_thema = request.args.get("thema", "").strip()
    anlass = request.args.get("anlass", "").strip()
    if anlass and not vorgabe_thema:
        with get_conn() as conn:
            row = conn.execute("SELECT anlass, steuer_hook FROM anlasstage WHERE anlass=?", (anlass,)).fetchone()
        if row:
            vorgabe_thema = ("%s – %s" % (row["anlass"], row["steuer_hook"] or "")).strip(" –")
        else:
            vorgabe_thema = anlass
    return render_template_string(EIGENER, **_ctx(vorgabe_datum=vorgabe_datum, vorgabe_thema=vorgabe_thema))

@app.route("/bild/<int:eid>")
@login_required
def bild(eid):
    with get_conn() as conn:
        e = conn.execute("SELECT bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e or not e["bild_pfad"] or not os.path.exists(e["bild_pfad"]):
        abort(404)
    return send_file(e["bild_pfad"], mimetype="image/png")

@app.route("/aktion/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def aktion(eid):
    aktion = request.form.get("aktion")
    feedback = request.form.get("feedback", "").strip()
    user = session["user"]
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        if aktion == "freigeben":
            # Bereits gesetzter Termin (z.B. Fristen-Countdown, eigener Beitrag) bleibt erhalten;
            # ansonsten startet der Beitrag bewusst OHNE Termin ("Noch nicht geplant").
            termin = e["geplant_fuer"] if "geplant_fuer" in e.keys() else None
            conn.execute("UPDATE entwuerfe SET status='freigegeben', geplant_fuer=? WHERE id=?", (termin, eid))
            audit_log(conn, user, "freigegeben", eid, "geplant fuer %s" % (termin or "(noch offen)"))
            if termin:
                flash("Entwurf %d freigegeben und für %s eingeplant." % (eid, _de_datum(termin)))
            else:
                flash("Entwurf %d freigegeben – Termin unter „4. Einplanung\" mit einem Klick bestätigen." % eid)
        elif aktion == "verwerfen":
            conn.execute("UPDATE entwuerfe SET status='verworfen' WHERE id=?", (eid,))
            audit_log(conn, user, "verworfen", eid); flash("Entwurf %d verworfen." % eid)
        elif aktion == "loeschen":
            if e["bild_pfad"] and os.path.exists(e["bild_pfad"]):
                try:
                    os.remove(e["bild_pfad"])
                except Exception:
                    pass
            conn.execute("DELETE FROM entwuerfe WHERE id=?", (eid,))
            audit_log(conn, user, "entwurf_geloescht", eid); flash("Entwurf %d gelöscht." % eid)
        elif aktion == "ueberarbeiten":
            if not feedback:
                flash("Bitte einen Änderungswunsch angeben."); return redirect(url_for("entwuerfe"))
            t = conn.execute("SELECT titel, volltext FROM themen WHERE id=?", (e["thema_id"],)).fetchone()
            thema = {"titel": t["titel"] if t else "", "volltext": (t["volltext"] if t else "") or ""}
            try:
                prev = json.loads(e["text"])
            except Exception:
                prev = {}
            try:
                neu = textgen.regenerate(thema, prev, feedback, e["kanal"])
                # Slogan und Bild-Felder aus dem vorherigen Beitrag uebernehmen (regenerate liefert sie nicht)
                neu.setdefault("slogan", prev.get("slogan", ""))
                neu.setdefault("bild_motiv", prev.get("bild_motiv", ""))
                neu.setdefault("bild_motiv_thema", prev.get("bild_motiv_thema", ""))
                neu.setdefault("bild_typ", prev.get("bild_typ", "person"))
                conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=NULL WHERE id=?", (json.dumps(neu, ensure_ascii=False), eid))
                conn.commit(); bildgen.render_drafts()
                audit_log(conn, user, "ueberarbeitet", eid, feedback); conn.commit()
                flash("Entwurf %d überarbeitet (neuer Vorschlag erstellt)." % eid)
            except Exception as ex:
                flash("Überarbeitung fehlgeschlagen: %s" % ex)
        conn.commit()
    return redirect(url_for("entwuerfe"))

def _publish_instagram(publish, fb_page_id, bilder, caption, fmt, eid, stelle_id, location_id=None):
    """Instagram-Veroeffentlichung: Bild(er) oeffentlich hochladen (IONOS) -> https-URL(s),
    das mit der Facebook-Seite verknuepfte IG-Konto ermitteln, dann posten. (ok, info).
    location_id = optionale Facebook-Orts-ID fuer den Geotag."""
    import uploader, time
    if not uploader.configured():
        return False, ("Instagram-Bild-Upload nicht konfiguriert (Secrets ionos_sftp_* + "
                       "ionos_public_base_url auf dem Pi setzen).")
    ig_id = None
    for pg in publish.list_pages():
        if str(pg.get("id")) == str(fb_page_id):
            ig_id = pg.get("ig_id"); break
    if not ig_id:
        return False, "Keine Instagram-Verknuepfung fuer diese Facebook-Seite gefunden."
    valid = [b for b in bilder if b and os.path.exists(b)]
    if not valid:
        return False, "Kein Bild zum Hochladen vorhanden."
    stamp = int(time.time())
    urls = [uploader.upload(b, remote_name="e%d_%s_%d_%d.png" % (eid, stelle_id or "p", stamp, i))
            for i, b in enumerate(valid)]
    if fmt == "karussell" and len(urls) > 1:
        return publish.publish_instagram_carousel(ig_id, urls, caption, location_id=location_id)
    return publish.publish_instagram(ig_id, urls[0], caption, location_id=location_id)

def _publish_story(publish, fb_page_id, bilder, eid, stelle_id):
    """Postet die uebergebenen Bilder NACHEINANDER als Instagram-Story-Frames (9:16) - so erscheint
    ein Karussell als mehrteilige Story. Jeder Slide wird auf 9:16 gebracht, oeffentlich hochgeladen
    (IONOS) und als eigene Story veroeffentlicht. (ok, info) - ok, wenn mind. ein Frame gepostet wurde."""
    import uploader, time
    if not uploader.configured():
        return False, "Bild-Upload nicht konfiguriert (IONOS-Secrets fehlen)."
    valid = [b for b in (bilder or []) if b and os.path.exists(b)]
    if not valid:
        return False, "Kein Bild fuer die Story vorhanden."
    ig_id = None
    for pg in publish.list_pages():
        if str(pg.get("id")) == str(fb_page_id):
            ig_id = pg.get("ig_id"); break
    if not ig_id:
        return False, "Keine Instagram-Verknuepfung fuer diese Facebook-Seite."
    stamp = int(time.time())
    gemacht, fehler = 0, []
    for i, square in enumerate(valid):
        out = os.path.join(DATA_DIR, "bilder", "story_%d_%s_%d.png" % (eid, stelle_id or "p", i))
        try:
            _status_hochkant(square, out)
            url = uploader.upload(out, remote_name="story_e%d_%s_%d_%d.png" % (eid, stelle_id or "p", stamp, i))
        except Exception as ex:
            fehler.append("Frame %d: %s" % (i + 1, ex)); continue
        s_ok, s_info = publish.publish_instagram_story(ig_id, url)
        if s_ok:
            gemacht += 1
        else:
            fehler.append("Frame %d: %s" % (i + 1, s_info))
    if gemacht:
        msg = "%d/%d Story-Bilder gepostet" % (gemacht, len(valid))
        return True, (msg + " (" + "; ".join(fehler) + ")") if fehler else msg
    return False, "; ".join(fehler) or "Story fehlgeschlagen"


def _veroeffentliche_ziel(conn, e, eid, f, fmt_fb, fmt_ig, kanal, stelle, page_id, user, publish, story=True):
    """Veroeffentlicht den Entwurf an EIN Ziel (Beratungsstelle personalisiert ODER Facebook-Seite).
    Das Bildformat ist je Kanal waehlbar: fmt_fb fuer Facebook, fmt_ig fuer Instagram
    (jeweils 'einzelbild' oder 'karussell'). Rueckgabe: (ziel_name, erfolg, [(kanal, ok, info), ...])."""
    stelle_id = str(stelle["id"]) if stelle else ""
    ziel_name = (stelle["name"] if stelle else page_id)
    ziel_seite = (stelle["fb_seite"] if stelle else page_id)
    # Orts-ID (Geotag) der Beratungsstelle - gilt fuer Facebook (place) UND Instagram (location_id).
    loc_id = (stelle["ort_id"] if (stelle and "ort_id" in stelle.keys() and stelle["ort_id"]) else None)
    _cache = {}

    def _caption(k):
        """Kanalspezifischer Begleittext, fuer eine Beratungsstelle zusaetzlich personalisiert."""
        if stelle:
            import personalisierung
            return personalisierung.caption_fuer_stelle(f, stelle, k)
        return textgen.caption_fuer(f, k) or f.get("ueberschrift") or ""

    def _render(fmt):
        """Bilderliste fuer dieses Format (gecacht). Das Bild ist kanalunabhaengig -
        nur der Begleittext (siehe _caption) unterscheidet sich je Kanal."""
        if fmt in _cache:
            return _cache[fmt]
        if stelle:
            import personalisierung
            if fmt == "karussell":
                out_dir = os.path.join(DATA_DIR, "bilder", "karussell_%d_stelle_%d" % (eid, int(stelle["id"])))
                _pf, bilder = personalisierung.render_slides_fuer_stelle(f, stelle, out_dir, "slide")
            else:
                out = os.path.join(DATA_DIR, "bilder", "post_%d_stelle_%d.png" % (eid, int(stelle["id"])))
                _pf, pfad = personalisierung.render_fuer_stelle(f, stelle, out); bilder = [pfad]
        else:
            if fmt == "karussell":
                import bildgen, bildmotiv
                out_dir = os.path.join(DATA_DIR, "bilder", "karussell_%d" % eid)
                photo = bildmotiv.ensure_photo_fuer(f)
                slogan = bildgen.pick_slogan(f.get("slogan"))
                bilder = bildgen.render_slides(f, photo, slogan, out_dir, "slide")
            else:
                bilder = [e["bild_pfad"]]
        bilder = [b for b in bilder if b and os.path.exists(b)]
        _cache[fmt] = bilder
        return bilder

    ergebnisse = []   # (kanal, ok, info)
    if kanal in ("facebook", "beide"):
        try:
            bilder = _render(fmt_fb)
            if not bilder:
                ok, info = False, "Kein Bild vorhanden"
            elif fmt_fb == "karussell":
                ok, info = publish.publish_facebook_carousel(ziel_seite, bilder, _caption("facebook"), place=loc_id)
            else:
                ok, info = publish.publish_facebook(ziel_seite, bilder[0], _caption("facebook"), place=loc_id)
        except Exception as ex:
            ok, info = False, str(ex)
        ergebnisse.append(("facebook", ok, info))
        # Erster Kommentar mit dem Termin-Link (FB-Caption verweist auf "Link in den Kommentaren").
        # Nur fuer Beratungsstellen mit hinterlegtem Buchungslink; rein protokolliert.
        if ok and stelle:
            import personalisierung
            link = personalisierung.buchungslink(stelle)
            if link:
                ort = (stelle["ort"] or "").strip()
                ktext = ("Termin vereinbaren bei Ihrer HILO-Beratungsstelle %s: %s" % (ort, link)) if ort \
                    else ("Termin vereinbaren: %s" % link)
                try:
                    k_ok, k_info = publish.comment_facebook(info, ziel_seite, ktext)
                except Exception as ex:
                    k_ok, k_info = False, str(ex)
                audit_log(conn, user, "fb_kommentar_%s" % ("ok" if k_ok else "fehler"), eid,
                          "Ziel %s / %s" % (ziel_seite, k_info))
    if kanal in ("instagram", "beide"):
        bilder = []
        try:
            bilder = _render(fmt_ig)
            if not bilder:
                ok, info = False, "Kein Bild vorhanden"
            else:
                ok, info = _publish_instagram(publish, ziel_seite, bilder, _caption("instagram"),
                                              fmt_ig, eid, stelle_id, location_id=loc_id)
        except Exception as ex:
            ok, info = False, str(ex)
        ergebnisse.append(("instagram", ok, info))
        # Zusaetzlich als Instagram-Story (9:16), wenn gewuenscht und der Feed-Post geklappt hat.
        # Story-Ergebnis wird nur protokolliert, nicht als eigener Post verbucht (Stories sind fluechtig).
        if story and ok:
            try:
                # Story = komplettes Karussell (alle Slides als Frames), unabhaengig vom Feed-Format.
                # _render('karussell') ist kanalunabhaengig gecacht -> kein doppeltes Rendern.
                slides = _render("karussell")
                s_ok, s_info = _publish_story(publish, ziel_seite, slides, eid, stelle_id)
            except Exception as ex:
                s_ok, s_info = False, str(ex)
            audit_log(conn, user, "instagram_story_%s" % ("ok" if s_ok else "fehler"), eid,
                      "Ziel %s / %s" % (ziel_seite, s_info))
    erfolg = False
    for k, ok, info in ergebnisse:
        if ok:
            erfolg = True
            conn.execute("INSERT INTO posts(entwurf_id, kanal, plattform_post_id, seite, "
                         "veroeffentlicht_am, status) VALUES (?,?,?,?,datetime('now'),'veroeffentlicht')",
                         (eid, k, info, ziel_seite))
            audit_log(conn, user, "veroeffentlicht_%s" % k, eid, "Ziel %s / Post %s" % (ziel_seite, info))
        else:
            conn.execute("INSERT INTO posts(entwurf_id, kanal, status, fehler) VALUES (?,?,?,?)",
                         (eid, k, "fehler", info))
            audit_log(conn, user, "veroeffentlichung_fehler_%s" % k, eid, info)
    # Pro Ziel sofort verbuchen: ein extern veroeffentlichter Post darf nie ohne DB-Eintrag bleiben,
    # auch wenn ein spaeteres Ziel scheitert.
    conn.commit()
    return ziel_name, erfolg, ergebnisse


@app.route("/veroeffentlichen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def veroeffentlichen(eid):
    stelle_ids = [s.strip() for s in request.form.getlist("stelle_id") if s.strip()]
    page_ids = [p.strip() for p in request.form.getlist("page_id") if p.strip()]
    user = session["user"]
    if not stelle_ids and not page_ids:
        flash("Bitte mindestens eine Beratungsstelle bzw. Facebook-Seite wählen."); return redirect(url_for("einplanung"))
    fmt_fb = _format("format_fb", "einzelbild")
    fmt_ig = _format("format_ig", "karussell")
    story = request.form.get("story_ig") == "1"
    haupt_fmt = "karussell" if "karussell" in (fmt_fb, fmt_ig) else "einzelbild"
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        try:
            f = json.loads(e["text"])
        except Exception:
            f = {}
        # Ziele zusammenstellen: gewaehlte Beratungsstellen (personalisiert) + gewaehlte Facebook-Seiten;
        # jeder Eintrag traegt seinen eigenen Kanal (pro Beratungsstelle waehlbar).
        ziele = []   # (stelle_row | None, page_id | None, kanal)
        for sid in stelle_ids:
            stelle = conn.execute("SELECT * FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
            if not stelle or not stelle["fb_seite"]:
                flash("Beratungsstelle (ID %s) hat keine Facebook-Seite – übersprungen." % sid); continue
            ziele.append((stelle, None, _kanal_fuer("s", sid)))
        for pid in page_ids:
            ziele.append((None, pid, _kanal_fuer("p", pid)))
        if not ziele:
            flash("Kein gültiges Ziel gewählt (Beratungsstelle ohne Facebook-Seite?)."); return redirect(url_for("einplanung"))
        # Format am Entwurf festhalten (fuer Kalender/Detailansicht): Karussell, wenn ein Kanal Karussell ist
        conn.execute("UPDATE entwuerfe SET format=? WHERE id=?", (haupt_fmt, eid))
        import publish
        gesamt_erfolg = False
        zeilen = []
        for stelle, pid, kanal in ziele:
            ziel_name, erfolg, ergebnisse = _veroeffentliche_ziel(conn, e, eid, f, fmt_fb, fmt_ig, kanal, stelle, pid, user, publish, story)
            gesamt_erfolg = gesamt_erfolg or erfolg
            teile = ["%s: %s" % (k.capitalize(), ("OK" if ok else "Fehler – %s" % info)) for k, ok, info in ergebnisse]
            zeilen.append("%s → %s" % (ziel_name, " | ".join(teile)))
        if gesamt_erfolg:
            conn.execute("UPDATE entwuerfe SET status='veroeffentlicht' WHERE id=?", (eid,))
        flash("Beitrag %d:  %s" % (eid, "   •   ".join(zeilen)))
        conn.commit()
    return redirect(url_for("einplanung"))

@app.route("/auto-einplanen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def auto_einplanen(eid):
    """Plant den Beitrag je gewaehlter Beratungsstelle/Seite zu einer vorgeschlagenen, gestreuten
    Uhrzeit (07-19 Uhr) auf dem geplanten Datum ein. Der Dienst veroeffentlicht dann automatisch."""
    import datetime
    stelle_ids = [s.strip() for s in request.form.getlist("stelle_id") if s.strip()]
    page_ids = [p.strip() for p in request.form.getlist("page_id") if p.strip()]
    fmt_fb = _format("format_fb", "einzelbild")
    fmt_ig = _format("format_ig", "karussell")
    haupt_fmt = "karussell" if "karussell" in (fmt_fb, fmt_ig) else "einzelbild"
    if not stelle_ids and not page_ids:
        flash("Bitte mindestens eine Beratungsstelle bzw. Facebook-Seite wählen.")
        return redirect(url_for("einplanung"))
    now = datetime.datetime.now()
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        datum = e["geplant_fuer"] or now.date().isoformat()
        # heute: Zeit muss in der Zukunft liegen; spaeteres Datum: ab 07:00
        min_m = (now.hour * 60 + now.minute + 2) if datum == now.date().isoformat() else 7 * 60
        belegt = [r[0][11:16] for r in conn.execute(
            "SELECT geplant_am FROM geplante_posts WHERE geplant_am LIKE ? AND status='geplant'", (datum + "T%",))]
        n = 0
        for sid in stelle_ids:
            stelle = conn.execute("SELECT id, fb_seite FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
            if not stelle or not stelle["fb_seite"]:
                flash("Beratungsstelle (ID %s) ohne Facebook-Seite – übersprungen." % sid); continue
            z = _vorschlag_zeit(belegt, min_m); belegt.append(z)
            conn.execute("INSERT INTO geplante_posts(entwurf_id, stelle_id, kanal, format, format_fb, format_ig, "
                         "geplant_am, status) VALUES (?,?,?,?,?,?,?, 'geplant')",
                         (eid, int(stelle["id"]), _kanal_fuer("s", sid), haupt_fmt, fmt_fb, fmt_ig, "%sT%s" % (datum, z)))
            n += 1
        for pid in page_ids:
            z = _vorschlag_zeit(belegt, min_m); belegt.append(z)
            conn.execute("INSERT INTO geplante_posts(entwurf_id, page_id, kanal, format, format_fb, format_ig, "
                         "geplant_am, status) VALUES (?,?,?,?,?,?,?, 'geplant')",
                         (eid, pid, _kanal_fuer("p", pid), haupt_fmt, fmt_fb, fmt_ig, "%sT%s" % (datum, z)))
            n += 1
        if n:
            audit_log(conn, session["user"], "auto_eingeplant", eid, "%d Ziel(e) am %s" % (n, datum))
        conn.commit()
    if n:
        flash("%d Beitrag/Beiträge automatisch für %s eingeplant – die Uhrzeiten kannst du unter "
              "„Geplante Veröffentlichungen“ anpassen." % (n, _de_datum(datum)))
    return redirect(url_for("geplant"))

@app.route("/geplant")
@login_required
def geplant():
    rows = []
    with get_conn() as conn:
        for gp in conn.execute(
            "SELECT g.id, g.entwurf_id, g.page_id, g.kanal, g.format, g.geplant_am, g.status, g.info, "
            "e.text AS etext, b.name AS sname, b.ort AS sort "
            "FROM geplante_posts g LEFT JOIN entwuerfe e ON e.id=g.entwurf_id "
            "LEFT JOIN beratungsstellen b ON b.id=g.stelle_id "
            "ORDER BY (g.status NOT IN ('geplant','laeuft')), g.geplant_am").fetchall():
            try:
                titel = json.loads(gp["etext"]).get("ueberschrift") or "Beitrag"
            except Exception:
                titel = "Beitrag"
            ziel = (gp["sname"] + ((" · " + gp["sort"]) if gp["sort"] else "")) if gp["sname"] \
                else ("Facebook-Seite %s" % gp["page_id"])
            parts = (gp["geplant_am"] or "").split("T")
            d = parts[0] if parts else ""
            t = parts[1][:5] if len(parts) > 1 else ""
            rows.append({"id": gp["id"], "eid": gp["entwurf_id"], "titel": titel, "ziel": ziel,
                         "kanal": _KANAL_DE.get(gp["kanal"], gp["kanal"]),
                         "format": "Karussell" if gp["format"] == "karussell" else "Einzelbild",
                         "datum": d, "zeit": t, "geplant_de": _de_datum(d),
                         "status": gp["status"], "info": gp["info"]})
    return render_template_string(GEPLANT, **_ctx(posts=rows))

@app.route("/geplant-aendern/<int:gpid>", methods=["POST"])
@rolle_required("freigeber")
def geplant_aendern(gpid):
    import re
    datum = request.form.get("datum", "").strip(); zeit = request.form.get("zeit", "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", datum) and re.match(r"^\d{2}:\d{2}$", zeit):
        with get_conn() as conn:
            conn.execute("UPDATE geplante_posts SET geplant_am=? WHERE id=? AND status='geplant'",
                         ("%sT%s" % (datum, zeit), gpid))
            audit_log(conn, session["user"], "geplant_aendern", None, "gp %d -> %sT%s" % (gpid, datum, zeit))
            conn.commit()
        flash("Termin angepasst.")
    else:
        flash("Bitte gültiges Datum und Uhrzeit angeben.")
    return redirect(url_for("geplant"))

@app.route("/geplant-loeschen/<int:gpid>", methods=["POST"])
@rolle_required("freigeber")
def geplant_loeschen(gpid):
    with get_conn() as conn:
        conn.execute("DELETE FROM geplante_posts WHERE id=? AND status IN ('geplant','laeuft')", (gpid,))
        audit_log(conn, session["user"], "geplant_loeschen", None, "gp %d" % gpid)
        conn.commit()
    flash("Geplante Veröffentlichung entfernt.")
    return redirect(url_for("geplant"))

@app.route("/vorschau/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def vorschau(eid):
    """Rendert vor dem Veroeffentlichen je gewaehlter Beratungsstelle die personalisierte
    Bildvariante (Portraet, Name, Ort, Begleittext) zur Pruefung - postet noch nichts."""
    stelle_ids = [s.strip() for s in request.form.getlist("stelle_id") if s.strip()]
    page_ids = [p.strip() for p in request.form.getlist("page_id") if p.strip()]
    fmt_fb = _format("format_fb", "einzelbild")
    fmt_ig = _format("format_ig", "karussell")
    story = request.form.get("story_ig") == "1"
    if not stelle_ids and not page_ids:
        flash("Bitte mindestens eine Beratungsstelle bzw. Facebook-Seite wählen.")
        return redirect(url_for("einplanung"))
    kanal_map = {}   # "s<sid>" / "p<pid>" -> Kanal (zum Weiterreichen an /veroeffentlichen)
    items = []
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        try:
            f = json.loads(e["text"])
        except Exception:
            f = {}
        pdir = os.path.join(DATA_DIR, "preview"); os.makedirs(pdir, exist_ok=True)
        # alte Vorschaubilder aufraeumen (aelter als 6 Stunden) - der Ordner ist nur ein Cache
        try:
            grenze = time.time() - 6 * 3600
            for fn in os.listdir(pdir):
                fp = os.path.join(pdir, fn)
                if os.path.isfile(fp) and os.path.getmtime(fp) < grenze:
                    os.remove(fp)
        except Exception:
            pass
        import personalisierung
        def _caps_fuer(kanal, base_fn):
            """Liste (Kanal-Label, Begleittext) fuer die je Ziel gewaehlten Kanaele."""
            out = []
            if kanal in ("facebook", "beide"):
                out.append((_KANAL_DE["facebook"], base_fn("facebook")))
            if kanal in ("instagram", "beide"):
                out.append((_KANAL_DE["instagram"], base_fn("instagram")))
            return out
        for sid in stelle_ids:
            kanal = _kanal_fuer("s", sid); kanal_map["s" + sid] = kanal
            stelle = conn.execute("SELECT * FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
            if not stelle or not stelle["fb_seite"]:
                items.append({"label": "Beratungsstelle %s" % sid, "ok": False, "kanal_de": _KANAL_DE[kanal],
                              "caption": "Keine Facebook-Seite zugeordnet – wird beim Veröffentlichen übersprungen."})
                continue
            out = os.path.join(pdir, "e%d_stelle_%d.png" % (eid, int(stelle["id"])))
            try:
                personalisierung.render_fuer_stelle(f, stelle, out)
                v = int(os.path.getmtime(out))
                caps = _caps_fuer(kanal, lambda k, st=stelle: personalisierung.caption_fuer_stelle(f, st, k))
                items.append({"label": "%s%s" % (stelle["name"], " · %s" % stelle["ort"] if stelle["ort"] else ""),
                              "ok": True, "kanal_de": _KANAL_DE[kanal], "caps": caps,
                              "url": url_for("preview_bild", eid=eid, sid=int(stelle["id"])) + "?v=%d" % v})
            except Exception:
                log.exception("Vorschau-Render fehlgeschlagen (Entwurf %s / Stelle %s)", eid, sid)
                items.append({"label": stelle["name"], "ok": False, "kanal_de": _KANAL_DE[kanal],
                              "caption": "Vorschau konnte nicht erstellt werden."})
        for pid in page_ids:
            kanal = _kanal_fuer("p", pid); kanal_map["p" + pid] = kanal
            caps = _caps_fuer(kanal, lambda k: textgen.caption_fuer(f, k) or f.get("ueberschrift") or "")
            items.append({"label": "Facebook-Seite %s" % pid, "ok": True, "kanal_de": _KANAL_DE[kanal],
                          "caps": caps, "url": url_for("bild", eid=eid)})
    ziel_count = sum(1 for it in items if it.get("ok"))
    return render_template_string(VORSCHAU, **_ctx(eid=eid, fmt_fb=fmt_fb, fmt_ig=fmt_ig, items=items,
                                  ziel_count=ziel_count, stelle_ids=stelle_ids, page_ids=page_ids,
                                  kanal_map=kanal_map, story_ig=story))

@app.route("/preview-bild/<int:eid>/<int:sid>")
@rolle_required("freigeber")
def preview_bild(eid, sid):
    p = os.path.join(DATA_DIR, "preview", "e%d_stelle_%d.png" % (eid, sid))
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png", max_age=0)

@app.route("/verwaltung", methods=["GET", "POST"])
@admin_required
def verwaltung():
    bereich = request.args.get("bereich", "").strip()
    with get_conn() as conn:
        if request.method == "POST":
            formular = request.form.get("formular")
            if formular == "benutzer_add":
                name = request.form.get("name", "").strip(); pw = request.form.get("passwort", "")
                rolle = request.form.get("rolle", "redakteur")
                if name and pw:
                    try:
                        conn.execute("INSERT OR REPLACE INTO benutzer(name, passwort_hash, rolle, aktiv) VALUES (?,?,?,1)",
                                     (name, generate_password_hash(pw, method="pbkdf2:sha256"), rolle))
                        audit_log(conn, session["user"], "benutzer_angelegt", None, "%s/%s" % (name, rolle))
                        flash("Benutzer '%s' angelegt." % name)
                    except Exception as ex:
                        flash("Fehler: %s" % ex)
                else:
                    flash("Name und Passwort nötig.")
            elif formular == "benutzer_toggle":
                name = request.form.get("name", "").strip()
                conn.execute("UPDATE benutzer SET aktiv=1-aktiv WHERE name=?", (name,)); flash("'%s' geändert." % name)
            elif formular == "stelle_save":
                name = request.form.get("name", "").strip(); ort = request.form.get("ort", "").strip()
                if name and ort:
                    conn.execute(
                        "INSERT INTO beratungsstellen(name, ort, leitung, fb_seite, homepage_url, buchungs_url, aktiv) "
                        "VALUES (?,?,?,?,?,?,1) ON CONFLICT(name) DO UPDATE SET ort=excluded.ort, "
                        "leitung=excluded.leitung, fb_seite=excluded.fb_seite, homepage_url=excluded.homepage_url, "
                        "buchungs_url=excluded.buchungs_url",
                        (name, ort, request.form.get("leitung", "").strip(), request.form.get("fb_seite", "").strip(),
                         request.form.get("homepage_url", "").strip(), request.form.get("buchungs_url", "").strip()))
                    audit_log(conn, session["user"], "beratungsstelle_gespeichert", None, name)
                    flash("Beratungsstelle '%s' gespeichert." % name)
                else:
                    flash("Name und Ort nötig.")
            elif formular == "stelle_fb":
                sid = request.form.get("stelle_id", "").strip()
                fb = request.form.get("fb_seite", "").strip()
                if sid:
                    conn.execute("UPDATE beratungsstellen SET fb_seite=? WHERE id=?", (fb, sid))
                    audit_log(conn, session["user"], "beratungsstelle_fb_gesetzt", None,
                              "Stelle %s -> %s" % (sid, fb or "(keine)"))
                    flash("Facebook-Seite aktualisiert." if fb else "Facebook-Seite entfernt.")
            elif formular == "stelle_ort_id":
                sid = request.form.get("stelle_id", "").strip()
                oid = request.form.get("ort_id", "").strip()
                if oid and not oid.isdigit():
                    flash("Die Facebook-Orts-ID darf nur Ziffern enthalten.")
                elif sid:
                    conn.execute("UPDATE beratungsstellen SET ort_id=? WHERE id=?", (oid, sid))
                    audit_log(conn, session["user"], "beratungsstelle_ort_id_gesetzt", None,
                              "Stelle %s -> %s" % (sid, oid or "(keine)"))
                    flash("Instagram-Orts-ID aktualisiert." if oid else "Instagram-Orts-ID entfernt.")
            elif formular == "stelle_portrait":
                sid = request.form.get("stelle_id", "").strip()
                file = request.files.get("portrait")
                if sid and sid.isascii() and sid.isdigit() and file and file.filename:
                    try:
                        from PIL import Image
                        pdir = os.path.join(DATA_DIR, "portraits"); os.makedirs(pdir, exist_ok=True)
                        dest = os.path.join(pdir, "stelle_%s.png" % sid)
                        img = Image.open(file.stream)
                        w, h = img.size                          # Header-Mass, noch nicht dekodiert
                        if w * h > 40_000_000:                   # ~40 MP Deckel - schuetzt den Pi vor Speicher-Bomben
                            raise ValueError("Bild zu gross")
                        img = img.convert("RGB")
                        s = min(w, h)                            # mittig quadratisch zuschneiden
                        img = img.crop(((w-s)//2, (h-s)//2, (w-s)//2+s, (h-s)//2+s))
                        if s > 400:
                            img = img.resize((400, 400), Image.LANCZOS)
                        img.save(dest)
                        conn.execute("UPDATE beratungsstellen SET portrait_pfad=? WHERE id=?", (dest, sid))
                        audit_log(conn, session["user"], "beratungsstelle_portrait_gesetzt", None, "Stelle %s" % sid)
                        flash("Porträt gespeichert.")
                    except Exception:
                        log.exception("Portrait-Upload fehlgeschlagen (Stelle %s)", sid)
                        flash("Porträt-Upload fehlgeschlagen – bitte eine gültige Bilddatei (max ~40 Megapixel) wählen.")
                else:
                    flash("Bitte eine Bilddatei wählen.")
            elif formular == "stelle_portrait_del":
                sid = request.form.get("stelle_id", "").strip()
                if sid:
                    row = conn.execute("SELECT portrait_pfad FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
                    if row and row["portrait_pfad"] and _under_portraits(row["portrait_pfad"]):
                        try:
                            os.remove(row["portrait_pfad"])
                        except Exception:
                            pass
                    conn.execute("UPDATE beratungsstellen SET portrait_pfad=NULL WHERE id=?", (sid,))
                    audit_log(conn, session["user"], "beratungsstelle_portrait_entfernt", None, "Stelle %s" % sid)
                    flash("Porträt entfernt – wieder blauer Punkt.")
            elif formular == "anlass_save":
                datum = request.form.get("datum", "").strip(); anlass = request.form.get("anlass", "").strip()
                if datum and anlass:
                    conn.execute("INSERT INTO anlasstage(datum, anlass, steuer_hook, aktiv) VALUES (?,?,?,1) "
                                 "ON CONFLICT(anlass) DO UPDATE SET datum=excluded.datum, steuer_hook=excluded.steuer_hook",
                                 (datum, anlass, request.form.get("steuer_hook", "").strip()))
                    audit_log(conn, session["user"], "anlasstag_gespeichert", None, anlass)
                    flash("Anlass-Tag '%s' gespeichert." % anlass)
                else:
                    flash("Datum und Anlass nötig.")
            elif formular == "anlass_toggle":
                anlass = request.form.get("anlass", "").strip()
                conn.execute("UPDATE anlasstage SET aktiv=1-aktiv WHERE anlass=?", (anlass,))
                flash("Anlass-Tag '%s' geändert." % anlass)
            elif formular == "wissen_save":
                titel = request.form.get("titel", "").strip()
                if titel:
                    conn.execute("INSERT INTO wissensthemen(titel, hook, aktiv) VALUES (?,?,1) "
                                 "ON CONFLICT(titel) DO UPDATE SET hook=excluded.hook",
                                 (titel, request.form.get("hook", "").strip()))
                    audit_log(conn, session["user"], "wissensthema_gespeichert", None, titel)
                    flash("Wissens-Thema '%s' gespeichert." % titel)
                else:
                    flash("Thema nötig.")
            elif formular == "wissen_toggle":
                titel = request.form.get("titel", "").strip()
                conn.execute("UPDATE wissensthemen SET aktiv=1-aktiv WHERE titel=?", (titel,))
                flash("Wissens-Thema '%s' geändert." % titel)
            conn.commit()
            # PRG: zurueck zum passenden Bereich (kein erneutes Absenden bei Reload)
            ziel = {"benutzer": "benutzer", "stelle": "stellen", "anlass": "anlass",
                    "wissen": "wissen"}.get((formular or "").split("_")[0])
            return redirect(url_for("verwaltung", bereich=ziel) if ziel else url_for("verwaltung"))
        if not bereich:
            return render_template_string(VERWALTUNG_HOME, **_ctx())
        bereich_titel = {"benutzer": "Benutzer", "stellen": "Beratungsstellen",
                         "anlass": "Anlass-Tage", "wissen": "Wissens-Serie"}.get(bereich)
        if not bereich_titel:
            return redirect(url_for("verwaltung"))
        users = conn.execute("SELECT name, rolle, aktiv FROM benutzer ORDER BY name").fetchall()
        stellen = conn.execute("SELECT * FROM beratungsstellen ORDER BY ort").fetchall()
        anlasstage = conn.execute("SELECT datum, anlass, steuer_hook, aktiv FROM anlasstage ORDER BY datum").fetchall()
        wissen = conn.execute("SELECT titel, hook, aktiv FROM wissensthemen ORDER BY titel").fetchall()
    pages, pages_err = (_pages() if bereich == "stellen" else ([], None))
    page_id_set = {str(p["id"]) for p in pages}
    fb_name = {str(p["id"]): p["name"] for p in pages}
    return render_template_string(VERWALTUNG, **_ctx(users=users, stellen=stellen, anlasstage=anlasstage,
                                                     wissen=wissen, bereich=bereich, bereich_titel=bereich_titel,
                                                     pages=pages, pages_err=pages_err, page_id_set=page_id_set,
                                                     fb_name=fb_name))

@app.route("/logo.png")
def logo():
    p = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png")

@app.route("/portrait/<int:sid>")
@login_required
def portrait(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT portrait_pfad FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
    if (not row or not row["portrait_pfad"] or not _under_portraits(row["portrait_pfad"])
            or not os.path.exists(row["portrait_pfad"])):
        abort(404)
    return send_file(row["portrait_pfad"], mimetype="image/png")

# --- WhatsApp (Baileys-Dienst auf demselben Host, nur localhost) -------------
def _wa_call(path, method="GET", payload=None, timeout=6):
    """Ruft die lokale HTTP-API des Node-/Baileys-Dienstes auf. Gibt (daten, fehler) zurueck."""
    import urllib.request, urllib.error
    url = WHATSAPP_URL.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}"), None
    except urllib.error.URLError as e:
        return None, "Dienst nicht erreichbar (%s)" % getattr(e, "reason", e)
    except Exception as e:  # noqa: BLE001
        return None, str(e)

WHATSAPP = """<!doctype html><meta charset=utf-8><title>HISOME - WhatsApp</title>
{% if wa and wa.state in ['qr','init','closed'] %}<meta http-equiv=refresh content=8>{% endif %}
<style>""" + _TOP + """
.wrap{max-width:760px;margin:0 auto}
.card{background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:20px;margin:0 auto 16px}
.qr{text-align:center}.qr img{width:300px;height:300px;border:1px solid #e2e8f0;border-radius:10px}
.ok{color:#2f7d32;font-weight:bold}.bad{color:#b00020;font-weight:bold}
.step{color:#475569;font-size:14px}
label{display:block;margin:8px 0 3px;font-weight:bold;font-size:14px}
input[type=text]{width:100%;box-sizing:border-box;padding:9px;border:1px solid #ccd3df;border-radius:8px}
button{background:#1f428d;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-weight:bold;cursor:pointer;margin-top:8px}
button.g{background:#4c7b2d}button.r{background:#b00020}
.muted{color:#6b7280;font-size:13px}</style>
""" + _NAV + """
<div style="max-width:760px;margin:0 auto 10px"><div class=top><h2 style="margin:0;color:#1f428d">WhatsApp</h2><a href="/">&larr; Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash style="max-width:760px">{{m[0]}}</div>{% endif %}{% endwith %}
<div class=wrap>
{% if wa_err %}
  <div class=card><p class=bad>WhatsApp-Dienst nicht erreichbar.</p>
  <p class=muted>{{wa_err}}</p>
  <p class=step>Der WhatsApp-Dienst (Node/Baileys) läuft noch nicht. Bitte einmalig auf dem Pi einrichten (siehe <code>whatsapp/README.md</code>) und den Dienst starten.</p></div>
{% elif wa.state == 'connected' %}
  <div class=card><p class=ok>&#x2705; Verbunden{% if wa.me %} als <code>{{wa.me}}</code>{% endif %}.</p>
    <p class=muted>Die WhatsApp-Sitzung ist aktiv. Synchronisierte Kontakte: <b>{{wa.contacts if wa.contacts is not none else '?'}}</b>.</p>
    <form method=post action="/whatsapp/logout" onsubmit="return confirm('Sitzung wirklich trennen? Du musst danach neu scannen.')"><button class=r>Sitzung trennen</button></form></div>
  <div class=card><h3 style="margin:0 0 6px;color:#1f428d">Test: Status</h3>
    <form method=post action="/whatsapp/test-status">
      <label>Text</label><input type=text name=caption placeholder="HISOME Test-Status">
      <label class=step style="font-weight:normal;margin-top:8px"><input type=checkbox name=to_contacts value="1"> An meine Kontakte senden (sonst nur an mich &ndash; ein „nur an mich"-Status wird von WhatsApp aber nicht angezeigt)</label>
      <button class=g>Test-Status senden</button></form>
    <p class=muted>Ein WhatsApp-Status erscheint nur, wenn er an echte Kontakte geht. Sind oben 0 Kontakte, muss die Nummer erst Kontakte gespeichert/synchronisiert haben.</p></div>
  <div class=card><h3 style="margin:0 0 6px;color:#1f428d">Test: Kanal</h3>
    <form method=post action="/whatsapp/test-channel">
      <label>Kanal-Einladungslink</label><input type=text name=invite placeholder="https://whatsapp.com/channel/...">
      <label>Text</label><input type=text name=caption placeholder="HISOME Test-Kanalbeitrag">
      <button class=g>Test-Kanalbeitrag senden</button></form>
    <p class=muted>Den Einladungslink findest du in WhatsApp: Kanal öffnen &rarr; Name antippen &rarr; „Link teilen".</p></div>
{% elif wa.state == 'qr' and wa.qr %}
  <div class="card qr"><h3 style="color:#1f428d">QR-Code scannen</h3>
    <img src="{{wa.qr}}" alt="WhatsApp QR">
    <ol class=step style="text-align:left;max-width:420px;margin:14px auto">
      <li>WhatsApp auf dem Handy mit der Beratungsstellen-Nummer öffnen</li>
      <li>Einstellungen &rarr; <b>Verknüpfte Geräte</b> &rarr; <b>Gerät verknüpfen</b></li>
      <li>Diesen QR-Code scannen</li></ol>
    <p class=muted>Die Seite aktualisiert sich automatisch.</p></div>
{% else %}
  <div class=card><p class=step>Verbindung wird aufgebaut&hellip; (Status: {{wa.state if wa else '—'}})</p>
    {% if wa and wa.error %}<p class=muted>{{wa.error}}</p>{% endif %}
    <p class=muted>Die Seite aktualisiert sich automatisch.</p></div>
{% endif %}
</div>"""

@app.route("/whatsapp")
@login_required
def whatsapp():
    st, err = _wa_call("/status")
    return render_template_string(WHATSAPP, **_ctx(wa=st, wa_err=err))

@app.route("/whatsapp/logout", methods=["POST"])
@login_required
def whatsapp_logout():
    _wa_call("/logout", method="POST", payload={})
    audit_log_safe("whatsapp_logout")
    flash("WhatsApp-Sitzung getrennt. Scanne den neuen QR-Code zum Neuverbinden.")
    return redirect(url_for("whatsapp"))

@app.route("/whatsapp/test-status", methods=["POST"])
@login_required
def whatsapp_test_status():
    caption = request.form.get("caption", "").strip() or "HISOME Test-Status"
    to_contacts = bool(request.form.get("to_contacts"))
    res, err = _wa_call("/post-status", method="POST",
                        payload={"caption": caption, "toContacts": to_contacts}, timeout=30)
    if err:
        flash("Fehler: " + err)
    elif res and res.get("error"):
        flash("WhatsApp: " + res["error"])
    else:
        n = res.get("recipients") if res else None
        flash("Test-Status gesendet%s." % ((" (an %d Empfaenger)" % n) if n else ""))
    return redirect(url_for("whatsapp"))

@app.route("/whatsapp/test-channel", methods=["POST"])
@login_required
def whatsapp_test_channel():
    invite = request.form.get("invite", "").strip()
    caption = request.form.get("caption", "").strip() or "HISOME Test-Kanalbeitrag"
    if not invite:
        flash("Bitte den Einladungslink des Kanals angeben.")
        return redirect(url_for("whatsapp"))
    res, err = _wa_call("/post-channel", method="POST",
                        payload={"invite": invite, "caption": caption}, timeout=30)
    if err:
        flash("Fehler: " + err)
    elif res and res.get("error"):
        flash("WhatsApp: " + res["error"])
    else:
        flash("Test-Kanalbeitrag gesendet.")
    return redirect(url_for("whatsapp"))

def audit_log_safe(aktion):
    """Audit-Eintrag ohne harten Fehler, falls keine DB-Verbindung verfuegbar ist."""
    try:
        with get_conn() as conn:
            audit_log(conn, session.get("user"), aktion, None, None)
            conn.commit()
    except Exception:
        pass

def serve(host="0.0.0.0", port=None):
    init_db()
    # Beim Start den Meta-Token (falls vorhanden) in einen Langzeit-Token tauschen/erneuern -
    # best effort, blockiert den Start nie.
    try:
        import publish
        if publish.ensure_long_lived():
            log.info("Meta-Langzeit-Token erneuert (~60 Tage).")
    except Exception as ex:
        log.info("Token-Verlaengerung beim Start uebersprungen: %s", ex)
    threading.Thread(target=_daily_scheduler, daemon=True).start()
    threading.Thread(target=_publish_scheduler, daemon=True).start()   # Auto-Veroeffentlichung zur Uhrzeit
    port = int(port or os.environ.get("HILO_DASHBOARD_PORT", "8530"))
    app.run(host=host, port=port, threaded=True)
