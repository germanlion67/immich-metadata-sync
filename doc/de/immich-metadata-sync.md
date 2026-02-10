# Immich Metadata Sync – Technische Dokumentation 
*(Script v1.2)*

Diese Dokumentation beschreibt Aufbau, Konfiguration und Ablauf des Skripts `immich-ultra-sync.py` im Ordner `/immich-metadata-sync/script/`. Ziel ist es, Immich-Metadaten (Personen, GPS, Beschreibungen, Zeitstempel, Rating, Alben, Gesichtskoordinaten) verlustfrei in die Originaldateien zurückzuschreiben.

## Architektur und Datenfluss
1. **Konfiguration & Startparameter**  
   - Umgebungsvariablen:  
     - `IMMICH_INSTANCE_URL` (ohne abschließenden `/api`, wird intern ergänzt/fallback)  
     - `IMMICH_API_KEY`  
     - `PHOTO_DIR` (Standard `/library`, interner Mount mit Fotos)  
   - CLI-Flags: `--all`, `--people`, `--gps`, `--caption`, `--time`, `--rating`, `--albums`, `--face-coordinates`, `--dry-run`, `--only-new`, `--resume`, `--clear-checkpoint`, `--clear-album-cache`, `--help`.

2. **Asset-Ermittlung**  
   - POST `/{api}/search/metadata` liefert Asset-Liste.  
   - Für jedes Asset folgt GET `/assets/{id}` für Detaildaten (EXIF, People, Favorite-Status).

3. **Pfad-Mapping**  
   - `originalPath` wird auf Containerpfad gemappt (`PHOTO_DIR/<Jahr>/<Monat>/<Datei>` anhand der letzten 3 Pfadsegmente).  
   - Existenzcheck verhindert Schreibversuch auf fehlende Dateien.

4. **Exif-Argumente bauen** (`build_exif_args`)  
   - People → `XMP:Subject`, `IPTC:Keywords`, `XMP-iptcExt:PersonInImage`  
   - GPS → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`  
   - Caption → `XMP:Description`, `IPTC:Caption-Abstract`  
   - Time → `DateTimeOriginal`, `CreateDate`, `XMP:CreateDate`, `XMP-photoshop:DateCreated`  
   - Rating → `Rating` (Immich-Favorit → `5`, sonst `0`)  
   - Albums → `XMP-iptcExt:Event`, `XMP:HierarchicalSubject`, `EXIF:UserComment`  
   - Face Coordinates → `RegionInfo` (MWG-RS Regionen mit Gesichtskoordinaten)

5. **Ausführung**  
   - `--dry-run`: Nur Logging, kein Schreiben.  
   - Regulär: `exiftool -overwrite_original <args> <file>`  
   - `--only-new` (nur mit Rating relevant): prüft vorhandenes Rating via `exiftool -Rating` und überspringt identische Werte.

6. **Logging**  
   - Datei: `immich_ultra_sync.txt` im Skript-Verzeichnis.  
   - Enthält Startparameter, Pfade mit Änderungen, Übersprünge und Fehler.

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
- **Datei nicht gefunden**: Stimmt das Mapping `/library/<jahr>/<monat>/<datei>` mit Immichs `originalPath`? Mount prüfen.  
- **Keine People/GPS**: Immich-Asset hat evtl. keine erkannten Personen oder GPS-Daten; `change_list` bleibt leer → Datei wird übersprungen.  
- **Langsame Läufe**: Nutze `--only-new` (wenn Rating aktiviert) oder `--dry-run` zum Testen.

## Sicherheit & Best Practices
- `--dry-run` für Tests nutzen.  
- `-overwrite_original` verhindert Backup-Dateien.  
- Timeout/Fehlertoleranz bei API-Calls; Script bricht nicht bei Einzel-Fehlern ab.  
- Rating-Check minimiert unnötige Schreibzugriffe.

## Änderungsprotokoll (Script v1.2)
- Robustere API-Aufrufe mit Fallback `/api`.  
- Module: People, GPS, Caption, Time, Rating, Albums, Face Coordinates (MWG-RS).  
- Smart-Skip für alle Metadaten (`--only-new`).  
- Logging erweitert (Start/Finish, Pfade, Fehler).  
- Gesichtserkennungs-Koordinaten als MWG-RS-Regionen (opt-in via `--face-coordinates`).  
- Album-Sync mit persistentem Cache und TTL.
