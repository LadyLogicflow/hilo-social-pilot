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
import threading
import uuid

from flask import Blueprint, request, redirect, url_for, session, flash, abort, render_template_string, send_file

from . import brand, kachel, guard, szene

log = logging.getLogger("hilo.bstnext")

FORMATE_FEED = (("quadrat", "Quadrat 1080×1080 (Feed)"), ("hochformat", "Hochformat 1080×1350 (Feed)"))
MAX_CAPTION = 2000
_cfg = {"data_dir": None,          # wird von register() gesetzt; Tests duerfen es ueberschreiben
        "szene_fn": None,          # Foto-Erzeugung (Standard: szene.erzeuge_szene)
        "sync": False,             # True: Foto-Job im Aufruf statt im Hintergrund (Tests)
        "pages_fn": None,
        "publish_fn": None}        # (conn, entwurf, eid, fields, kanal, page_id, user) -> (ziel, erfolg, [(kanal, ok, info)])          # liefert (Liste der Facebook-Seiten, Fehlertext); von register() gesetzt
MOTIVE = (("belege", "Belege"), ("termine", "Termine"), ("telefon", "Telefon"), ("werbung", "Werbung"),
          ("challenge", "Challenge"))

ANSICHT = """<!doctype html><meta charset=utf-8><title>BSt Next – Beitrag ansehen</title><style>{{ style|safe }}
.bn{max-width:760px;margin:0 auto}
.bn h2{color:#001942}
.bn img.gross{width:100%;max-width:540px;border-radius:10px;border:1px solid #e3e7ee;display:block;margin:0 0 14px}
.bn .cap{white-space:pre-wrap;background:#f6f8fb;border:1px solid #e3e7ee;border-radius:8px;padding:12px}
.bn .hint{color:#4B5563;font-size:13px}
.bn a.btn{display:inline-block;margin:0 8px 8px 0;padding:7px 13px;border-radius:8px;background:#001942;color:#fff;text-decoration:none;font-weight:700;font-size:14px}
</style>
<div class="bn">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
<h2 style="margin:0">BSt Next – Beitrag {{ eid }}</h2><a class="btn" href="{{ url_for('bstnext.index') }}">&larr; zur Liste</a></div>
<p class="hint">Status: <b>{{ status }}</b>{% if datum %} · Tag: {{ datum }}{% endif %}{% if typ == 'karussell' %} · Karussell, 3 Slides{% elif typ == 'foto' %} · Foto-Look{% endif %}{% if eingeplant %} · eingeplant für {{ eingeplant }}{% endif %}</p>
{% if bilder %}{% for nr in bilder %}<img class="gross" src="{{ url_for('bstnext.bild', eid=eid, nr=nr) }}" alt="">{% endfor %}
{% else %}<p class="hint">Das Bild ist noch nicht fertig.</p>{% endif %}
<h3>Begleittext (Facebook und Instagram)</h3><div class="cap">{{ caption }}</div>
<p class="hint">Alt-Text: {{ alt }}</p>
{% if bearbeitbar %}<a class="btn" href="{{ url_for('bstnext.bearbeiten', eid=eid) }}">Bearbeiten</a>{% endif %}
</div>"""

