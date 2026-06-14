# -*- coding: utf-8 -*-
"""Eigene Quellen: PDF-Dateien und Links aufnehmen, Text extrahieren, in einzelne
Themen zerlegen und als Thema ablegen. Eigene Quellen sind bereits ausgewaehlt
(Status 'ausgewaehlt' -> direkt zur Texterstellung, ohne Stufe 1).
Hinweis: NUR oeffentliche/unkritische Inhalte - keine Mandantendaten."""
import hashlib, logging, os
from db import get_conn

log = logging.getLogger("hilo.ingest")

def _store_topic(quelle, titel, url, volltext):
    key = "%s|%s|manual" % (url or "", titel)
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO themen(quelle, titel, url, status, volltext, hash) "
            "VALUES (?,?,?, 'ausgewaehlt', ?, ?)",
            (quelle, titel[:300], url, volltext, h),
        )
        return cur.rowcount  # 1 = neu, 0 = Dublette

def _ingest_text(quelle, basis_titel, url, volltext):
    """Zerlegt den Text in einzelne Themen (via Claude) und legt jedes als Thema ab.
    Faellt auf ein einzelnes Thema zurueck, wenn keine Zerlegung moeglich ist.
    Rueckgabe: Anzahl neu angelegter Themen."""
    import textgen  # lazy
    topics = []
    try:
        topics = textgen.extract_topics(volltext, basis_titel)
    except Exception as ex:
        log.warning("Themen-Extraktion fehlgeschlagen (%s) - lege als ein Thema ab.", ex)
    if not topics:
        n = _store_topic(quelle, basis_titel, url, volltext)
        log.info("Eigene Quelle (%s): 1 Thema gespeichert: %s", quelle, basis_titel[:80])
        return n
    neu = 0
    for t in topics:
        inhalt = t.get("inhalt") or volltext[:1500]
        neu += _store_topic(quelle, t["titel"], url, inhalt)
    log.info("Eigene Quelle (%s): %d Themen aus '%s' extrahiert (%d neu).",
             quelle, len(topics), basis_titel[:60], neu)
    return neu

def add_pdf(path):
    from pypdf import PdfReader  # lazy
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    titel = os.path.splitext(os.path.basename(path))[0]
    return _ingest_text("pdf", titel, None, text)

def _pruefe_url(url):
    """Laesst nur oeffentliche http(s)-URLs zu (Schutz vor SSRF auf interne Adressen)."""
    import ipaddress, socket
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Nur http(s)-Links mit Hostnamen sind erlaubt.")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except Exception:
        raise ValueError("Hostname nicht aufloesbar.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Interne/private Adressen sind nicht erlaubt.")

def add_url(url):
    import requests  # lazy
    from bs4 import BeautifulSoup  # lazy
    _pruefe_url(url)
    resp = requests.get(url, timeout=20, headers={"User-Agent": "HILO-Pilot/1.0"})
    resp.raise_for_status()
    if len(resp.content) > 5 * 1024 * 1024:   # max 5 MB
        raise ValueError("Inhalt zu gross (max 5 MB).")
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.extract()
    titel = (soup.title.string.strip() if soup.title and soup.title.string else url)
    text = " ".join(soup.get_text(" ").split())
    return _ingest_text("link", titel, url, text)
