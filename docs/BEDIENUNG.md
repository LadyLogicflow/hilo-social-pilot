# Bedienung (Dashboard)

HISOME wird komplett über den Browser bedient. Nach der Anmeldung landest du auf der
**Kachel-Startseite** mit dem Arbeitsablauf.

## Anmeldung

Öffne das Dashboard (Adresse vom Betreiber, z.B. über das Pi im lokalen Netz/Tailscale)
und melde dich mit Benutzername und Passwort an. Benutzer werden in der **Verwaltung**
angelegt (nur Admins).

## Der Arbeitsablauf (4 Schritte)

Die Startseite zeigt vier Kacheln – von links nach rechts:

1. **Freigabe: Themen (Stufe 1)** — Hier stehen die vom Radar gefundenen externen News.
   Hake die Themen an, die in die Kampagne sollen (oder „Alle markieren"), dann
   **„Markierte freigeben → Stufe 2"**. Erst dann werden Text und Bild erzeugt – das
   spart Token. (HILO- und BVL-Beiträge erscheinen nicht hier, sie gehen direkt weiter.)
2. **Texte & Bilder erzeugen** — Ein Klick erzeugt für alle ausgewählten Themen die
   Beiträge (läuft im Hintergrund; nach ein bis zwei Minuten die Seite neu laden).
3. **Freigabe: Texte & Bilder (Stufe 2)** — Jeder Entwurf mit Bild und Begleittext.
   Du kannst **freigeben**, **verwerfen** oder mit einem Änderungswunsch **überarbeiten**
   lassen. Freigegebene Beiträge werden automatisch auf den nächsten freien Werktag
   eingeplant.
4. **Einplanung Veröffentlichung** — Freigegebene Beiträge, sortiert nach Termin. Hier
   wählst du die **Beratungsstelle** und veröffentlichst; Bild-CTA und Begleittext werden
   automatisch auf die Stelle personalisiert.

Darunter liegt die Kachel **Content-Kalender**.

## Content-Kalender

Die Monatsansicht zeigt auf einen Blick, was wann geplant ist:

- **blau** = geplanter Beitrag (grün, wenn bereits veröffentlicht)
- **grün** = besonderer Tag (Anlass-Tag)
- **rot** = Fristende

Mit den Pfeilen blätterst du durch die Monate. Der heutige Tag ist hervorgehoben,
Wochenenden sind ausgegraut (an ihnen wird nicht veröffentlicht).

## Zufalls-Pool (Topf)

Für **zeitlose Beiträge**, die immer wieder passen (Wissens-Serie, allgemeine Tipps), gibt es
den **Zufalls-Pool**. Statt jeden Beitrag einzeln einzuplanen, legst du ihn **einmal** in den
Topf – das Tool spielt ihn dann automatisch aus.

- **In den Pool legen:** Schon bei **„3. Freigabe"** (und weiterhin bei **„4. Einplanung"**) hat
  jeder Beitrag den grünen Knopf **„♻️ In den Pool"**. Ein Klick = der Beitrag ist für alle Stellen
  freigegeben und liegt im Topf. Nach dem Klick bleibst du auf der Seite (keine Weiterleitung).
  Auf der Freigabe-Seite gibt es zusätzlich **„♻️ Alle in den Pool"** für alle offenen Entwürfe auf
  einmal.
