# -*- coding: utf-8 -*-
"""Traeger-Wechsler (#142): WIE die Botschaft praesentiert wird (Tafel/Rahmen/Holzschild/...).

Zweite Abwechslungs-Achse zu den Schauplaetzen (#140/#141): waehrend der Schauplatz die schoene
UMGEBUNG bestimmt, bestimmt der TRAEGER das DEVICE in der Szene, auf dem der KI-Tafel-Text steht
(z.B. Kreidetafel, Bilderrahmen, Holzschild). Der Traeger ist ein prompt_snippet, das im
KI-Tafel-Prompt das frueher hartkodierte 'Bilderrahmen/Tisch-Aufsteller'-Device ersetzt.

Auswahl HYBRID (Catrin):
- Zufall + nie-doppelt-im-Zyklus (Rotation via zuletzt_genutzt, analog waehle_schauplatz);
- leichte, optionale Themen-Passung (z.B. festliches Banner zu Weihnacht/Feier, Postkarte zu
  Reise/Urlaub/Sommer) - Kern bleibt aber Zufall+Rotation, bewusst NICHT ueberkonstruiert.
- Fallback wenn kein Traeger aktiv -> Bilderrahmen-Default-Snippet (#140-Verhalten).

Dieses Modul enthaelt NUR die Auswahl-Logik (gut testbar, ohne API-Call). Tabelle + Seed liegen in
db.py (traeger), die Verwaltung in web.py. Architektur bewusst analog zu schauplatz.py."""
import datetime
import logging

log = logging.getLogger("hilo.traeger")

# Fallback-Snippet, wenn KEIN Traeger aktiv/waehlbar ist: das bisherige #140-Bilderrahmen-Device.
# Identisch zum Seed-Snippet von 'Bilderrahmen/Aufsteller' -> rueckwaertskompatibles Verhalten.
DEFAULT_SNIPPET = ("ein eleganter heller Bilderrahmen bzw. Tisch-Aufsteller, der Text in "
                   "HILO-Dunkelblau, serifenlos, klar lesbar")

# Leichte, optionale Themen-Passung: Traeger-NAME -> saisonale/thematische Schlagwoerter
# (kleingeschrieben, Teilstring-Match im Beitragstext). Bewusst simpel und nur als BEVORZUGUNG -
# trifft ein Schlagwort, wird der passende, AKTIVE Traeger genommen (sofern noch nicht in diesem
# Zyklus genutzt); sonst greift die normale Zufall+Rotation. Catrin: "nicht ueberkonstruieren".
_THEMA_TRAEGER = {
    "Festliches Stoffbanner": ("weihnacht", "advent", "fest", "feier", "jubilaeum", "jubiläum",
                               "geburtstag", "silvester", "neujahr"),
    "Große Postkarte": ("reise", "urlaub", "ferien", "sommer", "strand", "meer"),
}


def _passung_keywords(fields):
    """Sammelt den durchsuchbaren Beitragstext (kleingeschrieben) aus den fields fuer die leichte
    Themen-Passung. Liefert "" bei fehlenden/nicht-dict fields (-> keine Passung, reine Rotation)."""
    if not isinstance(fields, dict):
        return ""
    teile = []
    for key in ("ueberschrift", "titel", "thema", "caption", "subline", "volltext"):
        wert = fields.get(key)
        if isinstance(wert, str):
            teile.append(wert)
    bullets = fields.get("bullets")
    if isinstance(bullets, (list, tuple)):
        teile.extend(str(b) for b in bullets if b)
    return " ".join(teile).lower()