SEITE = """<!doctype html><meta charset=utf-8><title>BSt Next – ShareNext</title>{% if laeuft %}<meta http-equiv=refresh content=8>{% endif %}<style>{{ style|safe }}
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
<h2 style="margin:0">BSt Next – {% if bearb %}Beitrag {{ bearb }} bearbeiten{% else %}Beitrag erstellen{% endif %}</h2><a href="/" style="background:#001942;color:#fff;padding:7px 13px;border-radius:8px">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=box>
<p class="hint">BSt Next ist eine eigene Marke neben HILO. Der Beitrag wird als Spruchkachel in der BSt-Next-CI
(Navy, weiße Headline, Lime als Akzent, Logo mit Claim) erzeugt, danach unter „Freigabe“ geprüft und freigegeben und
nur auf der BSt-Next-Facebook-Seite (und dem verknüpften Instagram-Konto) veröffentlicht.</p>
{% if bearb %}<p class="hint"><b>Bearbeiten:</b> Beim Speichern wird das Bild neu erzeugt und der Beitrag steht wieder auf „entwurf“ (danach neu freigeben). <a href="{{ url_for('bstnext.index') }}">Abbrechen</a></p>{% endif %}
<form method=post action="{{ form_action }}">
<div class=row><div><label>Weiße Zeilen (eine Bildzeile pro Zeile)</label>
<textarea name=weiss required placeholder="Wir fangen mit">{{ f.weiss }}</textarea></div>
<div><label>Lime-Zeilen (Akzent, optional)</label>
<textarea name=lime placeholder="Ihren Belegen an.">{{ f.lime }}</textarea></div></div>
<label>Weiße Zeilen nach dem Lime-Teil (optional, z. B. ein Schlusssatz)</label>
<textarea name=weiss_nach placeholder="Nur SortNext in time.">{{ f.weiss_nach }}</textarea>
<p class="hint"><b>Nur bei Karussell:</b> Die Zeilen oben sind Slide 1. Slide 1 und 2 haben nur Text, Slide 3 hat Text und unten das Logo mit Claim.</p>
<div class=row><div><label>Slide 2 – weiße Zeilen</label><textarea name=weiss2>{{ f.weiss2 }}</textarea></div>
<div><label>Slide 2 – Lime-Zeilen (optional)</label><textarea name=lime2>{{ f.lime2 }}</textarea></div></div>
<label>Slide 2 – weiße Zeilen nach dem Lime-Teil (optional)</label><textarea name=weiss_nach2>{{ f.weiss_nach2 }}</textarea>
<div class=row><div><label>Slide 3 – weiße Zeilen</label><textarea name=weiss3>{{ f.weiss3 }}</textarea></div>
<div><label>Slide 3 – Lime-Zeilen (optional)</label><textarea name=lime3>{{ f.lime3 }}</textarea></div></div>
<label>Slide 3 – weiße Zeilen nach dem Lime-Teil (optional)</label><textarea name=weiss_nach3>{{ f.weiss_nach3 }}</textarea>
<p class="hint">Foto-Look: Die KI erzeugt nur das Foto (ohne Schrift, nur fiktive Personen); Headline und Logo setzt das Programm. Danach prüft eine Bildkontrolle gegen die Vermeidungsliste.</p>
<p class="hint">Eigene Zeilenumbrüche bleiben erhalten; zu lange Zeilen bricht das Programm nach Wörtern selbst um (eine Zeile hat etwa 18 Zeichen Platz, höchstens 5–6 Zeilen insgesamt).</p>
<div class=row><div><label>Bildtyp</label><select name=bildtyp>
<option value="kachel" {% if f.bildtyp!='foto' %}selected{% endif %}>Spruchkachel (sofort fertig)</option>
<option value="foto" {% if f.bildtyp=='foto' %}selected{% endif %}>Foto-Look mit KI (dauert 1–2 Minuten)</option>
<option value="karussell" {% if f.bildtyp=='karussell' %}selected{% endif %}>Karussell mit 3 Slides (Facebook + Instagram)</option></select></div>
<div><label>Motiv (nur Foto-Look)</label><select name=motiv>
{% for k, n in motive %}<option value="{{k}}" {% if f.motiv==k %}selected{% endif %}>{{n}}</option>{% endfor %}</select></div></div>
<div class=row><div><label>Format</label><select name=format>
{% for k, n in formate %}<option value="{{k}}" {% if f.format==k %}selected{% endif %}>{{n}}</option>{% endfor %}</select></div>
<div><label>Tag der Veröffentlichung (optional)</label><input type=date name=datum value="{{ f.datum }}"></div></div>
<label>Begleittext (Facebook und Instagram)</label>
<textarea name=caption required placeholder="Ihr Text. Die BSt-Next-Hashtags werden angehängt, wenn sie fehlen.">{{ f.caption }}</textarea>
<label>Alt-Text (für Screenreader, optional)</label><input type=text name=alt value="{{ f.alt }}">
<button type=submit>{% if bearb %}Änderungen speichern und Bild neu erzeugen{% else %}Beitrag erstellen und als Entwurf speichern{% endif %}</button>
</form></div>
<div class=box style="margin-top:16px"><h3 style="margin-top:0">Facebook-Seite von BSt Next</h3>
{% if seiten %}<p>Hinterlegt: <b>{{ seiten }}</b></p>{% else %}<p class="hint">Noch keine Seite hinterlegt – ohne sie kann nichts veröffentlicht werden.</p>{% endif %}
{% if rolle == 'admin' %}<form method=post action="{{ url_for('bstnext.seite') }}">
{% if seiten_liste %}<label>Seite wählen (alle Facebook-Seiten, die der Zugang des Programms erreicht)</label>
<select name=seite_wahl><option value="">– keine Auswahl (unten ID eintragen oder Seite entfernen) –</option>
{% for p in seiten_liste %}<option value="{{p.id}}" {% if p.id in seiten_aktiv %}selected{% endif %}>{{p.name}} ({{p.id}}){% if p.ig_username %} · Instagram @{{p.ig_username}}{% else %} · kein Instagram verknüpft{% endif %}</option>{% endfor %}</select>
{% elif seiten_fehler %}<p class="hint">Die Seitenliste von Facebook konnte nicht geladen werden: {{seiten_fehler}}</p>{% endif %}
<label>Oder Facebook-Page-ID von Hand (kommagetrennt)</label><input type=text name=seiten value="{{ seiten if not seiten_liste else '' }}" placeholder="123456789012345">
<p class="hint">Die Auswahl hat Vorrang, wenn beides gefüllt ist. Beide Felder leer = Seite entfernen.</p>
<button type=submit>Speichern</button></form>{% else %}<p class="hint">Hinterlegen darf nur ein Admin.</p>{% endif %}</div>
<div class=box style="margin-top:16px"><h3 style="margin-top:0">Bisherige BSt-Next-Entwürfe</h3>
{% if rows %}<table><tr><th></th><th>Beitrag</th><th>Status</th><th>Tag</th><th></th></tr>
{% for r in rows %}<tr><td>{% if r.bild_status=='fertig' %}<img class=th src="/bild/{{r.id}}" alt="">{% endif %}</td><td>{{r.titel}}{% if r.typ=='foto' %} <span class="hint">(Foto-Look)</span>{% elif r.typ=='karussell' %} <span class="hint">(Karussell, 3 Slides)</span>{% endif %}</td>
<td>{{r.status}}{% if r.bild_status=='laeuft' %}<br><span class="hint">Bild wird erzeugt …</span>{% elif r.bild_status=='fehler' %}<br><span class="hint">Bild fehlgeschlagen: {{r.info}}</span>{% endif %}</td><td>{{r.datum}}</td>
<td>{% if r.bild_status!='fertig' %}<form method=post action="{{ url_for('bstnext.foto_neu', eid=r.id) }}" style="margin:0"><button type=submit style="margin:0;padding:6px 10px">Bild neu erzeugen</button></form>
{% elif r.status=='entwurf' %}<form method=post action="{{ url_for('bstnext.freigeben', eid=r.id) }}" style="margin:0"><button type=submit style="margin:0;padding:6px 10px">Freigeben</button></form>
{% elif r.status=='freigegeben' and r.eingeplant %}<b>eingeplant für {{r.eingeplant}}</b><br><span class="hint">Ändern oder löschen unter „Geplante Veröffentlichungen“ (<a href="/geplant">öffnen</a>).</span>
{% elif r.status=='freigegeben' %}
{% if seiten_ids %}<form method=post action="{{ url_for('bstnext.veroeffentlichen', eid=r.id) }}" style="margin:0 0 8px" onsubmit="return confirm('Jetzt auf der BSt-Next-Seite veröffentlichen? Das ist ein echter Post.')">
<select name=page_id>{% for pid in seiten_ids %}<option value="{{pid}}">Seite {{pid}}</option>{% endfor %}</select>
<select name=kanal><option value="beide">Facebook + Instagram</option><option value="facebook">nur Facebook</option><option value="instagram">nur Instagram</option></select>
{% if r.typ!='karussell' %}<label style="display:inline-block;margin:0 8px"><input type=checkbox name=story_fb value="1"> Zusätzlich als Facebook-Story</label>{% endif %}
<button type=submit style="margin:0;padding:6px 10px">Jetzt veröffentlichen</button></form>
{% if r.typ=='karussell' %}<span class="hint">Einplanen mit Karussell folgt später.</span>{% else %}<form method=post action="{{ url_for('bstnext.einplanen', eid=r.id) }}" style="margin:0">
<input type=date name=datum required style="width:auto"> <input type=time name=zeit required style="width:auto">
<select name=page_id>{% for pid in seiten_ids %}<option value="{{pid}}">Seite {{pid}}</option>{% endfor %}</select>
<select name=kanal><option value="beide">Facebook + Instagram</option><option value="facebook">nur Facebook</option><option value="instagram">nur Instagram</option></select>
<button type=submit style="margin:0;padding:6px 10px">Einplanen</button></form>{% endif %}
{% else %}<span class="hint">Erst oben die BSt-Next-Facebook-Seite hinterlegen.</span>{% endif %}
{% else %}<a href="/beitrag/{{r.id}}">ansehen</a>{% endif %}
<a href="{{ url_for('bstnext.ansehen', eid=r.id) }}" style="display:inline-block;margin:8px 8px 0 0;padding:6px 10px;border:1px solid #001942;border-radius:8px;color:#001942;font-weight:700;font-size:13px;text-decoration:none">Ansehen</a>
{% if r.status!='veroeffentlicht' and not r.eingeplant and r.bild_status!='laeuft' %}<a href="{{ url_for('bstnext.bearbeiten', eid=r.id) }}" style="display:inline-block;margin:8px 8px 0 0;padding:6px 10px;border:1px solid #001942;border-radius:8px;color:#001942;font-weight:700;font-size:13px;text-decoration:none">Bearbeiten</a>{% endif %}
{% if r.status!='veroeffentlicht' and not r.eingeplant %}<form method=post action="{{ url_for('bstnext.loeschen', eid=r.id) }}" style="margin:8px 0 0" onsubmit="return confirm('Diesen Beitrag wirklich löschen?')"><button type=submit style="margin:0;padding:6px 10px;background:#b00020">Löschen</button></form>{% endif %}</td></tr>{% endfor %}</table>
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


def register(app, get_conn, rolle_required, audit_log, get_einstellung, set_einstellung, data_dir, style,
             pages_fn=None, publish_fn=None):
    bp = Blueprint("bstnext", __name__)
    _cfg["data_dir"] = data_dir
    _cfg["pages_fn"] = pages_fn
    _cfg["publish_fn"] = publish_fn

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
                fl = json.loads(r["text"])
            except Exception:
                fl = {}
            out.append({"id": r["id"], "titel": fl.get("ueberschrift") or "Beitrag", "status": r["status"],
                        "datum": r["geplant_fuer"] or "", "typ": (fl.get("bstnext") or {}).get("typ", "kachel"),
                        "bild_status": fl.get("bild_status", "fertig"), "info": fl.get("bild_info", ""),
                        "eingeplant": _einplanung_text(conn, r["id"])})
        return out

    def _einplanung(conn, eid):
        """Fruehester noch offener geplanter Post dieses Beitrags (geplant_am) oder None.
        Gelöscht (/geplant-loeschen) oder gepostet = nicht mehr offen."""
        row = conn.execute("SELECT MIN(geplant_am) FROM geplante_posts WHERE entwurf_id=? "
                           "AND status IN ('geplant','laeuft')", (eid,)).fetchone()
        return row[0] if row and row[0] else None

    def _einplanung_text(conn, eid):
        t = _einplanung(conn, eid)
        if not t:
            return ""
        try:
            d = datetime.datetime.strptime(t[:16], "%Y-%m-%dT%H:%M")
            return d.strftime("%d.%m.%Y um %H:%M Uhr")
        except ValueError:
            return t

    def _seite(f=None, bearb=None):
        with get_conn() as conn:
            rows = _rows(conn)
        aktiv = guard.seiten_ids(get_einstellung(guard.EINSTELLUNG_SEITEN, ""))
        seiten = ", ".join(sorted(aktiv))
        liste, fehler = [], None
        if _cfg["pages_fn"] and session.get("rolle") == "admin":
            try:
                liste, fehler = _cfg["pages_fn"]()
                liste = [p for p in (liste or []) if p.get("id")]
            except Exception as ex:
                liste, fehler = [], str(ex)
        f = f or {"weiss": "", "lime": "", "format": "quadrat", "datum": "", "caption": "", "alt": "",
                  "bildtyp": "kachel", "motiv": "belege",
                  "weiss2": "", "lime2": "", "weiss3": "", "lime3": "",
                  "weiss_nach": "", "weiss_nach2": "", "weiss_nach3": ""}
        return render_template_string(SEITE, style=style, formate=FORMATE_FEED, motive=MOTIVE, rows=rows,
                                      seiten=seiten, seiten_liste=liste, seiten_fehler=fehler, seiten_aktiv=aktiv, seiten_ids=sorted(aktiv),
                                      rolle=session.get("rolle"), f=f, bearb=bearb,
                                      form_action=url_for("bstnext.bearbeiten", eid=bearb) if bearb else url_for("bstnext.neu"),
                                      laeuft=any(r["bild_status"] == "laeuft" for r in rows))

    def _foto_job(eid):
        """Erzeugt das Foto (Typ C) und traegt das Ergebnis in den Entwurf ein. Fehler werden sichtbar
        gespeichert (bild_status='fehler'), nie verschluckt."""
        try:
            with get_conn() as conn:
                row = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
            fl = json.loads(row["text"])
            bs = fl["bstnext"]
            ziel = os.path.join(_cfg["data_dir"], "bilder", "bstnext_%d.png" % eid)
            fn = _cfg["szene_fn"] or szene.erzeuge_szene
            prot = fn(fl["ueberschrift"], bs["weiss"], bs["lime"], bs["format"], bs.get("motiv"), ziel)
            fl["bild_status"], fl["bild_info"] = "fertig", ""
            fl["bstnext"]["protokoll"] = {k: prot.get(k) for k in ("route", "kategorie", "prompt", "jury", "qa", "versuche")}
            pfad = prot.get("pfad") or ziel
        except Exception as ex:
            log.warning("BSt-Next-Foto %s fehlgeschlagen: %s", eid, ex)
            try:
                with get_conn() as conn:
                    row = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
                    fl = json.loads(row["text"])
                    fl["bild_status"], fl["bild_info"] = "fehler", str(ex)[:300]
                    conn.execute("UPDATE entwuerfe SET text=? WHERE id=?",
                                 (json.dumps(fl, ensure_ascii=False), eid))
                    conn.commit()
            except Exception:
                log.exception("Fehlerstatus fuer Foto %s nicht speicherbar", eid)
            return
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(fl, ensure_ascii=False), pfad, eid))
            audit_log(conn, "system", "bstnext_foto_fertig", eid, "Route %s" % (fl["bstnext"]["protokoll"].get("route") or ""))
            conn.commit()

    def _foto_starten(eid):
        if _cfg["sync"]:
            _foto_job(eid)
        else:
            threading.Thread(target=_foto_job, args=(eid,), daemon=True).start()

    @bp.route("/bstnext/foto-neu/<int:eid>", methods=["POST"])
    @rolle_required("freigeber")
    def foto_neu(eid):
        with get_conn() as conn:
            row = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
            if not row:
                abort(404)
            fl = json.loads(row["text"])
            if not guard.ist_bstnext(fl) or (fl.get("bstnext") or {}).get("typ") != "foto":
                abort(404)
            if fl.get("bild_status") == "fertig":
                flash("Das Bild ist schon fertig.")
                return redirect(url_for("bstnext.index"))
            fl["bild_status"], fl["bild_info"] = "laeuft", ""
            conn.execute("UPDATE entwuerfe SET text=? WHERE id=?", (json.dumps(fl, ensure_ascii=False), eid))
            conn.commit()
        _foto_starten(eid)
        flash("Das Foto wird neu erzeugt (1–2 Minuten).")
        return redirect(url_for("bstnext.index"))

    @bp.route("/bstnext")
    @rolle_required("freigeber")
    def index():
        return _seite()

    def _bearbeiten_sperre(conn, row, f, eid):
        """Meldung, warum ein Beitrag nicht bearbeitbar ist, sonst leer."""
        if row["status"] == "veroeffentlicht":
            return "Ein veröffentlichter Beitrag bleibt als Nachweis erhalten und lässt sich nicht bearbeiten."
        eingeplant = _einplanung_text(conn, eid)
        if eingeplant:
            return ("Der Beitrag ist eingeplant für %s. Bitte zuerst die Einplanung unter „Geplante "
                    "Veröffentlichungen“ löschen." % eingeplant)
        if f.get("bild_status") == "laeuft":
            return "Das Foto wird gerade erzeugt – bitte warten, bis es fertig ist."
        return ""

    def _eingabe_aus(row, f):
        """Formularwerte aus einem gespeicherten Beitrag (fuer Bearbeiten)."""
        bs = f.get("bstnext") or {}
        typ = bs.get("typ", "kachel")

        def j(zeilen):
            return "\n".join(zeilen or [])
        titel = f.get("ueberschrift", "")
        alt = f.get("alt_text") or ""
        eingabe = {"weiss": j(bs.get("weiss")), "lime": j(bs.get("lime")), "weiss_nach": j(bs.get("weiss_nach")),
                   "format": bs.get("format", "quadrat"), "datum": row["geplant_fuer"] or "",
                   "caption": f.get("caption", ""), "alt": "" if alt == titel else alt,
                   "bildtyp": typ, "motiv": bs.get("motiv", "belege"),
                   "weiss2": "", "lime2": "", "weiss3": "", "lime3": "", "weiss_nach2": "", "weiss_nach3": ""}
        if typ == "karussell":
            slides = bs.get("slides") or []
            for nr, i in (("2", 1), ("3", 2)):
                if len(slides) > i:
                    eingabe["weiss" + nr] = j(slides[i].get("weiss"))
                    eingabe["lime" + nr] = j(slides[i].get("lime"))
                    eingabe["weiss_nach" + nr] = j(slides[i].get("weiss_nach"))
        return eingabe

    def _bild_pfade(row, f):
        bs = f.get("bstnext") or {}
        pfade = list(bs.get("bilder") or []) or ([row["bild_pfad"]] if row["bild_pfad"] else [])
        return [p for p in pfade if p and os.path.exists(p)]

    @bp.route("/bstnext/ansehen/<int:eid>")
    @rolle_required("freigeber")
    def ansehen(eid):
        """Grosse Ansicht: Bild(er), voller Begleittext, Alt-Text und Status."""
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            sperre = _bearbeiten_sperre(conn, row, f, eid)
            eingeplant = _einplanung_text(conn, eid)
        pfade = _bild_pfade(row, f)
        return render_template_string(
            ANSICHT, style=style, eid=eid, status=row["status"], datum=row["geplant_fuer"] or "",
            typ=(f.get("bstnext") or {}).get("typ", "kachel"), eingeplant=eingeplant,
            bilder=list(range(1, len(pfade) + 1)), caption=f.get("caption", ""),
            alt=f.get("alt_text", ""), bearbeitbar=not sperre)

    @bp.route("/bstnext/bild/<int:eid>/<int:nr>")
    @rolle_required("freigeber")
    def bild(eid, nr):
        with get_conn() as conn:
            row, f = _lade(conn, eid)
        pfade = _bild_pfade(row, f)
        if nr < 1 or nr > len(pfade):
            abort(404)
        return send_file(pfade[nr - 1], mimetype="image/png", max_age=0)

    @bp.route("/bstnext/neu", methods=["POST"])
    @rolle_required("freigeber")
    def neu():
        return _speichern(None)

    @bp.route("/bstnext/bearbeiten/<int:eid>", methods=["GET", "POST"])
    @rolle_required("freigeber")
    def bearbeiten(eid):
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            sperre = _bearbeiten_sperre(conn, row, f, eid)
            eingabe = _eingabe_aus(row, f)
        if sperre:
            flash(sperre)
            return redirect(url_for("bstnext.index"))
        if request.method == "POST":
            return _speichern(eid)
        return _seite(eingabe, eid)

    def _aktualisieren(eid, fields, titel, datum, foto, karussell, tmp, tmps, out_dir):
        """Bearbeiten: ersetzt Inhalt und Bild des Beitrags, Status zurueck auf 'entwurf'."""
        with get_conn() as conn:
            row, f_alt = _lade(conn, eid)
            alt = {row["bild_pfad"]} | set((f_alt.get("bstnext") or {}).get("bilder") or [])
            neue = set()
            bild = None
            if karussell:
                pfade = []
                for nr, t in enumerate(tmps, 1):
                    ziel = os.path.join(out_dir, "bstnext_%d_s%d.png" % (eid, nr))
                    os.replace(t, ziel)
                    pfade.append(ziel)
                fields["bstnext"]["bilder"] = pfade
                bild, neue = pfade[0], set(pfade)
            elif not foto:
                ziel = os.path.join(out_dir, "bstnext_%d.png" % eid)
                os.replace(tmp, ziel)
                bild, neue = ziel, {ziel}
            conn.execute("UPDATE entwuerfe SET text=?, status='entwurf', geplant_fuer=?, bild_pfad=? WHERE id=?",
                         (json.dumps(fields, ensure_ascii=False), datum or None, bild, eid))
            conn.execute("UPDATE themen SET titel=?, volltext=? WHERE id=(SELECT thema_id FROM entwuerfe WHERE id=?)",
                         (titel[:300], titel, eid))
            audit_log(conn, session.get("user"), "bstnext_bearbeitet", eid, titel[:60])
            conn.commit()
        for pfad in alt - neue:
            if pfad and os.path.exists(pfad):
                try:
                    os.remove(pfad)
                except OSError:
                    log.warning("Altes Bild %s von BSt-Next-Beitrag %s nicht loeschbar", pfad, eid)
        if foto:
            _foto_starten(eid)
            flash("Beitrag %d gespeichert – das Foto wird neu erzeugt (1–2 Minuten); danach neu freigeben." % eid)
        else:
            flash("Beitrag %d gespeichert – bitte prüfen und neu freigeben." % eid)
        return redirect(url_for("bstnext.index"))

    def _speichern(eid):
        """Neu anlegen (eid=None) oder bestehenden Beitrag bearbeiten."""
        alt_datum = None
        if eid:
            with get_conn() as conn:
                row0, f0 = _lade(conn, eid)
                sperre = _bearbeiten_sperre(conn, row0, f0, eid)
            if sperre:
                flash(sperre)
                return redirect(url_for("bstnext.index"))
            alt_datum = row0["geplant_fuer"] or ""
        fmt = request.form.get("format", "quadrat")
        weiss = _zeilen(request.form.get("weiss"))
        lime = _zeilen(request.form.get("lime"))
        if fmt in dict(FORMATE_FEED):
            # Zu lange Zeilen werden nach Woertern umgebrochen (eigene Umbrueche bleiben erhalten)
            weiss, lime = kachel.umbrechen(weiss, fmt), kachel.umbrechen(lime, fmt)
            nach = kachel.umbrechen(_zeilen(request.form.get("weiss_nach")), fmt)
        else:
            nach = _zeilen(request.form.get("weiss_nach"))
        datum = (request.form.get("datum") or "").strip()
        caption = (request.form.get("caption") or "").strip()
        alt = (request.form.get("alt") or "").strip()
        bildtyp = request.form.get("bildtyp", "kachel")
        motiv = request.form.get("motiv", "belege")
        karussell = bildtyp == "karussell"
        folien = [(weiss, lime, False, nach)]
        if karussell and fmt in dict(FORMATE_FEED):
            for nr in ("2", "3"):
                w2 = kachel.umbrechen(_zeilen(request.form.get("weiss" + nr)), fmt)
                l2 = kachel.umbrechen(_zeilen(request.form.get("lime" + nr)), fmt)
                n2 = kachel.umbrechen(_zeilen(request.form.get("weiss_nach" + nr)), fmt)
                folien.append((w2, l2, nr == "3", n2))   # Slide 3 traegt das Logo mit Claim
        eingabe = {"weiss": "\n".join(weiss), "lime": "\n".join(lime), "format": fmt, "datum": datum,
                   "caption": caption, "alt": alt, "bildtyp": bildtyp, "motiv": motiv,
                   "weiss_nach": "\n".join(nach),
                   "weiss_nach2": "\n".join(folien[1][3]) if len(folien) > 1 else "",
                   "weiss_nach3": "\n".join(folien[2][3]) if len(folien) > 2 else "",
                   "weiss2": "\n".join(folien[1][0]) if len(folien) > 1 else "",
                   "lime2": "\n".join(folien[1][1]) if len(folien) > 1 else "",
                   "weiss3": "\n".join(folien[2][0]) if len(folien) > 2 else "",
                   "lime3": "\n".join(folien[2][1]) if len(folien) > 2 else ""}
        if bildtyp not in ("kachel", "foto", "karussell") or motiv not in dict(MOTIVE):
            flash("Unbekannter Bildtyp oder Motiv.")
            return _seite(eingabe, eid)
        if fmt not in dict(FORMATE_FEED):
            flash("Unbekanntes Format.")
            return _seite(eingabe, eid)
        if not weiss:
            flash("Bitte mindestens eine weiße Zeile angeben.")
            return _seite(eingabe, eid)
        if bildtyp == "foto" and (nach or request.form.get("weiss_nach2") or request.form.get("weiss_nach3")):
            flash("Weiße Zeilen nach dem Lime-Teil gehen bisher nur bei Spruchkachel und Karussell, nicht beim Foto-Look.")
            return _seite(eingabe, eid)
        if karussell and any(not w for w, _l, _g, _n in folien):
            flash("Beim Karussell braucht jeder der 3 Slides mindestens eine weiße Zeile.")
            return _seite(eingabe, eid)
        if not caption:
            flash("Bitte einen Begleittext angeben.")
            return _seite(eingabe, eid)
        caption = _caption_mit_hashtags(caption)
        if len(caption) > MAX_CAPTION:
            flash("Der Begleittext ist zu lang (höchstens %d Zeichen inklusive Hashtags)." % MAX_CAPTION)
            return _seite(eingabe, eid)
        if datum:
            try:
                d = datetime.date.fromisoformat(datum)
            except ValueError:
                flash("Ungültiges Datum.")
                return _seite(eingabe, eid)
            if d < datetime.date.today() and not (eid and datum == alt_datum):
                flash("Der Tag liegt in der Vergangenheit – bitte einen Tag ab heute wählen.")
                return _seite(eingabe, eid)
        out_dir = os.path.join(_cfg["data_dir"], "bilder")
        os.makedirs(out_dir, exist_ok=True)
        titel = " ".join(weiss + lime + nach)
        foto = bildtyp == "foto"
        tmp = os.path.join(out_dir, "bstnext_tmp_%s.png" % uuid.uuid4().hex)
        tmps = []
        try:
            if foto:
                kachel.pruefe_zeilen(weiss, lime, fmt)        # keine KI-Kosten bei unbrauchbaren Zeilen
            elif karussell:
                for nr, (w, l, mit_logo, n) in enumerate(folien, 1):
                    t = os.path.join(out_dir, "bstnext_tmp_%s_s%d.png" % (uuid.uuid4().hex, nr))
                    tmps.append(t)
                    try:
                        kachel.render(w, l, t, fmt, mit_logo=mit_logo, weisse_nach=n)
                    except kachel.KachelFehler as ex:
                        raise kachel.KachelFehler("Slide %d: %s" % (nr, ex))
            else:
                kachel.render(weiss, lime, tmp, fmt, weisse_nach=nach)
        except kachel.KachelFehler as ex:
            for t in tmps:
                if os.path.exists(t):
                    os.remove(t)
            flash("Kachel nicht erzeugbar: %s" % ex)
            return _seite(eingabe, eid)
        fields = {
            "marke": guard.MARKE, "kampagne": guard.MARKE,
            "ueberschrift": titel,
            "caption": caption, "captions": {"facebook": caption, "instagram": caption},
            "alt_text": alt or titel,
            "bild_format": fmt,
            "bild_status": "laeuft" if foto else "fertig",
            "bstnext": {"typ": "foto" if foto else ("karussell" if karussell else "kachel"),
                        "weiss": weiss, "lime": lime, "weiss_nach": nach, "format": fmt, "motiv": motiv},
        }
        if karussell:
            fields["bstnext"]["slides"] = [{"weiss": w, "lime": l, "logo": g, "weiss_nach": n}
                                           for w, l, g, n in folien]
        if eid:
            return _aktualisieren(eid, fields, titel, datum, foto, karussell, tmp, tmps, out_dir)
        h = hashlib.sha256(("bstnext:%s:%s" % (titel, datetime.datetime.now().isoformat())).encode("utf-8")).hexdigest()
        with get_conn() as conn:
            # Thema als 'erledigt': nie vom HILO-Generator ('ausgewaehlt') aufgegriffen
            cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                               "VALUES ('bstnext', ?, 'erledigt', ?, ?)", (titel[:300], titel, h))
            cur = conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer) "
                               "VALUES (?, 'facebook', ?, 'entwurf', ?)",
                               (cur.lastrowid, json.dumps(fields, ensure_ascii=False), datum or None))
            eid = cur.lastrowid
            if karussell:
                pfade = []
                for nr, t in enumerate(tmps, 1):
                    ziel = os.path.join(out_dir, "bstnext_%d_s%d.png" % (eid, nr))
                    os.replace(t, ziel)
                    pfade.append(ziel)
                fields["bstnext"]["bilder"] = pfade
                conn.execute("UPDATE entwuerfe SET bild_pfad=?, text=? WHERE id=?",
                             (pfade[0], json.dumps(fields, ensure_ascii=False), eid))
            elif not foto:
                ziel = os.path.join(out_dir, "bstnext_%d.png" % eid)
                os.replace(tmp, ziel)
                conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (ziel, eid))
            audit_log(conn, session.get("user"), "bstnext_beitrag", eid,
                      "%s '%s'" % ("Foto-Look" if foto else ("Karussell" if karussell else "Kachel"), titel[:60]))
            conn.commit()
        if foto:
            _foto_starten(eid)
            flash("BSt-Next-Entwurf %d angelegt – das Foto wird erzeugt (1–2 Minuten); danach unter „Freigabe“ prüfen." % eid)
            return redirect(url_for("bstnext.index"))
        flash("BSt-Next-Entwurf %d erstellt – jetzt unter „Freigabe“ prüfen und freigeben." % eid)
        return redirect(url_for("bstnext.index"))

    @bp.route("/bstnext/seite", methods=["POST"])
    @rolle_required("admin")
    def seite():
        wahl = (request.form.get("seite_wahl") or "").strip()
        ids = sorted({wahl} if wahl else guard.seiten_ids(request.form.get("seiten", "")))
        if any(not i.isdigit() for i in ids):
            flash("Eine Facebook-Page-ID besteht nur aus Ziffern.")
            return redirect(url_for("bstnext.index"))
        set_einstellung(guard.EINSTELLUNG_SEITEN, ",".join(ids))
        with get_conn() as conn:
            audit_log(conn, session.get("user"), "bstnext_seite", None, "%d Seite(n)" % len(ids))
            conn.commit()
        flash("BSt-Next-Facebook-Seite gespeichert." if ids else "BSt-Next-Facebook-Seite entfernt.")
        return redirect(url_for("bstnext.index"))

    def _lade(conn, eid):
        row = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not row:
            abort(404)
        try:
            f = json.loads(row["text"])
        except Exception:
            f = {}
        if not guard.ist_bstnext(f):
            abort(404)
        return row, f

    @bp.route("/bstnext/freigeben/<int:eid>", methods=["POST"])
    @rolle_required("freigeber")
    def freigeben(eid):
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            if not guard.bild_bereit(f) or not (row["bild_pfad"] and os.path.exists(row["bild_pfad"])):
                flash(guard.MELDUNG_BILD_NICHT_FERTIG)
            elif row["status"] != "entwurf":
                flash("Der Beitrag ist nicht mehr im Entwurf.")
            else:
                conn.execute("UPDATE entwuerfe SET status='freigegeben' WHERE id=?", (eid,))
                audit_log(conn, session.get("user"), "bstnext_freigabe", eid, f.get("ueberschrift", "")[:60])
                conn.commit()
                flash("Beitrag %d freigegeben – jetzt veröffentlichen oder einplanen." % eid)
        return redirect(url_for("bstnext.index"))

    def _ziel(f):
        """Prueft Seite und Kanal aus dem Formular; Rueckgabe (page_id, kanal, Fehlertext)."""
        page_id = (request.form.get("page_id") or "").strip()
        kanal = (request.form.get("kanal") or "beide").strip()
        if kanal not in ("facebook", "instagram", "beide"):
            return None, None, "Unbekannter Kanal."
        ok, msg = guard.ziel_erlaubt(f, None, page_id, guard.seiten_ids(get_einstellung(guard.EINSTELLUNG_SEITEN, "")))
        if not ok:
            return None, None, msg
        return page_id, kanal, None

    @bp.route("/bstnext/veroeffentlichen/<int:eid>", methods=["POST"])
    @rolle_required("freigeber")
    def veroeffentlichen(eid):
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            page_id, kanal, fehler = _ziel(f)
            if fehler:
                flash(fehler)
                return redirect(url_for("bstnext.index"))
            if row["status"] != "freigegeben":
                flash("Der Beitrag muss zuerst freigegeben werden.")
                return redirect(url_for("bstnext.index"))
            eingeplant = _einplanung_text(conn, eid)
            if eingeplant:
                flash("Der Beitrag ist schon eingeplant für %s. Ändern oder löschen unter „Geplante "
                      "Veröffentlichungen“." % eingeplant)
                return redirect(url_for("bstnext.index"))
            if not _cfg["publish_fn"]:
                flash("Veröffentlichung ist nicht angebunden.")
                return redirect(url_for("bstnext.index"))
            ist_karussell = (f.get("bstnext") or {}).get("typ") == "karussell"
            ziel, erfolg, ergebnisse = _cfg["publish_fn"](conn, row, eid, f, kanal, page_id, session.get("user"),
                                                          request.form.get("story_fb") == "1" and not ist_karussell)
            if erfolg:
                conn.execute("UPDATE entwuerfe SET status='veroeffentlicht' WHERE id=?", (eid,))
            conn.commit()
        teile = ["%s: %s" % (k.capitalize(), ("OK" if ok else "Fehler – %s" % info)) for k, ok, info in ergebnisse]
        flash("Beitrag %d: %s" % (eid, " | ".join(teile)))
        return redirect(url_for("bstnext.index"))

    @bp.route("/bstnext/einplanen/<int:eid>", methods=["POST"])
    @rolle_required("freigeber")
    def einplanen(eid):
        datum = (request.form.get("datum") or "").strip()
        zeit = (request.form.get("zeit") or "").strip()
        try:
            wann = datetime.datetime.strptime("%sT%s" % (datum, zeit[:5]), "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Bitte Datum und Uhrzeit angeben.")
            return redirect(url_for("bstnext.index"))
        if wann < datetime.datetime.now():
            flash("Der Zeitpunkt liegt in der Vergangenheit.")
            return redirect(url_for("bstnext.index"))
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            page_id, kanal, fehler = _ziel(f)
            if fehler:
                flash(fehler)
                return redirect(url_for("bstnext.index"))
            if row["status"] != "freigegeben":
                flash("Der Beitrag muss zuerst freigegeben werden.")
                return redirect(url_for("bstnext.index"))
            eingeplant = _einplanung_text(conn, eid)
            if eingeplant:
                flash("Der Beitrag ist schon eingeplant für %s. Ändern oder löschen unter „Geplante "
                      "Veröffentlichungen“." % eingeplant)
                return redirect(url_for("bstnext.index"))
            if (f.get("bstnext") or {}).get("typ") == "karussell":
                flash("Ein Karussell lässt sich noch nicht einplanen – bitte „Jetzt veröffentlichen“ nutzen.")
                return redirect(url_for("bstnext.index"))
            conn.execute("INSERT INTO geplante_posts(entwurf_id, page_id, kanal, format, format_fb, format_ig, "
                         "geplant_am, status) VALUES (?,?,?,?,?,?,?, 'geplant')",
                         (eid, page_id, kanal, "einzelbild", "einzelbild", "einzelbild",
                          wann.strftime("%Y-%m-%dT%H:%M:00")))
            audit_log(conn, session.get("user"), "bstnext_eingeplant", eid, "%s %s" % (datum, zeit))
            conn.commit()
        flash("Beitrag %d eingeplant für %s um %s Uhr." % (eid, datum, zeit))
        return redirect(url_for("bstnext.index"))

    @bp.route("/bstnext/loeschen/<int:eid>", methods=["POST"])
    @rolle_required("freigeber")
    def loeschen(eid):
        """Loescht einen BSt-Next-Beitrag samt Bilddateien. Nicht: veroeffentlichte Beitraege (bleiben als
        Nachweis) und eingeplante (erst die Einplanung unter 'Geplante Veroeffentlichungen' loeschen)."""
        with get_conn() as conn:
            row, f = _lade(conn, eid)
            if row["status"] == "veroeffentlicht":
                flash("Ein veröffentlichter Beitrag bleibt als Nachweis erhalten und lässt sich hier nicht löschen.")
                return redirect(url_for("bstnext.index"))
            eingeplant = _einplanung_text(conn, eid)
            if eingeplant:
                flash("Der Beitrag ist eingeplant für %s. Bitte zuerst die Einplanung unter „Geplante "
                      "Veröffentlichungen“ löschen." % eingeplant)
                return redirect(url_for("bstnext.index"))
            pfade = {row["bild_pfad"]} | set((f.get("bstnext") or {}).get("bilder") or [])
            for pfad in pfade:
                if pfad and os.path.exists(pfad):
                    try:
                        os.remove(pfad)
                    except OSError:
                        log.warning("Bilddatei %s von BSt-Next-Beitrag %s nicht loeschbar", pfad, eid)
            conn.execute("DELETE FROM entwuerfe WHERE id=?", (eid,))
            audit_log(conn, session.get("user"), "bstnext_geloescht", eid, f.get("ueberschrift", "")[:60])
            conn.commit()
        flash("BSt-Next-Beitrag %d gelöscht." % eid)
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
        aktion = request.form.get("aktion")
        relevant = guard.endpoint_gesperrt(ep, aktion) or (ep == "aktion" and aktion == "freigeben")
        if not relevant:
            return None
        try:
            with get_conn() as conn:
                row = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
            f = json.loads(row["text"]) if row else {}
        except Exception:
            return None
        if not guard.ist_bstnext(f):
            return None
        if guard.endpoint_gesperrt(ep, aktion):
            flash(guard.MELDUNG_GESPERRT)
            return redirect(url_for("bstnext.index"))
        msg = guard.freigabe_blockiert(ep, aktion, f)
        if msg:
            flash(msg)
            return redirect(url_for("bstnext.index"))
        return None
