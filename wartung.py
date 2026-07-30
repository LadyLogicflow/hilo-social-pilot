# -*- coding: utf-8 -*-
"""Wartung des Datenordners (Issue #134): sicheres, orphan-basiertes Aufraeumen des
KI-Foto-Caches DATA_DIR/motive/ sowie Speicher-Status (Ordnergroesse, freier Plattenplatz).

Sicherheits-Grundsatz: im Zweifel NICHT loeschen. Geloescht werden ausschliesslich
.png-Dateien im motive/-Ordner, die KEIN aktiver Entwurf mehr nutzen koennte UND die
aelter als die Schonfrist sind. Niemals angefasst werden: die Datenbank, Entwurfs-Bilder
(entwuerfe.bild_pfad), gezeichnete Symbole (icon_*.png) und frisch erzeugte (noch nicht
verknuepfte) Dateien.

Hintergrund-Lebenszyklus (siehe #134): Ein gecachtes Foto wird beim ERZEUGEN UND beim
POSTEN gebraucht (die Personalisierung je Beratungsstelle re-rendert mit dem gecachten
Foto), und POOL-Beitraege nutzen es ueber Wochen wiederholt. Darum gilt die Datei als
'in Benutzung', solange irgendein aktiver Entwurf sie nutzen koennte."""
import json
import logging
import os

import bildmotiv
from bildmotiv import MOTIV_DIR
from config import DATA_DIR

log = logging.getLogger("hilo.wartung")

KAMPAGNE_DIR = os.path.join(DATA_DIR, "kampagne")

# Aktive Entwurfs-Status: deren Cache-Fotos werden NIE geloescht (auch 'pool' = dauerhaft aktiv).
AKTIVE_ENTWURF_STATUS = ("entwurf", "freigegeben", "pool")
# Aktive Einplanungen: solange ein geplanter/laufender Post auf einen Entwurf zeigt, bleibt dessen Foto.
AKTIVE_GEPLANT_STATUS = ("geplant", "laeuft")


def _in_benutzung_pfade(conn):
    """Liefert das set() aller absoluten Cache-Pfade, die von AKTIVEN Entwuerfen genutzt werden
    koennten. Aktiv = Status in AKTIVE_ENTWURF_STATUS ODER von einem geplanten/laufenden Post
    referenziert. Nicht-parsebare entwuerfe.text werden uebersprungen (kein Crash)."""
    in_benutzung = set()
    ph_status = ",".join("?" for _ in AKTIVE_ENTWURF_STATUS)
    ph_geplant = ",".join("?" for _ in AKTIVE_GEPLANT_STATUS)
    sql = (
        "SELECT id, text FROM entwuerfe WHERE status IN (%s) "
        "OR id IN (SELECT entwurf_id FROM geplante_posts WHERE status IN (%s))"
        % (ph_status, ph_geplant)
    )
    params = tuple(AKTIVE_ENTWURF_STATUS) + tuple(AKTIVE_GEPLANT_STATUS)
    for row in conn.execute(sql, params):
        try:
            fields = json.loads(row["text"]) if row["text"] else {}
        except Exception:
            # Defekter Entwurf: ueberspringen. Seine Dateien gelten dann nicht als 'in Benutzung' -
            # geschuetzt bleiben sie trotzdem ueber die 14-Tage-Schonfrist (mtime).
            log.warning("aufraeumen_motive: Entwurf %s nicht parsebar, uebersprungen.", row["id"])
            continue
        try:
            in_benutzung |= bildmotiv.cache_dateien_fuer_fields(fields)
        except Exception:
            log.warning("aufraeumen_motive: Cache-Pfade fuer Entwurf %s nicht ermittelbar, "
                        "uebersprungen.", row["id"])
            continue
    return in_benutzung


