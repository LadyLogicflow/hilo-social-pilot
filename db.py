# -*- coding: utf-8 -*-
"""SQLite-Datenbank: Themen, Entwuerfe, Posts, Log, Benutzer, Audit."""
import os, sqlite3
from config import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS themen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quelle TEXT NOT NULL, titel TEXT NOT NULL, url TEXT,
    veroeffentlicht_am TEXT, erkannt_am TEXT DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'neu', volltext TEXT, hash TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS entwuerfe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thema_id INTEGER REFERENCES themen(id),
    kanal TEXT NOT NULL DEFAULT 'google',
    text TEXT, bild_pfad TEXT,
    status TEXT NOT NULL DEFAULT 'entwurf',
    erstellt_am TEXT DEFAULT (datetime('now')), geplant_fuer TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER REFERENCES entwuerfe(id),
    kanal TEXT NOT NULL, plattform_post_id TEXT,
    veroeffentlicht_am TEXT, status TEXT NOT NULL DEFAULT 'geplant', fehler TEXT
);
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT DEFAULT (datetime('now')), ebene TEXT, nachricht TEXT
);
CREATE TABLE IF NOT EXISTS benutzer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL, passwort_hash TEXT NOT NULL,
    rolle TEXT NOT NULL DEFAULT 'freigeber', aktiv INTEGER NOT NULL DEFAULT 1,
    erstellt_am TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT DEFAULT (datetime('now')),
    benutzer TEXT, aktion TEXT, entwurf_id INTEGER, details TEXT
);
CREATE TABLE IF NOT EXISTS beratungsstellen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL, ort TEXT, leitung TEXT,
    homepage_url TEXT, buchungs_url TEXT, aktiv INTEGER NOT NULL DEFAULT 1,
    erstellt_am TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS anlasstage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datum TEXT NOT NULL,            -- MM-DD
    anlass TEXT UNIQUE NOT NULL, steuer_hook TEXT,
    aktiv INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS wissensthemen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titel TEXT UNIQUE NOT NULL, hook TEXT,
    aktiv INTEGER NOT NULL DEFAULT 1, zuletzt TEXT
);
"""

# Kuratierte Anlass-Tage mit Steuer-Aufhaenger (Startliste, in der Verwaltung erweiterbar)
ANLASS_SEED = [
    ("01-01", "Neujahr", "Was aendert sich steuerlich im neuen Jahr fuer Arbeitnehmer, Rentner und Familien?"),
    ("05-01", "Tag der Arbeit", "Arbeitnehmer-Pauschbetrag und Werbungskosten - was sich von der Steuer absetzen laesst."),
    ("04-23", "Tag des Bieres", "Die Biersteuer - wie viel Steuer in einem Glas Bier steckt (humorvoll, aber serioes)."),
    ("10-31", "Weltspartag", "Der Sparer-Pauschbetrag: bis 1.000 Euro Kapitalertraege steuerfrei (2.000 Euro bei Zusammenveranlagung)."),
    ("12-05", "Tag des Ehrenamts", "Ehrenamts- und Uebungsleiterpauschale - steuerfreie Aufwandsentschaedigungen fuer Ehrenamtliche."),
    ("06-21", "Tag des Gartens", "Haushaltsnahe Dienstleistungen und Handwerkerleistungen - Garten- und Pflegearbeiten von der Steuer absetzen."),
    ("09-21", "Weltalzheimertag", "Pflegekosten und Pflege-Pauschbetrag - steuerliche Entlastung fuer pflegende Angehoerige."),
    ("12-24", "Heiligabend", "Frohe Weihnachten - und der Hinweis: Spenden bis 31.12. mindern noch die Steuer dieses Jahres."),
]

# Zeitlose Wissens-Themen (Evergreen) - fuellen leere Kalendertage
WISSEN_SEED = [
    ("Wer muss eine Steuererklaerung machen?", "Wer ist zur Abgabe verpflichtet, wer gibt freiwillig ab - und warum sich Letzteres oft lohnt."),
    ("Typische Irrtuemer in der Steuererklaerung", "Haeufige Missverstaendnisse rund um die Steuererklaerung und was wirklich stimmt."),
    ("Welche Pauschbetraege gibt es?", "Arbeitnehmer-, Sparer-, Pflege- und weitere Pauschbetraege - ueberblick und Nutzen."),
    ("Werbungskosten fuer Arbeitnehmer", "Was Arbeitnehmer als Werbungskosten absetzen koennen und wann sich Einzelnachweise lohnen."),
    ("Homeoffice-Pauschale einfach erklaert", "Wie die Homeoffice-Pauschale funktioniert und wer sie nutzen kann."),
    ("Steuererklaerung fuer Rentner", "Was Rentnerinnen und Rentner bei der Steuererklaerung beachten sollten."),
    ("Kinderfreibetrag oder Kindergeld?", "Wie das Finanzamt vergleicht und was fuer Familien guenstiger ist."),
    ("Aussergewoehnliche Belastungen", "Krankheits-, Pflege- und weitere Kosten - was als aussergewoehnliche Belastung zaehlt."),
    ("Haushaltsnahe Dienstleistungen absetzen", "Handwerker, Reinigung, Gartenpflege - wie man Arbeitskosten von der Steuer absetzt."),
    ("Entfernungspauschale und Fahrtkosten", "Wie Pendler die Entfernungspauschale nutzen und was absetzbar ist."),
]

def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(themen)")]
    if "volltext" not in cols:
        conn.execute("ALTER TABLE themen ADD COLUMN volltext TEXT")
    bcols = [r[1] for r in conn.execute("PRAGMA table_info(beratungsstellen)")]
    if "fb_seite" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN fb_seite TEXT")
    # R1 Karussell: Format je Beitrag (einzelbild | karussell)
    ecols = [r[1] for r in conn.execute("PRAGMA table_info(entwuerfe)")]
    if "format" not in ecols:
        conn.execute("ALTER TABLE entwuerfe ADD COLUMN format TEXT NOT NULL DEFAULT 'einzelbild'")
    # BVL- und HILO-Meldungen gehoeren nicht in Stufe 1 -> bestehende Eintraege heilen
    conn.execute("UPDATE themen SET status='ausgewaehlt' "
                 "WHERE status='vorgeschlagen' AND quelle IN ('bvl_pm','bvl_dpa','hilo')")

def seed_anlasstage(conn):
    if conn.execute("SELECT COUNT(*) FROM anlasstage").fetchone()[0] == 0:
        conn.executemany("INSERT OR IGNORE INTO anlasstage(datum, anlass, steuer_hook) VALUES (?,?,?)",
                         ANLASS_SEED)

def seed_wissen(conn):
    if conn.execute("SELECT COUNT(*) FROM wissensthemen").fetchone()[0] == 0:
        conn.executemany("INSERT OR IGNORE INTO wissensthemen(titel, hook) VALUES (?,?)", WISSEN_SEED)

def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # gleichzeitiges Lesen/Schreiben (Webserver + Subprozesse)
        conn.executescript(SCHEMA)
        migrate(conn)
        seed_anlasstage(conn)
        seed_wissen(conn)

def audit_log(conn, benutzer, aktion, entwurf_id=None, details=""):
    conn.execute("INSERT INTO audit(benutzer, aktion, entwurf_id, details) VALUES (?,?,?,?)",
                 (benutzer, aktion, entwurf_id, details))
