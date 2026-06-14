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

## Eigene Quellen

Über das Menü **„Eigene Quellen"** wirfst du ein **PDF** oder einen **Link** ein. HISOME
liest den Inhalt, zerlegt ihn in die einzelnen Themen und merkt sie direkt zur
Texterstellung vor. **Wichtig:** nur öffentliche/unkritische Inhalte – keine Mandantendaten.

## Verwaltung (nur Admin)

Über das Menü **„Verwaltung"**:

- **Benutzer** – Redakteure und Freigeber anlegen, aktivieren/deaktivieren.
- **Beratungsstellen** – Name, Ort, Leitung, **Facebook-Seite** und Buchungslink. Die
  Facebook-Seite verknüpft die Stelle für personalisierte Beiträge und die richtige
  Veröffentlichung.
- **Anlass-Tage** – besondere Tage mit Steuer-Aufhänger (Datum als MM-TT). Fällt der Tag
  aufs Wochenende, erscheint der Beitrag am Freitag davor.
- **Wissens-Serie** – zeitlose Themen, die leere Kalendertage füllen.

## Automatik

- **Täglich 7:00 Uhr**: Themen werden automatisch geholt; fällige Fristen-Countdowns,
  Anlass-Beiträge und Wissens-Beiträge entstehen. Du musst nichts manuell anstoßen.
- **Veröffentlichung**: erfolgt erst nach deiner Freigabe – nichts geht ungefragt raus.
