# -*- coding: utf-8 -*-
"""Zentrale, NICHT-geheime Konfiguration. Secrets kommen aus secrets_store."""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("HILO_DATA_DIR", os.path.join(BASE_DIR, "data"))
LOG_DIR  = os.environ.get("HILO_LOG_DIR",  os.path.join(BASE_DIR, "logs"))
DB_PATH  = os.path.join(DATA_DIR, "hilo.db")
SECRETS_FILE = os.environ.get("HILO_SECRETS_FILE", os.path.join(BASE_DIR, "secrets.json"))

TIMEZONE = os.environ.get("HILO_TIMEZONE", "Europe/Berlin")
RUN_HOUR = int(os.environ.get("HILO_RUN_HOUR", "7"))

# WhatsApp-Dienst (eigener Node-/Baileys-Prozess auf demselben Host, nur localhost)
WHATSAPP_URL = os.environ.get("HILO_WHATSAPP_URL", "http://127.0.0.1:8769")

# RSS-/Atom-Quellen
SOURCES = {
    "hilo":     os.environ.get("HILO_SOURCES_HILO", "https://www.hilo.de/steuertipps/feed/"),
    "bfh":      os.environ.get("HILO_SOURCES_BFH", "https://www.bundesfinanzhof.de/de/precedent.rss"),
    "bfh_news": os.environ.get("HILO_SOURCES_BFH_NEWS", "https://www.bundesfinanzhof.de/de/news.rss"),
    "haufe":    os.environ.get("HILO_SOURCES_HAUFE", "https://www.haufe.de/xml/rss_129148.xml"),
    "bmf":      os.environ.get("HILO_SOURCES_BMF",
                "https://www.bundesfinanzministerium.de/SiteGlobals/Functions/RSSFeed/DE/Steuern/RSSSteuern.xml"),
}

# HTML-Quellen ohne RSS (werden gescrapt)
SCRAPE_SOURCES = {
    "bvl_pm":  os.environ.get("HILO_SOURCES_BVL_PM",  "https://www.bvl-verband.de/presse/pressemeldungen"),
    "bvl_dpa": os.environ.get("HILO_SOURCES_BVL_DPA", "https://www.bvl-verband.de/presse/dpa-presseinformationen"),
    "steuerrat24": os.environ.get("HILO_SOURCES_STEUERRAT24", "https://www.steuerrat24.de/steuerrat-aktuell/steuertipp-der-woche.html"),
    # steuertipps.de-Suchseite: 50 Artikel ueber alle relevanten Kategorien, nach Datum sortiert
    # (deckt ~3 Monate ab). Neue Artikel holt der taegliche Radar automatisch nach (Dublettenschutz).
    "steuertipps": os.environ.get("HILO_SOURCES_STEUERTIPPS",
        "https://www.steuertipps.de/suche?query=&size=50&sort=date&type=article&category=all-categories"
        "&category=altersvorsorge-rente-finanzen%2Fthemen&category=finanzamt-formalitaeten%2Fthemen"
        "&category=krankheit-betreuung-pflege%2Fthemen&category=wohnen-haus-vermietung%2Fthemen"
        "&category=beruf-ausbildung%2Fthemen&category=eltern-familie-ehe%2Fthemen"
        "&category=erben-vererben-schenken%2Fthemen&category=steuern-rente"),
}
