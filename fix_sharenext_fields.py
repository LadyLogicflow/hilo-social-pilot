#!/usr/bin/env python3
"""Löscht kampagne_motiv_pfad aus Entwürfen mit ShareNext-Bildern.

Problem:
Entwürfe haben bild_pfad=entwurf_*.png (ShareNext) UND kampagne_motiv_pfad (alt).
Die alte kampagne.py Logik greift weil kampagne_motiv_pfad noch gesetzt ist!

Lösung:
Lösche kampagne_motiv_pfad und kampagne_layout_template aus dem JSON
für alle Entwürfe die ShareNext-Bilder haben (bild_pfad startet mit "entwurf_").

Dann greift die ShareNext-Logik in personalisierung.py!
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn

def fix_sharenext_fields(dry_run=True):
    """Löscht kampagne_motiv_pfad aus ShareNext-Entwürfen."""

    with get_conn() as conn:
        # Finde alle Entwürfe mit ShareNext-Bildern
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
            bild_pfad = row["bild_pfad"]
            basename = os.path.basename(bild_pfad)

            # Parse JSON
            try:
                fields = json.loads(row["text"])
            except json.JSONDecodeError:
                print(f"⚠️  Entwurf {eid}: JSON-Fehler, überspringe")
                continue

            # Prüfe ob kampagne-Felder gesetzt sind
            has_motiv = "kampagne_motiv_pfad" in fields
            has_template = "kampagne_layout_template" in fields

            if not has_motiv and not has_template:
                # Nichts zu tun
                continue

            print(f"Entwurf {eid}: {basename}")
            if has_motiv:
                print(f"  ❌ kampagne_motiv_pfad: {fields['kampagne_motiv_pfad']}")
            if has_template:
                print(f"  ❌ kampagne_layout_template: {fields['kampagne_layout_template']}")

            if dry_run:
                print(f"  💡 DRY RUN - würde löschen")
            else:
                # Lösche die Felder
                if has_motiv:
                    del fields["kampagne_motiv_pfad"]
                if has_template:
                    del fields["kampagne_layout_template"]

                # Update DB
                new_text = json.dumps(fields, ensure_ascii=False)
                conn.execute("UPDATE entwuerfe SET text=? WHERE id=?", (new_text, eid))
                print(f"  ✅ kampagne-Felder gelöscht")
                fixed += 1

            print()

        if not dry_run and fixed > 0:
            conn.commit()

        print("=" * 60)
        if dry_run:
            print(f"💡 DRY RUN - {len([r for r in rows if 'kampagne_motiv_pfad' in json.loads(r['text'])])} Entwürfe würden gefixt")
            print("   Führe mit --fix aus um wirklich zu ändern!")
        else:
            print(f"✅ {fixed} Entwürfe gefixt!")
            print("   kampagne_motiv_pfad + kampagne_layout_template gelöscht")
            print("   ShareNext-Logik greift jetzt!")
        print("=" * 60)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fixe ShareNext-Entwürfe")
    parser.add_argument("--fix", action="store_true",
                       help="Wirklich fixen (ohne: nur dry-run)")
    args = parser.parse_args()

    fix_sharenext_fields(dry_run=not args.fix)
