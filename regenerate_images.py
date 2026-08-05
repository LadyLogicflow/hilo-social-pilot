#!/usr/bin/env python3
"""Regeneriert ShareNext Premium-Bilder für Entwürfe mit alten kampagne.py Bildern."""

import sys
import os
import json
import shutil
from pathlib import Path

# Pfad zum Projekt hinzufügen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn
from sharenext_pipeline import run_sharenext_pipeline
import bildgen
from config import DATA_DIR
import tempfile

def classify_image(bild_pfad):
    """Klassifiziert ein Bild nach Typ."""
    if not bild_pfad:
        return "KEIN_BILD"

    basename = os.path.basename(bild_pfad)

    # ShareNext: entwurf_{id}.png (ohne _premium)
    if basename.startswith("entwurf_") and "_premium" not in basename:
        return "SHARENEXT"

    # Alte Premium-Variante: entwurf_{id}_premium.png
    if basename.startswith("entwurf_") and "_premium" in basename:
        return "OLD_PREMIUM"

    # Kampagne.py: campaign_{timestamp}_{uuid}.png
    if basename.startswith("campaign_"):
        return "KAMPAGNE"

    # Andere
    return "UNBEKANNT"

def needs_regeneration(bild_pfad):
    """Prüft ob ein Entwurf neu generiert werden muss."""
    typ = classify_image(bild_pfad)
    return typ in ["KAMPAGNE", "OLD_PREMIUM", "UNBEKANNT"]

def regenerate_image(entwurf_id, entwurf_data, dry_run=False):
    """Generiert ein neues ShareNext-Bild für einen Entwurf.

    Args:
        entwurf_id: ID des Entwurfs
        entwurf_data: Dict mit Entwurf-Daten (text, kanal, bild_pfad)
        dry_run: Wenn True, nur simulieren (kein echtes Generieren)

    Returns:
        (success, message) Tuple
    """
    try:
        # Text aus JSON parsen
        fields = json.loads(entwurf_data["text"])

        # Überschrift und Bullets extrahieren
        ueberschrift = fields.get("ueberschrift", "")
        bullets = fields.get("bullets", [])
        kanal = entwurf_data.get("kanal", "google")

        if not ueberschrift:
            return (False, "Keine Überschrift gefunden")

        print(f"  Überschrift: {ueberschrift[:60]}...")
        print(f"  Bullets: {len(bullets)} Stichpunkte")

        if dry_run:
            return (True, "DRY RUN - nicht generiert")

        # ShareNext Pipeline ausführen
        print(f"  ShareNext Pipeline starten...")
        result = run_sharenext_pipeline(
            stream="radar",
            thema=ueberschrift,
            text="\n".join(bullets),
            kanal=kanal.capitalize(),
            headline=ueberschrift,
            size="1024x1024",
            quality="medium"
        )

        # Temporäres Bild speichern
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_raw:
            result.image.save(tmp_raw.name, "PNG")
            slogan = bildgen.pick_slogan("")

            # Neuer Bild-Pfad
            new_bild_pfad = os.path.join(DATA_DIR, f"entwurf_{entwurf_id}.png")

            # Altes Bild sichern (falls es existiert)
            old_bild_pfad = entwurf_data.get("bild_pfad")
            if old_bild_pfad and os.path.exists(old_bild_pfad):
                backup_pfad = old_bild_pfad + ".old"
                print(f"  Altes Bild sichern: {os.path.basename(backup_pfad)}")
                shutil.move(old_bild_pfad, backup_pfad)

            # Logo-Kreise hinzufügen
            bildgen.add_logo_circles(tmp_raw.name, slogan, new_bild_pfad, pos="unten")

            # DB aktualisieren
            with get_conn() as conn:
                conn.execute("UPDATE entwuerfe SET bild_pfad=? WHERE id=?",
                           (new_bild_pfad, entwurf_id))

            # Temp-Datei löschen
            os.unlink(tmp_raw.name)

            print(f"  ✓ Neues Bild: {os.path.basename(new_bild_pfad)}")
            return (True, "Erfolgreich generiert")

    except Exception as ex:
        return (False, f"Fehler: {ex}")

def main():
    """Hauptfunktion - regeneriert Bilder für alle betroffenen Entwürfe."""
    import argparse

    parser = argparse.ArgumentParser(description="Regeneriere ShareNext-Bilder für alte Entwürfe")
    parser.add_argument("--dry-run", action="store_true",
                       help="Nur simulieren, nicht wirklich generieren")
    args = parser.parse_args()

    print("=" * 70)
    print("REGENERIERUNG: ShareNext Premium-Bilder")
    print("=" * 70)
    print()

    if args.dry_run:
        print("⚠️  DRY RUN MODUS - es wird nichts generiert!\n")

    # Alle Entwürfe mit Bildern finden
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, kanal, text, bild_pfad, status
            FROM entwuerfe
            WHERE bild_pfad IS NOT NULL AND bild_pfad != ''
            ORDER BY id
        """).fetchall()

    # Filtern: Nur Entwürfe die neu generiert werden müssen
    to_regenerate = []
    for row in rows:
        if needs_regeneration(row["bild_pfad"]):
            to_regenerate.append(row)

    total = len(to_regenerate)

    if total == 0:
        print("✅ Keine Entwürfe gefunden die regeneriert werden müssen!")
        print("   Alle Bilder sind bereits ShareNext Premium.")
        return

    print(f"📊 Gefunden: {total} Entwürfe mit alten Bildern\n")
    print(f"💰 Geschätzte Kosten: ~${total * 0.10:.2f}\n")

    if not args.dry_run:
        antwort = input(f"Wirklich {total} Bilder neu generieren? (ja/nein): ")
        if antwort.lower() not in ["ja", "j", "yes", "y"]:
            print("Abgebrochen.")
            return
        print()

    # Regenerieren
    erfolg = 0
    fehler = 0

    for i, row in enumerate(to_regenerate, 1):
        eid = row["id"]
        old_typ = classify_image(row["bild_pfad"])

        print(f"[{i}/{total}] Entwurf {eid} ({row['status']}) - {old_typ}")

        success, message = regenerate_image(eid, row, dry_run=args.dry_run)

        if success:
            print(f"  ✅ {message}\n")
            erfolg += 1
        else:
            print(f"  ❌ {message}\n")
            fehler += 1

    print("=" * 70)
    print(f"✅ Erfolgreich: {erfolg}/{total}")
    if fehler > 0:
        print(f"❌ Fehler:      {fehler}/{total}")
    print("=" * 70)

    if not args.dry_run and erfolg > 0:
        print()
        print("🎉 Fertig! Die Vorschau sollte jetzt die neuen ShareNext-Bilder zeigen.")
        print("   Alte Bilder wurden als .old gesichert und können gelöscht werden.")

if __name__ == "__main__":
    main()
