#!/usr/bin/env python3
"""Setzt bei allen bestehenden Posts bild_stil auf 'standard'."""

import db
import json

conn = db.get_conn()
c = conn.cursor()
c.execute("SELECT id, text FROM entwuerfe")

count = 0
for eid, text_json in c.fetchall():
    if text_json:
        data = json.loads(text_json)
        if data.get('bild_stil') != 'standard':
            data['bild_stil'] = 'standard'
            c.execute("UPDATE entwuerfe SET text = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), eid))
            print(f"Post {eid}: Stil auf 'standard' gesetzt")
            count += 1

conn.commit()
print(f"\nFertig! {count} Posts aktualisiert.")
