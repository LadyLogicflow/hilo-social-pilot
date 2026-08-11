# Prompt-Changelog

Jede inhaltliche Regel-Änderung an den ShareNext-Pipeline-Prompts (`message_brief.py`,
`creative_director.py`, `concept_jury.py`, `art_director.py`, `image_producer.py`,
`visual_qa.py`) wird hier mit Datum, Anlass und betroffenen Dateien festgehalten.

**Zweck:** Regeln entstehen fast immer als Reaktion auf ein konkretes schlechtes Bild - das
ist richtig, führt aber ohne Gegenkontrolle dazu, dass immer neue Einschränkungen aufgehäuft
werden, ohne dass alte je wieder in Frage gestellt werden (Regel-Anhäufung ohne Regel-Hygiene).
Dieses Dokument macht sichtbar, *warum* eine Regel existiert, damit man später gezielt fragen
kann: "Ist das noch nötig, oder schränkt das inzwischen mehr ein, als es nützt?"

Bitte bei jeder neuen Regel einen Eintrag ergänzen (oben anfügen, neueste zuerst):
Datum, betroffene Datei(en), konkretes Bildproblem das behoben wird, Kurzbeschreibung der
Änderung.

---

## 2026-08-11 – Ursache statt Symptom: Kernaussage plattet auf "Geld sparen" (achte Runde)