def aufraeumen_motive(conn, schonfrist_tage=14):
    """Raeumt verwaiste KI-Foto-Dateien aus MOTIV_DIR auf.

    Loescht jede Datei in MOTIV_DIR, die ALLE folgenden Bedingungen erfuellt:
      - Endung .png
      - Name beginnt NICHT mit 'icon_' (gezeichnete Symbole bleiben dauerhaft)
      - NICHT in der In-Benutzung-Menge aktiver Entwuerfe (siehe _in_benutzung_pfade)
      - mtime aelter als `schonfrist_tage` Tage (Schutz vor frisch erzeugten, noch nicht
        verknuepften Dateien)

    Args:
        conn: offene SQLite-Verbindung.
        schonfrist_tage (int): Mindestalter (Tage), bevor eine verwaiste Datei loeschbar ist.

    Returns:
        tuple[int, int]: (Anzahl geloeschter Dateien, freigegebene Bytes).
    """
    import time

    if not os.path.isdir(MOTIV_DIR):
        return (0, 0)
    in_benutzung = _in_benutzung_pfade(conn)
    schwelle = time.time() - max(0, schonfrist_tage) * 86400
    geloescht = 0
    bytes_frei = 0
    for name in os.listdir(MOTIV_DIR):
        if not name.lower().endswith(".png"):
            continue
        if name.startswith("icon_"):
            continue  # gezeichnete Symbole: nie loeschen
        pfad = os.path.join(MOTIV_DIR, name)
        if pfad in in_benutzung:
            continue  # wird von einem aktiven Entwurf gebraucht
        try:
            st = os.stat(pfad)
        except OSError:
            continue
        if not os.path.isfile(pfad):
            continue
        if st.st_mtime >= schwelle:
            continue  # innerhalb der Schonfrist -> bleibt
        try:
            groesse = st.st_size
            os.remove(pfad)
            geloescht += 1
            bytes_frei += groesse
        except OSError as ex:
            log.warning("aufraeumen_motive: konnte %s nicht loeschen: %s", name, ex)
    log.info("aufraeumen_motive: %d Foto(s) geloescht, %.1f MB frei.",
             geloescht, bytes_frei / (1024 * 1024))
    return (geloescht, bytes_frei)


def motive_ordner_groesse():
    """Summe der Dateigroessen im motive/-Ordner in Bytes (0, wenn der Ordner fehlt)."""
    if not os.path.isdir(MOTIV_DIR):
        return 0
    gesamt = 0
    for name in os.listdir(MOTIV_DIR):
        pfad = os.path.join(MOTIV_DIR, name)
        try:
            if os.path.isfile(pfad):
                gesamt += os.path.getsize(pfad)
        except OSError:
            continue
    return gesamt


def _kampagne_in_benutzung_pfade(conn):
    """Analog zu _in_benutzung_pfade, aber fuer den 3-Stufen-Workflow: schuetzt sowohl das rohe
    Motiv (fields['kampagne_motiv_pfad'], gebraucht fuer die Personalisierung je
    Beratungsstelle - render_fuer_stelle) als auch entwuerfe.bild_pfad (falls es ausnahmsweise
    im kampagne/-Ordner liegt, z.B. bei einem expliziten output_path)."""
    in_benutzung = set()
    ph_status = ",".join("?" for _ in AKTIVE_ENTWURF_STATUS)
    ph_geplant = ",".join("?" for _ in AKTIVE_GEPLANT_STATUS)
    sql = (
        "SELECT id, text, bild_pfad FROM entwuerfe WHERE status IN (%s) "
        "OR id IN (SELECT entwurf_id FROM geplante_posts WHERE status IN (%s))"
        % (ph_status, ph_geplant)
    )
    params = tuple(AKTIVE_ENTWURF_STATUS) + tuple(AKTIVE_GEPLANT_STATUS)
    for row in conn.execute(sql, params):
        if row["bild_pfad"]:
            in_benutzung.add(row["bild_pfad"])
        try:
            fields = json.loads(row["text"]) if row["text"] else {}
        except Exception:
            log.warning("aufraeumen_kampagne: Entwurf %s nicht parsebar, uebersprungen.", row["id"])
            continue
        motiv = fields.get("kampagne_motiv_pfad")
        if motiv:
            in_benutzung.add(motiv)
    return in_benutzung


