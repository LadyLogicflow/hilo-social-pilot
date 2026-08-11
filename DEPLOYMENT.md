# Deployment-Anleitung: ShareNext-Features auf Pi5

**Version:** 1.0.0 (ShareNext-Integration)  
**Datum:** 2026-08-01  
**Neue Features:** Prompt-Builder-System + Multi-Stage Pipeline

---

## 🚀 Schnell-Update (Empfohlen)

Wenn HILO bereits auf dem Pi5 läuft:

```bash
# 1. Ins Projekt-Verzeichnis wechseln
cd ~/hilo-social-pilot

# 2. Änderungen von GitHub holen
git pull origin main

# 3. Dependencies prüfen (falls neue hinzugekommen)
source venv/bin/activate  # oder .venv/bin/activate
pip install -r requirements.txt

# 4. Tests ausführen (optional, empfohlen)
python -m pytest tests/ -v

# 5. Dienst neu starten
sudo systemctl restart hilo-dashboard.service

# 6. Status prüfen
sudo systemctl status hilo-dashboard.service
```

**Fertig!** Die neuen Features sind jetzt aktiv.

---

## 📋 Detaillierte Anleitung

### Schritt 1: Backup erstellen (Sicherheit)

```bash
# Aktuellen Stand sichern
cd ~/hilo-social-pilot
git stash  # Falls lokale Änderungen existieren

# Oder komplettes Backup
cd ~
cp -r hilo-social-pilot hilo-social-pilot.backup.$(date +%Y%m%d)
```

### Schritt 2: Code aktualisieren

```bash
cd ~/hilo-social-pilot

# Von GitHub ziehen (main branch)
git pull origin main

# Prüfe welche Dateien neu sind
git log --oneline -10
```

**Erwartete neue Dateien:**
- `prompt_builder.py`
- `image_pipeline/` (Verzeichnis mit 4 Modulen)
- `sharenext_integration.py`
- `tests/test_prompt_builder.py`
- `tests/test_image_pipeline.py`
- `tests/test_sharenext_integration.py`

### Schritt 3: Dependencies installieren

```bash
# Virtual Environment aktivieren
source venv/bin/activate
# ODER (je nach Setup)
source .venv/bin/activate

# Requirements installieren/aktualisieren
pip install -r requirements.txt

# Prüfe ob neue Packages fehlen
pip list | grep -E "openai|pydantic"
```

**Wichtig:** Falls `pytest` noch nicht installiert ist:
```bash
pip install pytest
```

### Schritt 4: Tests ausführen (Empfohlen)

```bash
# Alle neuen Tests ausführen
python -m pytest tests/test_prompt_builder.py -v
python -m pytest tests/test_image_pipeline.py -v
python -m pytest tests/test_sharenext_integration.py -v

# Oder alle Tests auf einmal
python -m pytest tests/ -v

# Erwartetes Ergebnis: 52 passed (Stand 2026-08-11; steigt mit neuen Tests).
# Hinweis: tests/manual_*.py sind KEINE pytest-Module (eigenstaendige Skripte, teils mit
# sys.exit() bei Fehlern) und werden ueber pytest.ini bewusst NICHT eingesammelt - einzeln
# ausfuehrbar per 'python tests/manual_<name>.py' (siehe jeweiliger Docstring fuer noetige
# Umgebungsvariablen wie HILO_DATA_DIR).
```

**Falls Tests feilen:**
- Prüfe ob alle Dependencies installiert sind
- Prüfe die Log-Ausgabe für Details
- Kontaktiere Support (mich!)

### Schritt 5: HILO-Service neu starten

```bash
# Service neu starten
sudo systemctl restart hilo-dashboard.service

# Status prüfen
sudo systemctl status hilo-dashboard.service

# Logs ansehen (letzte 50 Zeilen)
sudo journalctl -u hilo-dashboard.service -n 50 --no-pager

# Live-Logs verfolgen (Ctrl+C zum Beenden)
sudo journalctl -u hilo-dashboard.service -f
```

**Erwarteter Status:** `active (running)`

### Schritt 6: Funktionstest

```bash
# Python-Shell öffnen
python

# ShareNext-Integration testen
>>> from sharenext_integration import generate_optimized_image_prompt
>>> 
>>> prompt = generate_optimized_image_prompt(
...     text="Die Frist für Ihre Steuererklärung endet am 31. Dezember!",
...     theme="Steuerfrist",
...     content_type="deadline"
... )
>>> 
>>> print(len(prompt))  # Sollte > 200 sein
>>> print("HILO" in prompt or "#1a3a6b" in prompt)  # Sollte True sein
>>> 
>>> exit()
```

