# -*- coding: utf-8 -*-
"""Seite /bstnext: BSt-Next-Beitraege (Spruchkachel in der BSt-Next-CI) anlegen, Facebook-Seite
hinterlegen. Der Entwurf laeuft danach durch die bestehende Freigabe/Einplanung (web.py), mit den
Weichen aus bstnext.guard. HILO-Code bleibt unberuehrt.

register(app, ...) wird einmal von web.py aufgerufen."""
import datetime
import hashlib
import json
import logging
import os
import uuid

from flask import Blueprint, request, redirect, url_for, session, flash, abort, render_template_string

from . import brand, kachel, guard

log = logging.getLogger("hilo.bstnext")

FORMATE_FEED = (("quadrat", "Quadrat 1080×1080 (Feed)"), ("hochformat", "Hochformat 1080×1350 (Feed)"))
MAX_CAPTION = 2000
_cfg = {"data_dir": None}      # wird von register() gesetzt; Tests duerfen es ueberschreiben

SEITE = """<!doctype html><meta charset=utf-8><title>BSt Next – ShareNext</title><style>{{ style|safe }}
.bn{max-width:960px;margin:0 auto}
.bn h2{color:#001942}
.bn label{display:block;font-weight:600;margin:14px 0 4px}
.bn textarea,.bn input[type=text],.bn input[type=date],.bn select{width:100%;box-sizing:border-box;padding:9px;border:1px solid #ccd3df;border-radius:8px;font-size:15px}
.bn textarea{min-height:76px}
.bn button{margin-top:16px;background:#001942;color:#fff;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;font-weight:700}
.bn .lime{background:#A3E635;color:#001942}
.bn .row{display:flex;gap:12px;flex-wrap:wrap}.bn .row>div{flex:1;min-width:240px}
.bn table{width:100%;border-collapse:collapse;margin-top:10px}
.bn td,.bn th{border-bottom:1px solid #e3e7ee;padding:8px;text-align:left;vertical-align:middle}
.bn img.th{width:84px;height:84px;object-fit:cover;border-radius:8px;border:1px solid #e3e7ee}
.bn .hint{color:#4B5563;font-size:13px}
</style>
<div class="bn">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
<h2 style="margin:0">BSt Next – Beitrag erstellen</h2><a href="/" style="background:#001942;color:#fff;padding:7px 13px;border-radius:8px">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=box>
<p class="hint">BSt Next ist eine eigene Marke neben HILO. Der Beitrag wird als Spruchkachel in der BSt-Next-CI
(Navy, weiße Headline, Lime als Akzent, Logo mit Claim) erzeugt, danach unter „Freigabe“ geprüft und freigegeben und
nur auf der BSt-Next-Facebook-Seite (und dem verknüpften Instagram-Konto) veröffentlicht.</p>
<form method=post action="{{ url_for('bstnext.neu') }}">
<div class=row><div><label>Weiße Zeilen (eine Bildzeile pro Zeile)</label>
<textarea name=weiss required placeholder="Wir fangen mit">{{ f.weiss }}</textarea></div>
<div><label>Lime-Zeilen (Akzent, optional)</label>
<textarea name=lime placeholder="Ihren Belegen an.">{{ f.lime }}</textarea></div></div>
<p class="hint">Der Zeilenumbruch ist Ihr Umbruch; eine Zeile darf nicht breiter als die Kachel werden (ca. 18 Zeichen).</p>
<div class=row><div><label>Format</label><select name=format>
{% for k, n in formate %}<option value="{{k}}" {% if f.format==k %}selected{% endif %}>{{n}}</option>{% endfor %}</select></div>
<div><label>Tag der Veröffentlichung (optional)</label><input type=date name=datum value="{{ f.datum }}"></div></div>
<label>Begleittext (Facebook und Instagram)</label>
<textarea name=caption required placeholder="Ihr Text. Die BSt-Next-Hashtags werden angehängt, wenn sie fehlen.">{{ f.caption }}</textarea>
<label>Alt-Text (für Screenreader, optional)</label><input type=text name=alt value="{{ f.alt }}">
<button type=submit>Kachel erstellen und als Entwurf speichern</button>
</form></div>
<div class=box style="margin-top:16px"><h3 style="margin-top:0">Facebook-Seite von BSt Next</h3>
{% if seiten %}<p>Hinterlegt: <b>{{ seiten }}</b></p>{% else %}<p class="hint">Noch keine Seite hinterlegt – ohne sie kann nichts veröffentlicht werden.</p>{% endif %}
{% if rolle == 'admin' %}<form method=post action="{{ url_for('bstnext.seite') }}">
<label>Facebook-Page-ID(s) (kommagetrennt)</label><input type=text name=seiten value="{{ seiten }}" placeholder="123456789012345">
<button type=submit>Speichern</button></form>{% else %}<p class="hint">Hinterlegen darf nur ein Admin.</p>{% endif %}</div>
<div class=box style="margin-top:16px"><h3 style="margin-top:0">Bisherige BSt-Next-Entwürfe</h3>
{% if rows %}<table><tr><th></th><th>Beitrag</th><th>Status</th><th>Tag</th><th></th></tr>
{% for r in rows %}<tr><td><img class=th src="/bild/{{r.id}}" alt=""></td><td>{{r.titel}}</td><td>{{r.status}}</td><td>{{r.datum}}</td>
<td><a href="/beitrag/{{r.id}}">öffnen / freigeben</a></td></tr>{% endfor %}</table>
{% else %}<p class="hint">Noch keine.</p>{% endif %}</div>
</div>"""


