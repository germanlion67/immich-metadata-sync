Die docker-compose.yml definiert einen Service für die Metadaten-Synchronisation, der das lokale Dockerfile baut und als Container läuft.

```
version: '3.8'

services:
  immich-metadata-sync:
    build: .  # Verwendet das lokale Dockerfile
    container_name: immich-metadata-sync
    user: app  # Non-root User aus dem Dockerfile
    # restart: unless-stopped
    env_file:
      - .env  # Lädt Vars aus .env-Datei
    volumes:
      - /home/immich/immich-library:/library  # Mount deine Photo-Bibliothek
      - ./logs:/app/logs  # Optional: Für Logs persistieren
    healthcheck:
      test: ["CMD", "python", "--version"]  # Gleicher Check wie im Dockerfile
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    # Optional: Ports, wenn dein Script später einen Webserver hinzufügt
    # ports:
    #   - "8080:8080"

  
```
## Überprüfung und Dokumentation
- **Build-Kontext:** Baut aus dem lokalen Verzeichnis (`.`), was das Dockerfile nutzt.
- **User:** Setzt den non-root User '`app`, konsistent mit dem Dockerfile.
- **Umgebung:** Lädt Variablen aus `.env`, was für sensible Daten wie API-Keys geeignet ist.
- **Volumes:** Mountet die Immich-Bibliothek in `/library` für Zugriff auf Medien; Logs werden persistiert in `./logs`.
- **Healthcheck:** Identisch mit dem Dockerfile, prüft Python-Verfügbarkeit.
- **Restart-Policy:** Auskommentiert; könnte aktiviert werden für automatischen Neustart.
- **Ports:** Auskommentiert; falls das Script einen Webserver hinzufügt, kann freigegeben werden.
- **Potenzielle Verbesserungen:** Der Pfad `/home/immich/immich-library` ist hartcodiert; könnte als Variable gesetzt werden. Restart-Policy sollte aktiviert werden, um Zuverlässigkeit zu erhöhen. Sicherstellen, dass `.env` existiert und korrekt konfiguriert ist.
