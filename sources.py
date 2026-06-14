# -*- coding: utf-8 -*-
"""Quellen-Registry fuer den Themen-Radar. Konfiguration via .env (HILO_SOURCES_*)."""
from config import SOURCES

def configured_sources():
    """Nur Quellen mit hinterlegter URL zurueckgeben."""
    return {name: url for name, url in SOURCES.items() if url}
