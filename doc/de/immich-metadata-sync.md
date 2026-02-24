# Immich Metadata Sync – Technische Dokumentation 
*(Script v1.4)*

Diese Dokumentation beschreibt Aufbau, Konfiguration und Ablauf des Skripts `immich-ultra-sync.py` im Ordner `/immich-metadata-sync/script/`. Ziel ist es, Immich-Metadaten (Personen, GPS, Beschreibungen, Zeitstempel, Rating, Alben, Gesichtskoordinaten) verlustfrei in die Originaldateien zurückzuschreiben.

Für detaillierte Informationen siehe die englische README.md im Hauptverzeichnis.

## Architektur und Modularisierung

Das Projekt wurde in mehrere Module aufgeteilt für bessere Wartbarkeit:

### Modulstruktur
```
script/
├── immich-ultra-sync.py  # Hauptskript (Orchestrierung)
├── utils.py              # Hilfsfunktionen und Konstanten
├── api.py                # API-bezogene Funktionen und RateLimiter
└── exif.py               # EXIF/XMP-Metadaten-Verwaltung
```

### Module-Beschreibung
- **`utils.py`**: Enthält alle globalen Konstanten, LogLevel-System, allgemeine Hilfsfunktionen (Logging, Checkpoint, Konfiguration, Album-Cache, Pfad-Validierung)
- **`api.py`**: RateLimiter-Klasse, API-Aufrufe, Asset-Abruf, Batch-Operationen
- **`exif.py`**: ExifToolHelper-Klasse (stay-open mode), EXIF-Werte auslesen/schreiben, Normalisierung, MWG-RS-Konvertierung
- **`immich-ultra-sync.py`**: Hauptlogik (process_asset, CLI-Parsing, main-Funktion)

## Datenfluss
1. **Konfiguration & Startparameter**  
   - Umgebungsvariablen/Konfigdateien (`--config` unterstützt INI, `.env`, JSON):  
     - `IMMICH_INSTANCE_URL` (ohne abschließenden `/api`, wird intern ergänzt/fallback)  
     - `IMMICH_API_KEY`  
     - `IMMICH_PHOTO_DIR` (Standard `/library`, interner Mount mit Fotos)  
     - `IMMICH_LOG_FORMAT=json` oder `IMMICH_STRUCTURED_LOGS=true` für strukturierte JSON-Logs  
   - CLI-Flags: `--all`, `--people`, `--gps`, `--caption`, `--time`, `--rating`, `--albums`, `--face-coordinates`, `--dry-run`, `--only-new`, `--resume`, `--clear-checkpoint`, `--clear-album-cache`, `--log-level`, `--help`.

2. **Asset-Ermittlung** (`api.py`)  
   - POST `/{api}/search/metadata` liefert Asset-Liste.  
   - Batch-Endpoint (`/assets/batch`) für effizientes Abrufen von Asset-Details
   - Fallback auf einzelne GET `/assets/{id}` bei fehlender Batch-Unterstützung

3. **Pfad-Mapping** (`utils.py`)  
   - `originalPath` wird auf Containerpfad gemappt (`PHOTO_DIR/<Jahr>/<Monat>/<Datei>` anhand der letzten 3 Pfadsegmente).  
   - Existenzcheck verhindert Schreibversuch auf fehlende Dateien.
   - Sicherheitsprüfungen gegen Path-Traversal-Angriffe

