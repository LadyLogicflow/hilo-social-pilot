# -*- coding: utf-8 -*-
"""Schauplaetze-Bibliothek (#140): schoene, saisonale Umgebungen fuer den KI-Tafel-Look.

Statt einer stur zum Thema passenden Szene zeigt der KI-Tafel-Modus eine abwechslungsreiche,
schoene UMGEBUNG (Schauplatz); die Botschaft steht darin auf einem Bilderrahmen/Tisch-Aufsteller.

Catrin-Regeln:
- 20 Schauplaetze (5 pro Jahreszeit), in db.py geseedet.
- Die Jahreszeit des Schauplatzes passt ENTWEDER zur tatsaechlichen (Kalender-)Jahreszeit ODER
  zum THEMA des Beitrags (Anlass-Datum bzw. Schlagwoerter) -> ziel_jahreszeit().
- Aus der Ziel-Jahreszeit rotierend waehlen, NIE doppelt im Zyklus (zuletzt_genutzt-Steuerung).

Dieses Modul enthaelt NUR die Auswahl-/Jahreszeit-Logik (gut testbar, ohne API-Call). Das Seeding
und die Tabelle liegen in db.py (schauplaetze), die Verwaltung in web.py."""
import datetime
import logging

log = logging.getLogger("hilo.schauplatz")

JAHRESZEITEN = ("fruehling", "sommer", "herbst", "winter")

# Schlagwoerter -> Jahreszeit (kleingeschrieben, Teilstring-Match in Titel/Inhalt/Ueberschrift).
# Bewusst simpel gehalten (Catrin: "nicht ueberkonstruieren"). Reihenfolge der Pruefung egal,
# da ein klarer Treffer reicht; bei Mehrdeutigkeit gewinnt der erste gefundene Treffer.
_THEMA_KEYWORDS = {
    "sommer": ("sommer", "strand", "urlaub", "ferien", "meer", "see ", "badesee", "hitze"),
    "winter": ("winter", "weihnacht", "advent", "schnee", "nikolaus", "silvester", "neujahr"),
    "fruehling": ("fruehling", "frühling", "ostern", "bluete", "blüte", "bluehen", "blühen", "fruehjahr", "frühjahr"),
    "herbst": ("herbst", "erntedank", "laub", "ernte"),
}


def aktuelle_jahreszeit(monat):
    """Liefert die meteorologische Jahreszeit zum Monat (1-12):
    Maerz-Mai = fruehling, Juni-Aug = sommer, Sep-Nov = herbst, Dez-Feb = winter."""
    try:
        m = int(monat)
    except (TypeError, ValueError):
        m = datetime.date.today().month
    if m in (3, 4, 5):
        return "fruehling"
    if m in (6, 7, 8):
        return "sommer"
    if m in (9, 10, 11):
        return "herbst"
    return "winter"   # 12, 1, 2


def _jahreszeit_aus_mmdd(mmdd):
    """Liefert die Jahreszeit zu einem 'MM-DD'-Anlass-Datum (oder None bei ungueltigem Format)."""
    try:
        m, _d = (int(x) for x in str(mmdd).split("-")[:2])
    except (ValueError, TypeError):
        return None
    if 1 <= m <= 12:
        return aktuelle_jahreszeit(m)
    return None


def _jahreszeit_aus_schlagwoertern(text):
    """Sucht in 'text' (kleingeschrieben) nach saisonalen Schlagwoertern. Liefert die Jahreszeit
    des ersten Treffers oder None. Reihenfolge: sommer, winter, fruehling, herbst (dict-Order)."""
    if not text:
        return None
    t = text.lower()
    for jahreszeit, woerter in _THEMA_KEYWORDS.items():
        for w in woerter:
            if w in t:
                return jahreszeit
    return None


