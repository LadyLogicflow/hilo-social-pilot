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

from flask import Blueprint, request, redirect, url_for, session, flash, abort, render_template_string

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
<p class="hint">Foto-Look: Die KI erzeugt nur das Foto (ohne Schrift, nur fiktive Personen); Headline und Logo setzt das Programm. Danach prüft eine Bildkontrolle gegen die Vermeidungsliste.</p>
<p class="hint">Eigene Zeilenumbrüche bleiben erhalten; zu lange Zeilen bricht das Programm nach Wörtern selbst um (eine Zeile hat etwa 18 Zeichen Platz, höchstens 5–6 Zeilen insgesamt).</p>
<div class=row><div><label>Bildtyp</label><select name=bildtyp>
<option value="kachel" {% if f.bildtyp!='foto' %}selected{% endif %}>Spruchkachel (sofort fertig)</option>
<option value="foto" {% if f.bildtyp=='foto' %}selected{% endif %}>Foto-Look mit KI (dauert 1–2 Minuten)</option></select></div>
<div><label>Motiv (nur Foto-Look)</label><select name=motiv>
{% for k, n in motive %}<option value="{{k}}" {% if f.motiv==k %}selected{% endif %}>{{n}}</option>{% endfor %}</select></div></div>
<div class=row><div><label>Format</label><select name=format>
{% for k, n in formate %}<option value="{{k}}" {% if f.format==k %}selected{% endif %}>{{n}}</option>{% endfor %}</select></div>
<div><label>Tag der Veröffentlichung (optional)</label><input type=date name=datum value="{{ f.datum }}"></div></div>
<label>Begleittext (Facebook und Instagram)</label>
<textarea name=caption required placeholder="Ihr Text. Die BSt-Next-Hashtags werden angehängt, wenn sie fehlen.">{{ f.caption }}</textarea>
<label>Alt-Text (für Screenreader, optional)</label><input type=text name=alt value="{{ f.alt }}">
<button type=submit>Beitrag erstellen und als Entwurf speichern</button>
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
{% for r in rows %}<tr><td>{% if r.bild_status=='fertig' %}<img class=th src="/bild/{{r.id}}" alt="">{% endif %}</td><td>{{r.titel}}{% if r.typ=='foto' %} <span class="hint">(Foto-Look)</span>{% endif %}</td>
<td>{{r.status}}{% if r.bild_status=='laeuft' %}<br><span class="hint">Bild wird erzeugt …</span>{% elif r.bild_status=='fehler' %}<br><span class="hint">Bild fehlgeschlagen: {{r.info}}</span>{% endif %}</td><td>{{r.datum}}</td>
<td>{% if r.bild_status!='fertig' %}<form method=post action="{{ url_for('bstnext.foto_neu', eid=r.id) }}" style="margin:0"><button type=submit style="margin:0;padding:6px 10px">Bild neu erzeugen</button></form>
{% elif r.status=='entwurf' %}<form method=post action="{{ url_for('bstnext.freigeben', eid=r.id) }}" style="margin:0"><button type=submit style="margin:0;padding:6px 10px">Freigeben</button></form>
{% elif r.status=='freigegeben' %}
{% if seiten_ids %}<form method=post action="{{ url_for('bstnext.veroeffentlichen', eid=r.id) }}" style="margin:0 0 8px" onsubmit="return confirm('Jetzt auf der BSt-Next-Seite veröffentlichen? Das ist ein echter Post.')">
<select name=page_id>{% for pid in seiten_ids %}<option value="{{pid}}">Seite {{pid}}</option>{% endfor %}</select>
<select name=kanal><option value="beide">Facebook + Instagram</option><option value="facebook">nur Facebook</option><option value="instagram">nur Instagram</option></select>
<button type=submit style="margin:0;padding:6px 10px">Jetzt veröffentlichen</button></form>
<form method=post action="{{ url_for('bstnext.einplanen', eid=r.id) }}" style="margin:0">
<input type=date name=datum required style="width:auto"> <input type=time name=zeit required style="width:auto">
<select name=page_id>{% for pid in seiten_ids %}<option value="{{pid}}">Seite {{pid}}</option>{% endfor %}</select>
<select name=kanal><option value="beide">Facebook + Instagram</option><option value="facebook">nur Facebook</option><option value="instagram">nur Instagram</option></select>
<button type=submit style="margin:0;padding:6px 10px">Einplanen</button></form>
{% else %}<span class="hint">Erst oben die BSt-Next-Facebook-Seite hinterlegen.</span>{% endif %}
{% else %}<a href="/beitrag/{{r.id}}">ansehen</a>{% endif %}</td></tr>{% endfor %}</table>
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
                        "bild_status": fl.get("bild_status", "fertig"), "info": fl.get("bild_info", "")})
        return out

    def _seite(f=None):
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
                  "bildtyp": "kachel", "motiv": "belege"}
        return render_template_string(SEITE, style=style, formate=FORMATE_FEED, motive=MOTIVE, rows=rows,
                                      seiten=seiten, seiten_liste=liste, seiten_fehler=fehler, seiten_aktiv=aktiv, seiten_ids=sorted(aktiv),
                                      rolle=session.get("rolle"), f=f,
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

    @bp.route("/bstnext/neu", methods=["POST"])
    @rolle_required("freigeber")
    def neu():
        fmt = request.form.get("format", "quadrat")
        weiss = _zeilen(request.form.get("weiss"))
        lime = _zeilen(request.form.get("lime"))
        if fmt in dict(FORMATE_FEED):
            # Zu lange Zeilen werden nach Woertern umgebrochen (eigene Umbrueche bleiben erhalten)
            weiss, lime = kachel.umbrechen(weiss, fmt), kachel.umbrechen(lime, fmt)
        datum = (request.form.get("datum") or "").strip()
        caption = (request.form.get("caption") or "").strip()
        alt = (request.form.get("alt") or "").strip()
        bildtyp = request.form.get("bildtyp", "kachel")
        motiv = request.form.get("motiv", "belege")
        eingabe = {"weiss": "\n".join(weiss), "lime": "\n".join(lime), "format": fmt, "datum": datum,
                   "caption": caption, "alt": alt, "bildtyp": bildtyp, "motiv": motiv}
        if bildtyp not in ("kachel", "foto") or motiv not in dict(MOTIVE):
            flash("Unbekannter Bildtyp oder Motiv.")
            return _seite(eingabe)
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
        titel = " ".join(weiss + lime)
        foto = bildtyp == "foto"
        tmp = os.path.join(out_dir, "bstnext_tmp_%s.png" % uuid.uuid4().hex)
        try:
            if foto:
                kachel.pruefe_zeilen(weiss, lime, fmt)        # keine KI-Kosten bei unbrauchbaren Zeilen
            else:
                kachel.render(weiss, lime, tmp, fmt)
        except kachel.KachelFehler as ex:
            flash("Kachel nicht erzeugbar: %s" % ex)
            return _seite(eingabe)
        fields = {
            "marke": guard.MARKE, "kampagne": guard.MARKE,
            "ueberschrift": titel,
            "caption": caption, "captions": {"facebook": caption, "instagram": caption},
            "alt_text": alt or titel,
            "bild_format": fmt,
            "bild_status": "laeuft" if foto else "fertig",
            "bstnext": {"typ": "foto" if foto else "kachel", "weiss": weiss, "lime": lime, "format": fmt,
                        "motiv": motiv},
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
            if not foto:
                ziel = os.path.join(out_dir, "bstnext_%d.png" % eid)
                os.replace(tmp, ziel)
                conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (ziel, eid))
            audit_log(conn, session.get("user"), "bstnext_beitrag", eid,
                      "%s '%s'" % ("Foto-Look" if foto else "Kachel", titel[:60]))
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
            if not _cfg["publish_fn"]:
                flash("Veröffentlichung ist nicht angebunden.")
                return redirect(url_for("bstnext.index"))
            ziel, erfolg, ergebnisse = _cfg["publish_fn"](conn, row, eid, f, kanal, page_id, session.get("user"))
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
            conn.execute("INSERT INTO geplante_posts(entwurf_id, page_id, kanal, format, format_fb, format_ig, "
                         "geplant_am, status) VALUES (?,?,?,?,?,?,?, 'geplant')",
                         (eid, page_id, kanal, "einzelbild", "einzelbild", "einzelbild",
                          wann.strftime("%Y-%m-%dT%H:%M:00")))
            audit_log(conn, session.get("user"), "bstnext_eingeplant", eid, "%s %s" % (datum, zeit))
            conn.commit()
        flash("Beitrag %d eingeplant für %s um %s Uhr." % (eid, datum, zeit))
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
