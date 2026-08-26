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
CREATE TABLE IF NOT EXISTS geplante_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER NOT NULL,
    stelle_id INTEGER,                 -- Beratungsstelle (NULL bei reiner Facebook-Seite)
    page_id TEXT,                      -- Facebook-Seiten-ID (NULL bei Beratungsstelle)
    kanal TEXT NOT NULL DEFAULT 'facebook',
    format TEXT NOT NULL DEFAULT 'einzelbild',     -- Zusammenfassung (Karussell, wenn ein Kanal Karussell)
    format_fb TEXT DEFAULT 'einzelbild',           -- Bildformat fuer Facebook
    format_ig TEXT DEFAULT 'einzelbild',            -- Bildformat fuer Instagram (Karussell entfernt)
    geplant_am TEXT NOT NULL,          -- lokale deutsche Zeit "YYYY-MM-DDTHH:MM"
    status TEXT NOT NULL DEFAULT 'geplant',   -- geplant | laeuft | veroeffentlicht | fehler
    info TEXT,
    pool INTEGER NOT NULL DEFAULT 0,   -- 1 = aus dem Zufalls-Pool (Beitrag bleibt wiederverwendbar, kein Status-Flip)
    erstellt_am TEXT DEFAULT (datetime('now'))
);
-- Zufalls-Pool ("Topf"): zeitlose, einmal fuer ALLE Beratungsstellen freigegebene Beitraege,
-- aus denen taeglich je Stelle/Kanal zufaellig gezogen wird (Hybrid-Strategie Catrin 2026-06-23).
CREATE TABLE IF NOT EXISTS pool (
    entwurf_id INTEGER PRIMARY KEY,    -- ein freigegebener Entwurf = ein Topf-Beitrag
    aktiv INTEGER NOT NULL DEFAULT 1,  -- 0 = aus dem Topf genommen (nicht mehr ziehbar), bleibt fuer Historie
    freigegeben_am TEXT DEFAULT (datetime('now')),
    freigegeben_von TEXT
);
-- "Nie doppelt"-Gedaechtnis (Variante 1): jeder Beitrag wird je Stelle GENAU EINMAL pro Kanal
-- gezogen. Der UNIQUE-Schluessel verhindert die Doppel-Ausspielung dauerhaft (kein Rollover).
CREATE TABLE IF NOT EXISTS pool_nutzung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER NOT NULL,
    stelle_id INTEGER NOT NULL,
    kanal TEXT NOT NULL,               -- facebook | instagram | whatsapp_status | whatsapp_kanal
    verbraucht_am TEXT DEFAULT (datetime('now')),
    UNIQUE(entwurf_id, stelle_id, kanal)
);
-- Recruiting-Pool (EIGENE Tabellen, damit Steuer- und Recruiting-Beitraege sich NIE vermischen):
-- die taegliche Steuer-Ziehung liest ausschliesslich aus `pool`; Recruiting-Beitraege liegen in
-- `pool_recruiting` und werden nur vom woechentlichen Recruiting-Scheduler gezogen. Struktur bewusst
-- analog zu pool/pool_nutzung, damit die (nun tabellen-parametrisierbaren) pool.py-Funktionen
-- unveraendert wiederverwendbar sind.
CREATE TABLE IF NOT EXISTS pool_recruiting (
    entwurf_id INTEGER PRIMARY KEY,    -- ein freigegebener Recruiting-Entwurf = ein Topf-Beitrag
    aktiv INTEGER NOT NULL DEFAULT 1,  -- 0 = aus dem Topf genommen (nicht mehr ziehbar), bleibt fuer Historie
    freigegeben_am TEXT DEFAULT (datetime('now'))
);
-- "Nie doppelt"-Gedaechtnis fuer Recruiting: jeder Beitrag je Stelle GENAU EINMAL pro Kanal.
CREATE TABLE IF NOT EXISTS pool_nutzung_recruiting (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER NOT NULL,
    stelle_id INTEGER NOT NULL,
    kanal TEXT NOT NULL,               -- facebook | instagram | whatsapp_status
    verbraucht_am TEXT DEFAULT (datetime('now')),
    UNIQUE(entwurf_id, stelle_id, kanal)
);
-- Kanalwerbung-Pool (EIGENE Tabellen, damit Steuer-, Recruiting- und Kanalwerbung-Beitraege sich NIE
-- vermischen): der woechentliche/zufaellige Kanalwerbung-Scheduler zieht ausschliesslich aus
-- `pool_kanalwerbung`. Struktur bewusst analog zu pool/pool_nutzung(_recruiting), damit die
-- tabellen-parametrisierbaren pool.py-Funktionen unveraendert wiederverwendbar sind.
CREATE TABLE IF NOT EXISTS pool_kanalwerbung (
    entwurf_id INTEGER PRIMARY KEY,    -- ein freigegebener Kanalwerbung-Entwurf = ein Topf-Beitrag
    aktiv INTEGER NOT NULL DEFAULT 1,  -- 0 = aus dem Topf genommen (nicht mehr ziehbar), bleibt fuer Historie
    freigegeben_am TEXT DEFAULT (datetime('now'))
);
-- "Nie doppelt"-Gedaechtnis fuer Kanalwerbung: jeder Beitrag je Stelle GENAU EINMAL pro Kanal.
CREATE TABLE IF NOT EXISTS pool_nutzung_kanalwerbung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entwurf_id INTEGER,
    stelle_id INTEGER,
    kanal TEXT,                        -- facebook | instagram
    verbraucht_am TEXT DEFAULT (datetime('now')),
    UNIQUE(entwurf_id, stelle_id, kanal)
);
-- Globale Key-Value-Einstellungen (#132/#143): z.B. 'bild_stil' = 'standard' | 'ki_tafel' | 'kreativ'.
-- Bewusst minimal (Schluessel/Wert), damit weitere globale Schalter ohne Schema-Migration moeglich sind.
CREATE TABLE IF NOT EXISTS einstellungen (
    schluessel TEXT PRIMARY KEY,
    wert TEXT
);
-- Schauplaetze-Bibliothek (#140): schoene, saisonale Umgebungen fuer den KI-Tafel-Look.
-- Die Botschaft steht darin auf einem Bilderrahmen/Tisch-Aufsteller. 20 Seed (5/Jahreszeit),
-- rotierend (zuletzt_genutzt -> 'nie doppelt im Zyklus'), in der Verwaltung editierbar.
CREATE TABLE IF NOT EXISTS schauplaetze (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beschreibung TEXT NOT NULL,
    jahreszeit TEXT NOT NULL,          -- 'fruehling' | 'sommer' | 'herbst' | 'winter'
    aktiv INTEGER NOT NULL DEFAULT 1,
    zuletzt_genutzt TEXT               -- NULL = noch nie genutzt (kommt in der Rotation zuerst dran)
);
-- Traeger-Wechsler (#142): WIE die Botschaft praesentiert wird (Tafel/Rahmen/Holzschild/...).
-- Zweite Abwechslungs-Achse zu den Schauplaetzen; der Traeger ist das DEVICE in der Szene, auf
-- dem der KI-Tafel-Text steht. 16 Seed, hybride Auswahl (Zufall + nie-doppelt-im-Zyklus via
-- zuletzt_genutzt + leichte Themen-Passung), in der Verwaltung editierbar.
CREATE TABLE IF NOT EXISTS traeger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    prompt_snippet TEXT NOT NULL,      -- die Beschreibung des Devices fuer den KI-Tafel-Prompt
    aktiv INTEGER NOT NULL DEFAULT 1,
    zuletzt_genutzt TEXT               -- NULL = noch nie genutzt (kommt in der Rotation zuerst dran)
);
"""

# Kuratierte Anlass-Tage mit Steuer-Aufhaenger (Startliste, in der Verwaltung erweiterbar)
ANLASS_SEED = [
    ("01-01", "Neujahr", "Was ändert sich steuerlich im neuen Jahr für Arbeitnehmer, Rentner und Familien?"),
    ("05-01", "Tag der Arbeit", "Arbeitnehmer-Pauschbetrag und Werbungskosten - was sich von der Steuer absetzen lässt."),
    ("04-23", "Tag des Bieres", "Die Biersteuer - wie viel Steuer in einem Glas Bier steckt (humorvoll, aber seriös)."),
    ("10-31", "Weltspartag", "Der Sparer-Pauschbetrag: bis 1.000 Euro Kapitalerträge steuerfrei (2.000 Euro bei Zusammenveranlagung)."),
    ("12-05", "Tag des Ehrenamts", "Ehrenamts- und Übungsleiterpauschale - steuerfreie Aufwandsentschädigungen für Ehrenamtliche."),
    ("06-21", "Tag des Gartens", "Haushaltsnahe Dienstleistungen und Handwerkerleistungen - Garten- und Pflegearbeiten von der Steuer absetzen."),
    ("09-21", "Weltalzheimertag", "Pflegekosten und Pflege-Pauschbetrag - steuerliche Entlastung für pflegende Angehörige."),
    ("12-24", "Heiligabend", "Frohe Weihnachten - und der Hinweis: Spenden bis 31.12. mindern noch die Steuer dieses Jahres."),
]

# Steuerlicher Contentkalender (von Catrin, 2026-06-14) - besondere Tage mit Steuer-Bezug.
# Einmalig per seed_contentkalender() eingespielt (auch in bereits bestehende DBs).
CONTENT_KALENDER = [
    ("01-11", "Tag des deutschen Apfels", "Sachbezüge und die 50-Euro-Freigrenze für Arbeitnehmer."),
    ("01-28", "Datenschutztag", "Homeoffice-Pauschale und häusliches Arbeitszimmer absetzen."),
    ("02-10", "Safer Internet Day", "Heimcomputer und Arbeitsmittel von der Steuer absetzen."),
    ("03-05", "Energiespar-Tag", "Energetische Sanierung: Steuerbonus nach §35c EStG."),
    ("03-08", "Internationaler Frauentag", "Steuerklassenwahl und Ehegattensplitting."),
    ("04-01", "Tag der älteren Generation", "Rentenbesteuerung und Altersentlastungsbetrag."),
    ("04-23", "Girls' Day", "Ausbildungsfreibetrag und Kindergeld."),
    ("04-28", "Tag für Gesundheit am Arbeitsplatz", "Gesundheitsförderung durch den Arbeitgeber (§3 Nr. 34 EStG)."),
    ("05-03", "Welttag der Pressefreiheit", "Werbungskosten für nebenberufliche Journalisten."),
    ("05-15", "Tag der Familie", "Kinderfreibetrag oder Kindergeld und Betreuungskosten."),
    ("05-27", "Tag des Purzelbaums", "Ist das Fitnessstudio absetzbar? (meistens leider nicht)"),
    ("06-01", "Internationaler Kindertag", "Kinderbetreuungskosten nach §10 Abs. 1 Nr. 5 EStG."),
    ("06-03", "Tag des Fahrrades", "Dienstrad-Leasing und die 0,25-Prozent-Regelung."),
    ("06-20", "Weltflüchtlingstag", "Ehrenamtspauschale für ehrenamtliche Helfer."),
    ("07-26", "Tag der Seenotretter", "Spenden von der Steuer absetzen (§10b EStG)."),
    ("08-07", "Internationaler Tag des Bieres", "Bewirtungskosten und betriebliche Feiern."),
    ("08-12", "Tag der Jugend", "Ausbildungsfreibetrag sowie BAföG und Steuer."),
    ("09-05", "Tag des Kaffees", "Sachbezüge und Bewirtungskosten beim Arbeitgeber."),
    ("09-13", "Tag der Heimat", "Doppelte Haushaltsführung steuerlich nutzen."),
    ("09-25", "Tag der Zahngesundheit", "Zahnarztkosten als außergewöhnliche Belastung."),
    ("10-01", "Tag der Älteren", "Pflegekosten absetzen und Rentenbesteuerung."),
    ("10-17", "Tag gegen Armut", "Grundfreibetrag und steuerliches Existenzminimum."),
    ("10-29", "Welt-Schlaganfall-Tag", "Pflegekosten und Behinderten-Pauschbetrag absetzen."),
    ("10-30", "Weltspartag", "Freistellungsauftrag und Sparer-Pauschbetrag."),
    ("11-05", "Tsunami-Tag", "Spenden nach Katastrophen von der Steuer absetzen."),
    ("11-14", "Weltdiabetestag", "Außergewöhnliche Belastungen und Behinderten-Pauschbetrag."),
    ("11-16", "Vorlesetag", "Sind Nachhilfekosten absetzbar?"),
    ("11-28", "Kauf-Nix-Tag", "Was ist eigentlich NICHT von der Steuer absetzbar?"),
    ("12-05", "Tag der Freiwilligen", "Ehrenamts- und Übungsleiterpauschale."),
    ("12-09", "Anti-Korruptions-Tag", "Bestechungsgelder sind nicht abziehbar (§4 Abs. 5 EStG)."),
]

# Zeitlose Wissens-Themen (Evergreen) - fuellen leere Kalendertage
WISSEN_SEED = [
    ("Wer muss eine Steuererklärung machen?", "Wer ist zur Abgabe verpflichtet, wer gibt freiwillig ab - und warum sich Letzteres oft lohnt."),
    ("Typische Irrtümer in der Steuererklärung", "Häufige Missverständnisse rund um die Steuererklärung und was wirklich stimmt."),
    ("Welche Pauschbeträge gibt es?", "Arbeitnehmer-, Sparer-, Pflege- und weitere Pauschbeträge - Überblick und Nutzen."),
    ("Werbungskosten für Arbeitnehmer", "Was Arbeitnehmer als Werbungskosten absetzen können und wann sich Einzelnachweise lohnen."),
    ("Homeoffice-Pauschale einfach erklärt", "Wie die Homeoffice-Pauschale funktioniert und wer sie nutzen kann."),
    ("Steuererklärung für Rentner", "Was Rentnerinnen und Rentner bei der Steuererklärung beachten sollten."),
    ("Kinderfreibetrag oder Kindergeld?", "Wie das Finanzamt vergleicht und was für Familien günstiger ist."),
    ("Außergewöhnliche Belastungen", "Krankheits-, Pflege- und weitere Kosten - was als außergewöhnliche Belastung zählt."),
    ("Haushaltsnahe Dienstleistungen absetzen", "Handwerker, Reinigung, Gartenpflege - wie man Arbeitskosten von der Steuer absetzt."),
    ("Entfernungspauschale und Fahrtkosten", "Wie Pendler die Entfernungspauschale nutzen und was absetzbar ist."),
]

# Schauplaetze-Bibliothek (#140): 20 schoene Umgebungen, 5 pro Jahreszeit. Echte deutsche Umlaute.
# In der Verwaltung editierbar; seed_schauplaetze() greift nur bei leerer Tabelle (wie seed_wissen).
SCHAUPLATZ_SEED = [
    # fruehling
    ("Blühender Kirschblütengarten mit Holztisch im Morgenlicht", "fruehling"),
    ("Almwiese mit Bergpanorama und ersten Frühlingsblumen", "fruehling"),
    ("Sonnige Caféterrasse mit Tulpen und frischem Grün", "fruehling"),
    ("Park mit blühenden Magnolien und einer Holzbank", "fruehling"),
    ("Heller Wintergarten voller Pflanzen im Sonnenlicht", "fruehling"),
    # sommer
    ("Terrasse mit Blick auf den Sommerstrand am Meer", "sommer"),
    ("Biergarten in München unter schattigen Kastanien", "sommer"),
    ("Weinberg im goldenen Spätsommerlicht", "sommer"),
    ("Holzsteg am See im warmen Abendlicht", "sommer"),
    ("Strandcafé an der Nordsee mit Dünen", "sommer"),
    # herbst
    ("Stadtpark mit buntem Herbstlaub und Holzbank", "herbst"),
    ("Gemütliches Café am Fenster, draußen Herbstregen", "herbst"),
    ("Weinberg in herbstlichen Rottönen", "herbst"),
    ("Waldlichtung mit warmem Herbstlicht", "herbst"),
    ("Hofterrasse mit Kürbissen und Abendsonne", "herbst"),
    # winter
    ("Weihnachtsmarkt mit Lichterglanz", "winter"),
    ("Wohnzimmer mit knisterndem Kaminfeuer und Kerzen", "winter"),
    ("Sonnige Skihütte mit Schnee und Bergblick", "winter"),
    ("Verschneite Altstadtgasse mit Laternen", "winter"),
    ("Gemütliche Stube mit Tee und Schneeblick durchs Fenster", "winter"),
]

# Schauplaetze-Erweiterung (#141): 20 WEITERE Umgebungen, 5 pro Jahreszeit (zusammen mit
# SCHAUPLATZ_SEED dann 40, 10/Jahreszeit). Echte deutsche Umlaute. Additiv per
# seed_schauplaetze_extra() - auch in bereits geseedete DBs (Pi) nachgezogen, idempotent.
SCHAUPLATZ_SEED_EXTRA = [
    # fruehling
    ("Bauerngarten mit Frühlingskräutern und Bienenstock", "fruehling"),
    ("Sonniger Balkon mit Blumenkästen über der Stadt", "fruehling"),
    ("Flussufer mit frischem Grün und kleiner Brücke", "fruehling"),
    ("Gartenlaube mit Frühstückstisch im Grünen", "fruehling"),
    ("Obstwiese mit blühenden Apfelbäumen", "fruehling"),
    # sommer
    ("Bootssteg mit Liegestühlen am Bergsee", "sommer"),
    ("Mediterrane Innenhof-Terrasse mit Olivenbäumen", "sommer"),
    ("Sommerwiese mit Picknickdecke und Sonnenschirm", "sommer"),
    ("Hafenpromenade mit Segelbooten in der Abendsonne", "sommer"),
    ("Dachterrasse zur goldenen Stunde über der Stadt", "sommer"),
    # herbst
    ("Weinstube mit Holzbalken und Kerzenlicht", "herbst"),
    ("Allee mit goldenem Laub und Morgennebel", "herbst"),
    ("Gemütliche Bibliothek mit Lesesessel und Tee", "herbst"),
    ("Markthalle mit Herbstgemüse und warmem Licht", "herbst"),
    ("Berghütte mit Blick auf herbstliche Wälder", "herbst"),
    # winter
    ("Verschneiter Garten mit beleuchtetem Pavillon", "winter"),
    ("Café mit beschlagenen Fenstern und heißer Schokolade", "winter"),
    ("Holzchalet mit Fellen und Blick auf schneebedeckte Gipfel", "winter"),
    ("Eislauf-Szene auf einem zugefrorenen See", "winter"),
    ("Festlich gedeckter Wintertisch mit Tannenzweigen und Lichtern", "winter"),
]

# Traeger-Wechsler (#142): 16 Botschafts-Traeger (das DEVICE in der Szene). Echte deutsche Umlaute.
# In der Verwaltung editierbar; seed_traeger() greift nur bei leerer Tabelle (Muster wie seed_wissen).
# prompt_snippet beschreibt das Device fuer den KI-Tafel-Prompt (steht spaeter als Schild-/Tafel-Objekt
# in der Schauplatz-Szene, traegt den vollen sign_text).
TRAEGER_SEED = [
    ("Kreidetafel", "eine schwarze Kreidetafel mit sauberer, gut lesbarer heller Kreideschrift"),
    ("Bilderrahmen/Aufsteller", "ein eleganter heller Bilderrahmen bzw. Tisch-Aufsteller, der Text in HILO-Dunkelblau, serifenlos, klar lesbar"),
    ("Rustikales Holzschild", "ein rustikales Holzschild mit gut lesbarer, dunkler Schrift"),
    ("Plakat an der Wand", "ein gerahmtes helles Plakat an der Wand, der Text in HILO-Dunkelblau, klar lesbar"),
    ("Café-Aufstelltafel (A-Schild)", "eine Café-Aufstelltafel (A-Schild) mit sauberer Kreideschrift"),
    ("Pinnwand mit Notizzettel", "eine Pinnwand mit einem großen hellen Notizzettel, der Text in HILO-Dunkelblau gut lesbar"),
    ("Beschriftete Glastafel", "eine moderne Glastafel, mit Stift in HILO-Dunkelblau klar beschriftet"),
    ("Aufgeschlagenes Notizbuch", "ein aufgeschlagenes Notizbuch auf dem Tisch mit sauberer, gut lesbarer Handschrift in Dunkelblau"),
    ("Whiteboard", "ein Whiteboard mit klarer HILO-Dunkelblauer Marker-Schrift"),
    ("Vintage-Emaille-Schild", "ein Vintage-Emaille-Schild im Retro-Stil mit klarer, gut lesbarer Schrift"),
    ("Edle Schiefertafel", "eine edle, gerahmte Schiefertafel mit sauberer heller Kreideschrift"),
    ("Klemmbrett", "ein Klemmbrett mit einem hellen beschrifteten Blatt, der Text in Dunkelblau gut lesbar"),
    ("Cinema-Leuchtkasten", "ein Cinema-Leuchtkasten mit klaren Steckbuchstaben, gut lesbar"),
    ("Festliches Stoffbanner", "ein festliches helles Stoffbanner mit gut lesbarer Schrift in HILO-Dunkelblau"),
    ("Große Postkarte", "eine große helle Postkarte auf dem Tisch mit gut lesbarer Schrift in Dunkelblau"),
    ("Magnettafel", "eine Magnettafel, auf der Buchstaben-Magneten die Botschaft bilden, gut lesbar"),
]

# --- Einmalige Umlaut-Korrektur fuer bereits bestehende DBs (Pi) -------------
# Die urspruenglichen Seeds nutzten ASCII-Umschreibungen (ae/oe/ue/ss). seed_*()
# greift nur bei leerer Tabelle - bestehende DBs behalten sonst die alten Werte.
# fix_seed_umlaute() ersetzt sie durch echte Umlaute, matcht dabei den ALTEN Wert
# -> idempotent (laeuft nach der Korrektur ins Leere) und ueberschreibt keine
# spaeteren Nutzer-Aenderungen. Reihenfolge identisch zu ANLASS_SEED/WISSEN_SEED.
_ANLASS_SEED_OLD = [
    ("Neujahr", "Was aendert sich steuerlich im neuen Jahr fuer Arbeitnehmer, Rentner und Familien?"),
    ("Tag der Arbeit", "Arbeitnehmer-Pauschbetrag und Werbungskosten - was sich von der Steuer absetzen laesst."),
    ("Tag des Bieres", "Die Biersteuer - wie viel Steuer in einem Glas Bier steckt (humorvoll, aber serioes)."),
    ("Weltspartag", "Der Sparer-Pauschbetrag: bis 1.000 Euro Kapitalertraege steuerfrei (2.000 Euro bei Zusammenveranlagung)."),
    ("Tag des Ehrenamts", "Ehrenamts- und Uebungsleiterpauschale - steuerfreie Aufwandsentschaedigungen fuer Ehrenamtliche."),
    ("Tag des Gartens", "Haushaltsnahe Dienstleistungen und Handwerkerleistungen - Garten- und Pflegearbeiten von der Steuer absetzen."),
    ("Weltalzheimertag", "Pflegekosten und Pflege-Pauschbetrag - steuerliche Entlastung fuer pflegende Angehoerige."),
    ("Heiligabend", "Frohe Weihnachten - und der Hinweis: Spenden bis 31.12. mindern noch die Steuer dieses Jahres."),
]
_WISSEN_SEED_OLD = [
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

def fix_seed_umlaute(conn):
    """Ersetzt in bestehenden DBs die ASCII-Umschreibungen der urspruenglichen Seeds durch
    echte Umlaute. Matcht den ALTEN Wert -> idempotent + kein Ueberschreiben von Nutzer-Aenderungen.
    One-Shot-Migration: kann entfernt werden, sobald alle bestehenden DBs korrigiert sind."""
    # Positionsweise Paarung OLD<->NEU absichern (faengt versehentliches Verrutschen der Listen ab)
    assert len(_ANLASS_SEED_OLD) == len(ANLASS_SEED) and len(_WISSEN_SEED_OLD) == len(WISSEN_SEED)
    for (anlass, alt_hook), (_, _, neu_hook) in zip(_ANLASS_SEED_OLD, ANLASS_SEED):
        conn.execute("UPDATE anlasstage SET steuer_hook=? WHERE anlass=? AND steuer_hook=?",
                     (neu_hook, anlass, alt_hook))
    for (alt_titel, alt_hook), (neu_titel, neu_hook) in zip(_WISSEN_SEED_OLD, WISSEN_SEED):
        conn.execute("UPDATE wissensthemen SET titel=?, hook=? WHERE titel=? AND hook=?",
                     (neu_titel, neu_hook, alt_titel, alt_hook))

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
    # Kreisportraet je Beratungsstelle: optionales Bild, das im gerenderten Beitrag den
    # blauen Slogan-Kreis ersetzt (leer = blauer Punkt).
    if "portrait_pfad" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN portrait_pfad TEXT")
    # Facebook-Orts-ID (Place ID) je Stelle - fuer den Instagram-Geotag beim Posten
    if "ort_id" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN ort_id TEXT")
    # Comic-Portrait der Leitung je Stelle (Stil "Comic Beratung", Setup-Schritt): aus dem
    # vorhandenen Leitungs-Foto (portrait_pfad) erzeugtes Comic-Portrait. Nur ueber login-geschuetzte
    # Routen ausgeliefert (echtes Gesicht, DSGVO), gespeichert unter DATA_DIR/berater/comic_<id>.png.
    if "berater_comic" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN berater_comic TEXT")
    # Character-Bible je Stelle (#151, Stil "Comic Beratung"): eine hochgeladene Comic-/Stylesheet-
    # Vorlage (bibel_bild) sowie eine Charakter-Beschreibung (bibel_text). Ist ein bibel_bild
    # hinterlegt, wird es beim comic_beratung-Rendern als ERSTE (Berater-)Referenz genutzt (Vorrang
    # vor dem aus dem Foto abgeleiteten berater_comic); bibel_text wird an den Prompt angehaengt.
    # Das Bild kann echte Personen zeigen -> nur ueber login-geschuetzte Routen ausgeliefert (DSGVO),
    # gespeichert unter DATA_DIR/bibeln/stelle_<id>.png. Die globale Finanzamt-Bible liegt in den
    # Einstellungen (finanzamt_bibel_bild/finanzamt_bibel_text), braucht also kein neues Schema.
    if "bibel_bild" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN bibel_bild TEXT")
    if "bibel_text" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN bibel_text TEXT")
    # WhatsApp-Kanal je Stelle (Pool Phase 3, #127): Einladungslink des WhatsApp-Kanals der Stelle.
    # Gesetzt = die Stelle hat einen WhatsApp-Kanal -> wird bei der Pool-Ziehung bespielt; leer = nicht.
    if "wa_kanal_invite" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN wa_kanal_invite TEXT")
    # WhatsApp-Status je Stelle (Pool Phase 3, #127): Marker, dass die Stelle WhatsApp-Status nutzt.
    # 1 = Stelle hat eine eigene WhatsApp-Nummer/Session fuer Status -> taeglich bespielen; 0/NULL = nicht.
    # Hinweis: Der WhatsApp-Dienst (whatsapp/server.mjs) faehrt aktuell EINE globale Baileys-Sitzung;
    # dieser Marker steuert nur, OB fuer die Stelle gezogen wird (Single-Source-Sende-Limitierung siehe MR).
    if "wa_status_aktiv" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN wa_status_aktiv INTEGER NOT NULL DEFAULT 0")
    # WhatsApp-Kanal-Posterin (geteilter Kanal): Haben mehrere Stellen DENSELBEN Kanal-Link hinterlegt,
    # postet nur die markierte Stelle die Kanal-Beitraege -> verhindert Doppel-Posts im gemeinsamen Kanal.
    # Der Status-Funnel (Einladung zum Kanal) bleibt bei allen Stellen. 0/NULL = postet nicht selbst.
    if "wa_kanal_poster" not in bcols:
        conn.execute("ALTER TABLE beratungsstellen ADD COLUMN wa_kanal_poster INTEGER NOT NULL DEFAULT 0")
    # R1 Karussell: Format je Beitrag (einzelbild | karussell)
    ecols = [r[1] for r in conn.execute("PRAGMA table_info(entwuerfe)")]
    if "format" not in ecols:
        conn.execute("ALTER TABLE entwuerfe ADD COLUMN format TEXT NOT NULL DEFAULT 'einzelbild'")
    # Format pro Kanal bei geplanten Veroeffentlichungen
    gcols = [r[1] for r in conn.execute("PRAGMA table_info(geplante_posts)")]
    if gcols and "format_fb" not in gcols:
        conn.execute("ALTER TABLE geplante_posts ADD COLUMN format_fb TEXT DEFAULT 'einzelbild'")
    if gcols and "format_ig" not in gcols:
        conn.execute("ALTER TABLE geplante_posts ADD COLUMN format_ig TEXT DEFAULT 'einzelbild'")
    # Zufalls-Pool: Markierung, dass ein geplanter Post aus dem Topf stammt (Beitrag bleibt wiederverwendbar)
    if gcols and "pool" not in gcols:
        conn.execute("ALTER TABLE geplante_posts ADD COLUMN pool INTEGER NOT NULL DEFAULT 0")
    # Insights/Auswertung: Reichweite + Interaktionen je veroeffentlichtem Post, plus die
    # Facebook-Seiten-ID (fuer den Insights-Abruf ueber das Seiten-Token noetig).
    pcols = [r[1] for r in conn.execute("PRAGMA table_info(posts)")]
    if "seite" not in pcols:
        conn.execute("ALTER TABLE posts ADD COLUMN seite TEXT")
    if "reichweite" not in pcols:
        conn.execute("ALTER TABLE posts ADD COLUMN reichweite INTEGER")
    if "interaktionen" not in pcols:
        conn.execute("ALTER TABLE posts ADD COLUMN interaktionen INTEGER")
    if "insights_am" not in pcols:
        conn.execute("ALTER TABLE posts ADD COLUMN insights_am TEXT")
    if "insights_status" not in pcols:
        # NULL = normal abrufbar; 'nicht_verfuegbar' = von Facebook dauerhaft nicht mehr lieferbar
        # (geloescht / von der aktuellen Metrik nicht unterstuetzt) -> nicht mehr abfragen/als Fehler zaehlen.
        conn.execute("ALTER TABLE posts ADD COLUMN insights_status TEXT")
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

def seed_schauplaetze(conn):
    """Spielt die 20 Start-Schauplaetze ein - NUR bei leerer Tabelle (Muster wie seed_wissen).
    Bestehende/editierte Listen bleiben unangetastet."""
    if conn.execute("SELECT COUNT(*) FROM schauplaetze").fetchone()[0] == 0:
        conn.executemany("INSERT INTO schauplaetze(beschreibung, jahreszeit) VALUES (?,?)",
                         SCHAUPLATZ_SEED)

def seed_schauplaetze_extra(conn):
    """Spielt die 20 ZUSAETZLICHEN Schauplaetze (#141) EINMALIG ein - auch in bereits
    bestehende DBs (Muster wie seed_contentkalender, anders als seed_schauplaetze, das nur
    bei leerer Tabelle greift). Der Sentinel-Eintrag (erste neue Beschreibung) verhindert
    erneutes Einspielen; manuell von Catrin geloeschte Eintraege bleiben geloescht.
    'WHERE NOT EXISTS' je Eintrag -> idempotent (zweiter Lauf legt keine Duplikate an) und
    bereits vorhandene gleiche Beschreibungen bleiben unveraendert."""
    sentinel = SCHAUPLATZ_SEED_EXTRA[0][0]
    if conn.execute("SELECT 1 FROM schauplaetze WHERE beschreibung=?", (sentinel,)).fetchone():
        return
    for beschreibung, jahreszeit in SCHAUPLATZ_SEED_EXTRA:
        conn.execute(
            "INSERT INTO schauplaetze(beschreibung, jahreszeit) "
            "SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM schauplaetze WHERE beschreibung=?)",
            (beschreibung, jahreszeit, beschreibung))

def seed_traeger(conn):
    """Spielt die 16 Start-Traeger ein - NUR bei leerer Tabelle (Muster wie seed_wissen/
    seed_schauplaetze). Bestehende/editierte Listen bleiben unangetastet."""
    if conn.execute("SELECT COUNT(*) FROM traeger").fetchone()[0] == 0:
        conn.executemany("INSERT INTO traeger(name, prompt_snippet) VALUES (?,?)", TRAEGER_SEED)

def seed_contentkalender(conn):
    """Spielt Catrins Steuer-Contentkalender EINMALIG ein - auch in bereits bestehende DBs
    (anders als die seed_*-Startlisten, die nur bei leerer Tabelle greifen). Sentinel-Eintrag
    'Datenschutztag' verhindert erneutes Einspielen; manuell geloeschte Tage bleiben geloescht.
    INSERT OR IGNORE: Namensgleiche Tage (UNIQUE anlass) bleiben unveraendert erhalten."""
    if conn.execute("SELECT 1 FROM anlasstage WHERE anlass=?", ("Datenschutztag",)).fetchone():
        return
    conn.executemany("INSERT OR IGNORE INTO anlasstage(datum, anlass, steuer_hook) VALUES (?,?,?)",
                     CONTENT_KALENDER)

def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # gleichzeitiges Lesen/Schreiben (Webserver + Subprozesse)
        conn.executescript(SCHEMA)
        migrate(conn)
        seed_anlasstage(conn)
        seed_wissen(conn)
        seed_schauplaetze(conn)
        seed_schauplaetze_extra(conn)
        seed_traeger(conn)
        seed_contentkalender(conn)
        fix_seed_umlaute(conn)

def audit_log(conn, benutzer, aktion, entwurf_id=None, details=""):
    conn.execute("INSERT INTO audit(benutzer, aktion, entwurf_id, details) VALUES (?,?,?,?)",
                 (benutzer, aktion, entwurf_id, details))

def get_einstellung(schluessel, default=None):
    """Liest eine globale Einstellung (Key-Value). Fehlt der Schluessel, wird 'default'
    geliefert. Oeffnet bei Bedarf eine eigene Verbindung - kein Aufruferzustand noetig."""
    with get_conn() as conn:
        row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel=?",
                           (schluessel,)).fetchone()
    if row is None or row["wert"] is None:
        return default
    return row["wert"]

def set_einstellung(schluessel, wert):
    """Setzt (oder ueberschreibt) eine globale Einstellung. Wert wird als Text gespeichert."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO einstellungen(schluessel, wert) VALUES (?,?) "
            "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert",
            (schluessel, None if wert is None else str(wert)))
        conn.commit()