def _zeilen(text):
    return [z.strip() for z in (text or "").replace("\r", "").split("\n") if z.strip()]


def _caption_mit_hashtags(text):
    t = (text or "").strip()
    fehlend = [h for h in brand.HASHTAGS.split() if h.lower() not in t.lower()]
    if fehlend:
        t = (t + "\n\n" + " ".join(fehlend)).strip()
    return t


def register(app, get_conn, rolle_required, audit_log, get_einstellung, set_einstellung, data_dir, style):
    bp = Blueprint("bstnext", __name__)
    _cfg["data_dir"] = data_dir

    def _rows(conn):
        try:
            res = conn.execute("SELECT id, text, status, geplant_fuer FROM entwuerfe "
                               "WHERE json_extract(text,'$.marke')=? ORDER BY id DESC LIMIT 30",
                               (guard.MARKE,)).fetchall()
        except Exception:
            res = [r for r in conn.execute("SELECT id, text, status, geplant_fuer FROM entwuerfe "
                                           "ORDER BY id DESC LIMIT 300").fetchall()
                   if '"marke": "bstnext"' in (r["text"] or "")][:30]
        out = []
        for r in res:
            try:
                titel = json.loads(r["text"]).get("ueberschrift") or "Beitrag"
            except Exception:
                titel = "Beitrag"
            out.append({"id": r["id"], "titel": titel, "status": r["status"], "datum": r["geplant_fuer"] or ""})
        return out

    def _seite(f=None):
        with get_conn() as conn:
            rows = _rows(conn)
        seiten = ", ".join(sorted(guard.seiten_ids(get_einstellung(guard.EINSTELLUNG_SEITEN, ""))))
        f = f or {"weiss": "", "lime": "", "format": "quadrat", "datum": "", "caption": "", "alt": ""}
        return render_template_string(SEITE, style=style, formate=FORMATE_FEED, rows=rows, seiten=seiten,
                                      rolle=session.get("rolle"), f=f)

    @bp.route("/bstnext")
    @rolle_required("freigeber")
    def index():
        return _seite()

    @bp.route("/bstnext/neu", methods=["POST"])
    @rolle_required("freigeber")
    def neu():
        weiss = _zeilen(request.form.get("weiss"))
        lime = _zeilen(request.form.get("lime"))
        fmt = request.form.get("format", "quadrat")
        datum = (request.form.get("datum") or "").strip()
        caption = (request.form.get("caption") or "").strip()
        alt = (request.form.get("alt") or "").strip()
        eingabe = {"weiss": "\n".join(weiss), "lime": "\n".join(lime), "format": fmt, "datum": datum,
                   "caption": caption, "alt": alt}
        if fmt not in dict(FORMATE_FEED):
            flash("Unbekanntes Format.")
            return _seite(eingabe)
        if not weiss:
            flash("Bitte mindestens eine weiße Zeile angeben.")
            return _seite(eingabe)
        if not caption:
            flash("Bitte einen Begleittext angeben.")
            return _seite(eingabe)
        caption = _caption_mit_hashtags(caption)
        if len(caption) > MAX_CAPTION:
            flash("Der Begleittext ist zu lang (höchstens %d Zeichen inklusive Hashtags)." % MAX_CAPTION)
            return _seite(eingabe)
        if datum:
            try:
                d = datetime.date.fromisoformat(datum)
            except ValueError:
                flash("Ungültiges Datum.")
                return _seite(eingabe)
            if d < datetime.date.today():
                flash("Der Tag liegt in der Vergangenheit – bitte einen Tag ab heute wählen.")
                return _seite(eingabe)
        out_dir = os.path.join(_cfg["data_dir"], "bilder")
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, "bstnext_tmp_%s.png" % uuid.uuid4().hex)
        try:
            kachel.render(weiss, lime, tmp, fmt)
        except kachel.KachelFehler as ex:
            flash("Kachel nicht erzeugbar: %s" % ex)
            return _seite(eingabe)
        titel = " ".join(weiss + lime)
        fields = {
            "marke": guard.MARKE, "kampagne": guard.MARKE,
            "ueberschrift": titel,
            "caption": caption, "captions": {"facebook": caption, "instagram": caption},
            "alt_text": alt or titel,
            "bild_format": fmt,
            "bstnext": {"weiss": weiss, "lime": lime, "format": fmt},
        }
        h = hashlib.sha256(("bstnext:%s:%s" % (titel, datetime.datetime.now().isoformat())).encode("utf-8")).hexdigest()
        with get_conn() as conn:
            # Thema als 'erledigt': nie vom HILO-Generator ('ausgewaehlt') aufgegriffen
            cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                               "VALUES ('bstnext', ?, 'erledigt', ?, ?)", (titel[:300], titel, h))
            cur = conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer) "
                               "VALUES (?, 'facebook', ?, 'entwurf', ?)",
                               (cur.lastrowid, json.dumps(fields, ensure_ascii=False), datum or None))
            eid = cur.lastrowid
            ziel = os.path.join(out_dir, "bstnext_%d.png" % eid)
            os.replace(tmp, ziel)
            conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (ziel, eid))
            audit_log(conn, session.get("user"), "bstnext_beitrag", eid, "Kachel '%s'" % titel[:60])
            conn.commit()
        flash("BSt-Next-Entwurf %d erstellt – jetzt unter „Freigabe“ prüfen und freigeben." % eid)
        return redirect(url_for("bstnext.index"))

    @bp.route("/bstnext/seite", methods=["POST"])
    @rolle_required("admin")
    def seite():
        ids = sorted(guard.seiten_ids(request.form.get("seiten", "")))
        if any(not i.isdigit() for i in ids):
            flash("Eine Facebook-Page-ID besteht nur aus Ziffern.")
            return redirect(url_for("bstnext.index"))
        set_einstellung(guard.EINSTELLUNG_SEITEN, ",".join(ids))
        with get_conn() as conn:
            audit_log(conn, session.get("user"), "bstnext_seite", None, "%d Seite(n)" % len(ids))
            conn.commit()
        flash("BSt-Next-Facebook-Seite gespeichert." if ids else "BSt-Next-Facebook-Seite entfernt.")
        return redirect(url_for("bstnext.index"))

    app.register_blueprint(bp)

    @app.before_request
    def _bstnext_sperre():
        """HILO-Funktionen, die per HILO-Pipeline neu rendern oder in HILO-Pools/WhatsApp geben
        wuerden, sind fuer BSt-Next-Entwuerfe gesperrt (siehe bstnext.guard)."""
        ep = request.endpoint or ""
        eid = (request.view_args or {}).get("eid")
        if eid is None or request.method != "POST":
            return None
        if not guard.endpoint_gesperrt(ep, request.form.get("aktion")):
            return None
        try:
            with get_conn() as conn:
                row = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
            f = json.loads(row["text"]) if row else {}
        except Exception:
            return None
        if guard.ist_bstnext(f):
            flash(guard.MELDUNG_GESPERRT)
            return redirect(url_for("bstnext.index"))
        return None
