# HISOME – Technischer Funktionsumfang (Stand 2026-06-14)

Technische Zusammenfassung dessen, was **HISOME (HILO Social Media Tool)** aktuell kann.

## 1. Überblick

- **Zweck:** automatisierte Erstellung und Freigabe von Social-Media-Beiträgen für die
  HILO-Beratungsstellen.
- **Betrieb:** Python/Flask-Webanwendung mit SQLite-Datenbank, läuft auf einem
  Raspberry Pi, **komplett über den Browser** bedienbar (kein Terminal nötig).
- **Stack:** Python 3, Flask, SQLite, Pillow (Bildrendering), feedparser/BeautifulSoup
  (Quellen), Anthropic Claude (Texte), optional OpenAI (Foto-Motive).
- **Grundprinzip:** nichts geht ungefragt raus – **Veröffentlichung erst nach menschlicher
  Freigabe**; jede Aktion wird im Audit-Log protokolliert.

## 2. Content-Quellen (vier Streams)

Alle Quellen münden in denselben Freigabe- und Kalender-Prozess:

1. **Aktuelle Nachrichten (Radar):** täglich um 7:00 Uhr automatisch.
   - RSS: HILO-Steuertipps, Bundesfinanzhof (Entscheidungen + News), Haufe.
   - Webseiten-Scraper (kein RSS): BVL Pressemeldungen + dpa-Presseinformationen.
   - **Relevanzfilter:** behält Themen der HILO-Zielgruppe (Arbeitnehmer, Rentner,
     Familien, Vermieter), verwirft Unternehmens-/USt-Themen.
   - **HILO/BVL-Abgleich:** behandeln beide dasselbe Thema, gewinnt HILO; ein bereits
     veröffentlichtes Gegenstück macht das Duplikat zu „erledigt" (kein Doppelpost).
2. **Fristen-Countdown:** gestaffelte Erinnerungen vor den Abgabefristen
   (ohne Berater 31.07.2026; Mitglieder 01.03.2027). Häufigkeit: ab 3 Monaten 1×/Woche,
   letzte 4 Wochen 2×/Woche, letzte Woche täglich – nur werktags. Mit Motiv-Icons
   (Kalender/Wecker/Sanduhr) und den Pflichthinweisen (Mitglieds-Fristverlängerung,
   Verspätungszuschlag ab 25 €/Monat, 6-Wochen-Unterlagenfrist).
3. **Anlass-Tage:** besondere Tage mit Steuer-Aufhänger (z.B. Tag des Bieres → Biersteuer).
   Wochenend-Tage erscheinen am Freitag davor. Liste in der Verwaltung pflegbar.
4. **Wissens-Serie:** zeitlose Themen („Wer muss abgeben?", „Typische Irrtümer" …),
   die leere Kalendertage füllen, damit nie eine Lücke entsteht.

Zusätzlich: **Eigene Quellen** – PDF oder Link einwerfen; HISOME zerlegt den Inhalt
automatisch in einzelne Themen.

## 3. Beitragserstellung

- **Text:** Claude erzeugt strukturierte Beiträge (Überschrift, Stichpunkte, Call-to-Action,
  Begleittext) im HILO-Stil, faktentreu (keine erfundenen Zahlen/Fristen/Adressen).
- **Bild:** programmatisch im **HILO-Referenzdesign v10** gerendert (1080×1080, rauschfrei,
  ohne Bild-Token) – Verlaufsbänder, Logo, rotierender Slogan, CTA. Optionales freigestelltes
  Foto via OpenAI oder gezeichnetes Motiv-Icon.
