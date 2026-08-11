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
