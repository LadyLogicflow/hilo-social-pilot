# -*- coding: utf-8 -*-
"""HTML-Scraper für Steuerrat24 'Steuertipp der Woche' Seite.
Extrahiert alle Steuertipps mit Titel und vollständigem Text."""
import logging
import requests
from bs4 import BeautifulSoup, NavigableString

log = logging.getLogger("hilo.scraper_steuerrat24")

def scrape(url):
    """Scrapt die Steuerrat24 'Steuertipp der Woche' Seite.

    Args:
        url: URL zur Steuertipp-Seite (z.B. https://www.steuerrat24.de/steuerrat-aktuell/steuertipp-der-woche.html)

    Returns:
        Liste von Dicts mit {titel, url, datum, zusammenfassung}
    """
    r = requests.get(url, timeout=30, headers={"User-Agent": "HILO-Pilot/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    items = []

    # Finde alle Überschriften mit "Steuertipp der Woche Nr."
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        heading_text = heading.get_text(strip=True)

        # Nur Steuertipp-Überschriften
        if 'Steuertipp der Woche Nr.' not in heading_text:
            continue

        # Extrahiere Nummer (für Sortierung)
        try:
            # Format: "Steuertipp der Woche Nr. 454: Titel"
            parts = heading_text.split(':', 1)
            if len(parts) != 2:
                continue

            nr_part = parts[0]  # "Steuertipp der Woche Nr. 454"
            titel = parts[1].strip()  # "Titel"

            # Extrahiere Nummer
            nr = int(nr_part.split()[-1])  # Letzte Zahl

        except (ValueError, IndexError):
            log.warning("Konnte Nummer nicht extrahieren aus: %s", heading_text)
            continue

        # Finde den Text-Content
        # Struktur: <div class="page-header"><h3>...</h3></div> → <section>TEXT</section>
        parent = heading.parent
        if not parent:
            continue

        # Suche nächstes <section> Tag nach dem Parent
        content_sections = [s for s in parent.next_siblings
                           if not isinstance(s, NavigableString) and s.name == 'section']

        if not content_sections:
            log.warning("Kein Content-Section gefunden für: %s", heading_text)
            continue

        # Erster <section> ist der Text-Content
        content = content_sections[0].get_text(strip=True)

        # "Weiterlesen …" am Ende entfernen (falls vorhanden)
        if content.endswith("Weiterlesen …"):
            content = content[:-len("Weiterlesen …")].strip()

        # Zusammenfassung: Erste 300 Zeichen
        zusammenfassung = content[:300] + "..." if len(content) > 300 else content

        items.append({
            "titel": titel,
            "url": url,  # Alle Tipps sind auf derselben Seite
            "datum": "",  # Kein Datum verfügbar
            "zusammenfassung": zusammenfassung,
            "volltext": content,  # Vollständiger Text
            "nr": nr,  # Für Sortierung
        })

    # Sortiere nach Nummer (neueste zuerst)
    items.sort(key=lambda x: x.get('nr', 0), reverse=True)

    log.info("Steuerrat24: %d Steuertipps gefunden", len(items))
    return items