**Anlass:** Nutzer beobachtete, dass beim wiederholten Neu-Generieren AUS DEMSELBEN bereits
erzeugten Text (Ueberschrift, Bullets, Begleittext unveraendert) immer wieder Euro-Symbol-
Objekte entstanden (Euro-Kuchen, Euro-Schokolade, Schluessel mit Euro-Bart, 3D-Euro-Zeichen)
und fragte, ob der TEXT selbst die Ursache ist - nicht nur die Bild-Prompts. Textabgleich
bestaetigt das: beide betroffenen Texte sind durchgehend Geld-Vokabular ("bares Geld
verschenken", "Steuergeld", "Gehaltsbonus", "spart... echtes Geld"). Das Message Brief
reduziert das vermutlich auf eine generische "Geld sparen"-Kernaussage, die der Bildregie kaum
einen anderen Ansatzpunkt laesst als ein Geld-Symbol - genau das Euro-Symbol, das wir in Runde 1
selbst explizit als "kein Klischee" freigegeben hatten und das jetzt dadurch zum neuen Reflex
wurde.

**Umgesetzt:**

1. `message_brief.py`: neue Regel "KERNAUSSAGE NICHT AUF GELD SPAREN PLATTDRUECKEN" - das
   Modell soll den spezifischsten/ueberraschendsten inhaltlichen Aufhaenger aus dem Text
   extrahieren (z.B. die rechtliche Unterscheidung eigene Eltern vs. Schwiegereltern, oder dass
   Erholungsbeihilfe auch Ehegatte/Kinder einschliesst) statt die generische Geld-Ebene als
   Kernaussage zu verwenden. Das ist der Fix an der WURZEL der Pipeline, nicht nur am Symptom.
2. `creative_director.py`: NICHT geaendert wie urspruenglich geplant - der Nutzer hat die
   Ruecknahme der "Euro-Symbol ist kein Klischee"-Freigabe aus Runde 1 ausdruecklich gestoppt
   ("noch nicht zuruecknehmen"), um erst zu testen, ob der message_brief.py-Fix allein (Ursache
   statt Symptom) das Problem schon behebt, bevor zusaetzlich am Symptom nachgeschaerft wird.
   Nur ein Formatierungsfehler behoben (fehlender Zeilenumbruch nach der Ueberschrift
   "ABGENUTZTE BILDSPRACHE") - inhaltlich unveraendert.

**Lehre:** Diese Runde bestaetigt das Muster aus der vierten Runde nochmal auf einer anderen
Ebene - nicht nur einzelne Beispiele werden vom Modell generalisiert, sondern auch eine ZU
GENERISCHE vorgelagerte Kernaussage (Message Brief) zwingt alle nachfolgenden Stufen in
denselben engen Loesungsraum, unabhaengig davon wie gut deren eigene Prompts sind. Der
wirksamste Hebel gegen ein Wiederholungsmuster liegt manchmal nicht in der Stufe, die das
Symptom zeigt (Image Producer), sondern eine oder mehrere Stufen davor (Message Brief).

**Nicht geprueft:** Keine echte Bildgenerierung moeglich in dieser Umgebung.

---

## 2026-08-11 – Hoheitszeichen-Regel auf fremde Logos erweitert (siebte Runde)

**Anlass:** Ein Bild zu "Kindergeld weg" zeigte einen Brief-Umschlag mit deutlich lesbarem
"Agentur für Arbeit"-Logo - ein echtes Behoerdenlogo, kein Hoheitszeichen im engeren Sinne
(anders als der Bundesadler-Fall der fuenften Runde), aber derselbe Grundkonflikt: ein echtes
fremdes Institutions-Kennzeichen im Bild.

**Umgesetzt:** Die Regel aus der fuenften Runde in allen drei Dateien erweitert - nicht mehr
nur "keine Hoheitszeichen", sondern "keine Hoheitszeichen UND keine echten Institutions-/
Marken-Logos" (Behoerden, Banken, Versicherungen, andere Firmen), jeweils außer HILO:

1. `image_producer.py`: Prioritaet-A-Regel erweitert.
2. `creative_director.py`: Hinweis in der Konzeptphase erweitert.
3. `visual_qa.py`: Pydantic-Feld umbenannt von `enthaelt_hoheitszeichen` zu
   **`enthaelt_fremdes_kennzeichen`** (deckt jetzt beides ab), bleibt hartes
   Ausschlusskriterium unabhaengig vom Score. System-Prompt, User-Prompt und Freigabe-Regel-
   Text entsprechend nachgezogen.

**Nicht geprueft:** Keine echte Bildgenerierung moeglich in dieser Umgebung - insbesondere
nicht verifiziert, ob das Vision-Modell kleine/teilverdeckte Logos (wie auf einem Umschlag)
zuverlaessig erkennt.

---

## 2026-08-11 – Themenbezogener Slogan (sechste Runde)

**Anlass:** Nutzer bemaengelte, dass der Slogan im blauen Kreis nicht zum Thema des jeweiligen
Beitrags passt. Zwei Ursachen gefunden:

1. `textgen.py::_build_prompt()` (aktiver Text-Generierungs-Prompt fuer neue Beitraege) gab dem
   Slogan-Feld keinerlei inhaltliche Vorgabe - nur "max 3 Woerter oder leer". Claude lieferte
   dadurch beliebige austauschbare Floskeln unabhaengig vom Thema.
2. **Bug:** `textgen.py::_create_drafts()` (Bilderzeugung fuer NEU erstellte Beitraege) rief
   `bildgen.pick_slogan("")` mit hartcodiertem leeren String auf - der von Claude gerade erst
   generierte, themenbezogene Slogan (`data["slogan"]`) wurde dadurch nie verwendet, stattdessen
   IMMER zufaellig aus der generischen 6er-Standardliste gezogen. Nur beim spaeteren Klick auf
   "Nur Foto neu erzeugen" (anderer Code-Pfad in `web.py`) wurde der echte Slogan respektiert -
   das erklaerte die Inkonsistenz zwischen frisch erzeugten und neu generierten Bildern.

**Umgesetzt:**

1. `textgen.py::_build_prompt()`: Slogan-Feld-Vorgabe praezisiert - soll zur Kernaussage/Emotion
   DIESES Beitrags passen, keine austauschbare Standard-Floskel, mit Beispielen je Themenart.
2. `textgen.py::_create_drafts()`: Bug gefixt - `pick_slogan(data.get("slogan", ""))` statt
   `pick_slogan("")`, der generierte Slogan wird jetzt tatsaechlich verwendet.

**Nicht geprueft:** Keine echte Bildgenerierung moeglich in dieser Umgebung - insbesondere
nicht verifiziert, ob Claude mit der neuen Vorgabe zuverlaessig thematisch passende Slogans
liefert oder weiterhin oft leer/generisch bleibt.

---

## 2026-08-11 – Hoheitszeichen-Verbot (fünfte Runde)

**Anlass:** Ein generiertes Bild zu "Freiwilliger Wehrdienst – kein Kindergeld?" zeigte ein
erkennbares Bundesadler-Hoheitsabzeichen auf einer Uniformschulter. Das ist kein Gestaltungs-,
sondern ein Compliance-Risiko (Wappenschutz/amtliche Kennzeichen) - unabhängig von der sonstigen
Bildqualität nicht akzeptabel. Bewusst SOFORT gefixt, nicht erst gesammelt/abgewartet wie die
anderen offenen Beobachtungen (Text/Kreis-Kollision, Zielgruppen-Darstellung).

**Umgesetzt:**

1. `image_producer.py`: neue PRIORITÄT-A-Regel (unverhandelbar) - keine echten oder erkennbar
   nachgebildeten staatlichen Hoheitszeichen (Bundesadler, Bundeswehr-/Polizei-/Zoll-/Behörden-
   Abzeichen, Wappen, Dienstsiegel). Auch bei Uniform-/Behörden-Themen: Umfeld ja, Emblem nein.
2. `creative_director.py`: gleiche Regel als Hinweis für die Konzeptphase ergänzt, damit
   Routen mit Uniform-Bezug das Problem gar nicht erst anlegen.
3. `visual_qa.py`: neues **hartes Ausschlusskriterium** `enthaelt_hoheitszeichen` (analog zu
   `headline_text_exakt`) - unabhängig vom Gesamtscore führt ein erkanntes Hoheitszeichen immer
   zur Ablehnung. Sicherheitsnetz, falls Priorität A trotzdem mal nicht greift.

**Nicht geprüft:** Wie bei allen vorherigen Runden nur statisch getestet, keine echte
Bildgenerierung möglich in dieser Umgebung - insbesondere nicht verifiziert, ob das Vision-
Modell bei Visual QA ein stilisiertes/unscharfes Hoheitszeichen zuverlässig erkennt.


**Anlass:** Nutzer verglich 3 Bilder derselben Pipeline-Entwicklungsstufe und bemängelte den
Hintergrund als "langweilig trotz Wiedererkennungswert" - trotz unterschiedlicher Motive hatten
alle drei denselben Aufbau: ein Objekt freigestellt vor einer flachen Navy-Fläche. Ursache
identifiziert: Das eigene Brand-Signature-Beispiel aus der vorherigen Runde ("Navy als große
ruhige Hintergrundfläche...") wurde vom Modell als Standardlösung übernommen statt als eine
von mehreren Optionen - ein selbst verursachtes Problem.

**Umgesetzt:**

1. `art_director.py`: neues Enum-Feld **`hintergrund_typ`** (Echte fotografische Umgebung /
   Freigestellt vor einfarbiger Fläche / Nahaufnahme-Textur / Illustrativ-grafisch) - macht die
   bisher unausgesprochene Standardwahl explizit und damit steuerbar. In den Varianz-Mechanismus
   aufgenommen (verhindert Wiederholung über mehrere Beiträge).
2. `art_director.py`: neue 7. Achse "Hintergrund/Umgebung" mit expliziter
   **VORSICHT-PRODUKTSHOT-REFLEX**-Warnung; Brand-Signature-Beispiel von einem auf vier
   unterschiedliche, gleichwertige Umsetzungswege erweitert (Umgebungslicht in echter Szene,
   Material eines Objekts in echter Umgebung, Farbdetail im Raum, reiner Kontrast ohne
   wörtliche Farbfläche).
3. `creative_director.py`: "Objektmotiv"-Route Richtung echter Still-Life-Fotografie
   geschärft (Materialtextur, Umgebungslicht, Schärfentiefe) statt flachem Studio-/Render-Look.
4. `image_producer.py`: gleiche Produktshot-Warnung in Priorität B verankert, Hintergrund-Typ
   aus dem Art Board wird an den finalen Bildprompt durchgereicht.

**Lehre für künftige Runden:** Ein einzelnes konkretes Beispiel in einem LLM-Prompt wird leicht
als Standardlösung generalisiert, auch wenn es nur illustrativ gemeint war - bei neuen
Beispielen künftig entweder mehrere stilistisch unterschiedliche Varianten angeben oder explizit
als "eine von mehreren Optionen" markieren.

**Nicht geprüft:** Wie bei allen vorherigen Runden nur statisch getestet, keine echte
Bildgenerierung möglich in dieser Umgebung.

---

## 2026-08-11 – Hintergrund-Vielfalt gegen "Produktshot-Reflex" (vierte Runde)

**Anlass:** Nutzer verglich 3 Bilder derselben Pipeline-Entwicklungsstufe und bemängelte den
Hintergrund als "langweilig trotz Wiedererkennungswert" - trotz unterschiedlicher Motive hatten
alle drei denselben Aufbau: ein Objekt freigestellt vor einer flachen Navy-Fläche. Ursache
identifiziert: Das eigene Brand-Signature-Beispiel aus der vorherigen Runde ("Navy als große
ruhige Hintergrundfläche...") wurde vom Modell als Standardlösung übernommen statt als eine
von mehreren Optionen - ein selbst verursachtes Problem.

**Umgesetzt:**

1. `art_director.py`: neues Enum-Feld **`hintergrund_typ`** (Echte fotografische Umgebung /
   Freigestellt vor einfarbiger Fläche / Nahaufnahme-Textur / Illustrativ-grafisch) - macht die
   bisher unausgesprochene Standardwahl explizit und damit steuerbar. In den Varianz-Mechanismus
   aufgenommen (verhindert Wiederholung über mehrere Beiträge).
2. `art_director.py`: neue 7. Achse "Hintergrund/Umgebung" mit expliziter
   **VORSICHT-PRODUKTSHOT-REFLEX**-Warnung; Brand-Signature-Beispiel von einem auf vier
   unterschiedliche, gleichwertige Umsetzungswege erweitert (Umgebungslicht in echter Szene,
   Material eines Objekts in echter Umgebung, Farbdetail im Raum, reiner Kontrast ohne
   wörtliche Farbfläche).
3. `creative_director.py`: "Objektmotiv"-Route Richtung echter Still-Life-Fotografie
   geschärft (Materialtextur, Umgebungslicht, Schärfentiefe) statt flachem Studio-/Render-Look.
4. `image_producer.py`: gleiche Produktshot-Warnung in Priorität B verankert, Hintergrund-Typ
   aus dem Art Board wird an den finalen Bildprompt durchgereicht.

**Lehre für künftige Runden:** Ein einzelnes konkretes Beispiel in einem LLM-Prompt wird leicht
als Standardlösung generalisiert, auch wenn es nur illustrativ gemeint war - bei neuen
Beispielen künftig entweder mehrere stilistisch unterschiedliche Varianten angeben oder explizit
als "eine von mehreren Optionen" markieren.

**Nicht geprüft:** Wie bei allen vorherigen Runden nur statisch getestet, keine echte
Bildgenerierung möglich in dieser Umgebung.

---

## 2026-08-11 – Externe Kritik geprüft und teilweise umgesetzt (dritte Runde)

**Anlass:** Externe Bewertung (ChatGPT) der gesamten Pipeline nach der zweiten Runde oben.
Kritisch geprüft statt blind übernommen - siehe Chat-Protokoll für die vollständige
Punkt-für-Punkt-Bewertung. Wichtigster Fund beim Gegenchecken: Die Kritik berief sich auf eine
angeblich dokumentierte "Kernentscheidung" aus einer "Phase-1C-Architektur"/"Übernahmematrix" -
das existiert nirgends in diesem Repo und wurde daher ignoriert. Der zugehörige Vorschlag
("Pillow soll die Headline wieder rendern") wurde zusätzlich explizit vom Nutzer ausgeschlossen
und widerspricht der in dieser Session bereits getroffenen, begründeten Entscheidung
(GPT-integrierter Text statt Pillow-Karte).

**Umgesetzt (7 von 9 Vorschlägen, 2 verworfen/reduziert):**

1. `art_director.py`: neue 6. Achse **Brand Signature** (Freitext-Feld) - wie HILO im Motiv
   spürbar wird, unabhängig von Logo-/Slogan-Kreis. Wird bis zum finalen Bildprompt
   durchgereicht (`image_producer.py`).
2. `creative_director.py`: neues Feld **`scroll_stop_device`** pro Route (nur 1 statt der
   vorgeschlagenen 3 Felder - `first_500ms_read`/`visual_tension` wurden als redundant zu
   `beispiel_szene` eingeschätzt, mehr Felder = mehr Tokens ohne klaren Mehrwert). Wird an
   Jury, Art Director und Image Producer durchgereicht.
3. `concept_jury.py`: Scroll-Stop-Skala (1-10) konkretisiert - "funktioniert als Thumbnail ohne
   Text" statt "sofortiger Eye-Catcher".
4. `art_director.py` + `visual_qa.py`: **Thumbnail-Test-Regel** ergänzt (Leitidee muss auch bei
   ca. 180×180px sofort verständlich/dominant sein).
5. `image_producer.py`: System-Prompt komplett konsolidiert - zwei fast identische
   "Text-Regeln"-Blöcke (Dopplung, kein bewusstes Design) zu einer Prioritäts-Struktur
   A (unverhandelbar) / B (visuelle Wirkung) / C (Marke/Stil) zusammengeführt. Kein Inhalt
   verloren, nur entdoppelt und klarer hierarchisiert.
6. `creative_director.py`: neue Regel "HILO-Farben nicht als erzwungene Requisiten" (kein
   grüner Ordner/blauer Stift nur zur CI-Erfüllung).
7. `visual_qa.py`: neues Gate-A-Kriterium **`scroll_stop_wirkung`** - verifizierte echte
   Lücke: die Jury bewertet Scroll-Stop nur anhand der TEXT-Beschreibung der Route, bevor das
   Bild existiert; bisher prüfte niemand nach der Generierung, ob der Effekt im fertigen Bild
   tatsächlich ankommt.

**Verworfen:**
- Zusätzlicher Visual-QA-Score "Brand Distinctiveness" - ohne Referenzbilder einer
  "HILO-Bildwelt" kann ein Vision-Modell das nicht seriös bewerten, hohes Risiko für
  Schein-Präzision (Modell rät/rationalisiert). Überschneidet sich zudem stark mit
  vorhandener Originalität (Jury) und Markenpassung (QA).
- Pillow-Rückbau für Headline-Rendering - explizit ausgeschlossen (siehe oben).

**Nicht geprüft:** Wie bei den vorherigen Runden nur statisch getestet (Syntax + bestehende
Unit-Tests), keine echte Bildgenerierung möglich in dieser Umgebung.

---

## 2026-08-11 – Kreative Freiheit vs. Regel-Dichte (Review-Runde)

**Anlass:** Bild-Vergleich zeigte ein zu überladenes Waage-Motiv (schwach) gegen ein klares
Euro-Kuchen-Motiv (stark). Bei der Fehlersuche fiel auf, dass die Pipeline über mehrere
Migrationen hinweg immer neue MUSS-Regeln angesammelt hatte, ohne je eine zu entfernen oder
die Gewichtungen zu hinterfragen.

**Geänderte Dateien:**
- `concept_jury.py`: Jury-Gewichte verschoben - `scroll_stop_potenzial` 20→25%,
  `originalitaet` 15→20%, `umsetzbarkeit` 10→5%, `zielgruppenrelevanz` 10→5% (Summe weiterhin
  100%). Begründung: Umsetzbarkeit und Zielgruppenrelevanz werteten mutige/originelle Konzepte
  am häufigsten ab, ohne dass das bei HILOs eher kleinen, klar umsetzbaren Foto-/Still-Life-
  Motiven nötig wäre.
- `image_producer.py` + `visual_qa.py`: Die am 2026-08-11 (früherer Commit desselben Tages)
  eingeführte Pflicht "Text-Kontrastfläche MUSS Navy oder Grün sein" wurde gelockert zu
  "bevorzugt Navy/Grün, neutrale Farbe erlaubt WENN zusätzlich ein sichtbares HILO-Farbelement
  in der Nähe ist". Begründung: Die Kreise (Logo + Slogan) sind der deterministische
  Markenanker (von Pillow gesetzt, nicht von der Bild-KI) - die Flächenfarbe ist nur ein
  zweites, unzuverlässiges Signal. Eine starre Zwei-Farben-Pflicht kann in manchen Szenen
  unstimmiger wirken als eine zur Szene passende neutrale Fläche mit Markenfarb-Akzent.
- `art_director.py`: `komposition_prinzip`-Enum um "Bildfüllende Großaufnahme" und "Bewusst
  asymmetrisch/ungeordnet" ergänzt. Begründung: Die bisherigen 7 Optionen deckten diese beiden
  in der Praxis vorkommenden Kompositionsarten nicht ab.
- `creative_director.py`: Neue 5. Route "Unkonventionell" - passt bewusst in keine der 4
  festen Kategorien (Szene/Metapher/Objekt/Kontrast). Begründung: Die 4 festen Kategorien
  zwingen jede Idee in eine von vier Schubladen; eine Idee, die dazwischen liegt oder komplett
  anders ist (z.B. grafisch/typografisch statt fotografisch), entsteht in der bisherigen
  Struktur gar nicht erst. Zusätzliche Korrektur: "Waage" als Metapher-Beispiel entfernt
  (Ursache des Auslöser-Bildes), Regel "EIN dominantes Bildelement, keine Requisiten-
  Ansammlung" ergänzt (gilt für Metapher/Kontrast, NICHT für Emotionale Szene - dort gehören
  Mensch + Umfeld natürlicherweise zusammen). Geldregen-Verbot präzisiert: nur wörtlich
  fallende Scheine/Münzen sind gemeint, ein einzelnes mutiges Euro-Objekt ist ausdrücklich
  KEIN Klischee.

**Bewusst NICHT verändert:**
- Die technischen Art-Director-Enums (Kameraperspektive, Schärfentiefe, Lichtqualität) -
  hier gibt es real nur endlich viele sinnvolle fotografische Optionen, ein Freitext-
  Fluchtventil hätte hier eher zu vageren Anweisungen geführt als zu mehr Kreativität.
- Concept Jury / Visual QA Schwellwerte (7.0 / 8.0) selbst - beide sind KEINE harten Gates
  (verifiziert im Code: `concept_jury._recompute_verdict` wählt immer die höchstbewertete
  Route, auch unter 7.0; `run_sharenext_pipeline` hat keinen Retry bei `approved=False`),
  sondern nur Warnhinweise für die menschliche Freigabe-Prüfung. Ein "Override-Mechanismus"
  dafür wäre sinnlos gewesen, da es nichts zu übergehen gibt.

**Nicht geprüft:** Alle Änderungen sind bisher nur statisch (Syntax + bestehende Unit-Tests)
geprüft, nicht mit echten Bildgenerierungen - dafür fehlt in dieser Umgebung ein OpenAI-Key.

---

## 2026-08-11 – Erste Runde: Requisiten-Häufung + Text-Flächenfarbe (vorheriger Commit)

**Anlass:** Direkter Bild-Vergleich (Waage-Motiv vs. Euro-Kuchen-Motiv), siehe oben - dies war
die erste, noch ungeprüfte Fassung der Regeln, die in der Review-Runde direkt darüber
korrigiert wurde.

- `creative_director.py`: "Waage" als Metapher-Beispiel entfernt, Regel "EIN dominantes
  Bildelement" ergänzt, Geldregen-Verbot präzisiert.
- `art_director.py`: Focal-Point-Regel verschärft (ein dominantes Element, Rest untergeordnet).
- `concept_jury.py`: Scroll-Stop-Kriterium wertet Requisiten-Häufung ab.
- `image_producer.py`: Text-Kontrastfläche MUSS Navy/Grün sein (in der Review-Runde direkt
  darüber wieder gelockert, siehe oben).
- `visual_qa.py`: Gate-A-Check prüft Markenfarben der Text-Fläche.
