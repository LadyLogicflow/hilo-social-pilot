# -*- coding: utf-8 -*-
"""Einstiegspunkt des HILO-Piloten."""
import argparse, os
from logging_setup import setup_logging
from db import init_db
import radar, textgen, bildgen

log = setup_logging()

def daily_run():
    log.info("HILO-Pilot Tageslauf gestartet.")
    anzahl = radar.run()
    log.info("Tageslauf: %s neue Themen aus dem Radar.", anzahl)
    limit = int(os.environ.get("HILO_GENERATE_LIMIT", "3"))
    erzeugt = textgen.generate_drafts(limit=limit, kanal="google")
    log.info("Tageslauf: %s neue Textentwuerfe erzeugt.", erzeugt)
    bilder = bildgen.render_drafts()
    log.info("Tageslauf: %s Bilder erzeugt.", bilder)
    log.info("HILO-Pilot Tageslauf beendet.")

def add_user(name):
    import getpass
    from werkzeug.security import generate_password_hash
    from db import get_conn
    pw = getpass.getpass("Passwort fuer '%s' (verdeckt): " % name)
    pw2 = getpass.getpass("Passwort wiederholen: ")
    if not pw or pw != pw2:
        log.warning("Passwoerter leer oder ungleich - abgebrochen."); return
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO benutzer(name, passwort_hash, rolle, aktiv) "
                     "VALUES (?,?, 'admin', 1)", (name, generate_password_hash(pw, method="pbkdf2:sha256")))
    log.info("Benutzer '%s' angelegt/aktualisiert.", name)

