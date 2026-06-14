# -*- coding: utf-8 -*-
"""HISOME - HILO Social Media Tool. Kachel-Dashboard (Flask):
Startseite mit Workflow-Kacheln, Stufe 1 (Themenauswahl), Texte/Bilder erzeugen,
Stufe 2 (Entwuerfe freigeben), Einplanung/Veroeffentlichung, eigene Quellen,
Admin-Verwaltung (Benutzer + Beratungsstellen). Taeglicher Radar-Lauf um 7 Uhr."""
import json, os, time, sys, subprocess, threading, functools
from flask import (Flask, request, redirect, url_for, session, send_file,
                   render_template_string, flash, abort)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from db import get_conn, init_db, audit_log
from secrets_store import get_secret
from config import BASE_DIR, DATA_DIR
import textgen, bildgen

app = Flask(__name__)

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

# --- Hintergrund-Erzeugung als eigener Prozess -----------------------------
_gen = {"proc": None}

def _generation_running():
    p = _gen["proc"]
    return p is not None and p.poll() is None

def _start_generation(anzahl):
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"), "--generate", str(anzahl), "--render"],
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
<div><a href="/quellen">Eigene Quellen</a> &middot; {% if rolle=='admin' %}<a href="/verwaltung">Verwaltung</a> &middot; {% endif %}{{user}} &middot; <a href="/logout">Abmelden</a></div></div>"""

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
.badge{position:absolute;top:16px;right:16px;background:#1f428d;color:#fff;border-radius:18px;padding:2px 11px;font-weight:bold;font-size:14px}
.badge.g{background:#4c7b2d}
.tile form{margin:10px 0 0}.tile button{background:#4c7b2d;color:#fff;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;font-size:13px}
.run{color:#4c7b2d;font-weight:bold;font-size:13px;margin-top:8px}</style>
""" + _NAV + """
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=info>&#x1F552; Themen werden täglich um 7:00 Uhr automatisch aus allen Quellen geholt.</div>
<div class=grid>
  <a class=tile href="/themen">{% if themen_offen %}<span class=badge>{{themen_offen}}</span>{% endif %}<h3>1. Freigabe: Themen</h3><p>Themen für die Kampagne auswählen (Stufe 1).</p></a>
  <div class="tile action"><h3>2. Texte &amp; Bilder erzeugen</h3><p>Für ausgewählte Themen Beiträge erstellen.</p>
    {% if gen_running %}<div class=run>&#x23F3; Läuft im Hintergrund &hellip;</div>
    {% elif bereit %}<form method=post action="/generieren">
      <label style="font-size:13px;color:#15336e">Anzahl: <input type=number name=anzahl min=1 max="{{bereit}}" value="{{ [5, bereit]|min }}" style="width:64px;padding:6px"></label>
      <button>Jetzt erzeugen</button></form>
      <div class=hint>{{bereit}} Themen verfügbar – wähle, wie viele Beiträge erzeugt werden sollen.</div>
    {% else %}<p class=hint>Keine ausgewählten Themen offen. Erst unter „1. Freigabe: Themen" auswählen.</p>{% endif %}</div>
  <a class=tile href="/entwuerfe">{% if entwuerfe_offen %}<span class=badge>{{entwuerfe_offen}}</span>{% endif %}<h3>3. Freigabe: Texte &amp; Bilder</h3><p>Entwürfe prüfen, überarbeiten, freigeben (Stufe 2).</p></a>
  <a class=tile href="/einplanung">{% if freigegeben_offen %}<span class="badge g">{{freigegeben_offen}}</span>{% endif %}<h3>4. Einplanung Veröffentlichung</h3><p>Freigegebene Beiträge veröffentlichen.</p></a>
</div>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4c7b2d" href="/eigener"><h3>&#x270F;&#xFE0F; Eigenen Beitrag erstellen</h3><p>Thema und Tag angeben – das Tool erstellt einen Entwurf, den du freigibst und der dann fest für diesen Tag eingeplant wird.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4c7b2d" href="/kalender"><h3>&#x1F4C5; Content-Kalender</h3><p>Monatsübersicht: geplante Beiträge und besondere Tage (Anlass-Tage, Fristen) auf einen Blick.</p></a>"""

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
.ok{background:#2e7d32}.no{background:#9aa0a6}.re{background:#1f428d}</style>
<div class=top><h2 style="margin:0;color:#1f428d">Freigabe: Texte &amp; Bilder (Stufe 2)</h2><a href="/">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
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
    </form>
  </div></div>
{% else %}<p style="text-align:center">Keine offenen Entwürfe. Erst Themen auswählen und Beiträge erzeugen.</p>{% endfor %}"""

EINPLANUNG = """<!doctype html><meta charset=utf-8><title>Einplanung Veröffentlichung</title>
<style>""" + _TOP + """
.card{display:flex;gap:18px;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:16px;max-width:1040px;margin:0 auto 18px}
.card img{width:240px;height:240px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.t{flex:1}.t h3{color:#15336e;margin:.2em 0}.sub{color:#4c7b2d;font-weight:bold}
select,button{padding:9px;border-radius:8px;margin:4px 6px 4px 0}
button{border:0;background:#2e7d32;color:#fff;cursor:pointer}</style>
<div class=top><h2 style="margin:0;color:#1f428d">Einplanung Veröffentlichung</h2><a href="/">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<p class=hint style="max-width:1040px;margin:0 auto 12px">Freigegebene Beiträge werden automatisch auf die nächsten freien <b>Werktage</b> verteilt (max. 1 pro Tag, Sa+So frei). Termin unten anpassbar. Sondertage &amp; Fristen-Countdown folgen.</p>
{% if pages_err %}<div class=flash style="color:#b00020">Facebook-Seiten konnten nicht geladen werden: {{pages_err}}</div>{% endif %}
{% for e in freigegeben %}
<div class=card><img src="/bild/{{e.id}}" alt="Vorschau">
  <div class=t><h3>{{e.f.ueberschrift}}</h3><p class=sub>{{e.f.subline}}</p>
    <p><b style="color:#1f428d">&#x1F4C5; Geplant: {{e.geplant_de}}</b>
       <form method=post action="/umplanen/{{e.id}}" style="display:inline;margin-left:8px">
         <input type=date name=geplant_fuer value="{{e.geplant_fuer}}" style="padding:5px">
         <button style="background:#1f428d;padding:6px 10px">Termin ändern</button></form></p>
    <details><summary>Begleittext anzeigen</summary><p>{{e.f.caption}}</p></details>
    {% if stellen %}
    <form method=post action="/veroeffentlichen/{{e.id}}" onsubmit="return confirm('Diesen Beitrag personalisiert für die gewählte Beratungsstelle veröffentlichen?')">
      <select name=stelle_id required><option value="" disabled selected>Beratungsstelle wählen &hellip;</option>
        {% for s in stellen %}<option value="{{s.id}}">{{s.name}}{% if s.ort %} ({{s.ort}}){% endif %}</option>{% endfor %}</select>
      <select name=format title="Format des Beitrags">
        <option value="einzelbild"{% if e.format!='karussell' %} selected{% endif %}>Einzelbild</option>
        <option value="karussell"{% if e.format=='karussell' %} selected{% endif %}>Karussell (mehrere Slides)</option></select>
      <button>Personalisiert veröffentlichen</button>
    </form>
    <p class=hint>Bild-CTA und Begleittext werden automatisch auf die Beratungsstelle angepasst.</p>
    {% elif pages %}
    <form method=post action="/veroeffentlichen/{{e.id}}" onsubmit="return confirm('Diesen Beitrag jetzt auf der gewählten Facebook-Seite veröffentlichen?')">
      <select name=page_id required><option value="" disabled selected>Facebook-Seite wählen &hellip;</option>
        {% for p in pages %}<option value="{{p.id}}">{{p.name}}</option>{% endfor %}</select>
      <select name=format title="Format des Beitrags">
        <option value="einzelbild"{% if e.format!='karussell' %} selected{% endif %}>Einzelbild</option>
        <option value="karussell"{% if e.format=='karussell' %} selected{% endif %}>Karussell (mehrere Slides)</option></select>
      <button>Jetzt veröffentlichen</button>
    </form>
    <p class=hint>Tipp: Lege in der Verwaltung Beratungsstellen mit Facebook-Seite an, dann werden Beiträge automatisch personalisiert.</p>
    {% else %}<p class=sub>Kein Facebook-Zugang/keine Beratungsstelle aktiv.</p>{% endif %}
  </div></div>
{% else %}<p style="text-align:center">Keine freigegebenen Beiträge zur Einplanung.</p>{% endfor %}"""

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
{% for p in c.posts %}<span class="post{% if p.status=='veroeffentlicht' %} pub{% endif %}" title="{{p.titel}}">{{p.titel}}</span>{% endfor %}
{% if c.im_monat and not c.past %}<a class=addpost href="/eigener?datum={{c.iso}}" title="Beitrag für diesen Tag erstellen">+ Beitrag</a>{% endif %}
</td>{% endfor %}
</tr>{% endfor %}
</table>
<p class=hint style="max-width:1120px;margin:10px auto;text-align:center">Grün = besonderer Tag &middot; Rot = Fristende &middot; Blau = geplanter Beitrag (grün = bereits veröffentlicht)<br>Tipp: Auf einen Tag „+ Beitrag" klicken (oder direkt auf einen grünen Anlass-Tag) erstellt einen Beitrag für diesen Tag.</p>"""

THEMEN = """<!doctype html><meta charset=utf-8><title>Freigabe: Themen</title><style>""" + _STYLE + """
.q{display:inline-block;background:#eaf0fa;color:#1f428d;border-radius:10px;padding:1px 8px;font-size:12px;font-weight:bold}</style>
<div class=box style="max-width:980px">
<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">Freigabe: Themen (Stufe 1)</h2><a href="/">&larr; Startseite</a></div>
<p class=hint>Wähle die Themen aus, die in die Kampagne sollen. Erst für <b>ausgewählte</b> Themen werden danach Text und Bild erzeugt (spart Token).</p>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if themen %}
<form method=post>
<p><label><input type=checkbox onclick="for(var c of document.querySelectorAll('input[name=thema_ids]'))c.checked=this.checked"> <b>Alle markieren</b></label>
&nbsp;&nbsp;<button name=aktion value=auswaehlen>Markierte freigeben &rarr; Stufe 2</button>
<button name=aktion value=verwerfen style="background:#9aa0a6">Markierte verwerfen</button></p>
<table><tr><th></th><th>Quelle</th><th>Titel</th></tr>
{% for t in themen %}<tr><td><input type=checkbox name=thema_ids value="{{t.id}}"></td>
<td><span class=q>{{t.quelle}}</span></td>
<td>{% if t.url %}<a href="{{t.url}}" target=_blank rel=noopener>{{t.titel}}</a>{% else %}{{t.titel}}{% endif %}</td></tr>{% endfor %}
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

VERWALTUNG = """<!doctype html><meta charset=utf-8><title>{{bereich_titel}} - Verwaltung</title><style>""" + _STYLE + """</style>
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
<table><tr><th>Name</th><th>Ort</th><th>Leitung</th><th>Facebook-Seite</th><th>Buchung</th></tr>
{% for b in stellen %}<tr><td>{{b.name}}</td><td>{{b.ort}}</td><td>{{b.leitung}}</td><td>{{b.fb_seite or '-'}}</td><td>{{b.buchungs_url}}</td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=stelle_save>
<input name=name placeholder="Name der Beratungsstelle" required>
<input name=ort placeholder="Ort (z.B. Neuss)" required>
<input name=leitung placeholder="Name der Leitung">
<input name=fb_seite placeholder="Facebook-Seite (Name oder ID)">
<input name=homepage_url placeholder="Link Homepage">
<input name=buchungs_url placeholder="Link Buchungskalender">
<button>Beratungsstelle speichern</button></form>
<p class=hint>Die Facebook-Seite verknüpft die Stelle für personalisierte Beiträge und die richtige Veröffentlichung.</p>
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

def _naechster_freier_werktag(conn, ausser_id=None):
    """Naechster Werktag (Mo-Fr) ab morgen, der noch keinen eingeplanten Beitrag hat."""
    import datetime
    belegt = {r[0] for r in conn.execute(
        "SELECT geplant_fuer FROM entwuerfe WHERE status='freigegeben' "
        "AND geplant_fuer IS NOT NULL AND id != ?", (ausser_id or -1,))}
    d = datetime.date.today()
    for _ in range(400):
        d += datetime.timedelta(days=1)
        if d.weekday() >= 5:  # Sa/So ueberspringen
            continue
        if d.isoformat() not in belegt:
            return d.isoformat()
    return d.isoformat()

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
    return render_template_string(ENTWUERFE, **_ctx(entwuerfe=rows))

@app.route("/einplanung")
@login_required
def einplanung():
    rows = []
    with get_conn() as conn:
        for e in conn.execute("SELECT id, text, geplant_fuer, format FROM entwuerfe WHERE status='freigegeben' "
                              "ORDER BY geplant_fuer IS NULL, geplant_fuer, id"):
            rows.append(_parse(e))
        stellen = conn.execute("SELECT id, name, ort, fb_seite, buchungs_url FROM beratungsstellen "
                              "WHERE aktiv=1 AND fb_seite IS NOT NULL AND fb_seite!='' ORDER BY ort").fetchall()
    pages, pages_err = (_pages() if rows and not stellen else ([], None))
    return render_template_string(EINPLANUNG, **_ctx(freigegeben=rows, stellen=stellen,
                                  pages=pages, pages_err=pages_err))

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
        for e in conn.execute("SELECT text, geplant_fuer, status FROM entwuerfe "
                             "WHERE geplant_fuer LIKE ?", (praefix + "%",)):
            try:
                titel = (json.loads(e["text"]).get("ueberschrift") or "Beitrag")
            except Exception:
                titel = "Beitrag"
            posts.setdefault(e["geplant_fuer"], []).append({"titel": titel, "status": e["status"]})
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
            # Bereits gesetzter Termin (z.B. Fristen-Countdown) bleibt erhalten
            vorhanden = e["geplant_fuer"] if "geplant_fuer" in e.keys() else None
            termin = vorhanden or _naechster_freier_werktag(conn, eid)
            conn.execute("UPDATE entwuerfe SET status='freigegeben', geplant_fuer=? WHERE id=?", (termin, eid))
            audit_log(conn, user, "freigegeben", eid, "geplant fuer %s" % termin)
            flash("Entwurf %d freigegeben und für %s eingeplant." % (eid, _de_datum(termin)))
        elif aktion == "verwerfen":
            conn.execute("UPDATE entwuerfe SET status='verworfen' WHERE id=?", (eid,))
            audit_log(conn, user, "verworfen", eid); flash("Entwurf %d verworfen." % eid)
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
                # Slogan und Bild-Motiv aus dem vorherigen Beitrag uebernehmen (regenerate liefert sie nicht)
                neu.setdefault("slogan", prev.get("slogan", ""))
                neu.setdefault("bild_motiv", prev.get("bild_motiv", ""))
                conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=NULL WHERE id=?", (json.dumps(neu, ensure_ascii=False), eid))
                conn.commit(); bildgen.render_drafts()
                audit_log(conn, user, "ueberarbeitet", eid, feedback); conn.commit()
                flash("Entwurf %d überarbeitet (neuer Vorschlag erstellt)." % eid)
            except Exception as ex:
                flash("Überarbeitung fehlgeschlagen: %s" % ex)
        conn.commit()
    return redirect(url_for("entwuerfe"))

@app.route("/veroeffentlichen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def veroeffentlichen(eid):
    stelle_id = request.form.get("stelle_id", "").strip()
    page_id = request.form.get("page_id", "").strip()
    user = session["user"]
    if not stelle_id and not page_id:
        flash("Bitte eine Beratungsstelle bzw. Facebook-Seite wählen."); return redirect(url_for("einplanung"))
    fmt = request.form.get("format", "").strip()
    with get_conn() as conn:
        e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        if fmt not in ("einzelbild", "karussell"):
            fmt = e["format"] or "einzelbild"
        try:
            f = json.loads(e["text"])
        except Exception:
            f = {}
        # Einzelbild braucht das vorgerenderte Bild; Karussell wird frisch gerendert.
        if fmt == "einzelbild" and (not e["bild_pfad"] or not os.path.exists(e["bild_pfad"])):
            flash("Kein Bild vorhanden - Veröffentlichung abgebrochen."); return redirect(url_for("einplanung"))
        ziel_seite, bilder, caption = page_id, [e["bild_pfad"]], (f.get("caption") or f.get("ueberschrift") or "")
        if stelle_id:
            stelle = conn.execute("SELECT * FROM beratungsstellen WHERE id=?", (stelle_id,)).fetchone()
            if not stelle or not stelle["fb_seite"]:
                flash("Beratungsstelle ohne Facebook-Seite."); return redirect(url_for("einplanung"))
            import personalisierung
            if fmt == "karussell":
                out_dir = os.path.join(DATA_DIR, "bilder", "karussell_%d_stelle_%d" % (eid, int(stelle["id"])))
                pf, bilder = personalisierung.render_slides_fuer_stelle(f, stelle, out_dir, "slide")
            else:
                out = os.path.join(DATA_DIR, "bilder", "post_%d_stelle_%d.png" % (eid, int(stelle["id"])))
                pf, pfad = personalisierung.render_fuer_stelle(f, stelle, out); bilder = [pfad]
            ziel_seite, caption = stelle["fb_seite"], (pf.get("caption") or caption)
        elif fmt == "karussell":
            import bildgen, bildmotiv
            out_dir = os.path.join(DATA_DIR, "bilder", "karussell_%d" % eid)
            photo = bildmotiv.ensure_photo(f.get("bild_motiv"))
            slogan = bildgen.pick_slogan(f.get("slogan"))
            bilder = bildgen.render_slides(f, photo, slogan, out_dir, "slide")
        # Sicherstellen, dass tatsaechlich Bilder vorliegen (symmetrisch zum Einzelbild-Check)
        if not [b for b in bilder if b and os.path.exists(b)]:
            flash("Kein Bild vorhanden - Veröffentlichung abgebrochen."); return redirect(url_for("einplanung"))
        # gewaehltes Format am Entwurf festhalten (Format ist Entwurfs-Eigenschaft, unabhaengig vom Publish-Erfolg)
        conn.execute("UPDATE entwuerfe SET format=? WHERE id=?", (fmt, eid))
        try:
            import publish
            if fmt == "karussell":
                ok, info = publish.publish_facebook_carousel(ziel_seite, bilder, caption)
            else:
                ok, info = publish.publish_facebook(ziel_seite, bilder[0], caption)
        except Exception as ex:
            ok, info = False, str(ex)
        if ok:
            conn.execute("INSERT INTO posts(entwurf_id, kanal, plattform_post_id, "
                         "veroeffentlicht_am, status) VALUES (?,?,?,datetime('now'),'veroeffentlicht')",
                         (eid, "facebook", info))
            conn.execute("UPDATE entwuerfe SET status='veroeffentlicht' WHERE id=?", (eid,))
            audit_log(conn, user, "veroeffentlicht_facebook", eid, "Format %s / Seite %s / Post %s" % (fmt, ziel_seite, info))
            flash("Beitrag %d als %s auf Facebook veröffentlicht." % (eid, "Karussell" if fmt == "karussell" else "Einzelbild"))
        else:
            conn.execute("INSERT INTO posts(entwurf_id, kanal, status, fehler) VALUES (?,?,?,?)",
                         (eid, "facebook", "fehler", info))
            audit_log(conn, user, "veroeffentlichung_fehler", eid, info)
            flash("Veröffentlichung fehlgeschlagen: %s" % info)
        conn.commit()
    return redirect(url_for("einplanung"))

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
    return render_template_string(VERWALTUNG, **_ctx(users=users, stellen=stellen, anlasstage=anlasstage,
                                                     wissen=wissen, bereich=bereich, bereich_titel=bereich_titel))

@app.route("/logo.png")
def logo():
    p = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png")

def serve(host="0.0.0.0", port=None):
    init_db()
    threading.Thread(target=_daily_scheduler, daemon=True).start()
    port = int(port or os.environ.get("HILO_DASHBOARD_PORT", "8530"))
    app.run(host=host, port=port, threaded=True)
