# -*- coding: utf-8 -*-
"""HTML-Scraper fuer BVL-Presseseiten und Steuerrat24 (kein RSS).
BVL: Detail-Links + PDF-Pressemeldungen (Titel aus Umfeld).
Steuerrat24: Steuertipp der Woche mit vollständigem Text."""
import logging
from urllib.parse import urljoin
log = logging.getLogger("hilo.scraper")

def _slug_title(href):
    slug = href.rstrip("/").split("/")[-1].replace("-", " ").strip()
    return (slug[:1].upper() + slug[1:]) if slug else ""

def scrape(url):
    """Scrapt HTML-Seiten ohne RSS-Feed.

    Erkennt automatisch die Quelle und verwendet den passenden Scraper:
    - Steuerrat24: scraper_steuerrat24.scrape()
    - BVL (Default): scrape_bvl()
    """
    # Steuerrat24 Detection
    if "steuerrat24.de" in url.lower():
        import scraper_steuerrat24
        return scraper_steuerrat24.scrape(url)

    # BVL (Default)
    return scrape_bvl(url)

def scrape_bvl(url):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, timeout=20, headers={"User-Agent": "HILO-Pilot/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]; hl = href.lower(); text = a.get_text(" ", strip=True)
        is_detail = ("/presse/" in hl and "/detail/" in hl)
        is_pdf = hl.endswith(".pdf") and "/fileadmin/" in hl
        if not (is_detail or is_pdf):
            continue
        if is_detail:
            title = text if (text and len(text) >= 8 and not text.lower().endswith(".pdf")) else _slug_title(href)
        else:
            cand = text
            if (not cand) or cand.lower() in ("download", "mehr", "weiterlesen", "pdf") or cand.lower().endswith(".pdf") or " " not in cand:
                parent = a.find_parent(["li", "tr", "article", "div", "p"])
                cand = parent.get_text(" ", strip=True).replace("Download", "").strip() if parent else ""
            title = cand
        import re as _re
        title = " ".join((title or "").split())
        title = _re.sub(r"^Presseinfo\s+\S+\s+\d{4}\s*-\s*\d+\s*", "", title).strip()[:160]
        if len(title) < 12 or " " not in title or title.lower().endswith(".pdf"):
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"titel": title, "url": urljoin(url, href), "datum": "", "zusammenfassung": title})
    return items