4. **Exif-Argumente bauen** (`exif.py` - `build_exif_args`)  
   - People → `XMP:Subject`, `IPTC:Keywords`, `XMP-iptcExt:PersonInImage`  
   - GPS → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`  
   - Caption → `XMP:Description`, `IPTC:Caption-Abstract`  
   - Time → `DateTimeOriginal`, `CreateDate`, `XMP:CreateDate`, `XMP-photoshop:DateCreated`  
   - Rating → `Rating` (Immich-Favorit → `5`, sonst `0`)  
   - Albums → `XMP-iptcExt:Event`, `XMP:HierarchicalSubject`, `EXIF:UserComment`  
   - Face Coordinates → `RegionInfo` (MWG-RS Regionen mit Gesichtskoordinaten)

5. **Ausführung** (`exif.py` - `ExifToolHelper`)  
   - ExifTool im stay-open Modus für bessere Performance
   - `--dry-run`: Nur Logging, kein Schreiben.  
   - Regulär: `exiftool -overwrite_original <args> <file>`  
   - `--only-new`: Prüft vorhandene EXIF-Werte und überspringt unveränderte Dateien

6. **Logging** (`utils.py`)  
   - Datei: `immich_ultra_sync.txt` im Skript-Verzeichnis.  
   - Enthält Startparameter, Pfade mit Änderungen, Übersprünge und Fehler.
   - Konfigurierbare Log-Level: DEBUG, INFO, WARNING, ERROR

## Backup

Das Tool enthält umfassende Backup-Funktionalität für Ihre Immich-Instanz, einschließlich Datenbank- und Bibliotheks-Backups.

Für detaillierte Informationen siehe die englische README.md und `script/backup/BACKUP_SETUP.md`.

## CI/CD und Tests

Das Projekt verfügt nun über automatisierte Tests und CI/CD:
- **Pytest-Workflow**: `.github/workflows/pytest.yml` führt Tests bei jedem Push/PR aus
- **Test-Suite**: `tests/test_immich_ultra_sync.py` testet alle Kernfunktionen
- **Python-Versionen**: Tests laufen auf Python 3.9, 3.10, 3.11, 3.12

## Betriebs- und Deployment-Hinweise
- **Abhängigkeiten**: Python 3, `requests`, `exiftool`.  
- **Container**: Beispiel-Image siehe `immich-metadata-sync/dockerfile.yaml` (installiert exiftool + requests).  
- **Netzwerk**: Container muss Immich-API erreichen; `IMMICH_INSTANCE_URL` kann mit/ohne `/api` angegeben werden (Fallback-Logik im Code).  
- **Volumes**: Library muss unter `/library` (oder konfiguriertem `PHOTO_DIR`) gemountet werden.

## Nutzung – Beispiele
- Alle Module:  
  ```bash
  python3 immich-ultra-sync.py --all
  ```
- People + GPS, nur neue Ratings:  
  ```bash
  python3 immich-ultra-sync.py --people --gps --only-new
  ```
- Trockenlauf:  
  ```bash
  python3 immich-ultra-sync.py --all --dry-run
  ```
- Personen mit Gesichtskoordinaten:  
  ```bash
  python3 immich-ultra-sync.py --people --face-coordinates
  ```
- Alles inkl. Alben und Gesichtskoordinaten:  
  ```bash
  python3 immich-ultra-sync.py --all --albums --face-coordinates
  ```

## Fehlersuche
- **Kein API-Response**: Prüfe `IMMICH_INSTANCE_URL`, API-Key, Netzwerk; das Skript versucht `/api`- und Root-Pfad.  
- **Datei nicht gefunden**: 
  - Das Skript validiert jetzt automatisch `IMMICH_PHOTO_DIR` beim Start
  - Falls das Verzeichnis nicht existiert oder leer ist, bricht das Skript mit hilfreichen Fehlermeldungen ab
  - Bei >90% "file not found"-Fehlern während der Verarbeitung werden automatisch Warnungen zu möglichen Mount-/Konfigurationsproblemen ausgegeben
  - Stimmt das Mapping `/library/<jahr>/<monat>/<datei>` mit Immichs `originalPath`? Mount prüfen.
  - Stelle sicher, dass Docker-Volume-Mounts mit deiner `IMMICH_PHOTO_DIR`-Konfiguration übereinstimmen
  - Beispiel: Wenn Immich Dateien in `/mnt/media/library` speichert, verwende Volume-Mount `/mnt/media/library:/library` und setze `IMMICH_PHOTO_DIR=/library`
- **Path-Segment-Fehler**:
  - Bei >50% Path-Segment-Fehlern gibt das Skript detaillierte Hinweise zur Problembehebung aus
  - Prüfe die Struktur von `originalPath` in Immich (sichtbar in Asset-Details)
  - Setze `IMMICH_PATH_SEGMENTS` auf die Anzahl der Pfadkomponenten nach deinem Mount-Point
  - Beispiel: Für Pfad `library/user/2024/photo.jpg` mit `IMMICH_PHOTO_DIR=/library`, setze `IMMICH_PATH_SEGMENTS=3`
- **Keine People/GPS**: Immich-Asset hat evtl. keine erkannten Personen oder GPS-Daten; `change_list` bleibt leer → Datei wird übersprungen.  
- **Langsame Läufe**: Nutze `--only-new` (wenn Rating aktiviert) oder `--dry-run` zum Testen.

## Sicherheit & Best Practices
- `--dry-run` für Tests nutzen.  
- `-overwrite_original` verhindert Backup-Dateien.  
- Timeout/Fehlertoleranz bei API-Calls; Script bricht nicht bei Einzel-Fehlern ab.  
- Rating-Check minimiert unnötige Schreibzugriffe.

## Änderungsprotokoll (Script v1.4)
- **Modularisierung**: Code in separate Module aufgeteilt (utils.py, api.py, exif.py)
- **CI/CD**: Automatisierte Tests mit pytest über GitHub Actions
- **Verbesserte Dokumentation**: Strukturierte README mit Abschnitten für Features, Installation, Nutzung, Troubleshooting
- **Album-Cache**: Persistenter Cache für Album-Informationen mit TTL und Stale-Fallback
- **ExifTool stay-open**: Performante EXIF-Verarbeitung im stay-open Modus
- **Konfiguration & Logging**: `.env`/JSON-Config-Support und optionale strukturierte JSON-Logs mit Metriken
- Robustere API-Aufrufe mit Fallback `/api`.  
- Module: People, GPS, Caption, Time, Rating, Albums, Face Coordinates (MWG-RS).  
- Smart-Skip für alle Metadaten (`--only-new`).  
- Logging erweitert (Start/Finish, Pfade, Fehler, konfigurierbare Log-Level).  
- Gesichtserkennungs-Koordinaten als MWG-RS-Regionen (opt-in via `--face-coordinates`).  
- Album-Sync mit persistentem Cache und TTL.