**Erwartetes Ergebnis:**
- Prompt-Länge > 200 Zeichen
- Enthält HILO-Branding-Elemente

---

## 🆕 Neue Features nutzen

### In bestehendem Code

Die neuen Features können sofort genutzt werden:

```python
# Alt (direkt OpenAI API)
prompt = "Create an image showing a tax deadline..."

# Neu (optimiert mit ShareNext-Features)
from sharenext_integration import generate_optimized_image_prompt

prompt = generate_optimized_image_prompt(
    text="Die Frist für Ihre Steuererklärung endet am 31. Dezember!",
    theme="Steuerfrist",
    content_type="deadline"  # 'radar', 'deadline', 'knowledge', 'anlass'
)
```

### Verschiedene Content-Typen

```python
# Fristen-Countdown
prompt = generate_deadline_prompt(
    text="Wichtige Frist beachten!",
    deadline_date="31. Dezember 2026",
    topic="Steuererklärung"
)

# Wissens-Serie
prompt = generate_knowledge_prompt(
    text="Was sind Abschreibungen?",
    topic="Abschreibungen",
    knowledge_level="Einsteiger"
)

# News/Radar
prompt = generate_optimized_image_prompt(
    text="Neue Steuerregelung ab 2026",
    theme="Steuer-News",
    content_type="radar"
)
```

### Mit voller Pipeline (strategische Optimierung)

```python
from sharenext_integration import generate_with_pipeline

result = generate_with_pipeline(
    text="Ihr Text...",
    theme="Thema",
    content_type="radar"
)

# Zugriff auf alle Pipeline-Daten
print(result['creative_brief'].visual_strategy)
print(result['creative_brief'].mood)
print(result['production_brief'].prompt)
print(result['metadata'])
```

---

## ⚠️ Troubleshooting

### Problem: Import-Fehler

```
ModuleNotFoundError: No module named 'image_pipeline'
```

**Lösung:**
```bash
# Prüfe ob du im richtigen Verzeichnis bist
pwd  # Sollte ~/hilo-social-pilot sein

# Prüfe ob Dateien existieren
ls -la image_pipeline/

# Virtual Environment aktiviert?
which python  # Sollte .../venv/bin/python sein
```

### Problem: Tests feilen

```
ValueError: text must be at least 10 characters
```

**Lösung:**
Die neuen Features haben Input-Validierung. Prüfe:
- Text mindestens 10 Zeichen lang
- Theme nicht leer
- content_type einer von: 'radar', 'deadline', 'knowledge', 'anlass'

### Problem: Service startet nicht

```bash
# Detaillierte Logs ansehen
sudo journalctl -u hilo-dashboard.service -n 100 --no-pager

# Service-Status
sudo systemctl status hilo-dashboard.service -l

# Python-Fehler direkt testen
cd ~/hilo-social-pilot
source venv/bin/activate
python main.py
```

### Problem: Alte Version wird noch verwendet

```bash
# Python-Cache leeren
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Service komplett neu starten
sudo systemctl stop hilo-dashboard.service
sleep 2
sudo systemctl start hilo-dashboard.service
```

---

## 🔙 Rollback (Falls nötig)

Falls die neue Version Probleme macht:

```bash
# Zu alter Version zurück
cd ~/hilo-social-pilot
git log --oneline -10  # Finde alte Commit-ID
git checkout <alte-commit-id>

# Service neu starten
sudo systemctl restart hilo-dashboard.service

# Oder: Backup wiederherstellen
cd ~
rm -rf hilo-social-pilot
mv hilo-social-pilot.backup.20260801 hilo-social-pilot
sudo systemctl restart hilo-dashboard.service
```

---

## 📊 Versions-Info

**Aktuelle Version:** ShareNext-Integration v1.0.0

**Neue Module:**
- `prompt_builder.py` (336 Zeilen)
- `image_pipeline/` (599 Zeilen)
- `sharenext_integration.py` (247 Zeilen)
- Tests (784 Zeilen)

**Gesamt:** 1.966 Zeilen neuer Code  
**Tests:** 48 (alle bestanden ✅)  
**Security:** Argus 8/10+ (production-ready)

---

## 📞 Support

Bei Problemen:
- Logs prüfen: `sudo journalctl -u hilo-dashboard.service -f`
- Tests ausführen: `python -m pytest tests/ -v`
- Kontakt: Docky (dieser Agent!)

**Viel Erfolg mit den neuen Features! 🚀**
