# -*- coding: utf-8 -*-
"""Bild-Stil-Wahl (#144): der Bild-Stil wird ZUFAELLIG PRO BEITRAG aus den AKTIVEN Stilen gewaehlt
und stabil in fields['bild_stil'] abgelegt - statt global umzuschalten.

Catrin-Regeln:
- Drei Stile: 'standard' (v11-Layout), 'ki_tafel' (KI schreibt Text auf eine Tafel), 'kreativ'
  (kinoreifes Foto ohne Text, #143). WELCHE davon im Zufalls-Topf sind, steuern drei An/Aus-Flags
  in den Einstellungen: bild_stil_standard/_ki_tafel/_kreativ ('1' = aktiv, Default alle '1').
- Bei der Beitrags-Erzeugung wird EINMAL ein aktiver Stil gewaehlt (Zufall + leichtes nie-doppelt
  zum direkten Vorgaenger) und in fields['bild_stil'] gespeichert - STABIL ueber Re-Renders
  (nur wenn leer setzen), analog Schauplatz/Traeger (#140/#142).
- Mindestens EIN Stil muss aktiv bleiben; ist keiner aktiv, faellt die Wahl auf 'standard'.

bildmotiv/bildgen/textgen.art_director_motiv lesen den Stil PRO BEITRAG ueber aktiver_stil(fields):
fields['bild_stil'] (falls gesetzt+gueltig) ODER die globale Einstellung bild_stil ODER 'standard'.
So bleiben bestehende Entwuerfe OHNE fields['bild_stil'] rueckwaertskompatibel (Fallback auf die
globale Einstellung/'standard').

Dieses Modul enthaelt NUR die Auswahl-/Lese-Logik (gut testbar, ohne API-Call). Architektur bewusst
analog zu schauplatz.py/traeger.py."""
import logging
import random

log = logging.getLogger("hilo.stilwahl")

# Alle bekannten Bild-Stile (Reihenfolge = Anzeige-/Default-Reihenfolge).
STILE = ("standard", "ki_tafel", "kreativ")

# Einstellungs-Schluessel je Stil (An/Aus-Flag, '1' aktiv / '0' inaktiv, Default alle aktiv).
_FLAG_KEY = {
    "standard": "bild_stil_standard",
    "ki_tafel": "bild_stil_ki_tafel",
    "kreativ": "bild_stil_kreativ",
}


def aktive_stile(conn=None):
    """Liefert die Liste der aktuell AKTIVEN Stile (Reihenfolge wie STILE) anhand der drei
    An/Aus-Flags (bild_stil_standard/_ki_tafel/_kreativ). Ein Flag gilt als aktiv, wenn es NICHT
    explizit auf '0' steht (Default-aktiv: fehlt der Schluessel, ist der Stil im Topf).

    Mindestens einer muss aktiv sein: ist KEIN Stil aktiv (alle auf '0'), wird ['standard']
    geliefert (harter Fallback - es darf nie ein leerer Topf entstehen).

    'conn' wird (analog schauplatz/traeger) als Signatur angenommen, aber NICHT genutzt: die Flags
    liegen in der globalen Key-Value-Tabelle und werden ueber db.get_einstellung gelesen (eigene
    Verbindung). Der Parameter bleibt fuer eine einheitliche Aufruf-Signatur erhalten."""
    import db
    aktiv = []
    for stil in STILE:
        wert = db.get_einstellung(_FLAG_KEY[stil], "1")
        if str(wert).strip() != "0":
            aktiv.append(stil)
    return aktiv or ["standard"]