def aufraeumen_kampagne(conn, schonfrist_tage=14):
    """Raeumt verwaiste Dateien aus DATA_DIR/kampagne/ auf (rohe Motive + Text-Zwischenbilder
    des 3-Stufen-Workflows, VOR den finalen CI-Kreisen - die fertigen Bilder liegen unter
    DATA_DIR/bilder/ und werden hier NIE angefasst, siehe entwuerfe.bild_pfad-Schutz).

    Gleiche Sicherheitslogik wie aufraeumen_motive: geloescht wird nur, was kein aktiver
    Entwurf mehr referenziert UND aelter als die Schonfrist ist. Die rohen Motive muessen so
    lange erhalten bleiben, wie der Entwurf noch personalisiert werden koennte (#Kostenschutz -
    ohne sie wuerde die Personalisierung je Beratungsstelle wieder einen neuen, kostenpflichtigen
    GPT-Image-Call brauchen).

    Args:
        conn: offene SQLite-Verbindung.
        schonfrist_tage (int): Mindestalter (Tage), bevor eine verwaiste Datei loeschbar ist.

    Returns:
        tuple[int, int]: (Anzahl geloeschter Dateien, freigegebene Bytes).
    """
    import time

    if not os.path.isdir(KAMPAGNE_DIR):
        return (0, 0)
    in_benutzung = _kampagne_in_benutzung_pfade(conn)
    schwelle = time.time() - max(0, schonfrist_tage) * 86400
    geloescht = 0
    bytes_frei = 0
    for name in os.listdir(KAMPAGNE_DIR):
        if not name.lower().endswith(".png"):
            continue
        pfad = os.path.join(KAMPAGNE_DIR, name)
        if pfad in in_benutzung:
            continue  # wird von einem aktiven Entwurf gebraucht (Motiv ODER Bild)
        try:
            st = os.stat(pfad)
        except OSError:
            continue
        if not os.path.isfile(pfad):
            continue
        if st.st_mtime >= schwelle:
            continue  # innerhalb der Schonfrist -> bleibt
        try:
            groesse = st.st_size
            os.remove(pfad)
            geloescht += 1
            bytes_frei += groesse
        except OSError as ex:
            log.warning("aufraeumen_kampagne: konnte %s nicht loeschen: %s", name, ex)
    log.info("aufraeumen_kampagne: %d Datei(en) geloescht, %.1f MB frei.",
             geloescht, bytes_frei / (1024 * 1024))
    return (geloescht, bytes_frei)


def kampagne_ordner_groesse():
    """Summe der Dateigroessen im kampagne/-Ordner in Bytes (0, wenn der Ordner fehlt)."""
    if not os.path.isdir(KAMPAGNE_DIR):
        return 0
    gesamt = 0
    for name in os.listdir(KAMPAGNE_DIR):
        pfad = os.path.join(KAMPAGNE_DIR, name)
        try:
            if os.path.isfile(pfad):
                gesamt += os.path.getsize(pfad)
        except OSError:
            continue
    return gesamt


def freier_speicher(pfad):
    """Liefert (frei_bytes, gesamt_bytes) der Platte, auf der `pfad` liegt (shutil.disk_usage).
    Bei Fehler (0, 0)."""
    import shutil
    try:
        usage = shutil.disk_usage(pfad)
        return (usage.free, usage.total)
    except Exception:
        return (0, 0)


def menschlich(bytes_zahl):
    """Formatiert eine Byte-Zahl menschenlesbar (B/KB/MB/GB/TB), echte Umlaute, deutsches Komma."""
    try:
        wert = float(bytes_zahl)
    except (TypeError, ValueError):
        return "0 B"
    for einheit in ("B", "KB", "MB", "GB", "TB"):
        if wert < 1024 or einheit == "TB":
            if einheit == "B":
                return "%d B" % int(wert)
            return ("%.1f %s" % (wert, einheit)).replace(".", ",")
        wert /= 1024
    return "%.1f TB" % wert