def main():
    p = argparse.ArgumentParser(description="HILO Social-Media-Pilot")
    p.add_argument("--init-db", action="store_true", help="Datenbank anlegen/aktualisieren")
    p.add_argument("--once", action="store_true", help="Tageslauf: Radar + Text + Bild")
    p.add_argument("--generate", type=int, metavar="N", help="Bis zu N Textentwuerfe erzeugen")
    p.add_argument("--generate-ids", metavar="IDS", dest="generate_ids",
                   help="Textentwuerfe nur fuer diese Thema-IDs erzeugen (kommagetrennt, z.B. 12,15,17)")
    p.add_argument("--regenerate-drafts", action="store_true", dest="regenerate_drafts",
                   help="Alle noch nicht freigegebenen Entwuerfe nach aktuellen Vorgaben neu erzeugen")
    p.add_argument("--render", action="store_true", help="Fehlende Bilder fuer Entwuerfe erzeugen")
    p.add_argument("--serve", action="store_true", help="Freigabe-Dashboard starten (Webserver)")
    p.add_argument("--port", type=int, help="Port fuer das Dashboard (Standard 8530)")
    p.add_argument("--add-user", metavar="NAME", help="Dashboard-Benutzer anlegen (Passwort verdeckt)")
    p.add_argument("--add-pdf", metavar="PFAD", help="Eigene Quelle: PDF-Datei aufnehmen")
    p.add_argument("--add-url", metavar="URL", help="Eigene Quelle: Link aufnehmen")
    p.add_argument("--set-secret", metavar="NAME", help="Geheimnis sicher setzen (verdeckte Eingabe)")
    p.add_argument("--radar", action="store_true", help="Nur Themen-Radar laufen lassen (Stufe 1, ohne Text/Bild)")
    p.add_argument("--daily", action="store_true", help="Taeglicher Lauf: Radar + faellige Fristen-Countdowns + Bilder")
    p.add_argument("--countdowns", action="store_true", help="Nur faellige Fristen-Countdowns erzeugen")
    p.add_argument("--list-pages", action="store_true", help="Verbundene Facebook-Seiten + IG-Konten anzeigen")
    p.add_argument("--publish", type=int, metavar="ENTWURF_ID", help="Freigegebenen Entwurf veroeffentlichen")
    p.add_argument("--page", metavar="PAGE_ID", help="Ziel-Facebook-Seite fuer --publish")
    p.add_argument("--test-upload", action="store_true",
                   help="Test: ein Bild per SFTP hochladen und die oeffentliche URL anzeigen (fuer Instagram)")
    p.add_argument("--extend-token", action="store_true",
                   help="Meta-Token in einen Langzeit-Token (~60 Tage) tauschen (braucht meta_app_id + meta_app_secret)")
    args = p.parse_args()

    if args.extend_token:
        import publish
        try:
            if publish.ensure_long_lived():
                log.info("Langzeit-Token (~60 Tage) erzeugt und gespeichert.")
            else:
                log.info("Kein Tausch durchgefuehrt - meta_app_id/meta_app_secret fehlen oder der "
                         "Tausch war nicht moeglich (Token gueltig?).")
        except Exception as ex:
            log.error("Token-Verlaengerung fehlgeschlagen: %s", ex)
        return

    if args.test_upload:
        import uploader, tempfile
        if not uploader.configured():
            log.error("Upload nicht konfiguriert. Bitte zuerst setzen (verdeckt): "
                      "--set-secret ionos_sftp_host / ionos_sftp_user / ionos_sftp_password / "
                      "ionos_public_base_url (optional ionos_sftp_dir, ionos_sftp_port).")
            return
        testfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "hilo_logo.png")
        if not os.path.exists(testfile):
            from PIL import Image
            testfile = os.path.join(tempfile.gettempdir(), "hisome_upload_test.png")
            Image.new("RGB", (16, 16), (31, 66, 141)).save(testfile)
        try:
            url = uploader.upload(testfile, remote_name="hisome_upload_test.png")
            log.info("Upload OK. Oeffentliche URL (bitte im Browser oeffnen zum Pruefen): %s", url)
        except Exception as ex:
            log.error("Upload fehlgeschlagen: %s", ex)
        return

    if args.set_secret:
        import getpass, secrets_store
        wert = getpass.getpass("Wert fuer '%s' (Eingabe ist unsichtbar): " % args.set_secret).strip()
        if not wert:
            log.warning("Kein Wert eingegeben - abgebrochen."); return
        secrets_store.set_secret(args.set_secret, wert)
        log.info("Geheimnis '%s' gespeichert (secrets.json, chmod 600).", args.set_secret); return

    if args.list_pages:
        import publish
        try:
            for pg in publish.list_pages():
                ig = ("@%s" % pg["ig_username"]) if pg.get("ig_username") else "(kein IG verknuepft)"
                log.info("Seite: %s | id=%s | Instagram: %s", pg["name"], pg["id"], ig)
        except Exception as ex:
            log.error("Seiten konnten nicht geladen werden: %s", ex)
        return

    if args.publish is not None:
        import json as _json, publish
        from db import get_conn, audit_log
        init_db()
        if not args.page:
            log.error("Bitte Ziel-Seite angeben: --publish %s --page <PAGE_ID>", args.publish); return
        with get_conn() as conn:
            e = conn.execute("SELECT * FROM entwuerfe WHERE id=?", (args.publish,)).fetchone()
            if not e:
                log.error("Entwurf %s nicht gefunden.", args.publish); return
            if e["status"] != "freigegeben":
                log.warning("Entwurf %s ist nicht freigegeben (Status: %s).", args.publish, e["status"])
            try:
                f = _json.loads(e["text"])
            except Exception:
                f = {}
            caption = f.get("caption") or f.get("ueberschrift") or ""
            if not e["bild_pfad"] or not os.path.exists(e["bild_pfad"]):
                log.error("Kein Bild fuer Entwurf %s vorhanden.", args.publish); return
            ok, info = publish.publish_facebook(args.page, e["bild_pfad"], caption)
            if ok:
                conn.execute("INSERT INTO posts(entwurf_id, kanal, plattform_post_id, "
                             "veroeffentlicht_am, status) VALUES (?,?,?,datetime('now'),'veroeffentlicht')",
                             (args.publish, "facebook", info))
                conn.execute("UPDATE entwuerfe SET status='veroeffentlicht' WHERE id=?", (args.publish,))
                audit_log(conn, "cli", "veroeffentlicht_facebook", args.publish, str(info))
                conn.commit()
                log.info("Entwurf %s auf Facebook veroeffentlicht (Post-ID: %s).", args.publish, info)
            else:
                conn.execute("INSERT INTO posts(entwurf_id, kanal, status, fehler) VALUES (?,?,?,?)",
                             (args.publish, "facebook", "fehler", info))
                conn.commit()
                log.error("Veroeffentlichung fehlgeschlagen: %s", info)
        return

    if (args.init_db or args.once or args.generate is not None or args.generate_ids is not None
            or args.regenerate_drafts or args.render or args.add_pdf or args.add_url or args.add_user
            or args.serve or args.radar or args.daily or args.countdowns):
        init_db()
    if args.radar:
        neu = radar.run()
        log.info("Themen-Radar: %s neue Themen eingesammelt (Stufe 1). "
                 "Auswahl im Dashboard unter 'Themen (Stufe 1)'.", neu); return
    if args.countdowns:
        import fristen
        log.info("%s Fristen-Countdown(s) erzeugt.", fristen.erzeuge_countdowns())
        bildgen.render_drafts(); return
    if args.daily:
        import fristen, anlass, wissen
        neu = radar.run()
        cd = fristen.erzeuge_countdowns()
        an = anlass.erzeuge_anlass_posts()
        wi = wissen.auffuellen()
        bildgen.render_drafts()
        log.info("Tageslauf: %s neue Themen, %s Countdown(s), %s Anlass, %s Wissens-Beitrag.",
                 neu, cd, an, wi); return
    if args.add_user:
        add_user(args.add_user); return
    if args.init_db:
        log.info("Datenbank initialisiert.")
    if args.add_pdf:
        import ingest; ingest.add_pdf(args.add_pdf)
    if args.add_url:
        import ingest; ingest.add_url(args.add_url)
    if args.generate is not None:
        log.info("%s Textentwuerfe erzeugt.", textgen.generate_drafts(limit=args.generate, kanal="google"))
    if args.generate_ids is not None:
        ids = [x.strip() for x in args.generate_ids.split(",") if x.strip()]
        log.info("%s Textentwuerfe erzeugt (Auswahl von %d Themen).",
                 textgen.generate_for_ids(ids, kanal="google"), len(ids))
    if args.regenerate_drafts:
        log.info("%s Entwuerfe nach aktuellen Vorgaben neu erzeugt.", textgen.regenerate_open_drafts())
    if args.render:
        log.info("%s Bilder erzeugt.", bildgen.render_drafts())
    if args.once:
        daily_run()
    if args.serve:
        from web import serve
        port = args.port or int(os.environ.get("HILO_DASHBOARD_PORT", "8530"))
        log.info("Dashboard startet auf Port %s (Strg+C zum Beenden) ...", port)
        serve(port=port)
    if not (args.init_db or args.once or args.generate is not None or args.render
            or args.add_pdf or args.add_url or args.serve):
        p.print_help()

if __name__ == "__main__":
    main()
