# HISOME – Technischer Funktionsumfang (Stand 2026-08-06)

Technische Zusammenfassung dessen, was **HISOME (HILO Social Media Tool)** aktuell kann.

## 1. Überblick

- **Zweck:** automatisierte Erstellung und Freigabe von Social-Media-Beiträgen für die
  HILO-Beratungsstellen.
- **Betrieb:** Python/Flask-Webanwendung mit SQLite-Datenbank, läuft auf einem
  Raspberry Pi, **komplett über den Browser** bedienbar (kein Terminal nötig).
- **Stack:** Python 3, Flask, SQLite, Pillow (Bild-Overlays/CI-Kreise), feedparser/BeautifulSoup
  (Quellen), **Anthropic Claude** (Texte) und **OpenAI** (ShareNext-Bild-Pipeline, `gpt-image-2`).
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

- **Text:** **Claude** (`claude-sonnet-4-6`) erzeugt strukturierte Beiträge (Überschrift,
  Stichpunkte, Call-to-Action, Captions je Kanal) im HILO-Stil, faktentreu (keine erfundenen
  Zahlen/Fristen/Adressen). Ausnahme Fristen-Countdown: Text bleibt bewusst fest vorformuliert
  (rechtlich relevante Fristen/Beträge), nur das Bild kommt von der KI.
- **Bild:** quadratisch, erzeugt in der **ShareNext-Pipeline** (6-stufig: Message Brief →
  Creative Director → Concept Jury → Art Director → Image Producer → Visual QA; Bildmodell
  `gpt-image-2`, siehe [ARCHITEKTUR.md](ARCHITEKTUR.md#bild-design)). Die **Headline schreibt die
  KI direkt ins Bild**; danach setzt der Code nur noch die blau-weißen **CI-Kreise** auf (CI
  garantiert). Über den 🎲-Knopf in der Freigabe lässt sich je Beitrag ein neues Bild erzeugen
  (kein Auto-Retry – kostet bei jedem Klick). Das erzeugte Bild wird für die Personalisierung je
  Beratungsstelle wiederverwendet (kein neuer KI-Call nötig); ungenutzte Cache-Dateien werden
  automatisch aufgeräumt. *(Die alte Pipeline mit den drei Stilen Standard/KI-Tafel/Kreativ +
  Ideogram-Option bleibt als Fallback für Alt-Entwürfe, ist für neue Beiträge aber nicht mehr
  aktiv.)*
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

- **Facebook:** Feed-Beitrag direkt auf die Seite – als Einzelbild oder Karussell; optional
  zusätzlich als **Story** (9:16). Bei Beratungsstellen kommt der Termin-Link automatisch als
  erster Kommentar.
- **Instagram:** Feed-Beitrag (Einzelbild oder Karussell) und optional zusätzlich als **Story**
  (9:16). Zweistufig über Bild-Container → Veröffentlichung; benötigt eine öffentliche Bild-URL
  (automatischer SFTP-Upload) und ein verknüpftes Instagram-Business-Konto.
- **Story-Regel:** Eine Story wird nur **zusätzlich zu einem erfolgreichen Feed-Post** gepostet
  und ist flüchtig (24 h) – sie wird protokolliert, aber nicht als eigener Post verbucht.
- Veröffentlichungen werden protokolliert (Erfolg/Fehler). Details:
  [VEROEFFENTLICHUNG.md](VEROEFFENTLICHUNG.md).

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
- **Tägliche Zufalls-Ziehung:** je Beratungsstelle und Kanal wird täglich ein Beitrag aus dem
  Topf gezogen – **für jede Stelle ein anderer**.
- **Kanal je Stelle:** bespielt wird nur, was die Stelle tatsächlich hat – **Facebook** immer
  (wenn FB-Seite hinterlegt), **Instagram** nur bei verknüpftem IG-Konto, **WhatsApp-Status/
  -Kanal** nur bei eingerichteter WhatsApp-Einstellung. Nicht vorhandene Kanäle werden
  übersprungen (kein Verbrauch, keine Fehlpostings).
- **„Nie doppelt" (Variante 1):** jeder Beitrag erscheint je Stelle **genau einmal pro Kanal**
  (zeitversetzt über mehrere Kanäle erlaubt, nie zweimal auf demselben Kanal). Das Gedächtnis
  dafür ist dauerhaft (kein Rollover).
- **Frequenz je Kanal:** Facebook/Instagram/**WhatsApp-Status** täglich, **WhatsApp-Kanal** nur
  an festen Wochentagen (Standard Di+Fr, per `HILO_WA_KANAL_TAGE` einstellbar).
- **Wochenend-Regel:** am Wochenende werden nur leichtere Inhalte (Wissens-Serie) gezogen –
  abschaltbar per `HILO_POOL_WOCHENEND_FILTER`.
- **Nachschub-Warnung:** sind bei einer Stelle weniger als **14** ungenutzte Beiträge übrig,
  weist die Pool-Seite darauf hin.
- **Datumsgebundenes bleibt manuell:** Anlass-Tage und Fristen-Countdown laufen weiterhin über
  die Einplanung (nicht über den Topf).

Die menschliche Endkontrolle bleibt gewahrt – sie liegt beim **einmaligen Pool-Eintrag**
(Grundsatz „Veröffentlichung nur nach Freigabe").

> **WhatsApp-Hinweis:** Der WhatsApp-Dienst nutzt aktuell **eine** Nummer/Session (nicht je
> Stelle eine eigene). Das Posten läuft über diese eine Nummer; ist der Dienst nicht erreichbar,
> wird der betroffene Beitrag als „Fehler" markiert (kein Absturz). Dedizierte Nummern pro
> Beratungsstelle sind ein späterer Ausbau (Sperr-Restrisiko).

## 12. Status & Ausblick

**Funktionsfähig:** komplette Inhaltspipeline (Quellen → Text → Bild → Freigabe → Kalender →
Facebook & Instagram), 4 Content-Streams, Personalisierung, Verwaltung, Automatik.
Die Veröffentlichung ist für **Facebook und Instagram** implementiert und im Dashboard
verdrahtet – jeweils als Feed (Einzelbild/Karussell) und optional als Story.

**Noch offen / nächste Schritte:**
- Facebook-Langzeit-Token (App-Zugangsdaten) für den Dauerbetrieb.
- Instagram/Story im Live-Betrieb: Token mit IG-Freigabe (`instagram_content_publish`) und die
  öffentliche Bild-URL (IONOS-Upload-Secrets) hinterlegen; die Facebook-Story braucht
  `pages_manage_posts`.
- Beratungsstellen-Daten erfassen.
- Optional: automatische Veröffentlichung am geplanten Tag (statt manuell), weitere Kanäle
  (Google, LinkedIn), Newsletter.