def ziel_jahreszeit(fields, datum=None):
    """Bestimmt die ZIEL-Jahreszeit fuer den Schauplatz (ERGAENZUNG Catrin 2026-06-24):

    1. Klarer saisonaler Themenbezug -> diese Jahreszeit. Quellen:
       (a) Anlass-Datum (fields['anlass_datum'] oder fields['datum'] als 'MM-DD') -> Jahreszeit;
       (b) Schlagwoerter in ueberschrift/titel/caption/volltext (Sommer/Strand/Urlaub/Ferien ->
           sommer; Winter/Weihnacht/Advent/Schnee -> winter; Fruehling/Ostern/Bluete -> fruehling;
           Herbst/Erntedank/Laub -> herbst).
    2. Sonst -> tatsaechliche Kalender-Jahreszeit (aktuelle_jahreszeit) zum 'datum' (oder heute).

    'datum' ist ein datetime.date (oder None -> heute). 'fields' darf None/kein dict sein
    (-> fallen direkt auf die Kalender-Jahreszeit)."""
    datum = datum or datetime.date.today()
    # (a) Anlass-Datum hat Vorrang vor Schlagwoertern (es ist die explizitere Quelle).
    if isinstance(fields, dict):
        for key in ("anlass_datum", "datum"):
            jz = _jahreszeit_aus_mmdd(fields.get(key))
            if jz:
                return jz
        # (b) Schlagwoerter in den Textfeldern
        teile = []
        for key in ("ueberschrift", "titel", "thema", "caption", "subline", "volltext"):
            wert = fields.get(key)
            if isinstance(wert, str):
                teile.append(wert)
        # bullets (Liste) ebenfalls einbeziehen
        bullets = fields.get("bullets")
        if isinstance(bullets, (list, tuple)):
            teile.extend(str(b) for b in bullets if b)
        jz = _jahreszeit_aus_schlagwoertern(" ".join(teile))
        if jz:
            return jz
    # 2. Kein klarer Themenbezug -> Kalender-Jahreszeit
    return aktuelle_jahreszeit(getattr(datum, "month", datetime.date.today().month))


def waehle_schauplatz(conn, fields, datum=None):
    """Waehlt EINEN Schauplatz fuer den Beitrag und liefert dessen Beschreibung (String) oder "".

    Ablauf:
    1. Ziel-Jahreszeit bestimmen (ziel_jahreszeit -> Thema ODER Kalender).
    2. Aus den AKTIVEN Schauplaetzen dieser Jahreszeit den am LAENGSTEN nicht genutzten waehlen:
       zuletzt_genutzt NULL zuerst, dann aeltestes; bei Gleichstand zufaellig (RANDOM()).
       -> Rotation, 'nie doppelt im Zyklus', bis alle der Jahreszeit dran waren.
    3. zuletzt_genutzt = jetzt setzen (markiert den Schauplatz als gerade benutzt).
    Fallback: Ist fuer die Ziel-Jahreszeit nichts aktiv, wird aus ALLEN aktiven Schauplaetzen
    (jahreszeituebergreifend) nach derselben Rotationsregel gewaehlt; gibt es gar keine aktiven,
    wird "" geliefert (Aufrufer faellt dann auf das bisherige szene_motiv zurueck).

    'datum' = datetime.date (oder None -> heute). 'conn' = offene sqlite3-Verbindung."""
    jz = ziel_jahreszeit(fields, datum)
    row = conn.execute(
        "SELECT id, beschreibung FROM schauplaetze WHERE aktiv=1 AND jahreszeit=? "
        "ORDER BY zuletzt_genutzt IS NOT NULL, zuletzt_genutzt, RANDOM() LIMIT 1", (jz,)).fetchone()
    if row is None:
        # Fallback: irgendein aktiver Schauplatz (jahreszeituebergreifend), gleiche Rotationsregel
        row = conn.execute(
            "SELECT id, beschreibung FROM schauplaetze WHERE aktiv=1 "
            "ORDER BY zuletzt_genutzt IS NOT NULL, zuletzt_genutzt, RANDOM() LIMIT 1").fetchone()
    if row is None:
        return ""
    jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
    conn.execute("UPDATE schauplaetze SET zuletzt_genutzt=? WHERE id=?", (jetzt, row["id"]))
    return row["beschreibung"] or ""


def zuweisen_falls_fehlt(conn, fields, datum=None):
    """Setzt fields['schauplatz'] EINMALIG bei der Beitrags-Erzeugung (#140-C), falls es noch nicht
    gesetzt ist - so bleibt der Schauplatz ueber Re-Renders/Personalisierung je Stelle STABIL und
    der Bild-Cache passt (NICHT bei jedem Render neu wuerfeln).

    Robust: 'fields' muss ein dict sein (sonst No-Op). Schlaegt die Wahl fehl (kein aktiver
    Schauplatz), bleibt 'schauplatz' ungesetzt -> ki_tafel faellt auf das bisherige szene_motiv
    zurueck (rueckwaertskompatibel). Liefert den gewaehlten Schauplatz (oder den bestehenden)."""
    if not isinstance(fields, dict):
        return ""
    vorhanden = (fields.get("schauplatz") or "").strip()
    if vorhanden:
        return vorhanden
    try:
        sp = waehle_schauplatz(conn, fields, datum)
    except Exception as ex:
        log.warning("Schauplatz-Wahl fehlgeschlagen: %s", ex)
        return ""
    if sp:
        fields["schauplatz"] = sp
    return sp
