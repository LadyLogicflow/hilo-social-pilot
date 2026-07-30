# -*- coding: utf-8 -*-
"""Fristen-Countdown: erzeugt rechtzeitig Erinnerungs-Beitraege vor Abgabefristen.

Staffelung der Haeufigkeit:
  - ab 3 Monaten vor der Frist: 1x pro Woche (dienstags)
  - in den letzten 4 Wochen:    2x pro Woche (dienstags + donnerstags)
  - in der letzten Woche:        taeglich (nur Frist mit daily_last_week)
Nur an Werktagen (Mo-Fr). Texte sind faktentreu vorformuliert (kein KI-Token noetig).
"""
import datetime, hashlib, json, logging

log = logging.getLogger("hilo.fristen")

# Abgabefristen fuer die Steuererklaerung 2025 (Anzeige-Texte mit echten Umlauten)
FRISTEN = [
    {"name": "Steuererklärung 2025 – ohne Berater", "datum": "2026-07-31",
     "art": "self", "daily_last_week": True},
    # 28.02.2027 ist ein Sonntag -> Fristende 01.03.2027
    {"name": "Steuererklärung 2025 – HILO-Mitglieder", "datum": "2027-03-01",
     "art": "member", "daily_last_week": False},
]

MITGLIED_HINWEIS = ("Mit einer neuen HILO-Mitgliedschaft verlängert sich die Abgabefrist "
                    "automatisch bis zum 01.03.2027.")
VERSPAETUNG_HINWEIS = ("Wird die Frist versäumt, fällt ein Verspätungszuschlag von mindestens "
                       "25 Euro pro angefangenem Monat an.")
# Mitglieder muessen ihre Unterlagen mind. 6 Wochen vor Fristende einreichen
UNTERLAGEN_WOCHEN = 6

def _frist_datum(frist):
    return datetime.date.fromisoformat(frist["datum"])

def _de(d):
    return "%02d.%02d.%04d" % (d.day, d.month, d.year)

def faellig_heute(frist, heute):
    """Gibt (faellig: bool, resttage: int) zurueck - ist heute ein Countdown-Tag?"""
    rest = (_frist_datum(frist) - heute).days
    if rest <= 0:
        return False, rest
    if heute.weekday() >= 5:          # Samstag/Sonntag: keine Posts
        return False, rest
    if rest <= 7 and frist["daily_last_week"]:
        return True, rest             # letzte Woche: taeglich (Werktage)
    if rest <= 28:
        return heute.weekday() in (1, 3), rest   # letzte 4 Wochen: Di + Do
    if rest <= 92:
        return heute.weekday() == 1, rest        # ab 3 Monaten: dienstags
    return False, rest