- **Überarbeiten:** auf Knopfdruck mit Änderungswunsch („Bild freundlicher") neu erzeugen.

## 4. Freigabe-Workflow (Dashboard)

Kachel-Startseite mit 4 Schritten:

1. **Freigabe Themen (Stufe 1):** externe News auswählen, die in die Kampagne sollen
   (spart Token, weil nur Ausgewähltes erzeugt wird). HILO/BVL überspringen diese Stufe.
2. **Texte & Bilder erzeugen:** Generierung läuft im Hintergrund (Subprozess), Dashboard
   bleibt bedienbar.
3. **Freigabe Texte & Bilder (Stufe 2):** Entwürfe freigeben, verwerfen oder überarbeiten.
4. **Einplanung Veröffentlichung:** freigegebene Beiträge veröffentlichen (personalisiert).

## 5. Content-Kalender

- **Monatsansicht** als eigene Kachel: zeigt pro Tag geplante Beiträge (blau, grün wenn
  veröffentlicht), Anlass-Tage (grün) und Fristenden (rot), mit Monats-Navigation.
- **Einplanung:** freigegebene Beiträge werden automatisch auf die nächsten freien
  **Werktage** verteilt (max. 1/Tag, Sa+So frei); Termine sind verschiebbar.

## 6. Personalisierung je Beratungsstelle

Gleiches Bild, aber der **CTA im Bild** nennt die Stelle („…Beratungsstelle Neuss…") und der
**Begleittext** bekommt lokalen Bezug + Buchungslink – deterministisch, ohne zusätzliche
KI-Token. Die Veröffentlichung läuft auf die hinterlegte Facebook-Seite der Stelle.

## 7. Veröffentlichung

- **Facebook:** Foto-Beitrag direkt auf die Seite (umgesetzt).
- **Instagram:** im Code vorbereitet (braucht öffentliche Bild-URL + IG-Token-Freigabe).
- Veröffentlichungen werden protokolliert (Erfolg/Fehler).

## 8. Verwaltung & Rollen

- **Benutzer** mit Rollen: `admin`, `freigeber`, `redakteur`. Freigeben/Veröffentlichen/
  Umplanen nur für Freigeber/Admin.
- **Beratungsstellen:** Name, Ort, Leitung, Facebook-Seite, Buchungslink.
- **Anlass-Tage** und **Wissens-Themen** pflegbar.

## 9. Automatik & Betrieb

- **Täglich 7:00 Uhr:** Radar + fällige Countdowns + Anlass-Beiträge + Wissens-Beiträge
  (eingebauter Scheduler, startet `main.py --daily` als Subprozess).
- **Täglich ab 7:00 Uhr (Zufalls-Pool):** zieht je Beratungsstelle und Kanal (Facebook/
  Instagram) automatisch einen zeitlosen Beitrag aus dem Topf und plant ihn ein – siehe
  Abschnitt „Zufalls-Pool". Läuft genau 1×/Tag, keine Doppel-Einplanung.
- **Robustheit:** schwere Aufgaben laufen in Subprozessen (Webserver blockiert nie),
  SQLite im WAL-Modus mit Timeout (paralleler Zugriff), Sessions überleben Neustarts.

## 10. Sicherheit & Datenschutz

- Geheimnisse (Claude/OpenAI/Facebook) liegen nur in geschützter `secrets.json` (chmod 600),
  nie im Repo, nie im Log.
- Schutz gegen schädliche Links beim URL-Einwurf (keine internen Adressen), Upload-Limit.
- Grundsatz: nur öffentliche/unkritische Inhalte – **keine Mandanten- oder Steuerdaten**.

## 11. Zufalls-Pool (Hybrid-Strategie)

Für **zeitlose Beiträge** (z.B. Wissens-Serie, allgemeine Tipps) gibt es zusätzlich zum festen
Kalender einen **Zufalls-Pool („Topf")**:

- **Einmalige Freigabe für alle Stellen:** Ein freigegebener Beitrag wird über den Knopf
  **„In den Pool"** (Seite „4. Einplanung") in den Topf aufgenommen – danach wird er
  vollautomatisch ausgespielt, ohne tägliches Eingreifen.
- **Tägliche Zufalls-Ziehung:** je Beratungsstelle und Kanal (Facebook/Instagram) wird täglich
  ein Beitrag aus dem Topf gezogen – **für jede Stelle ein anderer**.
- **„Nie doppelt" (Variante 1):** jeder Beitrag erscheint je Stelle **genau einmal pro Kanal**
  (zeitversetzt über mehrere Kanäle erlaubt, nie zweimal auf demselben Kanal). Das Gedächtnis
  dafür ist dauerhaft (kein Rollover).
- **Nachschub-Warnung:** sind bei einer Stelle weniger als **14** ungenutzte Beiträge übrig,
  weist die Pool-Seite darauf hin.
- **Datumsgebundenes bleibt manuell:** Anlass-Tage und Fristen-Countdown laufen weiterhin über
  die Einplanung (nicht über den Topf).

Die menschliche Endkontrolle bleibt gewahrt – sie liegt beim **einmaligen Pool-Eintrag**
(Grundsatz „Veröffentlichung nur nach Freigabe"). WhatsApp-Status/-Kanal sind als nächste
Ausbaustufe vorgesehen.

## 12. Status & Ausblick

**Funktionsfähig:** komplette Inhaltspipeline (Quellen → Text → Bild → Freigabe → Kalender →
Facebook), 4 Content-Streams, Personalisierung, Verwaltung, Automatik.

**Noch offen / nächste Schritte:**
- Facebook-Langzeit-Token (App-Zugangsdaten) für den Dauerbetrieb.
- Instagram-Veröffentlichung scharf schalten (Token mit IG-Freigabe, öffentliche Bild-URL).
- Beratungsstellen-Daten erfassen.
- Optional: automatische Veröffentlichung am geplanten Tag (statt manuell), weitere Kanäle
  (Google, LinkedIn), Newsletter.
