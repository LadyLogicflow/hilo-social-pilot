#!/usr/bin/env python3
"""Setzt ALLE Posts auf bild_stil='standard'."""

import db
import json

conn = db.get_conn()
c = conn.cursor()
c.execute("SELECT id, text FROM entwuerfe")

count = 0
for eid, text_json in c.fetchall():
    if text_json:
        data = json.loads(text_json)
        alter_stil = data.get('bild_stil', 'KEIN')
        if alter_stil != 'standard':
            data['bild_stil'] = 'standard'
            c.execute("UPDATE entwuerfe SET text = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), eid))
            print(f"Post {eid}: {alter_stil} -> standard")
            count += 1

conn.commit()
print(f"\nFertig! {count} Posts auf 'standard' gesetzt.")
