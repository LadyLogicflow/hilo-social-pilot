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


def _load_list(key: str) -> list[str]:
    try:
        with open(_MEMORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        werte = data.get(key, [])
        return [w for w in werte if isinstance(w, str) and w.strip()][-_HISTORY_LEN:]
    except Exception:
        return []


def load_recent_heroes() -> list[str]:
    """Laedt die letzten Gewinner-Hero-Kategorien (aeltester zuerst). Leere Liste bei Fehler."""
    return _load_list("recent_heroes")


def load_recent_environments() -> list[str]:
    """Laedt die letzten Gewinner-Bedeutungswelten (semantic_environment). Leere Liste bei Fehler."""
    return _load_list("recent_environments")


def _append(werte: list[str], neu: str) -> list[str]:
    neu = (neu or "").strip()
    if not neu:
        return werte
    werte = [w for w in werte if w.lower() != neu.lower()] + [neu]
    return werte[-_HISTORY_LEN:]


def remember(hero_kurz: str, semantic_environment: str = "") -> None:
    """Haengt Gewinner-Hero-Kategorie UND Bedeutungswelt an die Historie an (je dedupliziert,
    auf _HISTORY_LEN begrenzt)."""
    heroes = _append(load_recent_heroes(), hero_kurz)
    envs = _append(load_recent_environments(), semantic_environment)
    if not heroes and not envs:
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"recent_heroes": heroes, "recent_environments": envs}, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Creative Memory konnte nicht gespeichert werden: %s", e)


def remember_hero(hero_kurz: str) -> None:
    """Rueckwaertskompatibel: merkt nur die Hero-Kategorie (ohne Bedeutungswelt)."""
    remember(hero_kurz, "")