def _themen_traeger(conn, fields):
    """Liefert das prompt_snippet eines THEMATISCH passenden, AKTIVEN und im aktuellen Zyklus noch
    NICHT genutzten Traegers (oder None). Bewusst nur eine leichte Bevorzugung: trifft kein
    Schlagwort oder ist der passende Traeger inaktiv/schon genutzt, faellt die Wahl auf die normale
    Rotation zurueck. Reihenfolge: dict-Order von _THEMA_TRAEGER (erster Treffer gewinnt)."""
    text = _passung_keywords(fields)
    if not text:
        return None
    for name, woerter in _THEMA_TRAEGER.items():
        if any(w in text for w in woerter):
            row = conn.execute(
                "SELECT id, prompt_snippet FROM traeger "
                "WHERE aktiv=1 AND name=? AND zuletzt_genutzt IS NULL LIMIT 1", (name,)).fetchone()
            if row is not None:
                jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
                conn.execute("UPDATE traeger SET zuletzt_genutzt=? WHERE id=?", (jetzt, row["id"]))
                return row["prompt_snippet"] or ""
    return None


def waehle_traeger(conn, fields, datum=None):
    """Waehlt EINEN Traeger fuer den Beitrag und liefert dessen prompt_snippet (String) oder den
    DEFAULT_SNIPPET (nie ""), damit der KI-Tafel-Prompt immer ein gueltiges Device bekommt.

    Ablauf:
    1. Leichte Themen-Passung (optional): festliches Banner bei Weihnacht/Feier, Postkarte bei
       Reise/Urlaub/Sommer - aber nur, wenn dieser Traeger aktiv und im Zyklus noch ungenutzt ist.
    2. Sonst: aus den AKTIVEN Traegern den am LAENGSTEN nicht genutzten waehlen
       (zuletzt_genutzt NULL zuerst, dann aeltester, bei Gleichstand RANDOM()) -> Rotation,
       'nie doppelt im Zyklus', bis alle aktiven Traeger dran waren.
    3. zuletzt_genutzt = jetzt setzen (markiert den Traeger als gerade benutzt).
    Fallback: gibt es gar keinen aktiven Traeger, wird DEFAULT_SNIPPET (#140-Bilderrahmen) geliefert.

    'datum' wird (analog schauplatz) als Signatur durchgereicht, aktuell nicht ausgewertet.
    'conn' = offene sqlite3-Verbindung."""
    treffer = _themen_traeger(conn, fields)
    if treffer:
        return treffer
    row = conn.execute(
        "SELECT id, prompt_snippet FROM traeger WHERE aktiv=1 "
        "ORDER BY zuletzt_genutzt IS NOT NULL, zuletzt_genutzt, RANDOM() LIMIT 1").fetchone()
    if row is None:
        return DEFAULT_SNIPPET
    jetzt = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
    conn.execute("UPDATE traeger SET zuletzt_genutzt=? WHERE id=?", (jetzt, row["id"]))
    return row["prompt_snippet"] or DEFAULT_SNIPPET


def zuweisen_traeger_falls_fehlt(conn, fields, datum=None):
    """Setzt fields['traeger'] EINMALIG bei der Beitrags-Erzeugung (#142-C), falls es noch nicht
    gesetzt ist - so bleibt der Traeger ueber Re-Renders/Personalisierung je Stelle STABIL und der
    Bild-Cache passt (NICHT bei jedem Render neu wuerfeln).

    Robust: 'fields' muss ein dict sein (sonst No-Op). Schlaegt die Wahl fehl (z.B. Tabelle fehlt
    in einer alten DB), bleibt 'traeger' ungesetzt -> ki_tafel faellt auf das bisherige
    Bilderrahmen-Device zurueck (rueckwaertskompatibel, #140). Liefert den gewaehlten Traeger
    (oder den bestehenden)."""
    if not isinstance(fields, dict):
        return ""
    vorhanden = (fields.get("traeger") or "").strip()
    if vorhanden:
        return vorhanden
    try:
        tr = waehle_traeger(conn, fields, datum)
    except Exception as ex:
        log.warning("Traeger-Wahl fehlgeschlagen: %s", ex)
        return ""
    if tr:
        fields["traeger"] = tr
    return tr
