# -*- coding: utf-8 -*-
"""HTML-Scraper fuer steuertipps.de-Themenseiten (nach Datum sortierte News).

Liest die News-Eintraege (div.news_desc mit <time datetime=ISO>, Titel-Link, Teaser-Absatz) und
liefert nur Beitraege der letzten ~3 Monate. Neue Beitraege werden beim naechsten Radar-Lauf
automatisch ergaenzt - der Dublettenschutz laeuft ueber den Hash im Radar (_store)."""
import datetime
import logging
import re
from urllib.parse import urljoin

# Fuehrendes "[ 24.08.2026 ] …" (Datums-Praefix aus dem <time>-Element) aus dem Teaser entfernen.
_DATUM_PRAEFIX = re.compile(r"^\[\s*\d{1,2}\.\d{1,2}\.\d{4}\s*\]\s*(?:…|\.\.\.)?\s*")

log = logging.getLogger("hilo.scraper.steuertipps")

MAX_ALTER_TAGE = 92   # ~3 Monate


def scrape(url):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, timeout=20, headers={"User-Agent": "HILO-Pilot/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    grenze = datetime.date.today() - datetime.timedelta(days=MAX_ALTER_TAGE)
    items, seen = [], set()
    for t in soup.find_all("time"):
        iso = (t.get("datetime") or "").strip()[:10]
        try:
            d = datetime.date.fromisoformat(iso)
        except Exception:
            d = None
        if d and d < grenze:
            continue   # aelter als 3 Monate -> weglassen
        # Container mit Titel-Link finden (bis zu 5 Ebenen ueber dem <time>)
        cont, a = t, None
        for _ in range(5):
            cont = cont.parent
            if cont is None:
                break
            a = cont.find("a", href=True)
            if a and a.get_text(strip=True):
                break
        if not (a and a.get_text(strip=True)):
            continue
        titel = " ".join(a.get_text(" ", strip=True).split())[:300]
        href = urljoin(url, a["href"])
        if len(titel) < 12 or href in seen:
            continue
        seen.add(href)
        # Teaser = laengster Absatz im Container
        ps = [" ".join(p.get_text(" ", strip=True).split()) for p in cont.find_all("p")]
        ps = [p for p in ps if len(p) > 30]
        teaser = max(ps, key=len) if ps else titel
        teaser = _DATUM_PRAEFIX.sub("", teaser).strip()
        items.append({"titel": titel, "url": href, "datum": iso, "zusammenfassung": teaser[:1500]})
    log.info("steuertipps.de: %d News (<= %d Tage alt) gefunden.", len(items), MAX_ALTER_TAGE)
    return items