def _rest_text(rest):
    if rest >= 14:
        return "Noch %d Wochen" % (rest // 7)
    if rest == 1:
        return "Nur noch 1 Tag"
    return "Nur noch %d Tage" % rest

ICONS = ["kalender", "wecker", "sanduhr"]   # rotieren pro Beitrag

def _icon(heute):
    return "icon:" + ICONS[heute.toordinal() % len(ICONS)]

def _post_fields(frist, rest, heute):
    d = _frist_datum(frist)
    rt = _rest_text(rest)
    if frist["art"] == "self":
        return {
            "ueberschrift": "%s bis zum Fristende" % rt,
            "subline": "Fristende Steuererklärung 2025: %s" % _de(d),
            "bullets": ["Fristende: %s" % _de(d), "Verspätungszuschlag ab 25 €/Monat", "Mitglied werden = mehr Zeit"],
            "cta": "Jetzt Termin bei Ihrer HILO-Beratungsstelle sichern",
            "slogan": "Wir sind HILO",
            "bild_motiv": _icon(heute),
            "caption": ("Das Fristende für die Steuererklärung 2025 ist der %s – %s! Wer die Frist "
                        "versäumt, zahlt einen Verspätungszuschlag von mindestens 25 Euro pro angefangenem "
                        "Monat. %s Vereinbaren Sie jetzt einen Termin bei Ihrer HILO-Beratungsstelle."
                        % (_de(d), rt.lower(), MITGLIED_HINWEIS)),
        }
    einreich = d - datetime.timedelta(weeks=UNTERLAGEN_WOCHEN)
    return {
        "ueberschrift": "%s bis zum Fristende" % rt,
        "subline": "Als HILO-Mitglied: %s" % _de(d),
        "bullets": ["Fristende: %s" % _de(d), "Unterlagen bis %s" % _de(einreich), "Termin jetzt sichern"],
        "cta": "Jetzt Beratungstermin vereinbaren",
        "slogan": "Wir sind HILO",
        "bild_motiv": _icon(heute),
        "caption": ("Als Mitglied im HILO Lohnsteuerhilfeverein haben Sie für die Steuererklärung 2025 "
                    "bis zum %s Zeit. Damit wir fristgerecht bearbeiten können, müssen Ihre Unterlagen "
                    "mindestens %d Wochen vor Fristende bei uns sein – bitte bis spätestens %s. "
                    "Sichern Sie sich rechtzeitig Ihren Beratungstermin."
                    % (_de(d), UNTERLAGEN_WOCHEN, _de(einreich))),
    }

def erzeuge_countdowns(heute=None):
    """Legt fuer heute faellige Countdown-Beitraege als Entwurf an (Stufe 2, auf den Tag geplant).
    Maximal 1 pro Tag (die dringlichste Frist). Idempotent (Dublettenschutz via hash).

    Bild: KI-generiertes Motiv statt statischem Icon (Art-Director-Stufe, kampagne.py) - der
    Text selbst bleibt UNVERAENDERT hart vorformuliert (_post_fields), nur das visuelle Konzept
    kommt von GPT-5.6 Terra + GPT Image 2. Rechtlich relevante Daten/Betraege werden dadurch
    NICHT von der KI angefasst."""
    from db import get_conn
    from secrets_store import get_secret
    heute = heute or datetime.date.today()
    faellig = [(rest, f) for f in FRISTEN for ok, rest in [faellig_heute(f, heute)] if ok]
    if not faellig:
        return 0
    rest, frist = sorted(faellig)[0]   # dringlichste (kleinster Rest)
    marke = "frist|%s|%s" % (frist["name"], heute.isoformat())
    h = hashlib.sha256(marke.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM themen WHERE hash=?", (h,)).fetchone():
            return 0   # heute schon erzeugt
    fields = _post_fields(frist, rest, heute)
    bild_pfad = None
    if get_secret("openai_api_key"):
        try:
            import kampagne
            image_path, review, motiv_path, layout_template = kampagne.generate_image_for_fixed_text(
                fields["ueberschrift"], fields["bullets"], fields["cta"],
                context=fields.get("subline", ""),
            )
            import bildgen
            final_path = str(image_path).replace(".png", "_ci.png")
            bildgen.add_logo_circles(str(image_path), bildgen.pick_slogan(fields.get("slogan")), final_path)
            bild_pfad = final_path
            fields["qa_approved"] = review.approved
            fields["qa_problems"] = review.problems if not review.approved else []
            fields["kampagne_motiv_pfad"] = str(motiv_path)
            fields["kampagne_layout_template"] = layout_template
        except Exception as ex:
            log.warning("Fristen-Bild fehlgeschlagen (%s): %s - Beitrag ohne Bild.", frist["name"], ex)
    else:
        log.info("Fristen-Bild uebersprungen: kein 'openai_api_key' hinterlegt (Beitrag ohne Bild).")
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO themen(quelle, titel, status, volltext, hash) "
                           "VALUES('frist', ?, 'erledigt', ?, ?)",
                           (frist["name"], "Fristen-Countdown", h))
        conn.execute("INSERT INTO entwuerfe(thema_id, kanal, text, status, geplant_fuer, bild_pfad) "
                     "VALUES (?, 'facebook', ?, 'entwurf', ?, ?)",
                     (cur.lastrowid, json.dumps(fields, ensure_ascii=False), heute.isoformat(), bild_pfad))
        conn.commit()
    log.info("Fristen-Countdown erzeugt: %s (%d Tage), geplant fuer %s.",
             frist["name"], rest, heute.isoformat())
    return 1
