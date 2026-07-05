# -*- coding: utf-8 -*-
"""ShareNext - HILO Social Media Tool. Kachel-Dashboard (Flask):
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

def _under_berater(path):
    """True nur, wenn der (aufgeloeste) Pfad innerhalb von DATA_DIR/berater liegt.
    Schutz davor, dass ein manipulierter DB-Wert eine fremde Datei ausliefert (wie
    _under_portraits). Die Comic-Portraits zeigen echte Gesichter -> nur login-geschuetzt."""
    try:
        base = os.path.realpath(os.path.join(DATA_DIR, "berater"))
        rp = os.path.realpath(path)
        return rp == base or rp.startswith(base + os.sep)
    except Exception:
        return False

def _under_bibeln(path):
    """True nur, wenn der (aufgeloeste) Pfad innerhalb von DATA_DIR/bibeln liegt (#151).
    Schutz davor, dass ein manipulierter DB-/Einstellungs-Wert eine fremde Datei ausliefert
    (wie _under_portraits/_under_berater). Character-Bible-Bilder koennen echte Personen als Comic
    zeigen -> nur login-geschuetzt ausliefern (DSGVO)."""
    try:
        base = os.path.realpath(os.path.join(DATA_DIR, "bibeln"))
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
    # Entkoppelt (Comic-Workflow): NUR Text erzeugen, KEIN '--render'. Das Bild entsteht erst,
    # wenn die Nutzerin je Beitrag einen Stil waehlt und auf "Bild generieren" klickt.
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"), "--generate", str(anzahl)],
        cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)

def _start_generation_ids(ids):
    """Hintergrund-Erzeugung nur fuer die ausgewaehlten Thema-IDs. Entkoppelt: NUR Text, KEIN
    Bild (kein '--render') - das Bild wird spaeter je Beitrag per Klick erzeugt."""
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"),
         "--generate-ids", ",".join(str(i) for i in ids)],
        cwd=BASE_DIR, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)

def _start_regenerate():
    """Hintergrund: alle offenen Entwuerfe nach aktuellen Vorgaben neu erzeugen. Entkoppelt: NUR
    Text (kein '--render') - das Bild wird spaeter je Beitrag per Klick erzeugt."""
    os.makedirs(DATA_DIR, exist_ok=True)
    logf = open(os.path.join(DATA_DIR, "generieren.log"), "a", encoding="utf-8")
    _gen["proc"] = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "main.py"), "--regenerate-drafts"],
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
    # Pool-Beitraege (gp['pool']==1) tragen den Status 'pool' (einmalige Freigabe beim Topf-Eintrag)
    # und sind ebenfalls postbar - sie bleiben aber wiederverwendbar (siehe Status-Flip unten).
    pool_post = bool(gp["pool"])
    erlaubte_status = ("freigegeben", "pool") if pool_post else ("freigegeben",)
    if not e or e["status"] not in erlaubte_status:
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
            if pool_post and kanal in ("whatsapp_status", "whatsapp_kanal"):
                # Eigener WhatsApp-Veroeffentlichungspfad (#127) - FB/IG-Pfad bleibt unveraendert.
                ziel_name, erfolg, ergebnisse = _veroeffentliche_whatsapp(
                    conn, e, gp["entwurf_id"], f, kanal, stelle, "scheduler")
            else:
                ziel_name, erfolg, ergebnisse = _veroeffentliche_ziel(
                    conn, e, gp["entwurf_id"], f, fmt_fb, fmt_ig, kanal, stelle, gp["page_id"], "scheduler", publish)
        except Exception as ex:
            erfolg, ergebnisse = False, [("-", False, str(ex))]
        info = " | ".join("%s: %s" % (k, ("OK" if ok else "Fehler – %s" % i)) for k, ok, i in ergebnisse)
        conn.execute("UPDATE geplante_posts SET status=?, info=? WHERE id=?",
                     ("veroeffentlicht" if erfolg else "fehler", info[:500], gpid))
        offen = conn.execute("SELECT COUNT(*) FROM geplante_posts WHERE entwurf_id=? AND status IN "
                             "('geplant','laeuft')", (gp["entwurf_id"],)).fetchone()[0]
        # Pool-Beitraege NICHT auf 'veroeffentlicht' flippen - sie muessen wiederverwendbar bleiben
        # (je Stelle/Kanal nur einmal, das regelt pool_nutzung, nicht der Entwurf-Status).
        if erfolg and offen == 0 and not pool_post:
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

# --- Taegliche Auto-Ziehung aus dem Zufalls-Pool (Pool Phase 2, Issue #126) ----
# Schedulerfaehige Kanaele fuer die Topf-Ziehung. facebook/instagram laufen ueber den bestehenden
# Veroeffentlichungs-Scheduler; whatsapp_* werden in Pool Phase 3 (#127) ueber den WhatsApp-Dienst
# (_wa_call) gepostet. WhatsApp-Status wird taeglich gezogen, der WhatsApp-Kanal nur kuratiert an
# bestimmten Wochentagen (1-2x/Woche).
POOL_SCHEDULER_KANAELE = ["facebook", "instagram", "whatsapp_status", "whatsapp_kanal"]

# Frequenz je Kanal (Pool Phase 3, #127): "taeglich" -> jeden Tag ziehen; eine Menge von Wochentagen
# (0=Montag .. 6=Sonntag) -> nur an diesen Tagen ziehen. So bleibt der WhatsApp-Kanal bewusst seltener
# (1-2x/Woche, kuratiert) als der taegliche Status. Konfigurierbar ueber HILO_WA_KANAL_TAGE (z.B. "1,4").
def _wa_kanal_tage():
    """Wochentage (0=Mo..6=So), an denen der WhatsApp-Kanal bespielt wird. Default: Dienstag+Freitag."""
    roh = os.environ.get("HILO_WA_KANAL_TAGE", "1,4")
    tage = set()
    for t in roh.split(","):
        t = t.strip()
        if t.isdigit() and 0 <= int(t) <= 6:
            tage.add(int(t))
    return tage or {1, 4}

POOL_KANAL_FREQUENZ = {
    "facebook": "taeglich",
    "instagram": "taeglich",
    "whatsapp_status": "taeglich",
    "whatsapp_kanal": _wa_kanal_tage,   # Callable -> Menge von Wochentagen
}

def _kanal_heute_faellig(kanal, wochentag):
    """True, wenn der Kanal am gegebenen Wochentag (0=Mo..6=So) bespielt werden soll."""
    freq = POOL_KANAL_FREQUENZ.get(kanal, "taeglich")
    if callable(freq):
        freq = freq()
    if freq == "taeglich":
        return True
    if isinstance(freq, (set, frozenset, list, tuple)):
        return wochentag in freq
    return True

# Wochenend-Regel (#127): am Wochenende leichtere Inhalte (Wissens-Serie), keine harten Fristen-/CTA-Posts.
# Der Topf enthaelt zeitlose Beitraege; am Wochenende ziehen wir bevorzugt aus der Wissens-Serie
# (quelle 'wissen'). Konfigurierbar abschaltbar ueber HILO_POOL_WOCHENEND_FILTER=0.
_POOL_WOCHENEND_QUELLEN = {"wissen"}   # "leichte" Inhalte fuers Wochenende

def _wochenend_filter_aktiv():
    return os.environ.get("HILO_POOL_WOCHENEND_FILTER", "1").strip() not in ("0", "false", "nein", "")

def _ist_wochenende(wochentag):
    return wochentag in (5, 6)   # Samstag, Sonntag

def _kanal_verfuegbarkeit(stellen):
    """Ermittelt je Pool-Kanal die Menge der Stellen-IDs, die diesen Kanal TATSAECHLICH haben (#127):
      - facebook: jede Stelle mit hinterlegter fb_seite (Vorbedingung der Auswahl),
      - instagram: nur Stellen, deren fb_seite ein verknuepftes Instagram-Konto hat (ig_id aus _pages()),
      - whatsapp_status: nur Stellen mit Marker wa_status_aktiv=1,
      - whatsapp_kanal: nur Stellen mit hinterlegtem wa_kanal_invite.
    'stellen' sind die bereits gefilterten aktiven Stellen mit fb_seite. Rueckgabe: dict[kanal] -> set(ids).
    Nicht vorhandene Kanaele werden so je Stelle uebersprungen (kein pool_nutzung-Verbrauch, keine Fehlpostings)."""
    fb_ids = {int(s["id"]) for s in stellen}
    # IG-faehige Facebook-Seiten (mit verknuepftem Instagram-Konto) aus dem Seiten-Cache.
    pages, _err = _pages()
    ig_seiten = {str(p["id"]) for p in (pages or []) if p.get("ig_id")}
    ig_ids = {int(s["id"]) for s in stellen if str(s["fb_seite"]) in ig_seiten}
    def _hat(s, key):
        return key in s.keys()
    wa_status_ids = {int(s["id"]) for s in stellen
                     if _hat(s, "wa_status_aktiv") and s["wa_status_aktiv"]}
    wa_kanal_ids = {int(s["id"]) for s in stellen
                    if _hat(s, "wa_kanal_invite") and (s["wa_kanal_invite"] or "").strip()}
    return {
        "facebook": fb_ids,
        "instagram": ig_ids,
        "whatsapp_status": wa_status_ids,
        "whatsapp_kanal": wa_kanal_ids,
    }

def _pool_wochenend_eids(conn):
    """IDs der Topf-Beitraege, die am Wochenende erlaubt sind (leichte Inhalte = Wissens-Serie, #127).
    Verknuepft pool -> entwuerfe -> themen.quelle. Rueckgabe: set(entwurf_id) oder None bei Fehler."""
    try:
        rows = conn.execute(
            "SELECT p.entwurf_id FROM pool p "
            "LEFT JOIN entwuerfe e ON e.id=p.entwurf_id "
            "LEFT JOIN themen t ON t.id=e.thema_id "
            "WHERE p.aktiv=1 AND t.quelle IN (%s)" %
            ",".join("?" * len(_POOL_WOCHENEND_QUELLEN)),
            tuple(_POOL_WOCHENEND_QUELLEN)).fetchall()
        return {int(r[0]) for r in rows}
    except Exception:
        log.exception("Pool-Wochenend-Filter: Quelle der Topf-Beitraege nicht ermittelbar")
        return None

def _pool_tagesziehung(conn, datum=None, rng=None):
    """Zieht EINMAL pro Tag je aktive Beratungsstelle und je schedulerfaehigem Kanal einen noch
    offenen Topf-Beitrag und legt dafuer einen geplante_posts-Eintrag mit pool=1 zu einer gestreuten
    Uhrzeit an; danach wird die Ziehung in pool_nutzung verbucht (markiere_verbraucht).

    Idempotent: Stellen, die fuer einen Kanal am 'datum' bereits einen pool=1-Eintrag haben, werden
    uebersprungen - ein zweiter Lauf am selben Tag plant nichts doppelt ein. 'rng' steuert den Zufall
    (testbar). Rueckgabe: Anzahl neu eingeplanter Beitraege."""
    import datetime, random
    import pool
    rng = rng or random.Random()
    now = datetime.datetime.now()
    datum = datum or now.date().isoformat()
    heute = (datum == now.date().isoformat())
    try:
        wochentag = datetime.date.fromisoformat(datum).weekday()   # 0=Montag .. 6=Sonntag
    except Exception:
        wochentag = now.weekday()
    # Nur postbare, aktive Stellen (Facebook-Seite hinterlegt) kommen fuer die Ziehung infrage.
    stellen = conn.execute("SELECT * FROM beratungsstellen WHERE aktiv=1 AND fb_seite IS NOT NULL "
                           "AND fb_seite!='' ORDER BY id").fetchall()
    stelle_ids = [int(r["id"]) for r in stellen]
    if not stelle_ids:
        return 0
    # Kanal-Verfuegbarkeit je Stelle (#127): nur Kanaele bespielen, die die Stelle TATSAECHLICH hat.
    verfuegbar = _kanal_verfuegbarkeit(stellen)   # dict[kanal] -> set(stelle_id)
    # Wochenend-Regel (#127): am Wochenende nur "leichte" Pool-Beitraege (Wissens-Serie) ziehen.
    erlaubte_eids = None
    if _wochenend_filter_aktiv() and _ist_wochenende(wochentag):
        erlaubte_eids = _pool_wochenend_eids(conn)
    # Bereits am 'datum' belegte Uhrzeiten (alle geplanten Posts) - fuer die Streuung der Vorschlaege.
    belegt = [r[0][11:16] for r in conn.execute(
        "SELECT geplant_am FROM geplante_posts WHERE geplant_am LIKE ? AND status='geplant'", (datum + "T%",))]
    min_m = (now.hour * 60 + now.minute + 2) if heute else 7 * 60
    n = 0
    for kanal in POOL_SCHEDULER_KANAELE:
        # Frequenz-Regel (#127): manche Kanaele (z.B. whatsapp_kanal) nur an bestimmten Wochentagen.
        if not _kanal_heute_faellig(kanal, wochentag):
            continue
        # Kanal-Verfuegbarkeit: nur Stellen, die diesen Kanal haben.
        kanal_stellen = [sid for sid in stelle_ids if sid in verfuegbar.get(kanal, set())]
        if not kanal_stellen:
            continue
        # Idempotenz: Stellen, die fuer diesen Kanal am 'datum' schon einen Pool-Eintrag haben, raus.
        schon = {int(r[0]) for r in conn.execute(
            "SELECT DISTINCT stelle_id FROM geplante_posts WHERE pool=1 AND kanal=? AND stelle_id IS NOT NULL "
            "AND geplant_am LIKE ?", (kanal, datum + "T%"))}
        offene_stellen = [sid for sid in kanal_stellen if sid not in schon]
        if not offene_stellen:
            continue
        # Je Stelle ein ANDERER Beitrag am selben Tag (Phase-1-Logik uebernimmt das Verteilen).
        auswahl = pool.ziehe_tagesauswahl(conn, offene_stellen, kanal, rng,
                                          erlaubte_eids=erlaubte_eids)
        for sid, eid in auswahl.items():
            z = _vorschlag_zeit(belegt, min_m); belegt.append(z)
            conn.execute("INSERT INTO geplante_posts(entwurf_id, stelle_id, kanal, format, format_fb, "
                         "format_ig, geplant_am, status, pool) VALUES (?,?,?,?,?,?,?, 'geplant', 1)",
                         (eid, sid, kanal, "einzelbild", "einzelbild", "karussell", "%sT%s" % (datum, z)))
            pool.markiere_verbraucht(conn, eid, sid, kanal)
            n += 1
    if n:
        audit_log(conn, "system", "pool_tagesziehung", None, "%d Pool-Beitrag/-Beitraege fuer %s" % (n, datum))
    conn.commit()
    return n

def _pool_scheduler():
    """Klinkt sich in den Tagesablauf ein (wie der Radar-Lauf um 7 Uhr) und stoesst die taegliche
    Topf-Ziehung genau EINMAL pro Tag an (Marker-Datei). Bricht nie den Dienst ab."""
    import datetime
    marker = os.path.join(DATA_DIR, "last_pool_ziehung.txt")
    while True:
        try:
            now = datetime.datetime.now()
            heute = now.strftime("%Y-%m-%d")
            last = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else ""
            if now.hour >= 7 and last != heute:
                with get_conn() as conn:
                    n = _pool_tagesziehung(conn)
                os.makedirs(DATA_DIR, exist_ok=True)
                open(marker, "w", encoding="utf-8").write(heute)
                log.info("Pool-Tagesziehung: %d Beitrag/Beitraege eingeplant (%s)", n, heute)
        except Exception:
            log.exception("Pool-Tagesziehung: Scheduler-Fehler")
        time.sleep(120)

def _cache_cleanup_scheduler():
    """Raeumt den KI-Foto-Cache (motive/) einmal pro Tag orphan-basiert auf (#134).
    Datums-getaktet ueber eine Marker-Datei (analog _pool_scheduler). Faengt jeden Fehler ab -
    der Thread darf nie sterben, das Aufraeumen ist best effort und niemals kritisch."""
    import datetime
    import wartung
    marker = os.path.join(DATA_DIR, "last_cache_cleanup.txt")
    while True:
        try:
            now = datetime.datetime.now()
            heute = now.strftime("%Y-%m-%d")
            last = open(marker, encoding="utf-8").read().strip() if os.path.exists(marker) else ""
            if now.hour >= 7 and last != heute:
                with get_conn() as conn:
                    n, frei = wartung.aufraeumen_motive(conn)
                os.makedirs(DATA_DIR, exist_ok=True)
                open(marker, "w", encoding="utf-8").write(heute)
                log.info("Cache-Aufraeumung: %d Foto(s) geloescht, %.1f MB frei (%s)",
                         n, frei / (1024 * 1024), heute)
        except Exception:
            log.exception("Cache-Aufraeumung: Scheduler-Fehler")
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
# --- BSt-Next-CI: self-hosted Fonts (kein Google-CDN) + Design-Tokens + Wortmarken-Chevron ---
_FONTS = """@font-face{font-family:'Archivo Black';font-weight:400;font-display:swap;src:url('/fonts/archivoblack-400.woff2') format('woff2')}
@font-face{font-family:'Inter';font-weight:400;font-display:swap;src:url('/fonts/inter-400.woff2') format('woff2')}
@font-face{font-family:'Inter';font-weight:500;font-display:swap;src:url('/fonts/inter-500.woff2') format('woff2')}
@font-face{font-family:'Inter';font-weight:600;font-display:swap;src:url('/fonts/inter-600.woff2') format('woff2')}
@font-face{font-family:'Inter';font-weight:700;font-display:swap;src:url('/fonts/inter-700.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:400;font-display:swap;src:url('/fonts/jetbrainsmono-400.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:500;font-display:swap;src:url('/fonts/jetbrainsmono-500.woff2') format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:700;font-display:swap;src:url('/fonts/jetbrainsmono-700.woff2') format('woff2')}
:root{--navy900:#0B2545;--navy500:#1E4A8A;--navy100:#E8F0F8;--lime:#A3E635;--lime600:#4D7C0F;--paper:#F8FAFC;--ink:#15191F;--inksoft:#4B5563}
.stx{display:inline-flex;align-items:center}
.stx-chev{width:.42em;height:.58em;margin-left:.05em;margin-bottom:.17em;align-self:flex-end;color:#A3E635;flex:none}
.chev{display:inline-block;width:.5em;height:.72em;vertical-align:-2px;background:no-repeat center/contain;background-image:url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 32%22><path d=%22M6 4 L20 16 L6 28%22 fill=%22none%22 stroke=%22%23A3E635%22 stroke-width=%226.5%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22/></svg>")}
"""

_STYLE = _FONTS + """body{font-family:'Inter',system-ui,Arial,sans-serif;background:var(--paper);padding:20px;margin:0;color:var(--ink)}
.box{max-width:920px;margin:0 auto;background:#fff;border:1.5px solid var(--navy100);border-radius:16px;box-shadow:0 6px 18px rgba(11,37,69,.06);padding:24px}
h1,h2{font-family:'Archivo Black',sans-serif;color:var(--navy900);margin-top:0}h3{color:var(--navy900)}a{color:var(--navy500);text-decoration:none}
table{width:100%;border-collapse:collapse;margin:12px 0}td,th{padding:8px;border-bottom:1px solid var(--navy100);text-align:left;font-size:14px}
th{font-family:'JetBrains Mono',monospace;font-size:12px;text-transform:uppercase;letter-spacing:.4px;color:var(--lime600)}input,select,textarea{font-family:'Inter',sans-serif;padding:9px;border:1px solid #ccd3df;border-radius:8px;margin:4px 6px 4px 0}
button{background:var(--navy900);color:#fff;border:0;padding:10px 15px;border-radius:8px;cursor:pointer;font-family:'Inter',sans-serif;font-weight:600}button:hover{filter:brightness(1.15)}
.flash{color:var(--navy500);margin:8px 0;font-weight:700}.hint{font-family:'JetBrains Mono',monospace;color:var(--inksoft);font-size:12px}"""

_NAV = """<div class=top><div class="stx" style="font-family:'Archivo Black',sans-serif;font-size:23px;color:var(--navy900)">ShareNext<svg class="stx-chev" viewBox="0 0 24 32" aria-hidden="true"><path d="M6 4 L20 16 L6 28" fill="none" stroke="currentColor" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
<div><a href="/whatsapp">WhatsApp</a> &middot; <a href="/quellen">Eigene Quellen</a> &middot; {% if rolle=='admin' %}<a href="/verwaltung">Verwaltung</a> &middot; {% endif %}{{user}} &middot; <a href="/logout">Abmelden</a></div></div>"""

LOGIN = """<!doctype html><meta charset=utf-8><title>ShareNext</title>
<style>""" + _FONTS + """
body{font-family:'Inter',system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--navy900);color:var(--ink)}
.box{background:#fff;border:1px solid var(--navy100);border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.35);width:340px;overflow:hidden}
.head{padding:30px 28px 4px;text-align:center}
.head .wm{font-family:'Archivo Black',sans-serif;font-size:30px;color:var(--navy900)}
.head .tag{font-family:'JetBrains Mono',monospace;color:var(--lime600);font-size:12px;margin:8px 0 0;letter-spacing:.3px}
.eyebrow{font-family:'JetBrains Mono',monospace;color:var(--lime600);font-size:11px;text-transform:uppercase;letter-spacing:1px;margin:16px 28px 0}
.body{padding:6px 28px 28px}
input{display:block;width:100%;box-sizing:border-box;margin:9px 0;padding:11px;border:1px solid #ccd3df;border-radius:9px;font-family:'Inter',sans-serif}
button{width:100%;background:var(--navy900);color:#fff;border:0;padding:12px;border-radius:9px;font-weight:700;cursor:pointer;margin-top:6px;font-family:'Inter',sans-serif}
button:hover{filter:brightness(1.15)}
.err{color:#b00020;font-size:13px;text-align:center}
</style>
<div class=box><div class=head><div class="wm"><span class="stx">ShareNext<svg class="stx-chev" viewBox="0 0 24 32" aria-hidden="true"><path d="M6 4 L20 16 L6 28" fill="none" stroke="currentColor" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><p class=tag>digital. effizient. besser.</p></div>
<div class=eyebrow>Anmeldung</div>
<div class=body>
{% with m=get_flashed_messages() %}{% if m %}<p class=err>{{m[0]}}</p>{% endif %}{% endwith %}
<form method=post><input name=name placeholder="Benutzer" autofocus><input name=passwort type=password placeholder="Passwort"><button>Anmelden</button></form>
</div></div>"""

_TOP = _FONTS + """body{font-family:'Inter',system-ui,Arial,sans-serif;background:var(--paper);margin:0;padding:18px;color:var(--ink)}
.top{display:flex;justify-content:space-between;align-items:center;max-width:1040px;margin:0 auto 14px}
.top a{color:var(--navy500);text-decoration:none}
.flash{max-width:1040px;margin:0 auto 12px;color:var(--navy500);font-weight:700}"""

HOME = """<!doctype html><meta charset=utf-8><title>ShareNext</title>
<style>""" + _TOP + """
.info{max-width:1040px;margin:0 auto 16px;background:#e6eef6;border-radius:10px;padding:11px 16px;color:#0B2545;font-weight:bold;font-size:14px}
.grid{max-width:1040px;margin:0 auto;display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.tile{display:block;background:#fff;border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:18px;position:relative;border-top:5px solid #0B2545;min-height:150px;color:inherit;text-decoration:none}
.tile:hover{transform:translateY(-3px);box-shadow:0 10px 26px rgba(0,0,0,.14);transition:.15s}
.tile.action{border-top-color:#4D7C0F;background:linear-gradient(180deg,#f6faf2,#fff)}
.tile h3{color:#0B2545;margin:6px 0 4px;font-size:16px}.tile p{color:#6b7280;font-size:13px;margin:0}
.badge{position:absolute;bottom:14px;right:16px;background:#0B2545;color:#fff;border-radius:18px;padding:2px 11px;font-weight:bold;font-size:14px}
.badge.g{background:#4D7C0F}
.tile form{margin:10px 0 0}.tile button{background:#4D7C0F;color:#fff;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;font-size:13px}
.run{color:#4D7C0F;font-weight:bold;font-size:13px;margin-top:8px}</style>
""" + _NAV + """
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=info>&#x1F552; Themen werden täglich um 7:00 Uhr automatisch aus allen Quellen geholt.</div>
<div class=grid>
  <a class=tile href="/themen">{% if themen_offen %}<span class=badge>{{themen_offen}}</span>{% endif %}<h3>1. Freigabe: Themen</h3><p>Themen für die Kampagne auswählen (Stufe 1).</p></a>
  <a class=tile href="/erzeugen">{% if bereit %}<span class="badge g">{{bereit}}</span>{% endif %}<h3>2. Texte &amp; Bilder erzeugen</h3><p>Themen anhaken und für die ausgewählten Themen Beiträge erstellen.{% if gen_running %} <b>(läuft gerade &hellip;)</b>{% endif %}</p></a>
  <a class=tile href="/entwuerfe">{% if entwuerfe_offen %}<span class=badge>{{entwuerfe_offen}}</span>{% endif %}<h3>3. Freigabe: Texte &amp; Bilder</h3><p>Entwürfe prüfen, überarbeiten, freigeben (Stufe 2).</p></a>
  <a class=tile href="/einplanung">{% if freigegeben_offen %}<span class="badge g">{{freigegeben_offen}}</span>{% endif %}<h3>4. Einplanung Veröffentlichung</h3><p>Freigegebene Beiträge veröffentlichen.</p></a>
</div>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4D7C0F" href="/pool"><h3>&#x267B;&#xFE0F; Zufalls-Pool (Topf)</h3><p>Zeitlose Beiträge sammeln – das Tool spielt sie automatisch und je Beratungsstelle unterschiedlich aus (jeder Beitrag je Stelle genau einmal pro Kanal). Anlass-Tage und Fristen bleiben in der Einplanung.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4D7C0F" href="/eigener"><h3>&#x270F;&#xFE0F; Eigenen Beitrag erstellen</h3><p>Thema und Tag angeben – das Tool erstellt einen Entwurf, den du freigibst und der dann fest für diesen Tag eingeplant wird.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4D7C0F" href="/kalender"><h3>&#x1F4C5; Content-Kalender</h3><p>Monatsübersicht: geplante Beiträge und besondere Tage (Anlass-Tage, Fristen) auf einen Blick.</p></a>
<a class=tile style="display:block;max-width:1040px;margin:16px auto 0;border-top-color:#4D7C0F" href="/auswertung"><h3>&#x1F4CA; Was funktioniert</h3><p>Auswertung der veröffentlichten Beiträge nach Reichweite – welcher Stream, welches Bild und welche Uhrzeit am besten ankommen.</p></a>"""

ERZEUGEN = """<!doctype html><meta charset=utf-8><title>Themen auswählen</title><style>""" + _STYLE + """
.bar{max-width:920px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#0B2545;color:#fff;padding:7px 13px;border-radius:8px}
.allrow{display:flex;align-items:center;gap:8px;background:#dfe7f3;color:#0B2545;padding:9px 11px;border-radius:8px;font-weight:bold;cursor:pointer}
.qgroup{border:1px solid #e3e7ee;border-radius:10px;margin:10px 0;overflow:hidden}
.qhead{display:flex;align-items:center;gap:8px;background:#eef2f8;color:#0B2545;padding:9px 11px;cursor:pointer;margin:0}
.qrow{display:flex;gap:11px;align-items:flex-start;padding:10px 11px;border-top:1px solid #F8FAFC;cursor:pointer;margin:0}
.qrow:hover{background:#f6f8fb}
.qhead input{margin:0}.qrow input{margin:3px 0 0}
.ti{font-weight:bold;color:#15191F}.meta{font-size:12px;color:#7a8694}
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
label{display:block;font-weight:bold;color:#15191F;margin:16px 0 4px}
textarea,input[type=date]{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ccd3df;border-radius:8px;font-size:15px}
textarea{min-height:84px;resize:vertical}
button{margin-top:18px;background:#4D7C0F;color:#fff;border:0;border-radius:8px;padding:11px 18px;cursor:pointer;font-weight:bold}</style>
<div class=top><h2 style="margin:0;color:#0B2545">Eigenen Beitrag erstellen</h2><a href="/">&larr; Startseite</a></div>
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
.t{flex:1}.t h3{color:#15191F;margin:.2em 0}.sub{color:#4D7C0F;font-weight:bold}
.cta{display:inline-block;background:#0B2545;color:#fff;padding:5px 10px;border-radius:14px;font-size:13px}
textarea{width:100%;min-height:54px;margin:8px 0;border:1px solid #ccd;border-radius:8px;padding:8px}
button{border:0;border-radius:8px;padding:9px 14px;cursor:pointer;margin-right:6px;color:#fff}
.ok{background:#4D7C0F}.no{background:#9aa0a6}.re{background:#0B2545}.del{background:#b00020}</style>
<div class=top><h2 style="margin:0;color:#0B2545">Freigabe: Texte &amp; Bilder (Stufe 2)</h2><a href="/">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
{% if entwuerfe %}<div style="max-width:1040px;margin:0 auto 14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
  <span style="color:#6b7280;font-size:13px">Tipp: Nach geänderten Vorgaben (Bildstil, keine Abkürzungen …) kannst du alle offenen Entwürfe neu erzeugen lassen.</span>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
  <form method=post action="/pool-aufnehmen-alle" onsubmit="return confirm('Alle {{entwuerfe|length}} offenen Entwürfe in den Zufalls-Pool aufnehmen?\n\nDas gilt als Freigabe. Es wird nichts sofort gepostet – die Veröffentlichung läuft erst über die tägliche Pool-Ziehung. Einzelne Beiträge kannst du auf der Pool-Seite jederzeit wieder entfernen.')">
    <button class=ok title="Alle offenen Entwürfe auf einen Schlag in den Pool legen">&#x267B;&#xFE0F; Alle in den Pool</button>
  </form>
  <form method=post action="/entwuerfe-neu" onsubmit="return confirm('Alle offenen Entwürfe nach den neuen Vorgaben NEU erzeugen? Das ersetzt die aktuellen Text- und Bildvorschläge und kostet KI-Tokens.')">
    <button class=re{% if gen_running %} disabled title="Es läuft bereits eine Erzeugung"{% endif %}>&#x21BB; Alle nach neuen Vorgaben neu erzeugen</button>
  </form></div></div>{% endif %}
{% for e in entwuerfe %}
<div class=card>{% if e.f.strip_panels %}<div style="display:flex;gap:6px;flex-wrap:wrap;align-self:flex-start">{% for _p in e.f.strip_panels %}<figure style="margin:0;text-align:center"><img src="/strip-panel/{{e.id}}/{{loop.index0}}" alt="Panel {{loop.index}}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;border:1px solid #e3e7ee;display:block"><figcaption style="font-size:12px;color:#6b7280">Bild {{loop.index}}</figcaption></figure>{% endfor %}</div>{% else %}<img src="/bild/{{e.id}}" alt="Vorschau">{% endif %}
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
    <form method=post action="/pool-aufnehmen/{{e.id}}" style="margin:6px 0;display:inline" onsubmit="return confirm('Diesen zeitlosen Beitrag direkt in den Zufalls-Pool legen?\n\nDas gilt als Freigabe für ALLE Beratungsstellen – er wird automatisch ausgespielt (je Stelle ein anderer, jeder Beitrag je Stelle genau einmal pro Kanal). Nur für zeitlose Inhalte; Anlass-Tage und Fristen bleiben in der Einplanung.')">
      <button class=ok style="background:#4D7C0F" title="Zeitlosen Beitrag direkt freigeben und in den Topf legen – wird automatisch je Stelle ausgespielt">&#x267B;&#xFE0F; In den Pool</button></form>
    <form method=post action="/bild-neu/{{e.id}}" style="margin-top:6px;display:inline" onsubmit="return confirm('Nur das Bild neu erzeugen? Der Text bleibt unverändert.')">
      <input type=hidden name=zurueck value=entwuerfe>
      <button style="background:#6b7280" title="Nur das Bild neu rendern (kostenlos), Text bleibt">&#x21BB; Nur Bild neu</button></form>
    <form method=post action="/anderes-bild/{{e.id}}" style="margin-top:6px;display:inline;margin-left:6px" onsubmit="return confirm('Für diesen Beitrag einen anderen Bild-Stil würfeln und das Bild neu erzeugen?\n\nDas kostet ein neues KI-Bild. Text und Termin bleiben unverändert.')">
      <input type=hidden name=zurueck value=entwuerfe>
      <button style="background:#7a4fae" title="Anderen aktiven Bild-Stil würfeln und das Bild neu erzeugen (kostet ein neues KI-Bild). Text bleibt">&#x1F3B2; Anderes Bild</button></form>
    <form method=post action="/bild-generieren/{{e.id}}" style="margin-top:6px;display:block">
      <input type=hidden name=zurueck value=entwuerfe>
      <input name=strip_zeile1 value="{{ e.f.strip_zeile1 or '' }}" placeholder="Comic-Strip: Text Feld 1 (optional – überschreibt die Überschrift)" title="Nur für Comic-Strip: eigener Satz für die Sprechblase in Feld 1 (leer = Überschrift)" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;margin:0 0 6px">
      <select name=strip_zeile2 title="Nur für Comic-Strip: Aussage im Bild 2 (Ärmelschoner). Automatisch = die KI wählt passend zum Thema und bestimmt damit die Story-Variante." style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;background:#fff;margin:0 0 6px">
        <option value="" {% if not e.f.strip_zeile2 %}selected{% endif %}>Comic-Strip Bild 2: Automatisch (KI wählt passend zum Thema)</option>
        <optgroup label="Jemand war bei HILO (traurig)">{% for v in strip_varianten.get('vorteil', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
        <optgroup label="Jemand war NICHT bei HILO (schadenfroh)">{% for v in strip_varianten.get('warnung', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
      </select>
      <select name=bild_stil style="padding:8px;border-radius:8px;border:1px solid #ccd3df;color:#15191F;background:#fff;margin-right:6px" title="Bild-Stil für diesen Beitrag wählen">
        <option value="" disabled selected>– Stil wählen –</option>
        <option value="comic">Comic</option>
        <option value="comic_beratung">Comic Beratung</option>
        <option value="comic_strip">Comic-Strip</option>
        <option value="ki_tafel">Tafel</option>
        <option value="kreativ">Kreativ</option></select>
      <button style="background:#0B2545" title="Bild in diesem Stil erzeugen (kostet ein KI-Bild). Text bleibt">&#x1F5BC;&#xFE0F; Bild generieren</button></form>
  </div></div>
{% else %}<p style="text-align:center">Keine offenen Entwürfe. Erst Themen auswählen und Beiträge erzeugen.</p>{% endfor %}"""

EINPLANUNG = """<!doctype html><meta charset=utf-8><title>Einplanung Veröffentlichung</title>
<style>""" + _TOP + """
.card{display:flex;gap:18px;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:16px;max-width:1040px;margin:0 auto 18px}
.card img{width:240px;height:240px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.t{flex:1}.t h3{color:#15191F;margin:.2em 0}.sub{color:#4D7C0F;font-weight:bold}
select,button{padding:9px;border-radius:8px;margin:4px 6px 4px 0}
button{border:0;background:#4D7C0F;color:#fff;cursor:pointer}
.checks{margin:6px 0;display:flex;flex-wrap:wrap;gap:8px 14px}
.checks label{font-size:14px;background:#eef2f8;padding:4px 10px;border-radius:7px;cursor:pointer}
.checks .stelle{display:flex;align-items:center;gap:6px;background:#eef2f8;padding:4px 8px;border-radius:7px}
.checks .stelle label{background:none;padding:0}
.checks .stelle select{padding:4px 6px;margin:0;font-size:13px;border-radius:6px}
.fmt{font-size:13px;color:#15191F;margin-right:6px}.fmt select{font-size:13px;padding:6px}</style>
<script>function need(f,n,m){return f.querySelectorAll('input[name='+n+']:checked').length>0||(alert(m),false);}</script>
<div class=top><h2 style="margin:0;color:#0B2545">Einplanung Veröffentlichung</h2><div><a href="/geplant">&#x23F0; Geplante Veröffentlichungen</a> &middot; <a href="/">Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<p class=hint style="max-width:1040px;margin:0 auto 12px">Neu freigegebene Beiträge sind zunächst <b>„Noch nicht geplant"</b>. Das Tool schlägt den nächsten freien <b>Werktag nach der letzten Einplanung</b> vor (max. 1 pro Tag, Sa+So frei) – mit einem Klick bestätigen. Termin bleibt jederzeit anpassbar.</p>
{% if pages_err %}<div class=flash style="color:#b00020">Facebook-Seiten konnten nicht geladen werden: {{pages_err}}</div>{% endif %}
{% for e in freigegeben %}
<div class=card>{% if e.f.strip_panels %}<div style="display:flex;gap:6px;flex-wrap:wrap;align-self:flex-start">{% for _p in e.f.strip_panels %}<figure style="margin:0;text-align:center"><img src="/strip-panel/{{e.id}}/{{loop.index0}}" alt="Panel {{loop.index}}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;border:1px solid #e3e7ee;display:block"><figcaption style="font-size:12px;color:#6b7280">Bild {{loop.index}}</figcaption></figure>{% endfor %}</div>{% else %}<img src="/bild/{{e.id}}" alt="Vorschau">{% endif %}
  <div class=t><h3>{{e.f.ueberschrift}}</h3><p class=sub>{{e.f.subline}}</p>
    <p>{% if e.geplant_fuer %}<b style="color:#0B2545">&#x1F4C5; Geplant: {{e.geplant_de}}</b>
       <form method=post action="/umplanen/{{e.id}}" style="display:inline;margin-left:8px">
         <input type=date name=geplant_fuer value="{{e.geplant_fuer}}" style="padding:5px">
         <button style="background:#0B2545;padding:6px 10px">Termin ändern</button></form>
       {% else %}<span style="display:inline-block;background:#b00020;color:#fff;font-size:16px;font-weight:bold;padding:10px 16px;border-radius:8px">&#x26A0;&#xFE0F; Noch nicht geplant</span>
       <form method=post action="/umplanen/{{e.id}}" style="display:inline;margin-left:10px">
         <span class=hint>Vorschlag: <b>{{e.vorschlag_de}}</b></span>
         <input type=date name=geplant_fuer value="{{e.vorschlag}}" style="padding:5px;margin-left:4px">
         <button style="background:#4D7C0F;color:#fff;padding:8px 13px;border-radius:8px;font-weight:bold">Für diesen Tag einplanen</button></form>
       {% endif %}
       <form method=post action="/beitrag-neu/{{e.id}}" style="display:inline;margin-left:6px" onsubmit="return confirm('Diesen Beitrag nach den aktuellen Vorgaben neu erzeugen (Text + Bild)? Der geplante Termin bleibt erhalten.')">
         <button style="background:#4D7C0F;padding:6px 10px" title="Text und Bild nach aktuellen Vorgaben neu erzeugen">&#x21BB; Neu erzeugen</button></form>
       <form method=post action="/bild-neu/{{e.id}}" style="display:inline;margin-left:6px" onsubmit="return confirm('Nur das Bild neu erzeugen? Text und Termin bleiben unverändert.')">
         <input type=hidden name=zurueck value=einplanung>
         <button style="background:#6b7280;padding:6px 10px" title="Nur das Bild neu rendern (kostenlos), Text bleibt">&#x21BB; Nur Bild neu</button></form></p>
    <form method=post action="/bild-generieren/{{e.id}}" style="margin:0 0 8px;display:block">
      <input type=hidden name=zurueck value=einplanung>
      <input name=strip_zeile1 value="{{ e.f.strip_zeile1 or '' }}" placeholder="Comic-Strip: Text Feld 1 (optional – überschreibt die Überschrift)" title="Nur für Comic-Strip: eigener Satz für die Sprechblase in Feld 1 (leer = Überschrift)" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;margin:0 0 6px">
      <select name=strip_zeile2 title="Nur für Comic-Strip: Aussage im Bild 2 (Ärmelschoner). Automatisch = die KI wählt passend zum Thema und bestimmt damit die Story-Variante." style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;background:#fff;margin:0 0 6px">
        <option value="" {% if not e.f.strip_zeile2 %}selected{% endif %}>Comic-Strip Bild 2: Automatisch (KI wählt passend zum Thema)</option>
        <optgroup label="Jemand war bei HILO (traurig)">{% for v in strip_varianten.get('vorteil', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
        <optgroup label="Jemand war NICHT bei HILO (schadenfroh)">{% for v in strip_varianten.get('warnung', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
      </select>
      <select name=bild_stil style="padding:8px;border-radius:8px;border:1px solid #ccd3df;color:#15191F;background:#fff;margin-right:6px" title="Bild-Stil für diesen Beitrag wählen">
        <option value="" disabled selected>– Stil wählen –</option>
        <option value="comic">Comic</option>
        <option value="comic_beratung">Comic Beratung</option>
        <option value="comic_strip">Comic-Strip</option>
        <option value="ki_tafel">Tafel</option>
        <option value="kreativ">Kreativ</option></select>
      <button style="background:#0B2545;color:#fff;padding:8px 12px" title="Bild im gewählten Stil neu erzeugen (kostet ein KI-Bild). Text bleibt">&#x1F5BC;&#xFE0F; Bild generieren</button></form>
    <form method=post action="/text-neu/{{e.id}}" style="margin:4px 0 8px" onsubmit="if(!this.feedback.value.trim()){alert('Bitte kurz angeben, was am Text geändert werden soll.');return false}return confirm('Nur den Text mit Ihrem Hinweis überarbeiten? Das nutzt die Text-KI; das Bild wird kostenlos an den neuen Text angepasst. Termin bleibt.')">
      <input type=hidden name=zurueck value=einplanung>
      <input name=feedback placeholder="Was am Text stört (z.B. „kürzer", „weniger werblich")" style="padding:6px;width:330px;border:1px solid #ccd3df;border-radius:6px">
      <button style="background:#0B2545;padding:6px 10px" title="Nur den Text mit Ihrem Hinweis überarbeiten; Bild wird an den neuen Text angepasst (Text-KI, Bild kostenlos)">&#x270E; Text überarbeiten</button></form>
    <details><summary>Begleittext anzeigen</summary><p>{{e.f.caption}}</p></details>
    <p><a href="/beitrag/{{e.id}}" style="color:#0B2545;font-weight:bold;text-decoration:none">{% if e.format=='karussell' %}&#x1F5BC;&#xFE0F; Komplettes Karussell ansehen{% else %}&#x1F50D; Beitrag ansehen{% endif %} &amp; für WhatsApp &rarr;</a></p>
    <form method=post action="/pool-aufnehmen/{{e.id}}" style="margin:4px 0 10px" onsubmit="return confirm('Diesen zeitlosen Beitrag in den Zufalls-Pool aufnehmen?\n\nEr wird dann automatisch ausgespielt – je Beratungsstelle ein anderer, jeder Beitrag je Stelle genau einmal pro Kanal. Nur für zeitlose Inhalte; Anlass-Tage und Fristen bleiben in der Einplanung.')">
      <button style="background:#4D7C0F" title="Zeitlosen Beitrag in den Topf legen – wird automatisch je Stelle ausgespielt">&#x267B;&#xFE0F; In den Pool (alle Stellen, automatisch)</button>
      <span class=hint>für zeitlose Beiträge – statt manuell einzuplanen</span></form>
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
      <label class=fmt style="font-weight:normal"><input type=checkbox name=story_fb value="1"> Bei Facebook zusätzlich als Story posten</label>
      <button>Vorschau ansehen</button>
      <button formaction="/auto-einplanen/{{e.id}}" style="background:#0B2545" title="Zur vorgeschlagenen Uhrzeit automatisch veröffentlichen">&#x23F0; Automatisch einplanen</button>
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
      <label class=fmt style="font-weight:normal"><input type=checkbox name=story_fb value="1"> Bei Facebook zusätzlich als Story posten</label>
      <button>Vorschau ansehen</button>
      <button formaction="/auto-einplanen/{{e.id}}" style="background:#0B2545" title="Zur vorgeschlagenen Uhrzeit automatisch veröffentlichen">&#x23F0; Automatisch einplanen</button>
      <button formaction="/veroeffentlichen/{{e.id}}" onclick="return confirm('Ohne Vorschau direkt auf den gewählten Facebook-Seiten veröffentlichen?')" style="background:#6b7280">Direkt veröffentlichen</button>
    </form>
    <p class=hint>Tipp: Lege in der Verwaltung Beratungsstellen mit Facebook-Seite an, dann werden Beiträge automatisch personalisiert.</p>
    {% else %}<p class=sub>Kein Facebook-Zugang/keine Beratungsstelle aktiv.</p>{% endif %}
  </div></div>
{% else %}<p style="text-align:center">Keine freigegebenen Beiträge zur Einplanung.</p>{% endfor %}"""

POOL = """<!doctype html><meta charset=utf-8><title>Zufalls-Pool</title><style>""" + _TOP + """
.card{display:flex;gap:16px;background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:14px;max-width:1040px;margin:0 auto 14px}
.card img{width:150px;height:150px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.t{flex:1}.t h3{color:#15191F;margin:.2em 0}.sub{color:#4D7C0F;font-weight:bold}
.meta{font-size:13px;color:#6b7280;margin:6px 0}
button{border:0;background:#6b7280;color:#fff;cursor:pointer;padding:8px 12px;border-radius:8px}
.intro{max-width:1040px;margin:0 auto 14px;background:#e6eef6;border-radius:10px;padding:11px 16px;color:#0B2545;font-size:14px}
.warn{max-width:1040px;margin:0 auto 14px;background:#fff3cd;border:1px solid #ffe69c;border-radius:10px;padding:11px 16px;color:#7a5b00;font-size:14px}
.hint{color:#4B5563;font-size:13px}
.sec{max-width:1040px;margin:24px auto 10px;font-family:'Archivo Black',sans-serif;color:#0B2545;font-size:18px}</style>
""" + _NAV + """
<div class=top><h2 style="margin:0;color:#0B2545">&#x267B;&#xFE0F; Zufalls-Pool (Topf)</h2><div><form method=get action="/pool-export" style="display:inline;margin:0"><button title="Alle Pool-Beitragstexte als Textdatei herunterladen">&#x2B07;&#xFE0F; Pool exportieren</button></form> &middot; <a href="/einplanung">&larr; Einplanung</a> &middot; <a href="/">Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=intro>Im Topf liegen <b>{{items|length}}</b> zeitlose Beiträge. Das Tool spielt sie automatisch aus – <b>je Beratungsstelle ein anderer</b> und <b>jeder Beitrag je Stelle genau einmal pro Kanal</b> ({{kanaele|join(', ')}}). Datumsgebundene Inhalte (Anlass-Tage, Fristen) laufen weiter über die <a href="/einplanung">Einplanung</a>.</div>
{% if warn %}<div class=warn>&#x26A0;&#xFE0F; <b>Nachschub nötig</b> – bei diesen Stellen/Kanälen sind weniger als {{schwelle}} Beiträge übrig:<br>{{ warn|join(' · ') }}<br><span class=hint>Lege weitere zeitlose Beiträge in den Topf (über „3. Freigabe" oder „4. Einplanung" &rarr; „In den Pool").</span></div>{% endif %}
{% macro poolcard(e, slots, n_stellen, n_kanaele) %}
<div class=card>{% if e.f.strip_panels %}<div style="display:flex;gap:6px;flex-wrap:wrap;align-self:flex-start">{% for _p in e.f.strip_panels %}<figure style="margin:0;text-align:center"><img src="/strip-panel/{{e.id}}/{{loop.index0}}" alt="Panel {{loop.index}}" style="width:100px;height:100px;object-fit:cover;border-radius:8px;border:1px solid #e3e7ee;display:block"><figcaption style="font-size:12px;color:#6b7280">Bild {{loop.index}}</figcaption></figure>{% endfor %}</div>{% else %}<img src="/bild/{{e.id}}" alt="Vorschau">{% endif %}
  <div class=t><h3>{{e.f.ueberschrift}}</h3><p class=sub>{{e.f.subline}}</p>
    <p class=meta>Im Topf seit {{e.freigegeben_de}} · bereits ausgespielt: <b>{{e.bespielt}}</b> von {{slots}} möglichen ({{n_stellen}} Stellen × {{n_kanaele}} Kanäle)</p>
    <details><summary>Begleittext anzeigen</summary><p>{{e.f.caption}}</p></details>
    <form method=post action="/pool-entfernen/{{e.id}}" style="margin-top:8px;display:inline" onsubmit="return confirm('Diesen Beitrag aus dem Topf nehmen? Er wird nicht mehr automatisch ausgespielt (bereits Ausgespieltes bleibt gespeichert). Du findest ihn danach wieder unter „Einplanung".')">
      <button title="Aus dem Topf nehmen">Aus dem Pool nehmen</button></form>
    <form method=post action="/bild-generieren/{{e.id}}" style="margin-top:8px;display:block">
      <input type=hidden name=zurueck value=pool>
      <input name=strip_zeile1 value="{{ e.f.strip_zeile1 or '' }}" placeholder="Comic-Strip: Text Feld 1 (optional – überschreibt die Überschrift)" title="Nur für Comic-Strip: eigener Satz für die Sprechblase in Feld 1 (leer = Überschrift)" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;margin:0 0 6px">
      <select name=strip_zeile2 title="Nur für Comic-Strip: Aussage im Bild 2 (Ärmelschoner). Automatisch = die KI wählt passend zum Thema und bestimmt damit die Story-Variante." style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px;color:#15191F;background:#fff;margin:0 0 6px">
        <option value="" {% if not e.f.strip_zeile2 %}selected{% endif %}>Comic-Strip Bild 2: Automatisch (KI wählt passend zum Thema)</option>
        <optgroup label="Jemand war bei HILO (traurig)">{% for v in strip_varianten.get('vorteil', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
        <optgroup label="Jemand war NICHT bei HILO (schadenfroh)">{% for v in strip_varianten.get('warnung', []) %}<option value="{{v}}" {% if e.f.strip_zeile2==v %}selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>
      </select>
      <select name=bild_stil style="padding:8px;border-radius:8px;border:1px solid #ccd3df;color:#15191F;background:#fff;margin-right:6px" title="Bild-Stil für diesen Beitrag wählen">
        <option value="" disabled selected>– Stil wählen –</option>
        <option value="comic">Comic</option>
        <option value="comic_beratung">Comic Beratung</option>
        <option value="comic_strip">Comic-Strip</option>
        <option value="ki_tafel">Tafel</option>
        <option value="kreativ">Kreativ</option></select>
      <button style="background:#0B2545;color:#fff" title="Bild in diesem Stil erzeugen (kostet ein KI-Bild). Text bleibt">&#x1F5BC;&#xFE0F; Bild generieren</button></form>
  </div></div>
{% endmacro %}
<div class=sec>&#x267B;&#xFE0F; Aktiv im Umlauf ({{aktiv|length}})</div>
{% for e in aktiv %}{{ poolcard(e, slots, n_stellen, n_kanaele) }}
{% else %}<p style="text-align:center;max-width:1040px;margin:20px auto">{% if archiv %}Aktuell ist kein Beitrag „im Umlauf" – alle liegen im Archiv (siehe unten).{% else %}Der Topf ist noch leer. Lege bei einem Beitrag unter <a href="/entwuerfe">„3. Freigabe"</a> oder <a href="/einplanung">„4. Einplanung"</a> „In den Pool".{% endif %}</p>{% endfor %}
{% if archiv %}
<div class=sec>&#x1F4E6; Archiv &ndash; komplett ausgespielt ({{archiv|length}})</div>
<p class=hint style="max-width:1040px;margin:0 auto 12px">Diese Beiträge wurden für <b>alle aktuellen Beratungsstellen</b> ausgespielt. Sie bleiben erhalten und werden für <b>neue Beratungsstellen</b> automatisch wieder herangezogen.</p>
{% for e in archiv %}{{ poolcard(e, slots, n_stellen, n_kanaele) }}{% endfor %}
{% endif %}"""

VORSCHAU = """<!doctype html><meta charset=utf-8><title>Vorschau vor Veröffentlichung</title><style>""" + _STYLE + """
.bar{max-width:1200px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#0B2545;color:#fff;padding:7px 13px;border-radius:8px}
.pv{display:flex;flex-wrap:wrap;gap:18px;justify-content:center}
.pvc{background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:12px;width:340px}
.pvc img{width:316px;height:316px;object-fit:cover;border-radius:8px;border:1px solid #F8FAFC}
.pvh{font-weight:bold;color:#15191F;margin-bottom:8px}
.pvc details{margin-top:8px}.pvc summary{cursor:pointer;color:#0B2545;font-size:13px}
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
    <div style="font-size:12px;color:#4D7C0F;font-weight:bold;margin-bottom:6px">Kanal: {{it.kanal_de}}</div>
    {% if it.ok %}<img src="{{it.url}}" alt="Vorschau {{it.label}}">{% else %}<p class=cap style="color:#b00020">{{it.caption}}</p>{% endif %}
    {% if it.ok %}{% for kn, cap in it.caps %}<details{% if loop.first %} open{% endif %}><summary>Begleittext {{kn}}</summary><p class=cap style="white-space:pre-wrap">{{cap}}</p></details>{% endfor %}{% endif %}
  </div>
{% endfor %}
</div>
<form method=post action="/veroeffentlichen/{{eid}}" onsubmit="return confirm('Jetzt an die {{ziel_count}} gültigen Ziele veröffentlichen?')">
  {% for s in stelle_ids %}<input type=hidden name=stelle_id value="{{s}}"><input type=hidden name="kanal_s{{s}}" value="{{kanal_map.get('s'+s,'facebook')}}">{% endfor %}
  {% for p in page_ids %}<input type=hidden name=page_id value="{{p}}"><input type=hidden name="kanal_p{{p}}" value="{{kanal_map.get('p'+p,'facebook')}}">{% endfor %}
  <input type=hidden name=format_fb value="{{fmt_fb}}"><input type=hidden name=format_ig value="{{fmt_ig}}">{% if story_ig %}<input type=hidden name=story_ig value="1">{% endif %}{% if story_fb %}<input type=hidden name=story_fb value="1">{% endif %}
  <div class=foot><a href="/einplanung">&larr; Auswahl ändern</a>
    <span class=hint>{{ziel_count}} Ziel(e) – Kanal je Beratungsstelle wie oben angezeigt</span>
    <button{% if not ziel_count %} disabled{% endif %}>Jetzt veröffentlichen</button></div>
</form>"""

GEPLANT = """<!doctype html><meta charset=utf-8><title>Geplante Veröffentlichungen</title><style>""" + _STYLE + """
.bar{max-width:1120px;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center}
.bar a{background:#0B2545;color:#fff;padding:7px 13px;border-radius:8px}
table.gp{max-width:1120px;margin:0 auto;width:100%}
.gp td,.gp th{font-size:13px;vertical-align:middle}
.st{font-weight:bold;font-size:12px;border-radius:6px;padding:2px 8px}
.st.geplant{background:#eaf0fa;color:#0B2545}.st.veroeffentlicht{background:#e3efe0;color:#3c6322}
.st.fehler{background:#fdeaea;color:#b00020}.st.laeuft{background:#fff3e0;color:#9a6a00}
.gp input{padding:4px 6px;margin:0}.gp form button{padding:5px 9px;margin:0}</style>
<div class=bar><h2 style="margin:0;color:#0B2545">Geplante Veröffentlichungen</h2><a href="/einplanung">&larr; Einplanung</a></div>
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
.kbar a{background:#0B2545;color:#fff;padding:7px 13px;border-radius:8px;text-decoration:none}
table.kal{max-width:1120px;margin:0 auto;border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.kal th{background:#0B2545;color:#fff;padding:8px;font-size:13px}
.kal td{border:1px solid #F8FAFC;vertical-align:top;height:98px;width:14.28%;padding:4px 6px;font-size:12px}
.kal td.out{background:#f6f7f9;color:#c2c8d0}
.kal td.we{background:#fafbfc}
.kal td.heute{outline:3px solid #4D7C0F;outline-offset:-3px}
.kt{font-weight:bold;color:#0B2545}
.anl{display:block;background:#eaf3e2;color:#3c6322;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.frist{display:block;background:#fdeaea;color:#b00020;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post{display:block;background:#eaf0fa;color:#15191F;border-radius:6px;padding:1px 5px;margin:2px 0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post.pub{background:#e3efe0;color:#3c6322}
a.anl{text-decoration:none;cursor:pointer}a.anl:hover{filter:brightness(.94)}
a.post{text-decoration:none;cursor:pointer}a.post:hover{filter:brightness(.94)}
.addpost{display:inline-block;margin-top:4px;color:#4D7C0F;font-size:11px;font-weight:bold;text-decoration:none}
.addpost:hover{text-decoration:underline}</style>
""" + _NAV + """
<div style="max-width:1120px;margin:0 auto 10px"><a href="/" style="color:#0B2545;text-decoration:none;font-weight:bold">&larr; Startseite</a></div>
<div class=kbar>
  <a href="/kalender?jahr={{prev.year}}&monat={{prev.month}}">&larr; {{prev_name}}</a>
  <h2 style="margin:0;color:#0B2545">{{monatname}} {{jahr}}</h2>
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
.bar a{background:#0B2545;color:#fff;padding:7px 13px;border-radius:8px;margin-left:6px}
.slides{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin:6px 0}
.slides figure{margin:0}
.slides img,.single img{width:300px;height:300px;object-fit:cover;border-radius:10px;border:1px solid #e3e7ee}
.slides figcaption{text-align:center;font-size:12px;color:#7a8694;margin-top:3px}
.single{text-align:center;margin:6px 0}.meta{color:#4D7C0F;font-weight:bold}
.wa{margin-top:18px;border-top:1px solid #F8FAFC;padding-top:14px}
.wa textarea{width:100%;box-sizing:border-box;min-height:90px;border:1px solid #ccd3df;border-radius:8px;padding:8px;font:inherit}
.wa .row{margin-top:8px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.wa a.dl,.wa button{background:#0B2545;color:#fff;border:0;border-radius:8px;padding:8px 13px;text-decoration:none;cursor:pointer;font-size:14px}
.wa a.dl.gn{background:#25638f}</style>
<script>function copyId(id,b){navigator.clipboard.writeText(document.getElementById(id).value).then(function(){var t=b.textContent;b.textContent='✓ Kopiert';setTimeout(function(){b.textContent=t;},1500);});}</script>
<div class=bar><h2 style="margin:0;color:#0B2545">Geplanter Beitrag</h2><div><a href="/kalender">&larr; Kalender</a><a href="/einplanung">Alle geplanten</a></div></div>
<div class=box style="max-width:1000px">
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<h3 style="margin-top:0">{{e.f.ueberschrift}}</h3>
<p class=meta>{{e.f.subline}}</p>
<p><b style="color:#0B2545">&#x1F4C5; Geplant: {{e.geplant_de}}</b> &middot; <span class=hint>{% if fmt=='karussell' %}Karussell ({{n_slides}} Slides){% else %}Einzelbild{% endif %} &middot; Status: {{status}}</span></p>
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
  <b style="color:#15191F">Bildtyp:</b>
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
  <p style="margin:.2em 0;font-weight:bold;color:#15191F">Allgemein (ohne Beratungsstelle)</p>
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
  <p style="margin:16px 0 .2em;font-weight:bold;color:#15191F">Personalisiert je Beratungsstelle <span class=hint style="font-weight:normal">(mit Porträt-Kreis und Ort)</span></p>
  {% for w in wa_stellen %}
  <div style="border:1px solid #e3e7ee;border-radius:10px;padding:10px;margin:8px 0">
    <b style="color:#0B2545">{{w.name}}{% if w.ort %} &middot; {{w.ort}}{% endif %}</b>
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
.q{display:inline-block;background:#eaf0fa;color:#0B2545;border-radius:10px;padding:1px 8px;font-size:12px;font-weight:bold}
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
.q{display:inline-block;background:#eaf0fa;color:#0B2545;border-radius:10px;padding:1px 8px;font-size:12px;font-weight:bold}
.drop{border:2px dashed #ccd3df;border-radius:12px;padding:18px;margin:8px 0;background:#fafbfc}</style>
<div class=box>
<div style="display:flex;justify-content:space-between;align-items:center"><h2 style="margin:0">Eigene Quellen einwerfen</h2><a href="/">&larr; Startseite</a></div>
<p class=hint>Wirf hier ein <b>PDF</b> oder einen <b>Link</b> ein. ShareNext liest den Inhalt, <b>zerlegt ihn in die einzelnen Themen</b> und merkt jedes direkt zur Texterstellung vor. <b>Wichtig:</b> Nur öffentliche/unkritische Inhalte &ndash; keine Mandantendaten.</p>
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
.tile{display:block;background:#fff;border-radius:16px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:20px;border-top:5px solid #0B2545;color:inherit;text-decoration:none;min-height:92px}
.tile:hover{transform:translateY(-3px);box-shadow:0 10px 26px rgba(0,0,0,.14);transition:.15s}
.tile h3{color:#0B2545;margin:4px 0 4px;font-size:17px}.tile p{color:#6b7280;font-size:13px;margin:0}</style>
<div class=top><h2 style="margin:0;color:#0B2545">Verwaltung</h2><a href="/" style="color:#0B2545;text-decoration:none">&larr; Startseite</a></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m[0]}}</div>{% endif %}{% endwith %}
<div class=grid>
  <a class=tile href="/verwaltung?bereich=benutzer"><h3>&#x1F465; Benutzer</h3><p>Konten anlegen, Rollen vergeben, aktivieren oder deaktivieren.</p></a>
  <a class=tile href="/verwaltung?bereich=stellen"><h3>&#x1F3E2; Beratungsstellen</h3><p>Stellen mit Ort, Facebook-Seite und Buchungslink pflegen.</p></a>
  <a class=tile href="/verwaltung?bereich=anlass"><h3>&#x1F4C5; Anlass-Tage</h3><p>Besondere Tage mit Steuer-Aufh&auml;nger verwalten.</p></a>
  <a class=tile href="/verwaltung?bereich=wissen"><h3>&#x1F4A1; Wissens-Serie</h3><p>Zeitlose Themen, die leere Kalendertage f&uuml;llen.</p></a>
  <a class=tile href="/verwaltung?bereich=schauplatz"><h3>&#x1F5BC; Schaupl&auml;tze</h3><p>Sch&ouml;ne saisonale Umgebungen f&uuml;r den KI-Tafel-Look (mit Bilderrahmen-Botschaft).</p></a>
  <a class=tile href="/verwaltung?bereich=traeger"><h3>&#x1FAA7; Tr&auml;ger</h3><p>Wie die Botschaft pr&auml;sentiert wird (Tafel, Rahmen, Holzschild &hellip;) &ndash; abwechselnd gew&auml;hlt.</p></a>
  <a class=tile href="/verwaltung?bereich=bildstil"><h3>&#x1F5BC; Bild-Stil</h3><p>Standard (v11) oder Testmodus „KI schreibt den Text selbst auf eine Tafel".</p></a>
  <a class=tile href="/verwaltung?bereich=speicher"><h3>&#x1F4BE; Speicher</h3><p>Foto-Cache und freien Plattenplatz ansehen, ungenutzte KI-Fotos aufr&auml;umen.</p></a>
</div>"""

VERWALTUNG = """<!doctype html><meta charset=utf-8><title>{{bereich_titel}} - Verwaltung</title>
{% if any_wa_pending %}<meta http-equiv=refresh content=6>{% endif %}<style>""" + _STYLE + """
.filebtn{display:inline-block;background:#eef2f8;border:1px solid #cfd8e6;border-radius:7px;padding:6px 11px;cursor:pointer;font-size:13px;color:#0B2545;white-space:nowrap}
.filebtn:hover{background:#e2e9f4}
button:disabled{opacity:.45;cursor:not-allowed}
.wide{max-width:1480px}
.scrollx{overflow-x:auto}
.vtab td,.vtab th{padding:11px 13px}
.nw{white-space:nowrap}
.stcards{max-width:840px;margin:0 auto}
.stcard{background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:14px 16px;margin:0 0 12px;box-shadow:0 2px 6px rgba(0,0,0,.05)}
.sthead{font-size:16px;color:#0B2545;margin-bottom:10px}
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
    <div class=stfield><label>WhatsApp (Pool)</label>
      <form method=post><input type=hidden name=formular value=stelle_whatsapp><input type=hidden name=stelle_id value="{{b.id}}">
        <label style="font-weight:normal;font-size:13px;display:block;margin:0 0 8px"><input type=checkbox name=wa_status_aktiv value="1"{% if b.wa_status_aktiv %} checked{% endif %}> Täglichen WhatsApp-Status bespielen</label>
        <label style="font-weight:normal;font-size:13px;display:block;margin:0 0 3px">WhatsApp-Kanal-Link <span class=hint>(optional – Einladungslink des Kanals dieser Stelle)</span></label>
        <div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">
          <input name=wa_kanal_invite value="{{b.wa_kanal_invite or ''}}" placeholder="https://whatsapp.com/channel/…" title="Einladungslink des WhatsApp-Kanals dieser Stelle - leer = kein Kanalbeitrag aus dem Pool" style="flex:1;min-width:260px">
          <button style="padding:7px 13px">OK</button>
        </div></form>
    </div>
    <div class=stfield><label>WhatsApp-Verbindung</label>
      {% if wa_dienst_err %}<div class=hint>WhatsApp-Dienst nicht erreichbar.</div>{% endif %}
      <div style="margin:0 0 6px">
        {% if b.wa.state == 'connected' %}<span style="color:#4D7C0F;font-weight:bold">&#x2705; verbunden</span>{% if b.wa.me %} <span class=hint>· {{b.wa.me}}</span>{% endif %}
        {% elif b.wa.state == 'qr' %}<span style="color:#475569;font-weight:bold">QR bereit</span>
        {% else %}<span class=hint>nicht verbunden</span>{% endif %}
      </div>
      {% if b.wa.state == 'connected' %}
        <form method=post action="/whatsapp/logout/{{b.id}}" onsubmit="return confirm('Verbindung dieser Stelle trennen? Du musst danach neu scannen.')"><input type=hidden name=zurueck value=verwaltung><button style="background:#b00020;padding:6px 12px">Trennen</button></form>
      {% elif b.wa.state == 'qr' and b.wa.qr %}
        <img src="{{b.wa.qr}}" alt="WhatsApp QR" style="width:180px;height:180px;border:1px solid #e2e8f0;border-radius:8px">
        <ol class=hint style="margin:6px 0;padding-left:18px">
          <li>WhatsApp auf dem Handy <b>dieser Stelle</b> öffnen</li>
          <li>Einstellungen &rarr; <b>Verknüpfte Geräte</b> &rarr; <b>Gerät verknüpfen</b></li>
          <li>Diesen QR-Code scannen</li></ol>
        <p class=hint style="margin:4px 0 0">Die Seite aktualisiert sich automatisch.</p>
      {% else %}
        <form method=post action="/whatsapp/connect/{{b.id}}"><input type=hidden name=zurueck value=verwaltung><button style="padding:6px 12px">Verbinden (QR anzeigen)</button></form>
      {% endif %}
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
    {# #152: Comic-Berater-UI (Variante A) ausgeblendet. Seit #151 hat die Character-Bible
       (bibel_bild) Vorrang vor dem aus dem Foto abgeleiteten berater_comic, daher ist der
       "Comic-Berater erzeugen"-Knopf hier ueberfluessig. Der Code-Fallback bleibt vollstaendig
       erhalten (DB-Spalte berater_comic, POST /berater-comic/<id>, GET /berater-comic-bild/<id>,
       bildmotiv.erzeuge_berater_comic + Personalisierungs-Fallback bibel_bild > berater_comic).
       Nur dieser UI-Block ist auskommentiert; zum Reaktivieren einfach wieder einblenden.
    <div class=stfield><label>Comic-Berater <span class=hint style="font-weight:normal">(für den Stil „Comic Beratung")</span></label>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        {% if b.berater_comic %}<a href="/berater-comic-bild/{{b.id}}" target="_blank" title="Comic-Portrait der Leitung – klicken für große Ansicht"><img src="/berater-comic-bild/{{b.id}}?v={{b.id}}" alt="Comic-Berater" style="width:170px;height:170px;border-radius:12px;object-fit:cover;border:1px solid #ccd3df"></a>{% endif %}
        {% if b.portrait_pfad %}<form method=post action="/berater-comic/{{b.id}}" style="margin:0"><button style="padding:6px 12px">{% if b.berater_comic %}Comic-Berater neu erzeugen{% else %}Comic-Berater erzeugen{% endif %}</button></form>
        {% else %}<span class=hint>Erst ein Porträt hochladen, dann kann der Comic-Berater erzeugt werden.</span>{% endif %}
      </div>
      {% if b.berater_comic %}<p class=hint style="margin:6px 0 0">Wird für den Stil „Comic Beratung“ verwendet.</p>{% endif %}
    </div>
    #}
    <div class=stfield><label>Character-Bible / Stylesheet <span class=hint style="font-weight:normal">(Comic-Vorlage für den Stil „Comic Beratung")</span></label>
      <p class=hint style="margin:0 0 6px">Optionale Comic-/Stylesheet-Vorlage für den/die Berater:in. Ist ein Bild hinterlegt, wird es beim Rendern <b>bevorzugt</b> als Vorlage genutzt (vor dem automatisch erzeugten Comic-Berater). Die Beschreibung fließt zusätzlich in den Bild-Prompt ein. Bilder werden nur nach Login angezeigt (Datenschutz).</p>
      <form method=post enctype="multipart/form-data" style="margin:0">
        <input type=hidden name=formular value=stelle_bibel><input type=hidden name=stelle_id value="{{b.id}}">
        <div style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap">
          {% if b.bibel_bild %}<a href="/bibel-bild/{{b.id}}" target="_blank" title="Character-Bible – klicken für große Ansicht"><img src="/bibel-bild/{{b.id}}?v={{b.id}}" alt="Character-Bible" style="width:170px;height:170px;object-fit:cover;border-radius:12px;border:1px solid #ccd3df"></a>{% endif %}
          <div style="flex:1;min-width:220px">
            <textarea name=bibel_text rows=4 placeholder="Charakter-Beschreibung (Comic): z.B. Aussehen, Kleidung, Ausstrahlung des/der Berater:in" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px">{{b.bibel_text or ''}}</textarea>
            <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:6px">
              <label class=filebtn>{% if b.bibel_bild %}Anderes Bild …{% else %}Bild wählen …{% endif %}
                <input type=file name=bibel_bild accept="image/*" style="display:none"
                       onchange="var f=this.files[0];this.form.querySelector('.bfn').textContent=f?f.name:''"></label>
              <span class=bfn style="font-size:12px;color:#5a6472;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
              <button style="padding:6px 12px">Speichern</button>
            </div>
          </div>
        </div>
      </form>
      {% if b.bibel_bild %}<form method=post style="margin:6px 0 0" onsubmit="return confirm('Character-Bible-Bild entfernen?')"><input type=hidden name=formular value=stelle_bibel_del><input type=hidden name=stelle_id value="{{b.id}}"><button title="Bild entfernen" style="background:#b00020;padding:6px 11px">Bild entfernen</button></form>{% endif %}
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

{% if bereich=='schauplatz' %}
<p class=hint>Schöne, abwechslungsreiche Umgebungen für den KI-Tafel-Look: Die Szene wird zu einem dieser Schauplätze, die Botschaft steht darin auf einem Bilderrahmen/Tisch-Aufsteller. Pro Jahreszeit fünf Schauplätze; gewählt wird passend zur Jahreszeit (oder zum Thema) und rotierend – nie zweimal hintereinander derselbe. „Aus" nimmt einen Schauplatz aus der Auswahl, ohne ihn zu löschen.</p>
<table><tr><th>Beschreibung</th><th>Jahreszeit</th><th>Aktiv</th><th></th></tr>
{% for s in schauplaetze %}<tr>
<td><form method=post style="display:flex;gap:6px;align-items:center;margin:0"><input type=hidden name=formular value=schauplatz_save><input type=hidden name=id value="{{s.id}}">
  <input name=beschreibung value="{{s.beschreibung}}" required style="flex:1;min-width:280px">
  <select name=jahreszeit>
    <option value=fruehling{% if s.jahreszeit=='fruehling' %} selected{% endif %}>Frühling</option>
    <option value=sommer{% if s.jahreszeit=='sommer' %} selected{% endif %}>Sommer</option>
    <option value=herbst{% if s.jahreszeit=='herbst' %} selected{% endif %}>Herbst</option>
    <option value=winter{% if s.jahreszeit=='winter' %} selected{% endif %}>Winter</option>
  </select>
  <label style="font-weight:normal;font-size:13px;white-space:nowrap"><input type=checkbox name=aktiv value=1{% if s.aktiv %} checked{% endif %}> aktiv</label>
  <button>Speichern</button></form></td>
<td>{{s.jahreszeit}}</td>
<td>{{'ja' if s.aktiv else 'nein'}}</td>
<td class=nw>
  <form method=post style=display:inline><input type=hidden name=formular value=schauplatz_toggle><input type=hidden name=id value="{{s.id}}"><button>{{'Aus' if s.aktiv else 'Ein'}}</button></form>
  <form method=post style=display:inline onsubmit="return confirm('Diesen Schauplatz wirklich löschen?')"><input type=hidden name=formular value=schauplatz_delete><input type=hidden name=id value="{{s.id}}"><button style="background:#b00020">Löschen</button></form>
</td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=schauplatz_save>
<input name=beschreibung placeholder="Beschreibung (z.B. Sonnige Caféterrasse mit Tulpen)" required style="width:45%">
<select name=jahreszeit>
  <option value=fruehling>Frühling</option><option value=sommer>Sommer</option>
  <option value=herbst>Herbst</option><option value=winter>Winter</option>
</select>
<label style="font-weight:normal;font-size:13px"><input type=checkbox name=aktiv value=1 checked> aktiv</label>
<button>Schauplatz anlegen</button></form>
{% endif %}
{% if bereich=='traeger' %}
<p class=hint>Der „Träger" bestimmt, WIE die Botschaft im KI-Tafel-Look präsentiert wird – z.B. als Kreidetafel, Bilderrahmen, Holzschild oder Postkarte. Pro Beitrag wird ein Träger gewählt: abwechselnd (nie zweimal hintereinander derselbe) und mit leichter Themen-Passung. „Aus" nimmt einen Träger aus der Auswahl, ohne ihn zu löschen. Das „Snippet" ist die Beschreibung, die ins KI-Bild einfließt.</p>
<table><tr><th>Name</th><th>Prompt-Snippet</th><th>Aktiv</th><th></th></tr>
{% for t in traeger %}<tr>
<td><form method=post style="display:flex;gap:6px;align-items:center;margin:0;flex-wrap:wrap"><input type=hidden name=formular value=traeger_save><input type=hidden name=id value="{{t.id}}">
  <input name=name value="{{t.name}}" required style="min-width:180px">
  <input name=prompt_snippet value="{{t.prompt_snippet}}" required style="flex:1;min-width:320px">
  <label style="font-weight:normal;font-size:13px;white-space:nowrap"><input type=checkbox name=aktiv value=1{% if t.aktiv %} checked{% endif %}> aktiv</label>
  <button>Speichern</button></form></td>
<td>{{t.prompt_snippet}}</td>
<td>{{'ja' if t.aktiv else 'nein'}}</td>
<td class=nw>
  <form method=post style=display:inline><input type=hidden name=formular value=traeger_toggle><input type=hidden name=id value="{{t.id}}"><button>{{'Aus' if t.aktiv else 'Ein'}}</button></form>
  <form method=post style=display:inline onsubmit="return confirm('Diesen Träger wirklich löschen?')"><input type=hidden name=formular value=traeger_delete><input type=hidden name=id value="{{t.id}}"><button style="background:#b00020">Löschen</button></form>
</td></tr>{% endfor %}</table>
<form method=post><input type=hidden name=formular value=traeger_save>
<input name=name placeholder="Name (z.B. Rustikales Holzschild)" required style="width:25%">
<input name=prompt_snippet placeholder="Prompt-Snippet (z.B. ein rustikales Holzschild mit gut lesbarer Schrift)" required style="width:50%">
<label style="font-weight:normal;font-size:13px"><input type=checkbox name=aktiv value=1 checked> aktiv</label>
<button>Träger anlegen</button></form>
{% endif %}

{% if bereich=='bildstil' %}
<p class=hint>Der Bild-Stil wird jetzt <b>automatisch und zufällig pro Beitrag</b> aus den hier <b>aktivierten</b> Stilen gewählt – kein manuelles Umschalten mehr. Haken Sie die Stile an, die in den Zufalls-Topf sollen. In der Freigabe (Schritt&nbsp;3) lässt sich für einen einzelnen Beitrag mit „Anderes Bild“ ein anderer aktiver Stil würfeln. <b>Mindestens ein Stil</b> muss aktiv bleiben.</p>
<form method=post><input type=hidden name=formular value=bildstil_save>
<div style="max-width:560px">
  <label style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <input type=checkbox name=stil_standard value="1"{% if stil_standard %} checked{% endif %}>
    <span><b>Standard (v11)</b><br><span class=hint>Bewährtes Layout: Foto + weißes Textfeld mit Überschrift, Bullets und CTA. (Empfohlen)</span></span></label>
  <label style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <input type=checkbox name=stil_ki_tafel value="1"{% if stil_ki_tafel %} checked{% endif %}>
    <span><b>KI-Tafel (Testmodus)</b><br><span class=hint>Die KI schreibt den Text selbst auf eine Tafel – Testmodus. Nur die Überschrift steht auf der Tafel; CTA und HILO-Kreise kommen exakt per Code.</span></span></label>
  <label style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <input type=checkbox name=stil_kreativ value="1"{% if stil_kreativ %} checked{% endif %}>
    <span><b>Kreativ</b><br><span class=hint>Kinoreifes Foto ohne Text – die Bild-KI entwirft (über einen Art-Director-Schritt) eine fotorealistische Szene zur überraschendsten Erkenntnis des Beitrags. Überschrift, Bullets, CTA und HILO-Kreise kommen wie im Standard-Look exakt per Code als Overlay.</span></span></label>
  <button>Auswahl speichern</button>
</div></form>

<h3 style="margin-top:26px">Bild-Tool</h3>
<p class=hint>Legt fest, <b>welche KI</b> das Foto erzeugt (unabhängig vom Bild-Stil oben). <b>OpenAI</b> ist die bewährte Standard-Wahl. <b>Ideogram</b> ist ein Text-Spezialist – die Schrift im Bild (z.&nbsp;B. auf der KI-Tafel) wird deutlich genauer; benötigt aber einen <b>eigenen API-Schlüssel</b> (in den Secrets als <code>ideogram_api_key</code> hinterlegen). So lassen sich beide am selben Beitrag vergleichen.</p>
<form method=post><input type=hidden name=formular value=bildtool_save>
<div style="max-width:560px">
  <label style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <input type=radio name=bild_tool value="openai"{% if bild_tool=='openai' %} checked{% endif %}>
    <span><b>OpenAI</b><br><span class=hint>Bewährtes Standard-Bildtool (GPT Image). (Empfohlen)</span></span></label>
  <label style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <input type=radio name=bild_tool value="ideogram"{% if bild_tool=='ideogram' %} checked{% endif %}>
    <span><b>Ideogram</b><br><span class=hint>Bessere Schrift im Bild; braucht einen eigenen API-Schlüssel (<code>ideogram_api_key</code>).</span></span></label>
  <button>Bild-Tool speichern</button>
</div></form>

<h3 style="margin-top:26px">Bild-Modell <span class=hint style="font-weight:normal">(OpenAI, für die Comic-Bilder)</span></h3>
<p class=hint>Legt fest, <b>welches OpenAI-Bildmodell</b> die Comic-Bilder erzeugt. <b>gpt-image-1</b> ist die bewährte Standard-Wahl (wirkt oft reicher und plastischer). <b>gpt-image-2</b> ist ein Testmodell zum Vergleichen. Nach dem Umschalten erzeugt „Neu erzeugen“ ein <b>frisches</b> Bild mit dem gewählten Modell – so lassen sich beide am selben Beitrag vergleichen (A/B). Schlägt das Testmodell fehl, wird automatisch auf gpt-image-1 zurückgefallen.</p>
<form method=post><input type=hidden name=formular value=bildmodell_save>
<div style="max-width:560px">
  <label style="display:flex;gap:10px;align-items:center;padding:12px;border:1px solid #ccd3df;border-radius:8px;margin-bottom:10px">
    <span><b>Bild-Modell:</b></span>
    <select name=bild_modell style="padding:8px;border-radius:8px;border:1px solid #ccd3df;color:#15191F;background:#fff" title="OpenAI-Bildmodell für die Comic-Bilder wählen">
      <option value="gpt-image-1"{% if bild_modell=='gpt-image-1' %} selected{% endif %}>gpt-image-1 (Standard)</option>
      <option value="gpt-image-2"{% if bild_modell=='gpt-image-2' %} selected{% endif %}>gpt-image-2 (Test)</option>
    </select>
  </label>
  <button>Bild-Modell speichern</button>
</div></form>

<h3 style="margin-top:26px">Finanzamt-Bible <span class=hint style="font-weight:normal">(global, für den Stil „Comic Beratung")</span></h3>
<p class=hint>Globale Comic-/Stylesheet-Vorlage des wiederkehrenden Finanzamt-Charakters. Ist ein Bild hinterlegt, wird es beim Rendern <b>statt</b> der eingebauten Standard-Referenz als Finanzamt-Vorlage genutzt; die Beschreibung fließt zusätzlich in den Bild-Prompt ein. Ohne Eintrag bleibt alles wie bisher. Anzeige nur nach Login (Datenschutz).</p>
<form method=post enctype="multipart/form-data" style="max-width:560px">
  <input type=hidden name=formular value=finanzamt_bibel>
  <div style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap">
    {% if finanzamt_bibel_bild %}<a href="/finanzamt-bibel-bild?v=1" target="_blank" title="Finanzamt-Bible – klicken für große Ansicht"><img src="/finanzamt-bibel-bild?v=1" alt="Finanzamt-Bible" style="width:170px;height:170px;object-fit:cover;border-radius:12px;border:1px solid #ccd3df"></a>{% endif %}
    <div style="flex:1;min-width:220px">
      <textarea name=finanzamt_bibel_text rows=4 placeholder="Charakter-Beschreibung des Finanzamt-Beamten (Comic)" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd3df;border-radius:8px">{{finanzamt_bibel_text or ''}}</textarea>
      <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:6px">
        <label class=filebtn>{% if finanzamt_bibel_bild %}Anderes Bild …{% else %}Bild wählen …{% endif %}
          <input type=file name=finanzamt_bibel_bild accept="image/*" style="display:none"
                 onchange="var f=this.files[0];this.form.querySelector('.ffn').textContent=f?f.name:''"></label>
        <span class=ffn style="font-size:12px;color:#5a6472;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
        <button style="padding:6px 12px">Finanzamt-Bible speichern</button>
      </div>
    </div>
  </div>
</form>
{% if finanzamt_bibel_bild %}<form method=post style="margin:6px 0 0;max-width:560px" onsubmit="return confirm('Finanzamt-Bible-Bild entfernen?')"><input type=hidden name=formular value=finanzamt_bibel_del><button title="Bild entfernen" style="background:#b00020;padding:6px 11px">Bild entfernen</button></form>{% endif %}
{% endif %}

{% if bereich=='speicher' %}
<p class=hint>Jedes „Neu erzeugen" legt ein neues KI-Foto im Cache ab; ungenutzte Fotos sammeln sich mit der Zeit an. Hier siehst du, wie viel Platz der Foto-Cache belegt und wie viel auf der Platte frei ist. Das Aufr&auml;umen l&ouml;scht <b>nur</b> Fotos, die <b>kein aktiver Beitrag mehr braucht</b> (Entw&uuml;rfe, Freigaben, Pool-Beitr&auml;ge und geplante Posts bleiben immer erhalten) und die &auml;lter als {{schonfrist_tage}} Tage sind. Es l&auml;uft zus&auml;tzlich automatisch einmal t&auml;glich.</p>
{% if speicher_warnung %}<p class=hint style="color:#b00020"><b>Achtung:</b> Es sind nur noch {{frei_lesbar}} frei. Bitte Speicher pr&uuml;fen.</p>{% endif %}
<table style="max-width:560px">
  <tr><th style="text-align:left">Foto-Cache (motive/)</th><td>{{motive_lesbar}}</td></tr>
  <tr><th style="text-align:left">Frei auf der Platte</th><td>{{frei_lesbar}} von {{gesamt_lesbar}}</td></tr>
</table>
<form method=post style="margin-top:14px"><input type=hidden name=formular value=cache_aufraeumen>
  <button>Jetzt aufr&auml;umen</button>
  <span class=hint style="margin-left:10px">L&ouml;scht ungenutzte KI-Fotos &auml;lter als {{schonfrist_tage}} Tage.</span>
</form>
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
    # #155: Bild-2-Varianten (Comic-Strip) je Stimmung fuer das Dropdown in den drei Pickern.
    try:
        import bildmotiv
        kw.setdefault("strip_varianten", bildmotiv.COMIC_STRIP_VARIANTEN)
    except Exception:
        kw.setdefault("strip_varianten", {})
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

@app.route("/pool")
@login_required
def pool_seite():
    """Zufalls-Pool ("Topf"): zeitlose, einmal fuer alle Stellen freigegebene Beitraege. Zeigt
    je Beitrag, wie oft er schon ausgespielt wurde, und warnt bei knappem Vorrat je Stelle/Kanal."""
    import pool as poolmod
    items = []
    with get_conn() as conn:
        stellen = conn.execute("SELECT id, name, ort FROM beratungsstellen WHERE aktiv=1 ORDER BY ort").fetchall()
        stelle_ids = [s["id"] for s in stellen]
        nutzung = {r["entwurf_id"]: r["n"] for r in
                   conn.execute("SELECT entwurf_id, COUNT(*) n FROM pool_nutzung GROUP BY entwurf_id")}
        # #148 Archiv: "komplett ausgespielt" = fuer ALLE aktuellen aktiven Stellen auf ALLEN ihren
        # tatsaechlich verfuegbaren Kanaelen bereits verbraucht. Bleibt im Topf (aktiv=1) und wird fuer
        # NEUE Stellen automatisch wieder gezogen -> reine Anzeige-Gruppierung, Ziehung unveraendert.
        verbraucht = poolmod.verbrauchte_paare(conn)
        voll_stellen = conn.execute("SELECT * FROM beratungsstellen WHERE aktiv=1 "
                                    "AND fb_seite IS NOT NULL AND TRIM(fb_seite)!=''").fetchall()
        kv = _kanal_verfuegbarkeit(voll_stellen) if voll_stellen else {}
        alle_paare = {(sid, kanal) for kanal, sids in kv.items() for sid in sids}
        for e in conn.execute("SELECT p.entwurf_id id, p.freigegeben_am, e.text FROM pool p "
                              "JOIN entwuerfe e ON e.id=p.entwurf_id WHERE p.aktiv=1 "
                              "ORDER BY p.freigegeben_am, p.entwurf_id"):
            row = _parse(e)
            row["freigegeben_de"] = _de_datum((e["freigegeben_am"] or "")[:10])
            row["bespielt"] = nutzung.get(e["id"], 0)
            row["archiv"] = bool(alle_paare) and all(
                (e["id"], sid, kanal) in verbraucht for (sid, kanal) in alle_paare)
            items.append(row)
        knapp = poolmod.knappe_vorraete(conn, stelle_ids) if stelle_ids else []
    namen = {s["id"]: s["name"] for s in stellen}
    warn = ["%s · %s: noch %d" % (namen.get(sid, sid), poolmod.KANAL_LABEL.get(kanal, kanal), rest)
            for sid, kanal, rest in knapp]
    aktiv = [r for r in items if not r.get("archiv")]
    archiv = [r for r in items if r.get("archiv")]
    return render_template_string(POOL, **_ctx(
        items=items, aktiv=aktiv, archiv=archiv, n_stellen=len(stellen), n_kanaele=len(poolmod.POOL_KANAELE),
        slots=len(stellen) * len(poolmod.POOL_KANAELE),
        kanaele=[poolmod.KANAL_LABEL[k] for k in poolmod.POOL_KANAELE],
        warn=warn, schwelle=poolmod.WARNSCHWELLE))

def _pool_export_body(f):
    """Voller Begleittext eines Pool-Beitrags fuer den Export. Bevorzugt die kanal-spezifischen
    Captions (captions.*), faellt auf das einfache Feld caption zurueck. Sind mehrere Kanal-Texte
    unterschiedlich, werden sie je Kanal beschriftet ausgegeben, damit nichts verloren geht."""
    caps = f.get("captions")
    if isinstance(caps, dict) and caps:
        texte = [(k, (v or "").strip()) for k, v in caps.items() if (v or "").strip()]
        if texte:
            if len({t for _, t in texte}) == 1:
                return texte[0][1]
            label = {"facebook": "Facebook", "instagram": "Instagram",
                     "whatsapp_kanal": "WhatsApp-Kanal", "whatsapp_story": "WhatsApp-Status"}
            return "\n\n".join("[%s]\n%s" % (label.get(k, k), t) for k, t in texte)
    return (f.get("caption") or "").strip() or "(kein Begleittext hinterlegt)"

@app.route("/pool-export")
@login_required
def pool_export():
    """Ein-Klick-Export ALLER aktuell im Zufalls-Pool liegenden Beitraege als herunterladbare
    UTF-8-Textdatei. Nutzt dieselbe Datenquelle wie pool_seite() (Tabelle pool JOIN entwuerfe,
    aktiv=1, gleiche Sortierung), zusaetzlich Quelle/Kanal fuer Stream- und Kanal-Angabe.
    Rein lesend - aendert nichts im Pool."""
    import datetime
    from flask import Response
    trenn = "=" * 60
    zeilen = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.entwurf_id id, p.freigegeben_am, e.text, e.kanal, t.quelle "
            "FROM pool p JOIN entwuerfe e ON e.id=p.entwurf_id "
            "LEFT JOIN themen t ON t.id=e.thema_id "
            "WHERE p.aktiv=1 ORDER BY p.freigegeben_am, p.entwurf_id").fetchall()
    for i, r in enumerate(rows, 1):
        f = _parse(r).get("f", {})
        titel = (f.get("ueberschrift") or f.get("subline") or "(ohne Titel)").strip()
        stream = _stream(r["quelle"])
        kanal = _KANAL_DE.get(r["kanal"], r["kanal"] or "-")
        zeilen.append(trenn)
        zeilen.append("[%d] %s" % (i, titel))
        zeilen.append("Stream: %s" % stream)
        zeilen.append("Kanal: %s" % kanal)
        zeilen.append("-" * 60)
        zeilen.append(_pool_export_body(f))
        zeilen.append("")
    jetzt = datetime.datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")
    kopf = ["ShareNext – Zufalls-Pool: Export aller Beitragstexte",
            "Erstellt: %s" % jetzt,
            "Anzahl Beiträge: %d" % len(rows), ""]
    inhalt = "\n".join(kopf + zeilen)
    if not inhalt.endswith("\n"):
        inhalt += "\n"
    resp = Response(inhalt, mimetype="text/plain")
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Content-Disposition"] = 'attachment; filename="sharenext-pool-export.txt"'
    return resp

def _pool_back():
    """Nach einer Pool-Aufnahme NICHT auf die Pool-Seite umleiten (ueberfluessig), sondern zurueck
    zur Ausgangsseite (Freigabe oder Einplanung). Die Pool-Seite erreicht man nur ueber die
    Startseiten-Kachel. Endpunkt anhand des Referers, Default Einplanung."""
    if "/entwuerfe" in (request.referrer or ""):
        return redirect(url_for("entwuerfe"))
    return redirect(url_for("einplanung"))

@app.route("/pool-aufnehmen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def pool_aufnehmen(eid):
    """Nimmt einen freigegebenen Beitrag in den Topf auf (einmalige Freigabe fuer ALLE Stellen).
    Der Status wechselt auf 'pool' -> faellt aus dem Einmal-Posten-Fluss heraus, wird stattdessen
    automatisch je Stelle/Kanal gezogen."""
    user = session["user"]
    with get_conn() as conn:
        e = conn.execute("SELECT id FROM entwuerfe WHERE id=?", (eid,)).fetchone()
        if not e:
            abort(404)
        conn.execute("INSERT OR IGNORE INTO pool(entwurf_id, freigegeben_von) VALUES (?,?)", (eid, user))
        conn.execute("UPDATE pool SET aktiv=1 WHERE entwurf_id=?", (eid,))   # frueher entfernten reaktivieren
        conn.execute("UPDATE entwuerfe SET status='pool' WHERE id=?", (eid,))
        audit_log(conn, user, "pool_aufgenommen", eid, "in den Zufalls-Pool aufgenommen (alle Stellen)")
        conn.commit()
    flash("Beitrag %d ist im Pool – er wird ab jetzt automatisch je Beratungsstelle ausgespielt (jeder Beitrag je Stelle genau einmal pro Kanal)." % eid)
    return _pool_back()

@app.route("/pool-entfernen/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def pool_entfernen(eid):
    """Nimmt einen Beitrag aus dem Topf (aktiv=0). Das 'nie doppelt'-Gedaechtnis (pool_nutzung)
    bleibt erhalten. Der Beitrag geht zurueck auf 'freigegeben' -> wieder manuell einplanbar."""
    user = session["user"]
    with get_conn() as conn:
        conn.execute("UPDATE pool SET aktiv=0 WHERE entwurf_id=?", (eid,))
        conn.execute("UPDATE entwuerfe SET status='freigegeben' WHERE id=? AND status='pool'", (eid,))
        audit_log(conn, user, "pool_entfernt", eid, "aus dem Zufalls-Pool genommen")
        conn.commit()
    flash("Beitrag %d ist nicht mehr im Pool. Du findest ihn wieder unter „4. Einplanung\"." % eid)
    return redirect(url_for("pool_seite"))

@app.route("/pool-aufnehmen-alle", methods=["POST"])
@rolle_required("freigeber")
def pool_aufnehmen_alle():
    """Sammelaktion (Issue #128): nimmt ALLE aktuell offenen Entwuerfe (status='entwurf') auf einen
    Schlag in den Zufalls-Pool auf. Der Pool-Eintrag gilt bewusst als Freigabe; es wird nichts sofort
    veroeffentlicht (Posten erst ueber die taegliche Pool-Ziehung). Idempotent: bereits gepoolte/
    freigegebene/veroeffentlichte/verworfene Beitraege werden NICHT angefasst, nur status='entwurf'."""
    user = session["user"]
    n = 0
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM entwuerfe WHERE status='entwurf'")]
        for eid in ids:
            conn.execute("INSERT OR IGNORE INTO pool(entwurf_id, freigegeben_von) VALUES (?,?)", (eid, user))
            conn.execute("UPDATE pool SET aktiv=1 WHERE entwurf_id=?", (eid,))  # frueher entfernten reaktivieren
            conn.execute("UPDATE entwuerfe SET status='pool' WHERE id=?", (eid,))
            audit_log(conn, user, "pool_aufgenommen", eid, "Sammelaktion: in den Zufalls-Pool aufgenommen (alle Stellen)")
            n += 1
        conn.commit()
    if n:
        flash("%d Beiträge in den Pool aufgenommen – sie werden ab jetzt automatisch je Beratungsstelle "
              "ausgespielt. Einzelne kannst du hier jederzeit wieder „Aus dem Pool nehmen\"." % n)
    else:
        flash("Es gab keine offenen Entwürfe, die in den Pool aufgenommen werden konnten.")
    return _pool_back()

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

@app.route("/anderes-bild/<int:eid>", methods=["POST"])
@rolle_required("freigeber")
def anderes_bild(eid):
    """#144-C 'Anderes Bild': wuerfelt fuer DIESEN Entwurf einen ANDEREN aktiven Bild-Stil
    (ungleich dem aktuellen fields['bild_stil']), ergaenzt ggf. fehlende Felder (kreativ_motiv,
    falls der neue Stil 'kreativ' ist) und rendert das Bild NEU (neuer Stil/neues Foto = KI-Kosten
    wie 'Neu erzeugen'). Status, Termin und Text des Beitrags bleiben unveraendert."""
    zurueck = request.form.get("zurueck", "entwuerfe")
    ziel = url_for("entwuerfe") if zurueck == "entwuerfe" else url_for("einplanung")
    with get_conn() as conn:
        e = conn.execute("SELECT id, text, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    if e["status"] not in ("freigegeben", "entwurf"):
        flash("Bild von Beitrag %d kann nicht gewechselt werden (Status: %s)." % (eid, e["status"]))
        return redirect(ziel)
    try:
        import bildmotiv, stilwahl, textgen
        data = json.loads(e["text"])
        with get_conn() as conn:
            neu = stilwahl.anderen_stil_waehlen(conn, data)
        if neu is None:
            flash("Es ist nur ein Bild-Stil aktiv – bitte erst in der Verwaltung unter „Bild-Stil“ "
                  "weitere Stile aktivieren, dann lässt sich ein anderes Bild würfeln.")
            return redirect(ziel)
        # Neuer Stil 'kreativ' und noch kein kreativ_motiv -> Art-Director-Motiv erzeugen (No-Op
        # ohne Key; dann faellt kreativ auf die bestehende Szene zurueck).
        if neu == "kreativ" and not (data.get("kreativ_motiv") or "").strip():
            textgen.art_director_motiv(data)
        photo = bildmotiv.ensure_photo_fuer(data)   # neuer Stil -> ggf. neues KI-Foto
        slogan = bildgen.pick_slogan(data.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(data, photo, slogan, out)
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), out, eid))
            audit_log(conn, session["user"], "bild_stil_gewechselt", eid, neu)
            conn.commit()
        _stil_label = {"standard": "Standard", "ki_tafel": "KI-Tafel", "kreativ": "Kreativ",
                       "comic": "Comic"}
        flash("Beitrag %d hat ein anderes Bild (Stil: %s, neues KI-Bild). Text und Termin bleiben."
              % (eid, _stil_label.get(neu, neu)))
    except Exception as ex:
        flash("Anderes Bild konnte nicht erzeugt werden: %s" % ex)
    return redirect(ziel)

@app.route("/bild-generieren/<int:eid>", methods=["POST"])
@login_required
def bild_generieren(eid):
    """Comic-Workflow (entkoppelt): erzeugt AUF KLICK der Nutzerin das Bild eines Entwurfs im
    von ihr GEWAEHLTEN Stil (Formularfeld bild_stil) - es gibt KEINE Stil-Vorauswahl. Ablauf
    (Vorbild: anderes_bild): Stil validieren -> data['bild_stil'] setzen -> je nach Stil den noetigen
    KI-Vorbereitungsschritt (comic: comic_brief, kreativ: art_director_motiv) -> ensure_photo_fuer ->
    pick_slogan -> render -> bild_pfad speichern. Alle externen KI-/Bild-Aufrufe sind gekapselt
    (kein 500 fuer die Nutzerin, sondern eine verstaendliche Meldung). Gilt fuer /entwuerfe UND /pool
    (Rueckkehr ueber den zurueck-Parameter)."""
    zurueck = request.form.get("zurueck", "entwuerfe")
    ziel = (url_for("pool_seite") if zurueck == "pool"
            else url_for("einplanung") if zurueck == "einplanung"
            else url_for("entwuerfe"))
    stil = (request.form.get("bild_stil") or "").strip()
    if stil not in ("comic", "comic_beratung", "comic_strip", "ki_tafel", "kreativ"):
        flash("Bitte einen Stil wählen.")
        return redirect(ziel)
    with get_conn() as conn:
        e = conn.execute("SELECT id, text, status FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    try:
        import bildmotiv, textgen
        data = json.loads(e["text"])
        data["bild_stil"] = stil
        # #157: strip_panels gehoeren ausschliesslich zum comic_strip. Wird ein ANDERER Stil
        # generiert, die (ggf. alten) Panel-Verweise entfernen, damit die Vorschau nicht
        # faelschlich weiter den alten 3er-Strip statt des neuen Einzelbilds zeigt.
        if stil != "comic_strip":
            data.pop("strip_panels", None)
        # comic_strip (#154): 3-Felder-Comic-Karussell mit Sprechblasen, personalisiert pro Stelle.
        # Fuer die stellenlose Vorschau REPRAESENTATIV mit dem Berater DER ERSTEN aktiven Stelle
        # rendern, die eine Berater-Referenz hat (bibel_bild > berater_comic). Gibt es keine ->
        # Hinweis + kein Bild. Die 3 rohen Panels werden erzeugt; als Einzel-Vorschau (bild_pfad)
        # dient Panel 1, und das Format wird als 'karussell' festgehalten.
        if stil == "comic_strip":
            # #156: optionales Override fuer die Sprechblase in Feld 1. Nicht-leer -> ersetzt die
            # Ueberschrift, leer -> Override entfernen (wieder Ueberschrift). Wird im Entwurf-JSON
            # (data) persistiert und unten mitgeschrieben; so bleibt es bei erneutem Generieren
            # erhalten und wird in JEDEM der drei Wege (Entwuerfe/Pool/Einplanung) bis in
            # ensure_comic_strip_bilder als fields['strip_zeile1'] durchgereicht.
            data["strip_zeile1"] = (request.form.get("strip_zeile1") or "").strip()
            # #155: Bild-2-Auswahl (Aermelschoner) -> steuert den Archetyp. Eine KONKRETE Variante
            # bestimmt den Archetyp direkt (aus COMIC_STRIP_VARIANTEN). "Automatisch" (leer) ->
            # leichte KI-Vorauswahl (robust, Fallback ohne Key) waehlt Archetyp + Variante. Beides
            # (strip_archetyp + strip_zeile2) wird unten im Entwurf-JSON persistiert, damit alle drei
            # Wege (Entwuerfe/Pool/Einplanung) denselben Wert lesen und es beim erneuten Generieren
            # erhalten bleibt; ensure_comic_strip_bilder loest daraus Szenen + Sprechblasen auf.
            strip_zeile2 = (request.form.get("strip_zeile2") or "").strip()
            if strip_zeile2:
                arche = bildmotiv._comic_strip_variante_archetyp(strip_zeile2) or "vorteil"
                data["strip_zeile2"] = strip_zeile2
                data["strip_archetyp"] = arche
            else:
                vor = textgen.comic_strip_vorauswahl(data)
                arche = (vor or {}).get("archetyp") or "vorteil"
                idx = (vor or {}).get("variant_index") or 0
                varianten = bildmotiv.COMIC_STRIP_VARIANTEN.get(arche, [])
                data["strip_archetyp"] = arche
                data["strip_zeile2"] = (varianten[idx] if 0 <= idx < len(varianten)
                                        else (varianten[0] if varianten else ""))
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT berater_comic, bibel_bild FROM beratungsstellen WHERE aktiv=1 "
                    "AND ((berater_comic IS NOT NULL AND TRIM(berater_comic)<>'') "
                    "OR (bibel_bild IS NOT NULL AND TRIM(bibel_bild)<>'')) ORDER BY id").fetchall()
            berater_ref = None
            for r in rows:
                for feld in ("bibel_bild", "berater_comic"):
                    p = (r[feld] or "").strip()
                    if p and os.path.exists(p):
                        berater_ref = p
                        break
                if berater_ref:
                    break
            if not berater_ref:
                flash("Bitte zuerst mind. einen Comic-Berater in der Beratungsstellen-Verwaltung erzeugen.")
                return redirect(ziel)
            panels = bildmotiv.ensure_comic_strip_bilder(data, berater_ref)
            if not panels:
                flash("Comic-Strip konnte gerade nicht erzeugt werden (Bild-KI nicht erreichbar?).")
                return redirect(ziel)
            # #157: alle drei Panels zusaetzlich im Entwurf-JSON persistieren, damit die
            # Beitrags-Vorschau (Entwuerfe/Pool/Einplanung) alle drei Bilder DIREKT zeigt.
            # Gleiches Pfad-Format wie bild_pfad -> Auslieferung ueber die /strip-panel-Route.
            # bild_pfad bleibt Panel 1 (Einzel-Fallback). Nur tatsaechlich vorhandene Pfade.
            data["strip_panels"] = [p for p in panels if p and os.path.exists(p)]
            with get_conn() as conn:
                conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=?, format='karussell' WHERE id=?",
                             (json.dumps(data, ensure_ascii=False), panels[0], eid))
                audit_log(conn, session["user"], "bild_generiert", eid, stil)
                conn.commit()
            flash("Comic-Strip (3-Felder-Karussell) für Beitrag %d erzeugt." % eid)
            return redirect(ziel)
        # comic_beratung ist personalisiert pro Stelle; in der stellenlosen Vorschau rendern wir
        # REPRAESENTATIV mit dem Berater-Comic der ERSTEN aktiven Stelle, die einen hinterlegt hat.
        # Gibt es keine -> Hinweis + kein Bild (der Berater-Comic wird in der Verwaltung erzeugt).
        if stil == "comic_beratung":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT berater_comic, bibel_bild, bibel_text FROM beratungsstellen WHERE aktiv=1 "
                    "AND ((berater_comic IS NOT NULL AND TRIM(berater_comic)<>'') "
                    "OR (bibel_bild IS NOT NULL AND TRIM(bibel_bild)<>'')) ORDER BY id").fetchall()
            # #151: Character-Bible (bibel_bild) hat Vorrang vor dem aus dem Foto abgeleiteten
            # berater_comic; die erste Stelle mit einer vorhandenen Datei liefert die Vorschau.
            gewaehlt = None
            for r in rows:
                for feld in ("bibel_bild", "berater_comic"):
                    p = (r[feld] or "").strip()
                    if p and os.path.exists(p):
                        gewaehlt = r
                        data["berater_comic"] = p
                        break
                if gewaehlt is not None:
                    break
            if gewaehlt is None:
                flash("Bitte zuerst mind. einen Comic-Berater in der Beratungsstellen-Verwaltung erzeugen.")
                return redirect(ziel)
            if (gewaehlt["bibel_text"] or "").strip():
                data["bibel_text"] = gewaehlt["bibel_text"].strip()
        # Nur der jeweils noetige KI-Vorbereitungsschritt (on-demand, nur beim gewaehlten Stil):
        if stil in ("comic", "comic_beratung"):
            # Bei jedem expliziten Klick einen FRISCHEN Bild-Einfall wuerfeln: alten Brief verwerfen,
            # damit (a) "Bild generieren" erneut eine NEUE Idee liefert und (b) der verbesserte Prompt
            # + das hoehere Modell wirklich greifen (der Bild-Cache haengt am Prompt-String). Bei
            # comic_beratung liefert der Brief das optionale Thema/Anlass (szene) fuer den Prompt.
            data.pop("comic_brief", None)
            textgen.comic_brief(data)          # neuer Einfall (Kunst/Metapher/Finanzamt-Typ)
        elif stil == "kreativ" and not (data.get("kreativ_motiv") or "").strip():
            textgen.art_director_motiv(data)   # kinoreifes Motiv (No-Op ohne Key)
        photo = bildmotiv.ensure_photo_fuer(data)
        slogan = bildgen.pick_slogan(data.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(data, photo, slogan, out)
        with get_conn() as conn:
            conn.execute("UPDATE entwuerfe SET text=?, bild_pfad=? WHERE id=?",
                         (json.dumps(data, ensure_ascii=False), out, eid))
            audit_log(conn, session["user"], "bild_generiert", eid, stil)
            conn.commit()
        _stil_label = {"comic": "Comic", "comic_beratung": "Comic Beratung",
                       "ki_tafel": "Tafel", "kreativ": "Kreativ"}
        flash("Bild für Beitrag %d im Stil „%s“ erzeugt." % (eid, _stil_label.get(stil, stil)))
    except Exception as ex:
        flash("Bild konnte nicht erzeugt werden: %s" % ex)
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
.bar>div{background:#0B2545;height:18px;border-radius:6px}
</style>
<div style="max-width:780px;margin:0 auto 10px"><div class=top><h2 style="margin:0;color:#0B2545">&#x1F4CA; Was funktioniert</h2><a href="/" style="color:#0B2545;text-decoration:none;font-weight:bold">&larr; Startseite</a></div></div>
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
            # #144: Bild-Stil EINMAL zufaellig aus den aktiven Stilen waehlen (stabil in
            # fields['bild_stil']); danach im kreativ-Fall das Art-Director-Motiv erzeugen
            # (No-Op ausserhalb kreativ / ohne Key). Robust gegen Fehler.
            try:
                import stilwahl
                stilwahl.zuweisen_stil_falls_fehlt(conn, data)
                textgen.art_director_motiv(data)
            except Exception as ex:
                log.warning("Stil-Zuweisung uebersprungen: %s", ex)
            # #140: Schauplatz EINMAL bei der Erzeugung waehlen (Datum des eigenen Beitrags ->
            # Kalender-Jahreszeit, sofern das Thema keinen saisonalen Bezug hat).
            import schauplatz
            schauplatz.zuweisen_falls_fehlt(conn, data, datum=d)
            # #142: Traeger (Device der Botschaft) EINMAL waehlen, stabil in fields['traeger'].
            # Robust: fehlt die Tabelle (alte DB) -> No-Op.
            try:
                import traeger
                traeger.zuweisen_traeger_falls_fehlt(conn, data, datum=d)
            except Exception as ex:
                log.warning("Traeger-Zuweisung uebersprungen: %s", ex)
            conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer) "
                         "VALUES (?, 'google', ?, 'entwurf', ?)",
                         (thema_id, json.dumps(data, ensure_ascii=False), datum))
            audit_log(conn, session["user"], "eigener_beitrag", None, "Thema '%s' fuer %s" % (thema_txt[:60], datum))
            conn.commit()
        # Entkoppelt (Comic-Workflow): KEIN automatisches Rendern mehr. bild_pfad bleibt NULL;
        # die Nutzerin waehlt spaeter unter "3. Freigabe" je Beitrag einen Stil und erzeugt das
        # Bild per Klick ("Bild generieren").
        flash("Beitrag-Entwurf zum Thema „%s“ für %s erstellt – jetzt unter „3. Freigabe: Texte & Bilder“ "
              "prüfen, Bild-Stil wählen und Bild erzeugen." % (thema_txt[:60], _de_datum(datum)))
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

@app.route("/strip-panel/<int:eid>/<int:idx>")
@login_required
def strip_panel(eid, idx):
    """#157: liefert Panel <idx> (0..2) des Comic-Strips eines Entwurfs aus - GLEICHE Schutzstufe
    (@login_required) wie das Einzel-Vorschaubild /bild. Die Panel-Pfade stammen aus dem
    Entwurf-JSON (Feld 'strip_panels'), das beim comic_strip-Generieren gefuellt wird. Existiert
    das Feld/der Index/die Datei nicht -> 404 (kein oeffentlicher Zugriff, keine neuen Rechte)."""
    with get_conn() as conn:
        e = conn.execute("SELECT text FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    try:
        panels = (json.loads(e["text"]) or {}).get("strip_panels") or []
    except Exception:
        panels = []
    if not (0 <= idx < len(panels)):
        abort(404)
    pfad = panels[idx]
    if not pfad or not os.path.exists(pfad):
        abort(404)
    return send_file(pfad, mimetype="image/png")

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

def _publish_story(publish, fb_page_id, bilder, eid, stelle_id, do_ig=True, do_fb=False):
    """Postet die uebergebenen Bilder NACHEINANDER als Story-Frames (9:16) - ein Karussell
    erscheint so als mehrteilige Story. Jeder Slide wird auf 9:16 gebracht.
      do_ig -> Instagram-Story (braucht oeffentliche URL via IONOS-Upload + IG-Verknuepfung)
      do_fb -> Facebook-Seiten-Story (direkter Bild-Upload, KEINE URL noetig)
    (ok, info) - ok, wenn mind. ein Frame irgendwo gepostet wurde."""
    import time
    valid = [b for b in (bilder or []) if b and os.path.exists(b)]
    if not valid:
        return False, "Kein Bild fuer die Story vorhanden."
    ig_id = None
    if do_ig:
        import uploader
        if not uploader.configured():
            if not do_fb:
                return False, "Bild-Upload nicht konfiguriert (IONOS-Secrets fehlen)."
            do_ig = False   # Instagram-Story nicht moeglich, Facebook-Story trotzdem versuchen
        else:
            for pg in publish.list_pages():
                if str(pg.get("id")) == str(fb_page_id):
                    ig_id = pg.get("ig_id"); break
            if not ig_id:
                if not do_fb:
                    return False, "Keine Instagram-Verknuepfung fuer diese Facebook-Seite."
                do_ig = False
    stamp = int(time.time())
    gemacht, fehler = 0, []
    for i, square in enumerate(valid):
        out = os.path.join(DATA_DIR, "bilder", "story_%d_%s_%d.png" % (eid, stelle_id or "p", i))
        try:
            _status_hochkant(square, out)
        except Exception as ex:
            fehler.append("Frame %d: %s" % (i + 1, ex)); continue
        if do_ig and ig_id:
            try:
                import uploader
                url = uploader.upload(out, remote_name="story_e%d_%s_%d_%d.png" % (eid, stelle_id or "p", stamp, i))
                s_ok, s_info = publish.publish_instagram_story(ig_id, url)
            except Exception as ex:
                s_ok, s_info = False, str(ex)
            if s_ok:
                gemacht += 1
            else:
                fehler.append("IG-Frame %d: %s" % (i + 1, s_info))
        if do_fb:
            try:
                f_ok, f_info = publish.publish_facebook_story(fb_page_id, out)
            except Exception as ex:
                f_ok, f_info = False, str(ex)
            if f_ok:
                gemacht += 1
            else:
                fehler.append("FB-Frame %d: %s" % (i + 1, f_info))
    if gemacht:
        msg = "%d Story-Frames gepostet" % gemacht
        return True, (msg + " (" + "; ".join(fehler) + ")") if fehler else msg
    return False, "; ".join(fehler) or "Story fehlgeschlagen"


def _ensure_bild_pfad(conn, eid, fields):
    """Sicherheitsnetz nach dem Entkoppeln von Text und Bild (Comic-Workflow): liefert einen
    gueltigen Bild-Pfad fuer den Entwurf. Ist entwuerfe.bild_pfad noch NULL (Bild noch nicht per
    Klick erzeugt), wird das Bild JETZT on-demand gerendert (ensure_photo_fuer -> pick_slogan ->
    render) und in bild_pfad gespeichert - damit ein automatischer Pool-Post NIE ohne Bild rausgeht.

    Robust: schlaegt das Rendern fehl, wird None geliefert (der Aufrufer meldet dann 'Kein Bild
    vorhanden' statt zu crashen)."""
    try:
        row = conn.execute("SELECT bild_pfad FROM entwuerfe WHERE id=?", (eid,)).fetchone()
    except Exception:
        row = None
    pfad = (row["bild_pfad"] if row else None)
    if pfad and os.path.exists(pfad):
        return pfad
    try:
        import bildmotiv
        photo = bildmotiv.ensure_photo_fuer(fields)
        slogan = bildgen.pick_slogan(fields.get("slogan"))
        out = os.path.join(DATA_DIR, "bilder", "entwurf_%d.png" % eid)
        bildgen.render(fields, photo, slogan, out)
        conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?", (out, eid))
        conn.commit()
        log.info("Bild on-demand gerendert (Veroeffentlichungs-Fallback) fuer Beitrag %s", eid)
        return out
    except Exception as ex:
        log.warning("On-demand-Bild (Veroeffentlichungs-Fallback) fuer Beitrag %s fehlgeschlagen: %s",
                    eid, ex)
        return None


def _veroeffentliche_ziel(conn, e, eid, f, fmt_fb, fmt_ig, kanal, stelle, page_id, user, publish, story=True, story_fb=False):
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
                # Einzelbild-Feed OHNE Stelle: hier (und NUR hier) wird das allgemeine Beitragsbild
                # tatsaechlich als Post-Bild konsumiert. Sicherheitsnetz (Entkopplung): ist bild_pfad
                # noch NULL, JETZT lazy on-demand rendern - so entsteht nie ungefragt ein "Notbild"
                # fuer Stelle-/Karussell-Posts (die rendern ohnehin frisch pro Stelle).
                bilder = [_ensure_bild_pfad(conn, eid, f)]
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
        # Zusaetzlich als Facebook-Story (9:16), wenn gewuenscht und der Feed-Post geklappt hat.
        # Story-Ergebnis wird nur protokolliert (Stories sind fluechtig).
        if story_fb and ok:
            try:
                slides = _render("karussell")
                sf_ok, sf_info = _publish_story(publish, ziel_seite, slides, eid, stelle_id,
                                                do_ig=False, do_fb=True)
            except Exception as ex:
                sf_ok, sf_info = False, str(ex)
            audit_log(conn, user, "facebook_story_%s" % ("ok" if sf_ok else "fehler"), eid,
                      "Ziel %s / %s" % (ziel_seite, sf_info))
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


def _veroeffentliche_whatsapp(conn, e, eid, f, kanal, stelle, user):
    """Veroeffentlicht einen Pool-Beitrag ueber den WhatsApp-Dienst (#127) - getrennt vom FB/IG-Pfad.

    kanal: 'whatsapp_status' (taeglicher 9:16-Status, moeglichst personalisiertes Bild) oder
    'whatsapp_kanal' (kuratierter Kanalbeitrag mit Bild + Begleittext an den Kanal der Stelle).
    Gibt (ziel_name, erfolg, [(kanal, ok, info), ...]) zurueck - selbe Form wie _veroeffentliche_ziel,
    damit der Aufrufer (Scheduler) unveraendert weiterverbuchen kann. Ein nicht erreichbarer
    WhatsApp-Dienst fuehrt zu erfolg=False (-> status='fehler'), niemals zu einem Crash."""
    import personalisierung
    ziel_name = (stelle["name"] if stelle else "WhatsApp")
    ziel_seite = "whatsapp"
    quelle_url = ""
    try:
        kanal_text, story_text = personalisierung.whatsapp_texte(f, stelle, quelle_url)
    except Exception as ex:
        kanal_text, story_text = (f.get("caption") or ""), ""
        log.exception("WhatsApp-Texte fuer Beitrag %s nicht erzeugbar: %s", eid, ex)

    ok, info = False, ""
    if kanal == "whatsapp_status":
        # Personalisiertes 9:16-Status-Bild (Portraet/Ort), Fallback: allgemeines Hochkant-Bild.
        bild = None
        try:
            if stelle:
                quad = _render_stelle_bild(eid, int(stelle["id"]))
                if quad and os.path.exists(quad):
                    bild = _status_hochkant(quad, os.path.join(
                        DATA_DIR, "preview", "wa_status_e%d_stelle_%d.png" % (eid, int(stelle["id"]))))
            # Basisbild-Fallback NUR ohne Stelle (dann gibt es kein per-Stelle-Bild): hier wird das
            # allgemeine Bild konsumiert -> lazy on-demand rendern erlaubt. MIT Stelle rendert
            # _render_stelle_bild frisch; kein generisches "Notbild" erzeugen/persistieren (Klick-Regel).
            if not bild and not stelle:
                _bp = _ensure_bild_pfad(conn, eid, f)
                if _bp and os.path.exists(_bp):
                    bild = _status_hochkant(_bp, os.path.join(
                        DATA_DIR, "preview", "status_%d.png" % eid))
        except Exception as ex:
            log.exception("WhatsApp-Status-Bild fuer Beitrag %s fehlgeschlagen: %s", eid, ex)
            bild = None
        caption = story_text or kanal_text or (f.get("caption") or "")
        payload = {"caption": caption, "toContacts": True}
        if bild:
            payload["imagePath"] = bild
        # Multi-Session: jede Beratungsstelle postet ihren Status von IHRER eigenen Nummer.
        res, err = _wa_call("/post-status", method="POST", payload=payload, timeout=60,
                            session=(stelle["id"] if stelle else None))
        ok, info = _wa_ergebnis(res, err)
    elif kanal == "whatsapp_kanal":
        invite = (stelle["wa_kanal_invite"] if (stelle and "wa_kanal_invite" in stelle.keys()) else "") or ""
        invite = invite.strip()
        if not invite:
            ok, info = False, "Kein WhatsApp-Kanal (Einladungslink) fuer diese Stelle hinterlegt"
        else:
            bild = None
            try:
                if stelle:
                    bild = _render_stelle_bild(eid, int(stelle["id"]))
                # Basisbild-Fallback NUR ohne Stelle (Klick-Regel: kein generisches Bild fuer
                # Stelle-Posts erzeugen/persistieren).
                if not bild and not stelle:
                    _bp = _ensure_bild_pfad(conn, eid, f)
                    if _bp and os.path.exists(_bp):
                        bild = _bp
            except Exception as ex:
                log.exception("WhatsApp-Kanal-Bild fuer Beitrag %s fehlgeschlagen: %s", eid, ex)
                bild = None
            payload = {"invite": invite, "caption": kanal_text or (f.get("caption") or "")}
            if bild and os.path.exists(bild):
                payload["imagePath"] = bild
            # Multi-Session: Kanalbeitrag ueber die eigene Nummer der Stelle (Admin ihres Kanals).
            res, err = _wa_call("/post-channel", method="POST", payload=payload, timeout=60,
                                session=(stelle["id"] if stelle else None))
            ok, info = _wa_ergebnis(res, err)
    else:
        ok, info = False, "Unbekannter WhatsApp-Kanal: %s" % kanal

    ergebnisse = [(kanal, ok, info)]
    if ok:
        conn.execute("INSERT INTO posts(entwurf_id, kanal, plattform_post_id, seite, "
                     "veroeffentlicht_am, status) VALUES (?,?,?,?,datetime('now'),'veroeffentlicht')",
                     (eid, kanal, info, ziel_seite))
        audit_log(conn, user, "veroeffentlicht_%s" % kanal, eid, "Ziel %s / %s" % (ziel_name, info))
    else:
        conn.execute("INSERT INTO posts(entwurf_id, kanal, status, fehler) VALUES (?,?,?,?)",
                     (eid, kanal, "fehler", info))
        audit_log(conn, user, "veroeffentlichung_fehler_%s" % kanal, eid, info)
    conn.commit()
    return ziel_name, ok, ergebnisse


def _wa_ergebnis(res, err):
    """Normalisiert die _wa_call-Antwort des WhatsApp-Dienstes zu (ok, info)."""
    if err:
        return False, "WhatsApp-Dienst: %s" % err
    if res and res.get("error"):
        return False, "WhatsApp: %s" % res["error"]
    if res and res.get("ok"):
        teile = []
        if res.get("recipients") is not None:
            teile.append("%s Empfaenger" % res["recipients"])
        if res.get("jid"):
            teile.append(str(res["jid"]))
        return True, ("OK" + ((" (%s)" % ", ".join(teile)) if teile else ""))
    return False, "WhatsApp: unerwartete Antwort"


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
    story_fb = request.form.get("story_fb") == "1"
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
            ziel_name, erfolg, ergebnisse = _veroeffentliche_ziel(conn, e, eid, f, fmt_fb, fmt_ig, kanal, stelle, pid, user, publish, story, story_fb)
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
    story_fb = request.form.get("story_fb") == "1"
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
                                  kanal_map=kanal_map, story_ig=story, story_fb=story_fb))

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
            elif formular == "stelle_whatsapp":
                # WhatsApp-Konfiguration je Stelle (Pool Phase 3, #127): steuert, ob die Stelle bei der
                # taeglichen Pool-Ziehung mit WhatsApp-Status bzw. WhatsApp-Kanal bespielt wird.
                sid = request.form.get("stelle_id", "").strip()
                wa_status = 1 if request.form.get("wa_status_aktiv") else 0
                wa_invite = request.form.get("wa_kanal_invite", "").strip()
                if wa_invite and not (wa_invite.startswith("http://") or wa_invite.startswith("https://")):
                    flash("Der WhatsApp-Kanal-Link muss mit http:// oder https:// beginnen.")
                elif sid and sid.isdigit():
                    conn.execute("UPDATE beratungsstellen SET wa_status_aktiv=?, wa_kanal_invite=? WHERE id=?",
                                 (wa_status, wa_invite or None, sid))
                    audit_log(conn, session["user"], "beratungsstelle_whatsapp_gesetzt", None,
                              "Stelle %s -> Status=%d, Kanal=%s" % (sid, wa_status, "ja" if wa_invite else "nein"))
                    flash("WhatsApp-Einstellungen der Beratungsstelle gespeichert.")
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
            elif formular == "stelle_bibel":
                # Character-Bible je Stelle (#151, Stil "Comic Beratung"): optionaler Bild-Upload
                # (Comic-/Stylesheet-Vorlage) + Charakter-Beschreibung. Das Bild wird ueber PIL neu
                # kodiert (entschaerft manipulierte Dateien) und nach DATA_DIR/bibeln/stelle_<id>.png
                # geschrieben; der Text landet in bibel_text. Auslieferung nur login-geschuetzt (DSGVO).
                sid = request.form.get("stelle_id", "").strip()
                if sid and sid.isascii() and sid.isdigit():
                    bibel_text = request.form.get("bibel_text", "").strip()
                    conn.execute("UPDATE beratungsstellen SET bibel_text=? WHERE id=?",
                                 (bibel_text or None, sid))
                    file = request.files.get("bibel_bild")
                    if file and file.filename:
                        try:
                            from PIL import Image
                            bdir = os.path.join(DATA_DIR, "bibeln"); os.makedirs(bdir, exist_ok=True)
                            dest = os.path.join(bdir, "stelle_%s.png" % sid)
                            img = Image.open(file.stream)
                            w, h = img.size                      # Header-Mass, noch nicht dekodiert
                            if w * h > 40_000_000:               # ~40 MP Deckel (Speicher-Bomben-Schutz)
                                raise ValueError("Bild zu gross")
                            img = img.convert("RGB")
                            gr = max(w, h)                       # laengste Kante deckeln (Pi-Speicher)
                            if gr > 1536:
                                skala = 1536.0 / gr
                                img = img.resize((max(1, int(w*skala)), max(1, int(h*skala))), Image.LANCZOS)
                            img.save(dest)
                            conn.execute("UPDATE beratungsstellen SET bibel_bild=? WHERE id=?", (dest, sid))
                            flash("Character-Bible (Bild und Beschreibung) gespeichert.")
                        except Exception:
                            log.exception("Character-Bible-Upload fehlgeschlagen (Stelle %s)", sid)
                            flash("Character-Bible-Bild-Upload fehlgeschlagen – bitte eine gültige Bilddatei (max ~40 Megapixel) wählen.")
                    else:
                        flash("Charakter-Beschreibung gespeichert.")
                    audit_log(conn, session["user"], "beratungsstelle_bibel_gesetzt", None, "Stelle %s" % sid)
                else:
                    flash("Bitte eine Beratungsstelle wählen.")
            elif formular == "stelle_bibel_del":
                sid = request.form.get("stelle_id", "").strip()
                if sid:
                    row = conn.execute("SELECT bibel_bild FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
                    if row and row["bibel_bild"] and _under_bibeln(row["bibel_bild"]):
                        try:
                            os.remove(row["bibel_bild"])
                        except Exception:
                            pass
                    conn.execute("UPDATE beratungsstellen SET bibel_bild=NULL WHERE id=?", (sid,))
                    audit_log(conn, session["user"], "beratungsstelle_bibel_bild_entfernt", None, "Stelle %s" % sid)
                    flash("Character-Bible-Bild entfernt.")
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
            elif formular == "schauplatz_save":
                # #140: Schauplatz neu anlegen ODER bestehenden bearbeiten (per id). Jahreszeit
                # validiert; Beschreibung Pflicht. aktiv-Checkbox steuert die Sichtbarkeit in der Wahl.
                import schauplatz as _sp
                sid = request.form.get("id", "").strip()
                beschreibung = request.form.get("beschreibung", "").strip()
                jahreszeit = request.form.get("jahreszeit", "").strip().lower()
                aktiv = 1 if request.form.get("aktiv") else 0
                if beschreibung and jahreszeit in _sp.JAHRESZEITEN:
                    if sid.isdigit():
                        conn.execute("UPDATE schauplaetze SET beschreibung=?, jahreszeit=?, aktiv=? WHERE id=?",
                                     (beschreibung, jahreszeit, aktiv, int(sid)))
                        flash("Schauplatz aktualisiert.")
                    else:
                        conn.execute("INSERT INTO schauplaetze(beschreibung, jahreszeit, aktiv) VALUES (?,?,?)",
                                     (beschreibung, jahreszeit, aktiv))
                        flash("Schauplatz angelegt.")
                    audit_log(conn, session["user"], "schauplatz_gespeichert", None, beschreibung[:60])
                else:
                    flash("Beschreibung und gültige Jahreszeit (fruehling/sommer/herbst/winter) nötig.")
            elif formular == "schauplatz_toggle":
                sid = request.form.get("id", "").strip()
                if sid.isdigit():
                    conn.execute("UPDATE schauplaetze SET aktiv=1-aktiv WHERE id=?", (int(sid),))
                    flash("Schauplatz geändert.")
            elif formular == "schauplatz_delete":
                sid = request.form.get("id", "").strip()
                if sid.isdigit():
                    conn.execute("DELETE FROM schauplaetze WHERE id=?", (int(sid),))
                    audit_log(conn, session["user"], "schauplatz_geloescht", None, sid)
                    flash("Schauplatz gelöscht.")
            elif formular == "traeger_save":
                # #142: Traeger neu anlegen ODER bestehenden bearbeiten (per id). Name + Snippet
                # Pflicht; aktiv-Checkbox steuert die Sichtbarkeit in der Auswahl.
                tid = request.form.get("id", "").strip()
                name = request.form.get("name", "").strip()
                prompt_snippet = request.form.get("prompt_snippet", "").strip()
                aktiv = 1 if request.form.get("aktiv") else 0
                if name and prompt_snippet:
                    if tid.isdigit():
                        conn.execute("UPDATE traeger SET name=?, prompt_snippet=?, aktiv=? WHERE id=?",
                                     (name, prompt_snippet, aktiv, int(tid)))
                        flash("Träger aktualisiert.")
                    else:
                        conn.execute("INSERT INTO traeger(name, prompt_snippet, aktiv) VALUES (?,?,?)",
                                     (name, prompt_snippet, aktiv))
                        flash("Träger angelegt.")
                    audit_log(conn, session["user"], "traeger_gespeichert", None, name[:60])
                else:
                    flash("Name und Prompt-Snippet sind nötig.")
            elif formular == "traeger_toggle":
                tid = request.form.get("id", "").strip()
                if tid.isdigit():
                    conn.execute("UPDATE traeger SET aktiv=1-aktiv WHERE id=?", (int(tid),))
                    flash("Träger geändert.")
            elif formular == "traeger_delete":
                tid = request.form.get("id", "").strip()
                if tid.isdigit():
                    conn.execute("DELETE FROM traeger WHERE id=?", (int(tid),))
                    audit_log(conn, session["user"], "traeger_geloescht", None, tid)
                    flash("Träger gelöscht.")
            elif formular == "bildstil_save":
                # #144: Bild-Stil-Topf (Mehrfach-Aktivierung). Je Stil ein An/Aus-Flag in den
                # Einstellungen (bild_stil_standard/_ki_tafel/_kreativ = '1'/'0'). Bei der
                # Beitrags-Erzeugung wird zufaellig aus den AKTIVEN Stilen gewaehlt (stilwahl).
                # Mindestens EINER muss aktiv bleiben: ist keiner angehakt, wird 'standard'
                # erzwungen (server-seitiger Fallback, nie ein leerer Topf).
                flags = {
                    "standard": "1" if request.form.get("stil_standard") else "0",
                    "ki_tafel": "1" if request.form.get("stil_ki_tafel") else "0",
                    "kreativ": "1" if request.form.get("stil_kreativ") else "0",
                }
                if "1" not in flags.values():
                    flags["standard"] = "1"   # Fallback: nie alle aus
                for stil, wert in flags.items():
                    conn.execute(
                        "INSERT INTO einstellungen(schluessel, wert) VALUES (?, ?) "
                        "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert",
                        ("bild_stil_%s" % stil, wert))
                _stil_label = {"standard": "Standard (v11)", "ki_tafel": "KI-Tafel (Testmodus)",
                               "kreativ": "Kreativ (kinoreifes Foto ohne Text)"}
                aktiv_namen = [_stil_label[s] for s in ("standard", "ki_tafel", "kreativ")
                               if flags[s] == "1"]
                audit_log(conn, session["user"], "bild_stil_topf_gesetzt", None, ", ".join(aktiv_namen))
                flash("Aktive Bild-Stile (Zufalls-Topf): %s." % ", ".join(aktiv_namen))
            elif formular == "bildtool_save":
                # Globales Bild-Tool (#137): 'openai' (Default) oder 'ideogram' (Text-Spezialist).
                # Orthogonal zum Bild-Stil; bestimmt nur, welche KI das Foto erzeugt.
                tool = request.form.get("bild_tool", "openai").strip().lower()
                if tool not in ("openai", "ideogram"):
                    tool = "openai"
                conn.execute(
                    "INSERT INTO einstellungen(schluessel, wert) VALUES ('bild_tool', ?) "
                    "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert", (tool,))
                audit_log(conn, session["user"], "bild_tool_gesetzt", None, tool)
                flash("Bild-Tool gespeichert: %s." % ("OpenAI" if tool == "openai" else "Ideogram"))
            elif formular == "bildmodell_save":
                # Globales OpenAI-Bild-Modell (#161): 'gpt-image-1' (Default/Standard) oder
                # 'gpt-image-2' (Test). Umschaltbar fuer den A/B-Vergleich am selben Beitrag; ein
                # Modellwechsel erzeugt frische Comic-Bilder (Modell-Praefix im Cache). Der Default
                # (gpt-image-1) aendert sich NICHT; unbekannte Werte fallen darauf zurueck.
                modell = request.form.get("bild_modell", "gpt-image-1").strip().lower()
                if modell not in ("gpt-image-1", "gpt-image-2"):
                    modell = "gpt-image-1"
                conn.execute(
                    "INSERT INTO einstellungen(schluessel, wert) VALUES ('bild_modell', ?) "
                    "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert", (modell,))
                audit_log(conn, session["user"], "bild_modell_gesetzt", None, modell)
                flash("Bild-Modell gespeichert: %s." % modell)
            elif formular == "finanzamt_bibel":
                # Globale Finanzamt-Bible (#151): optionaler Bild-Upload (Comic-/Stylesheet-Vorlage des
                # wiederkehrenden Finanzamt-Charakters) + Charakter-Beschreibung. Key/Value in
                # einstellungen (finanzamt_bibel_bild/finanzamt_bibel_text). Bild ueber PIL neu kodiert
                # und nach DATA_DIR/bibeln/finanzamt.png geschrieben; Auslieferung nur login-geschuetzt.
                fa_text = request.form.get("finanzamt_bibel_text", "").strip()
                conn.execute(
                    "INSERT INTO einstellungen(schluessel, wert) VALUES ('finanzamt_bibel_text', ?) "
                    "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert", (fa_text or None,))
                file = request.files.get("finanzamt_bibel_bild")
                if file and file.filename:
                    try:
                        from PIL import Image
                        bdir = os.path.join(DATA_DIR, "bibeln"); os.makedirs(bdir, exist_ok=True)
                        dest = os.path.join(bdir, "finanzamt.png")
                        img = Image.open(file.stream)
                        w, h = img.size
                        if w * h > 40_000_000:
                            raise ValueError("Bild zu gross")
                        img = img.convert("RGB")
                        gr = max(w, h)
                        if gr > 1536:
                            skala = 1536.0 / gr
                            img = img.resize((max(1, int(w*skala)), max(1, int(h*skala))), Image.LANCZOS)
                        img.save(dest)
                        conn.execute(
                            "INSERT INTO einstellungen(schluessel, wert) VALUES ('finanzamt_bibel_bild', ?) "
                            "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert", (dest,))
                        flash("Finanzamt-Bible (Bild und Beschreibung) gespeichert.")
                    except Exception:
                        log.exception("Finanzamt-Bible-Upload fehlgeschlagen")
                        flash("Finanzamt-Bible-Bild-Upload fehlgeschlagen – bitte eine gültige Bilddatei (max ~40 Megapixel) wählen.")
                else:
                    flash("Finanzamt-Beschreibung gespeichert.")
                audit_log(conn, session["user"], "finanzamt_bibel_gesetzt", None, "Bild=%s" % ("ja" if (file and file.filename) else "nein"))
            elif formular == "finanzamt_bibel_del":
                row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='finanzamt_bibel_bild'").fetchone()
                if row and row["wert"] and _under_bibeln(row["wert"]):
                    try:
                        os.remove(row["wert"])
                    except Exception:
                        pass
                conn.execute("UPDATE einstellungen SET wert=NULL WHERE schluessel='finanzamt_bibel_bild'")
                audit_log(conn, session["user"], "finanzamt_bibel_bild_entfernt", None, None)
                flash("Finanzamt-Bible-Bild entfernt.")
            elif formular == "cache_aufraeumen":
                # Manuelles, sicheres Aufraeumen des KI-Foto-Caches (#134): loescht nur verwaiste,
                # alte motive/-PNGs - aktive/Pool-Fotos und icon_-Dateien bleiben.
                import wartung
                try:
                    n, frei = wartung.aufraeumen_motive(conn)
                    audit_log(conn, session["user"], "cache_aufgeraeumt", None,
                              "%d Foto(s), %d Bytes" % (n, frei))
                    flash("%d Foto(s) geloescht, %s frei." % (n, wartung.menschlich(frei)))
                except Exception as ex:
                    log.exception("Cache-Aufraeumung (manuell) fehlgeschlagen")
                    flash("Aufraeumen fehlgeschlagen: %s" % ex)
            conn.commit()
            # PRG: zurueck zum passenden Bereich (kein erneutes Absenden bei Reload)
            ziel = {"benutzer": "benutzer", "stelle": "stellen", "anlass": "anlass",
                    "wissen": "wissen", "schauplatz": "schauplatz", "traeger": "traeger",
                    "bildstil": "bildstil",
                    "bildtool": "bildstil", "bildmodell": "bildstil", "finanzamt": "bildstil",
                    "cache": "speicher"}.get((formular or "").split("_")[0])
            return redirect(url_for("verwaltung", bereich=ziel) if ziel else url_for("verwaltung"))
        if not bereich:
            return render_template_string(VERWALTUNG_HOME, **_ctx())
        bereich_titel = {"benutzer": "Benutzer", "stellen": "Beratungsstellen",
                         "anlass": "Anlass-Tage", "wissen": "Wissens-Serie",
                         "schauplatz": "Schauplätze", "traeger": "Träger",
                         "bildstil": "Bild-Stil", "speicher": "Speicher"}.get(bereich)
        if not bereich_titel:
            return redirect(url_for("verwaltung"))
        users = conn.execute("SELECT name, rolle, aktiv FROM benutzer ORDER BY name").fetchall()
        stellen = conn.execute("SELECT * FROM beratungsstellen ORDER BY ort").fetchall()
        anlasstage = conn.execute("SELECT datum, anlass, steuer_hook, aktiv FROM anlasstage ORDER BY datum").fetchall()
        wissen = conn.execute("SELECT titel, hook, aktiv FROM wissensthemen ORDER BY titel").fetchall()
        # #140: Schauplaetze nach Jahreszeit (Reihenfolge fruehling->sommer->herbst->winter), dann id.
        schauplaetze = conn.execute(
            "SELECT id, beschreibung, jahreszeit, aktiv FROM schauplaetze "
            "ORDER BY CASE jahreszeit WHEN 'fruehling' THEN 1 WHEN 'sommer' THEN 2 "
            "WHEN 'herbst' THEN 3 WHEN 'winter' THEN 4 ELSE 5 END, id").fetchall()
        # #142: Traeger nach id (Seed-Reihenfolge). Robust gegen alte DBs ohne Tabelle.
        try:
            traeger = conn.execute(
                "SELECT id, name, prompt_snippet, aktiv FROM traeger ORDER BY id").fetchall()
        except Exception:
            traeger = []
        # #144: Drei An/Aus-Flags fuer den Bild-Stil-Topf (Default aktiv: fehlt der Schluessel oder
        # steht nicht auf '0', ist der Stil im Topf). Steuern die Zufallswahl pro Beitrag.
        def _stil_aktiv(stil):
            r = conn.execute("SELECT wert FROM einstellungen WHERE schluessel=?",
                             ("bild_stil_%s" % stil,)).fetchone()
            return (r is None) or (str(r["wert"]).strip() != "0")
        stil_standard = _stil_aktiv("standard")
        stil_ki_tafel = _stil_aktiv("ki_tafel")
        stil_kreativ = _stil_aktiv("kreativ")
        _bt = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='bild_tool'").fetchone()
        bild_tool = (_bt["wert"] if _bt and _bt["wert"] else "openai")
        # OpenAI-Bild-Modell (#161): aktueller Stand fuers Dropdown. Unbekannt/leer -> Standard.
        _bm = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='bild_modell'").fetchone()
        bild_modell = (_bm["wert"] if _bm and _bm["wert"] in ("gpt-image-1", "gpt-image-2") else "gpt-image-1")
        # Globale Finanzamt-Bible (#151): aktueller Stand fuer die Anzeige im Bild-Stil-Bereich.
        _fab = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='finanzamt_bibel_bild'").fetchone()
        finanzamt_bibel_bild = (_fab["wert"] if _fab and _fab["wert"] else "")
        _fat = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='finanzamt_bibel_text'").fetchone()
        finanzamt_bibel_text = (_fat["wert"] if _fat and _fat["wert"] else "")
    pages, pages_err = (_pages() if bereich == "stellen" else ([], None))
    page_id_set = {str(p["id"]) for p in pages}
    fb_name = {str(p["id"]): p["name"] for p in pages}
    # WhatsApp-Verbindung je Stelle direkt in der Beratungsstellen-Verwaltung (#alles-an-einem-Ort).
    # NUR im Stellen-Bereich, NUR fuer aktive Stellen, kurzer Timeout und komplett fehlertolerant:
    # ist der Node-/Baileys-Dienst aus, merken wir EINEN wa_dienst_err und zeigen die Stelle als
    # "nicht_verbunden" - die Verwaltung darf davon NIE brechen.
    wa_dienst_err = None
    any_wa_pending = False
    if bereich == "stellen":
        stellen_mit_wa = []
        for r in stellen:
            b = dict(r)
            wa = {"state": "nicht_verbunden", "qr": None, "me": None, "error": None, "contacts": 0}
            if r["aktiv"]:
                try:
                    st, err = _wa_call("/status", session=r["id"], timeout=4)
                    if err:
                        if wa_dienst_err is None:
                            wa_dienst_err = err
                    elif st:
                        wa = st
                except Exception as e:  # noqa: BLE001 - Verwaltung robust halten
                    if wa_dienst_err is None:
                        wa_dienst_err = str(e)
            b["wa"] = wa
            if wa.get("state") in ("qr", "init", "closed"):
                any_wa_pending = True
            stellen_mit_wa.append(b)
        stellen = stellen_mit_wa
    # Speicher-Status (#134): Foto-Cache-Groesse + freier Plattenplatz, menschenlesbar.
    speicher = {"schonfrist_tage": 14, "motive_lesbar": "", "frei_lesbar": "",
                "gesamt_lesbar": "", "speicher_warnung": False}
    if bereich == "speicher":
        import wartung
        frei, gesamt = wartung.freier_speicher(DATA_DIR)
        speicher = {
            "schonfrist_tage": 14,
            "motive_lesbar": wartung.menschlich(wartung.motive_ordner_groesse()),
            "frei_lesbar": wartung.menschlich(frei),
            "gesamt_lesbar": wartung.menschlich(gesamt),
            "speicher_warnung": bool(frei and frei < 1024 * 1024 * 1024),  # < 1 GB
        }
    return render_template_string(VERWALTUNG, **_ctx(users=users, stellen=stellen, anlasstage=anlasstage,
                                                     wissen=wissen, schauplaetze=schauplaetze,
                                                     traeger=traeger,
                                                     bereich=bereich, bereich_titel=bereich_titel,
                                                     pages=pages, pages_err=pages_err, page_id_set=page_id_set,
                                                     fb_name=fb_name,
                                                     stil_standard=stil_standard,
                                                     stil_ki_tafel=stil_ki_tafel,
                                                     stil_kreativ=stil_kreativ,
                                                     wa_dienst_err=wa_dienst_err,
                                                     any_wa_pending=any_wa_pending,
                                                     bild_tool=bild_tool,
                                                     bild_modell=bild_modell,
                                                     finanzamt_bibel_bild=finanzamt_bibel_bild,
                                                     finanzamt_bibel_text=finanzamt_bibel_text,
                                                     **speicher))

@app.route("/logo.png")
def logo():
    p = os.path.join(BASE_DIR, "assets", "hilo_logo.png")
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png")

@app.route("/fonts/<path:fname>")
def serve_font(fname):
    # Public (KEIN @login_required): self-hosted BSt-Next-Fonts, read-only, nur validierte .woff2.
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9._-]+\.woff2", fname):
        abort(404)
    p = os.path.join(BASE_DIR, "assets", "fonts", fname)
    if not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="font/woff2", max_age=31536000)

@app.route("/portrait/<int:sid>")
@login_required
def portrait(sid):
    with get_conn() as conn:
        row = conn.execute("SELECT portrait_pfad FROM beratungsstellen WHERE id=?", (sid,)).fetchone()
    if (not row or not row["portrait_pfad"] or not _under_portraits(row["portrait_pfad"])
            or not os.path.exists(row["portrait_pfad"])):
        abort(404)
    return send_file(row["portrait_pfad"], mimetype="image/png")

@app.route("/berater-comic/<int:stelleid>", methods=["POST"])
@admin_required
def berater_comic_erzeugen(stelleid):
    """Erzeugt (oder erneuert) das Comic-Portrait der Leitung aus dem vorhandenen Leitungs-Foto
    (portrait_pfad) der Stelle. Rolle wie die uebrige Beratungsstellen-Verwaltung (admin).
    Ohne Foto -> flash-Hinweis. Ergebnis wird nach DATA_DIR/berater/comic_<id>.png geschrieben und
    in berater_comic hinterlegt. Erneutes Erzeugen ueberschreibt die alte Datei."""
    import bildmotiv
    with get_conn() as conn:
        row = conn.execute("SELECT portrait_pfad FROM beratungsstellen WHERE id=?", (stelleid,)).fetchone()
        if not row:
            abort(404)
        foto = row["portrait_pfad"]
        if not foto or not _under_portraits(foto) or not os.path.exists(foto):
            flash("Für diese Stelle ist noch kein Leitungs-Foto (Porträt) hinterlegt – bitte erst oben ein Porträt hochladen.")
            return redirect(url_for("verwaltung", bereich="stellen"))
        pfad = bildmotiv.erzeuge_berater_comic(foto)
        if pfad and _under_berater(pfad) and os.path.exists(pfad):
            conn.execute("UPDATE beratungsstellen SET berater_comic=? WHERE id=?", (pfad, stelleid))
            audit_log(conn, session["user"], "beratungsstelle_berater_comic_erzeugt", None, "Stelle %s" % stelleid)
            flash("Comic-Berater erzeugt – Vorschau erscheint unten.")
        else:
            flash("Comic-Berater konnte nicht erzeugt werden (kein API-Zugang oder Bild-Fehler). Bitte später erneut versuchen.")
    return redirect(url_for("verwaltung", bereich="stellen"))

@app.route("/berater-comic-bild/<int:stelleid>")
@login_required
def berater_comic_bild(stelleid):
    """Liefert das Comic-Portrait der Leitung aus (login-geschützt – echtes Gesicht, DSGVO, NICHT
    public). Analog zur Portrait-Route: Pfad-Guard (_under_berater) gegen manipulierte DB-Werte."""
    with get_conn() as conn:
        row = conn.execute("SELECT berater_comic FROM beratungsstellen WHERE id=?", (stelleid,)).fetchone()
    if (not row or not row["berater_comic"] or not _under_berater(row["berater_comic"])
            or not os.path.exists(row["berater_comic"])):
        abort(404)
    return send_file(row["berater_comic"], mimetype="image/png", max_age=0)

@app.route("/bibel-bild/<int:stelleid>")
@login_required
def bibel_bild(stelleid):
    """Liefert die Character-Bible / Comic-Vorlage einer Stelle aus (login-geschützt – kann echte
    Personen als Comic zeigen, DSGVO; #151). Pfad-Guard (_under_bibeln) gegen manipulierte DB-Werte."""
    with get_conn() as conn:
        row = conn.execute("SELECT bibel_bild FROM beratungsstellen WHERE id=?", (stelleid,)).fetchone()
    if (not row or not row["bibel_bild"] or not _under_bibeln(row["bibel_bild"])
            or not os.path.exists(row["bibel_bild"])):
        abort(404)
    return send_file(row["bibel_bild"], mimetype="image/png", max_age=0)

@app.route("/finanzamt-bibel-bild")
@login_required
def finanzamt_bibel_bild():
    """Liefert die globale Finanzamt-Bible aus (login-geschützt; #151). Pfad-Guard (_under_bibeln)
    gegen manipulierte Einstellungs-Werte."""
    with get_conn() as conn:
        row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='finanzamt_bibel_bild'").fetchone()
    p = row["wert"] if row and row["wert"] else None
    if not p or not _under_bibeln(p) or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png", max_age=0)

# --- WhatsApp (Baileys-Dienst auf demselben Host, nur localhost) -------------
def _wa_call(path, method="GET", payload=None, timeout=6, session=None):
    """Ruft die lokale HTTP-API des Node-/Baileys-Dienstes auf. Gibt (daten, fehler) zurueck.
    Mit 'session' (Multi-Session, i.d.R. die Beratungsstellen-ID) wird die WhatsApp-Verbindung
    genau dieser Stelle angesprochen: bei GET als ?session=..., sonst im JSON-Body."""
    import urllib.request, urllib.error, urllib.parse
    url = WHATSAPP_URL.rstrip("/") + path
    if session is not None:
        if method == "GET":
            sep = "&" if "?" in url else "?"
            url += "%ssession=%s" % (sep, urllib.parse.quote(str(session)))
        else:
            payload = dict(payload or {}); payload["session"] = str(session)
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

WHATSAPP = """<!doctype html><meta charset=utf-8><title>ShareNext - WhatsApp</title>
{% if any_pending %}<meta http-equiv=refresh content=6>{% endif %}
<style>""" + _TOP + """
.wrap{max-width:760px;margin:0 auto}
.card{background:#fff;border-radius:14px;box-shadow:0 6px 18px rgba(0,0,0,.08);padding:20px;margin:0 auto 16px}
.qr{text-align:center}.qr img{width:300px;height:300px;border:1px solid #e2e8f0;border-radius:10px}
.ok{color:#4D7C0F;font-weight:bold}.bad{color:#b00020;font-weight:bold}
.step{color:#475569;font-size:14px}
label{display:block;margin:8px 0 3px;font-weight:bold;font-size:14px}
input[type=text]{width:100%;box-sizing:border-box;padding:9px;border:1px solid #ccd3df;border-radius:8px}
button{background:#0B2545;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-weight:bold;cursor:pointer;margin-top:8px}
button.g{background:#4D7C0F}button.r{background:#b00020}
.muted{color:#6b7280;font-size:13px}</style>
""" + _NAV + """
<div style="max-width:760px;margin:0 auto 10px"><div class=top><h2 style="margin:0;color:#0B2545">WhatsApp</h2><a href="/">&larr; Startseite</a></div></div>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash style="max-width:760px">{{m[0]}}</div>{% endif %}{% endwith %}
<div class=wrap>
{% if dienst_err %}
  <div class=card><p class=bad>WhatsApp-Dienst nicht erreichbar.</p>
  <p class=muted>{{dienst_err}}</p>
  <p class=step>Der WhatsApp-Dienst (Node/Baileys) läuft noch nicht. Bitte einmalig auf dem Pi einrichten (siehe <code>whatsapp/README.md</code>) und den Dienst starten.</p></div>
{% endif %}
<div class=card><p class=step>Verbinde je Beratungsstelle deren <b>eigene WhatsApp-Nummer</b> (Handy der Stelle). Danach postet jede Stelle ihren <b>eigenen Status</b> an ihre eigenen Kontakte; auch der WhatsApp-Kanal wird über die Nummer der Stelle bespielt.</p></div>
{% for s in stellen %}
<div class=card>
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div><b>{{s.name}}</b> <span class=muted>· {{s.ort}}</span>{% if not s.status_aktiv %} <span class=muted>(Status in der Verwaltung nicht aktiviert)</span>{% endif %}</div>
    <div>{% if s.wa.state == 'connected' %}<span class=ok>&#x2705; verbunden</span>{% elif s.wa.state == 'qr' %}<span class=step>QR bereit</span>{% else %}<span class=muted>nicht verbunden</span>{% endif %}</div>
  </div>
  {% if s.wa.state == 'connected' %}
    <p class=muted>Nummer: <code>{{s.wa.me or '—'}}</code> · Kontakte: <b>{{s.wa.contacts}}</b></p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
      <form method=post action="/whatsapp/test-status/{{s.id}}" style="flex:1;min-width:240px">
        <input type=text name=empfaenger placeholder="Test-Nummer (optional, z. B. 49160…)">
        <label class=step style="font-weight:normal;margin:6px 0"><input type=checkbox name=to_contacts value="1"> an alle Kontakte (sonst nur an die Test-Nummer bzw. die eigene Nummer)</label>
        <button class=g>Test-Status senden</button></form>
      <form method=post action="/whatsapp/logout/{{s.id}}" onsubmit="return confirm('Verbindung dieser Stelle trennen? Du musst danach neu scannen.')"><button class=r>Trennen</button></form>
    </div>
  {% elif s.wa.state == 'qr' and s.wa.qr %}
    <div class=qr><img src="{{s.wa.qr}}" alt="WhatsApp QR"></div>
    <ol class=step style="text-align:left;max-width:440px;margin:12px auto">
      <li>WhatsApp auf dem Handy <b>dieser Stelle</b> öffnen</li>
      <li>Einstellungen &rarr; <b>Verknüpfte Geräte</b> &rarr; <b>Gerät verknüpfen</b></li>
      <li>Diesen QR-Code scannen</li></ol>
    <p class=muted>Die Seite aktualisiert sich automatisch.</p>
  {% else %}
    <form method=post action="/whatsapp/connect/{{s.id}}"><button>Verbinden (QR anzeigen)</button></form>
    {% if s.wa.state in ['init','closed'] %}<p class=muted>Verbindung wird aufgebaut&hellip;{% if s.wa.error %} ({{s.wa.error}}){% endif %}</p>{% endif %}
  {% endif %}
</div>
{% else %}
<div class=card><p class=step>Noch keine aktiven Beratungsstellen. Lege zuerst unter <a href="/verwaltung?bereich=stellen">Verwaltung &rarr; Beratungsstellen</a> welche an.</p></div>
{% endfor %}
</div>"""

@app.route("/whatsapp")
@login_required
def whatsapp():
    """Multi-Session-Uebersicht: je aktiver Beratungsstelle eine eigene WhatsApp-Verbindung
    (eigene Nummer -> eigener Status an eigene Kontakte). session-Schluessel = Beratungsstellen-ID."""
    dienst_err = None
    stellen = []
    any_pending = False
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, ort, wa_status_aktiv FROM beratungsstellen "
                            "WHERE aktiv=1 ORDER BY ort").fetchall()
    for r in rows:
        st, err = _wa_call("/status", session=r["id"], timeout=6)
        if err and dienst_err is None:
            dienst_err = err
        wa = st or {"state": "nicht_verbunden", "qr": None, "me": None, "error": None, "contacts": 0}
        if wa.get("state") in ("qr", "init", "closed"):
            any_pending = True
        stellen.append({"id": r["id"], "name": r["name"], "ort": r["ort"],
                        "status_aktiv": bool(r["wa_status_aktiv"]), "wa": wa})
    return render_template_string(WHATSAPP, **_ctx(stellen=stellen, dienst_err=dienst_err,
                                                   any_pending=any_pending))

def _wa_zurueck():
    """Ziel nach Verbinden/Trennen: zurueck zur Beratungsstellen-Verwaltung, wenn das Formular
    von dort kam (hidden zurueck=verwaltung), sonst zur bestehenden /whatsapp-Uebersicht."""
    if request.form.get("zurueck") == "verwaltung":
        return redirect(url_for("verwaltung", bereich="stellen"))
    return redirect(url_for("whatsapp"))

@app.route("/whatsapp/connect/<int:sid>", methods=["POST"])
@login_required
def whatsapp_connect(sid):
    res, err = _wa_call("/connect", method="POST", payload={}, session=sid, timeout=15)
    if err:
        flash("WhatsApp-Dienst nicht erreichbar: " + err)
    else:
        audit_log_safe("whatsapp_connect")
        flash("Verbindung wird aufgebaut - der QR-Code erscheint gleich. Scanne ihn mit dem Handy dieser Stelle.")
    return _wa_zurueck()

@app.route("/whatsapp/logout/<int:sid>", methods=["POST"])
@login_required
def whatsapp_logout(sid):
    _wa_call("/logout", method="POST", payload={}, session=sid)
    audit_log_safe("whatsapp_logout")
    flash("WhatsApp-Verbindung dieser Stelle getrennt.")
    return _wa_zurueck()

@app.route("/whatsapp/test-status/<int:sid>", methods=["POST"])
@login_required
def whatsapp_test_status(sid):
    import re
    caption = request.form.get("caption", "").strip() or "ShareNext Test-Status"
    to_contacts = bool(request.form.get("to_contacts"))
    payload = {"caption": caption, "toContacts": to_contacts}
    # Optionale Test-Empfaenger-Nummer -> WhatsApp-JID (deutsche 0... -> 49...)
    digits = re.sub(r"\D", "", request.form.get("empfaenger", ""))
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    if digits:
        payload["statusJidList"] = [digits + "@s.whatsapp.net"]
    res, err = _wa_call("/post-status", method="POST", payload=payload, timeout=30, session=sid)
    if err:
        flash("Fehler: " + err)
    elif res and res.get("error"):
        flash("WhatsApp: " + res["error"])
    else:
        n = res.get("recipients") if res else None
        flash("Test-Status gesendet%s." % ((" (an %d Empfaenger)" % n) if n else ""))
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
    threading.Thread(target=_pool_scheduler, daemon=True).start()      # Taegliche Auto-Ziehung aus dem Topf (#126)
    threading.Thread(target=_cache_cleanup_scheduler, daemon=True).start()  # Taegliches Cache-Aufraeumen (#134)
    port = int(port or os.environ.get("HILO_DASHBOARD_PORT", "8530"))
    app.run(host=host, port=port, threaded=True)
