#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Creative Memory - Serien-Vielfalt / Novelty-Kontrolle fuer die ShareNext-Pipeline.

Merkt sich die Kurz-KATEGORIEN (hero_kurz) der zuletzt gewaehlten Gewinner-Motive und stellt
sie der Concept Jury zur Verfuegung, damit sie Routen abwerten kann, die dieselbe Grundidee/
dasselbe Material wiederholen.

WICHTIG (Vorgabe catrin/Chatty 2026-08-25): Diese Historie wird NUR der bewertenden Stufe
(Concept Jury) gezeigt, NIEMALS dem generierenden Creative Director - sonst wuerde das Modell
die alten Motive als Vorlage nehmen und sie erst recht wiederholen (Re-Seeding). Deshalb sind
es bewusst abstrakte Kategorien (z.B. 'Papierdokument-Objekt'), keine konkreten Motiv-Texte.

Spiegelt bewusst den bestehenden _VARIANZ-Mechanismus in art_director.py.
"""
from __future__ import annotations

import json
import logging
import os

from config import DATA_DIR

log = logging.getLogger("hilo.creative_memory")

_MEMORY_PATH = os.path.join(DATA_DIR, "creative_memory.json")
_HISTORY_LEN = 5  # wie viele letzte Gewinner-Kategorien gemerkt werden


def load_recent_heroes() -> list[str]:
    """Laedt die letzten Gewinner-Hero-Kategorien (aeltester zuerst). Leere Liste bei Fehler."""
    try:
        with open(_MEMORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        heroes = data.get("recent_heroes", [])
        return [h for h in heroes if isinstance(h, str) and h.strip()][-_HISTORY_LEN:]
    except Exception:
        return []


def remember_hero(hero_kurz: str) -> None:
    """Haengt eine Gewinner-Hero-Kategorie an die Historie an (dedupliziert, auf _HISTORY_LEN begrenzt)."""
    hero_kurz = (hero_kurz or "").strip()
    if not hero_kurz:
        return
    heroes = load_recent_heroes()
    # gleiche Kategorie nicht doppelt fuehren - ans Ende schieben
    heroes = [h for h in heroes if h.lower() != hero_kurz.lower()] + [hero_kurz]
    heroes = heroes[-_HISTORY_LEN:]
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"recent_heroes": heroes}, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Creative Memory konnte nicht gespeichert werden: %s", e)
