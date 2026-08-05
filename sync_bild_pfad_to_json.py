#!/usr/bin/env python3
"""Synchronisiert bild_pfad aus der DB-Spalte ins JSON (text Spalte).

Problem:
Die DB hat bild_pfad=entwurf_95.png (ShareNext), aber das JSON hat noch
den alten bild_pfad=campaign_*.png!

render_fuer_stelle() liest bild_pfad aus dem JSON, nicht aus der DB!

Lösung:
Für alle Entwürfe mit ShareNext-Bildern (bild_pfad in DB = entwurf_*.png):
- JSON laden
- bild_pfad im JSON auf den Wert aus der DB Spalte setzen
- JSON zurückschreiben
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn

def sync_bild_pfad(dry_run=True):
    """Synchronisiert bild_pfad aus der DB-Spalte ins JSON."""

    with get_conn() as conn:
        # Finde alle Entwürfe mit ShareNext-Bildern (DB Spalte)
        rows = conn.execute("""
            SELECT id, bild_pfad, text
            FROM entwuerfe
            WHERE bild_pfad LIKE '%entwurf_%'
            AND bild_pfad NOT LIKE '%_premium%'
        """).fetchall()

        if not rows:
            print("✅ Keine ShareNext-Entwürfe gefunden!")
            return

        print(f"📊 Gefunden: {len(rows)} ShareNext-Entwürfe\n")

        fixed = 0
        for row in rows:
            eid = row["id"]
            db_bild_pfad = row["bild_pfad"]
            basename = os.path.basename(db_bild_pfad)

            # Parse JSON
            try:
                fields = json.loads(row["text"])
            except json.JSONDecodeError:
                print(f"⚠️  Entwurf {eid}: JSON-Fehler, überspringe")
                continue

            json_bild_pfad = fields.get("bild_pfad", "")

            # Prüfe ob bild_pfad im JSON anders ist als in der DB
            if json_bild_pfad == db_bild_pfad:
                # Schon synchron
                continue

            print(f"Entwurf {eid}:")
            print(f"  DB:   {basename}")
            print(f"  JSON: {os.path.basename(json_bild_pfad) if json_bild_pfad else 'KEIN'}")

            if dry_run:
                print(f"  💡 DRY RUN - würde synchronisieren")
            else:
                # Synchronisiere: JSON bild_pfad = DB bild_pfad
                fields["bild_pfad"] = db_bild_pfad

                # Update DB
                new_text = json.dumps(fields, ensure_ascii=False)
                conn.execute("UPDATE entwuerfe SET text=? WHERE id=?", (new_text, eid))
                print(f"  ✅ JSON aktualisiert")
                fixed += 1

            print()

        if not dry_run and fixed > 0:
            conn.commit()

        print("=" * 60)
        if dry_run:
            count = sum(1 for r in rows if json.loads(r["text"]).get("bild_pfad") != r["bild_pfad"])
            print(f"💡 DRY RUN - {count} Entwürfe würden synchronisiert")
            print("   Führe mit --fix aus um wirklich zu ändern!")
        else:
            print(f"✅ {fixed} Entwürfe synchronisiert!")
            print("   bild_pfad im JSON = bild_pfad in DB Spalte")
        print("=" * 60)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synchronisiere bild_pfad DB → JSON")
    parser.add_argument("--fix", action="store_true",
                       help="Wirklich synchronisieren (ohne: nur dry-run)")
    args = parser.parse_args()

    sync_bild_pfad(dry_run=not args.fix)
