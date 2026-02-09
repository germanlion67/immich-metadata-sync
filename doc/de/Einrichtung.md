## Immich Metadata Exif-Sync Tool
Dieses Tool synchronisiert in Immich erkannte Tags wie Personen (Gesichter), GPS-Koordinaten, Favorit-Status direkt zurück in die Metadaten (`EXIF/XMP`) der Originaldateien in deiner Immich-Library.



## 🛠 1. Vorbereitung auf dem Host
Erstelle ein Verzeichnis für das Skript (z.B. `/home/user/immich-tools`) und speichere dort die `immich-ultra-sync.py`.


## 🐳 2. Image Build (Portainer / Docker)
Erstelle ein neues Image `immich-metadata-sync:latest` in Portainer mit folgendem **Dockerfile:**
```bash
FROM python:3.11-slim

# Installiere nur notwendige Abhängigkeiten (ExifTool fuer Metadaten, curl für Tests)
RUN apt-get update && apt-get install -y exiftool curl && \
    pip install --no-cache-dir requests && \
    rm -rf /var/lib/apt/lists/*  # Cache aufräumen für kleinere Images

# Arbeitsverzeichnis setzen
WORKDIR /app

# Standardbefehl: Container läuft dauerhaft für interaktive Nutzung
CMD ["sleep", "infinity"]
```


## 📦 3. Container Deployment
Erstelle den Container mit diesen Einstellungen:
| Einstellung | Wert |
|-------------|------|
| **Image** | `immich-metadata-sync:latest` |
| **Network** | `immich_default` (Muss im selben Netz wie Immich sein) |
| **Env: `IMMICH_INSTANCE_URL`** | `http://immich_server:2283` (Ohne `/api` am Ende!) |
| **Env: `IMMICH_API_KEY`** | Dein API-Key aus den Immich-Einstellungen (jeweils nur für einen Benutzer)  |


### Volume Mappings (Bind-Mounts)
- `Host: /home/user/immich-tools` → `Container: /app`
- `Host: /pfad/zu/immich/library/UUID` → `Container: /library`

## 🖥 4. Nutzung & Testbefehle
Verbinde dich mit der Konsole des Containers in Portainer (/bin/sh).
### A. Verbindungstest (API Check)
Prüfe, ob der Container den Immich-Server erreicht:
```bash
curl -I -H "x-api-key: $IMMICH_API_KEY" "$IMMICH_INSTANCE_URL/asset"
```
Erwartetes Ergebnis: *`HTTP/1.1 200 OK`*
### B. Library Check
Prüfe, ob deine Fotos sichtbar sind:
```bash
ls -la /library
```

### C. Synchronisation starten
Trockenlauf:
```bash
python3 immich-ultra-sync.py --all --dry-run
```

Vollständiger Lauf:
```bash
python3 immich-ultra-sync.py --all
```

Nur neue/ungetaggte Bilder (empfohlen):
```bash
python3 immich-ultra-sync.py --all --only-new
```

## ⚠️ Wichtige Hinweise
1. **Immich-Refresh:** Nachdem das Skript gelaufen ist, erkennt Immich die Änderungen erst nach einem "Offline Assets Scan" (Administration -> Library).
2. **Container-Name:** Stelle sicher, dass IMMICH_INSTANCE_URL den exakten Namen deines Immich-Server-Containers nutzt (z.B. immich_server).
3. **Logdatei:** Die Ergebnisse findest du unter `/app/immich_ultra_sync.txt` (Mount anpassen, falls das Log persistent gespeichert werden soll).