- **Pool-Seite** (nur über die **Kachel „Zufalls-Pool" auf der Startseite**): zeigt alle Beiträge im
  Topf und bei jedem, **wie oft er schon ausgespielt** wurde. Mit **„Aus dem Pool nehmen"** holst du
  einen Beitrag wieder heraus (er landet zurück bei „4. Einplanung").
- **Automatik:** Das Tool zieht täglich je Beratungsstelle einen Beitrag aus dem Topf – **für
  jede Stelle einen anderen** und **jeden Beitrag je Stelle nur einmal pro Kanal**. Bespielt wird
  nur, was die Stelle hat: Facebook immer, Instagram wo verknüpft, WhatsApp wo eingerichtet
  (WhatsApp-Status täglich, WhatsApp-Kanal an festen Wochentagen). Am Wochenende kommen nur
  leichtere Inhalte (Wissens-Serie). Sind bei einer Stelle weniger als **14** Beiträge übrig,
  warnt die Seite.
- **Wichtig:** Nur **zeitlose** Inhalte in den Topf. Anlass-Tage und Fristen bleiben in der
  Einplanung, weil sie an ein festes Datum gehören.

## Eigene Quellen

Über das Menü **„Eigene Quellen"** wirfst du ein **PDF** oder einen **Link** ein. HISOME
liest den Inhalt, zerlegt ihn in die einzelnen Themen und merkt sie direkt zur
Texterstellung vor. **Wichtig:** nur öffentliche/unkritische Inhalte – keine Mandantendaten.

## Verwaltung (nur Admin)

Über das Menü **„Verwaltung"**:

- **Benutzer** – Redakteure und Freigeber anlegen, aktivieren/deaktivieren.
- **Beratungsstellen** – Name, Ort, Leitung, **Facebook-Seite** und Buchungslink. Die
  Facebook-Seite verknüpft die Stelle für personalisierte Beiträge und die richtige
  Veröffentlichung. Zusätzlich je Stelle: **WhatsApp-Status** (an/aus) und ein
  **WhatsApp-Kanal-Link** – nur damit zieht der Pool für die Stelle auch diese Kanäle.
- **Anlass-Tage** – besondere Tage mit Steuer-Aufhänger (Datum als MM-TT). Fällt der Tag
  aufs Wochenende, erscheint der Beitrag am Freitag davor.
- **Wissens-Serie** – zeitlose Themen, die leere Kalendertage füllen.
- **Bild-Stil** – legt fest, welche der **drei Stile** im Zufalls-Topf sind (je an/aus):
  **Standard** (Foto + Textfeld), **KI-Tafel** (Botschaft auf einer Tafel/einem Rahmen in einer
  Umgebung) und **Kreativ** (kinoreifes Foto ohne Text). Das Tool **mischt automatisch pro Beitrag** –
  du musst nicht umschalten. (Mindestens ein Stil muss aktiv bleiben.)
- **Schauplätze** – die schönen Umgebungen (z.B. „Terrasse am Meer", „Biergarten in München"),
  in denen Tafel/Rahmen stehen. Pflegbar wie die Anlass-Tage; je Eintrag eine Jahreszeit.
- **Träger** – wie die Botschaft präsentiert wird (Tafel, Bilderrahmen, Holzschild, Postkarte …).
  Einzelne Träger an/aus schalten, wenn einer zu oft daneben liegt.
- **Bild-Tool** – welche Bild-KI das Foto macht: **OpenAI (GPT Image 2)** oder **Ideogram**
  (bessere Schrift im Bild; braucht einen eigenen API-Schlüssel).
- **Speicher** – Größe des Foto-Cache + freier Platz auf dem Pi, mit Knopf „Jetzt aufräumen"
  (löscht nur Fotos, die kein aktiver Beitrag mehr braucht).

> **In der Freigabe (Stufe 3)** hat jeder Beitrag den 🎲-Knopf **„Anderes Bild"** – damit
> würfelst du für genau diesen Beitrag einen anderen Stil und erzeugst das Bild neu. **Wichtig:**
> Bei KI-Tafeln den Text vor dem Posten kurz gegenlesen (die Bild-KI kann sich verschreiben).

## Automatik

- **Täglich 7:00 Uhr**: Themen werden automatisch geholt; fällige Fristen-Countdowns,
  Anlass-Beiträge und Wissens-Beiträge entstehen. Du musst nichts manuell anstoßen.
- **Veröffentlichung**: erfolgt erst nach deiner Freigabe – nichts geht ungefragt raus.
