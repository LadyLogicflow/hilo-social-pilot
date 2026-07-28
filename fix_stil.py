#!/usr/bin/env python3
"""Setzt bei allen bestehenden Posts bild_stil auf 'standard'."""

import db
import json

conn = db.get_conn()
c = conn.cursor()
c.execute("SELECT id, fields FROM entwuerfe")

count = 0
for eid, fields_json in c.fetchall():
    if fields_json:
        fields = json.loads(fields_json)
        if fields.get('bild_stil') != 'standard':
            fields['bild_stil'] = 'standard'
            c.execute("UPDATE entwuerfe SET fields = ? WHERE id = ?", (json.dumps(fields), eid))
            print(f"Post {eid}: Stil auf 'standard' gesetzt")
            count += 1

conn.commit()
print(f"\nFertig! {count} Posts aktualisiert.")
