#!/usr/bin/env python3
"""Prüfe wie viele Entwürfe noch alte kampagne.py Bilder haben."""

import sys
sys.path.insert(0, '/workspace/hilo-social-pilot')

from db import get_conn
import os

# Verschiedene Bild-Typen erkennen
def classify_image(bild_pfad):
    """Klassifiziert ein Bild nach Typ."""
    if not bild_pfad:
        return "KEIN_BILD"

    basename = os.path.basename(bild_pfad)

    # ShareNext: entwurf_{id}.png
    if basename.startswith("entwurf_") and not "_premium" in basename:
        return "SHARENEXT"

    # Alte Premium-Variante: entwurf_{id}_premium.png
    if basename.startswith("entwurf_") and "_premium" in basename:
        return "OLD_PREMIUM"

    # Kampagne.py: campaign_{timestamp}_{uuid}.png
    if basename.startswith("campaign_"):
        return "KAMPAGNE"

    # Andere
    return "UNBEKANNT"

print("=" * 60)
print("BESTANDSAUFNAHME: Alte vs. Neue Bilder")
print("=" * 60)

with get_conn() as conn:
    # Alle Entwürfe mit Bildern holen
    rows = conn.execute("""
        SELECT id, status, bild_pfad
        FROM entwuerfe
        WHERE bild_pfad IS NOT NULL AND bild_pfad != ''
        ORDER BY id DESC
    """).fetchall()

    stats = {
        "SHARENEXT": [],
        "KAMPAGNE": [],
        "OLD_PREMIUM": [],
        "KEIN_BILD": [],
        "UNBEKANNT": []
    }

    for row in rows:
        typ = classify_image(row["bild_pfad"])
        stats[typ].append({
            "id": row["id"],
            "status": row["status"],
            "pfad": row["bild_pfad"],
            "exists": os.path.exists(row["bild_pfad"]) if row["bild_pfad"] else False
        })

print("\n📊 STATISTIK:\n")
print(f"✅ ShareNext Premium (neu):     {len(stats['SHARENEXT']):3d} Entwürfe")
print(f"📄 Kampagne.py (alt):           {len(stats['KAMPAGNE']):3d} Entwürfe")
print(f"🔄 Alte Premium-Variante:       {len(stats['OLD_PREMIUM']):3d} Entwürfe")
print(f"❓ Unbekannter Typ:             {len(stats['UNBEKANNT']):3d} Entwürfe")
print(f"🚫 Kein Bild:                   {len(stats['KEIN_BILD']):3d} Entwürfe")
print()

# Entwürfe die neu generiert werden müssen
need_regen = len(stats['KAMPAGNE']) + len(stats['OLD_PREMIUM']) + len(stats['UNBEKANNT'])
print("=" * 60)
print(f"🔧 MÜSSEN NEU GENERIERT WERDEN: {need_regen} Entwürfe")
print("=" * 60)
print()

if need_regen > 0:
    print(f"💰 Geschätzte Kosten: ~${need_regen * 0.10:.2f} (${0.10} pro Bild)")
    print()
    print("📋 Details der betroffenen Entwürfe:")
    print()

    for typ in ['KAMPAGNE', 'OLD_PREMIUM', 'UNBEKANNT']:
        if stats[typ]:
            print(f"\n{typ}:")
            for e in stats[typ][:5]:  # Nur erste 5 zeigen
                exists = "✓" if e["exists"] else "✗"
                print(f"  - Entwurf {e['id']:4d} ({e['status']:12s}): {exists} {os.path.basename(e['pfad'])}")
            if len(stats[typ]) > 5:
                print(f"  ... und {len(stats[typ]) - 5} weitere")

print()
print("=" * 60)