def aktiver_stil(fields, conn=None):
    """Liefert den fuer DIESEN Beitrag massgeblichen Bild-Stil. Reihenfolge:
    1. fields['bild_stil'] (falls gesetzt UND ein gueltiger Stil) - der PRO-BEITRAG-Stil (#144);
    2. sonst die globale Einstellung 'bild_stil' (Abwaerts-Fallback, bestehende Entwuerfe);
    3. sonst 'standard'.

    So lesen bildmotiv/bildgen/textgen.art_director_motiv den Stil EINHEITLICH pro Beitrag, ohne
    bestehende Renders (ohne fields['bild_stil']) zu veraendern. 'conn' wird nicht genutzt (Signatur
    fuer Einheitlichkeit). Robust: nicht-dict fields -> globale Einstellung/'standard'."""
    if isinstance(fields, dict):
        wert = (fields.get("bild_stil") or "").strip()
        if wert in STILE:
            return wert
    try:
        import db
        glob = (db.get_einstellung("bild_stil", "standard") or "standard").strip()
    except Exception:
        glob = "standard"
    return glob if glob in STILE else "standard"


def waehle_stil(conn, fields, vorgaenger=None):
    """Waehlt EINEN Stil zufaellig aus den AKTIVEN Stilen und liefert ihn.

    Leichtes 'nie-doppelt zum direkten Vorgaenger': ist 'vorgaenger' ein aktiver Stil UND gibt es
    mindestens einen weiteren aktiven Stil, wird der Vorgaenger aus der Wahl ausgeschlossen (so
    mischen sich die Stile staerker). Bei nur einem aktiven Stil wird genau dieser geliefert.

    'conn' wird (analog schauplatz/traeger) durchgereicht; die Flags liegen in den Einstellungen.
    Liefert immer einen gueltigen Stil (nie ""), Default 'standard' wenn nichts aktiv ist."""
    aktiv = aktive_stile(conn)
    kandidaten = aktiv
    if vorgaenger in aktiv and len(aktiv) > 1:
        kandidaten = [s for s in aktiv if s != vorgaenger]
    return random.choice(kandidaten) if kandidaten else "standard"


def zuweisen_stil_falls_fehlt(conn, fields):
    """Setzt fields['bild_stil'] EINMALIG bei der Beitrags-Erzeugung (#144-A), falls es noch nicht
    gesetzt ist - so bleibt der Stil ueber Re-Renders/Personalisierung je Beitrag STABIL und der
    Bild-Cache passt (NICHT bei jedem Render neu wuerfeln). Analog schauplatz.zuweisen_falls_fehlt.

    Robust: 'fields' muss ein dict sein (sonst No-Op, liefert ""). Schlaegt die Wahl fehl, bleibt
    'bild_stil' ungesetzt -> aktiver_stil faellt auf die globale Einstellung/'standard' zurueck
    (rueckwaertskompatibel). Liefert den gewaehlten (oder den bestehenden) Stil."""
    if not isinstance(fields, dict):
        return ""
    vorhanden = (fields.get("bild_stil") or "").strip()
    if vorhanden in STILE:
        return vorhanden
    try:
        stil = waehle_stil(conn, fields)
    except Exception as ex:
        log.warning("Stil-Wahl fehlgeschlagen: %s", ex)
        return ""
    if stil in STILE:
        fields["bild_stil"] = stil
    return stil


def anderen_stil_waehlen(conn, fields):
    """#144-C ('Anderes Bild'): waehlt fuer DIESEN Entwurf einen ANDEREN aktiven Stil als den
    aktuellen (fields['bild_stil'] bzw. aktiver_stil). Setzt fields['bild_stil'] auf den neuen Stil
    und liefert ihn.

    Gibt es keinen anderen aktiven Stil (nur einer aktiv, oder der einzige aktive ist bereits der
    aktuelle), wird None geliefert und fields NICHT veraendert - der Aufrufer zeigt dann einen
    Hinweis. Robust: nicht-dict fields -> None."""
    if not isinstance(fields, dict):
        return None
    aktuell = aktiver_stil(fields, conn)
    aktiv = aktive_stile(conn)
    kandidaten = [s for s in aktiv if s != aktuell]
    if not kandidaten:
        return None
    neu = random.choice(kandidaten)
    fields["bild_stil"] = neu
    return neu
