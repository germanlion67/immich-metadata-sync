Das Dockerfile definiert ein Multi-Stage Build für eine Python-Anwendung, die Metadaten synchronisiert. Es verwendet Python 3.11 und integriert ExifTool für Bildmetadaten.

```
# Multi-Stage Build: Builder-Stage für Abhängigkeiten
FROM python:3.11-slim AS builder

# Installiere Build-Abhängigkeiten (z.B. exiftool)
RUN apt-get update && apt-get install -y \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

# Runtime-Stage: Schlankes finales Image
FROM python:3.11-slim AS runtime

# Kopiere ExifTool-Binary und Perl-Module aus Builder-Stage
COPY --from=builder /usr/bin/exiftool /usr/bin/exiftool
COPY --from=builder /usr/lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu
COPY --from=builder /usr/share/perl5 /usr/share/perl5
# Optional: Kopiere weitere @INC-Pfade, falls nötig (z.B. /etc/perl)
COPY --from=builder /etc/perl /etc/perl

# Installiere Python-Abhängigkeiten (ohne Cache für Sicherheit)
RUN pip install --no-cache-dir requests tqdm

# Erstelle non-root User für Sicherheit
RUN useradd --create-home --shell /bin/bash app

# Arbeitsverzeichnis setzen
WORKDIR /app

# Gib /app dem User app (für Schreibrechte auf Logs)
RUN chown -R app:app /app

# Kopiere das Haupt-Script aus dem Repository
COPY script/immich-ultra-sync.py /app/immich-ultra-sync.py

# Mache das Script ausführbar (noch als root)
RUN chmod +x /app/immich-ultra-sync.py

# Jetzt non-root User setzen
USER app

# Optional: Healthcheck (prüft, ob Python verfügbar ist; passe an, wenn du einen echten Endpoint hast)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python --version || exit 1

# Standard-Command: Starte das Script mit Default-Args (Simulation)
# CMD ["python", "/app/immich-ultra-sync.py", "--all", "--dry-run"]

# Standard-Command: Starte das Script mit Default-Args
CMD ["python", "/app/immich-ultra-sync.py", "--all"]
```

## Überprüfung und Dokumentation
- **Multi-Stage Build:** Effizient, da nur notwendige Binaries (ExifTool) aus der Builder-Stage kopiert werden, um das finale Image schlank zu halten.
- **Sicherheit:** Verwendet einen non-root User (app), was Best Practice ist, um Privilegien zu minimieren.
- **Abhängigkeiten:** Installiert requests und tqdm für HTTP-Anfragen und Fortschrittsbalken. ExifTool wird für Metadaten-Handling benötigt.
- **Healthcheck:** Prüft die Python-Verfügbarkeit; könnte erweitert werden, um das Script zu testen.
- **CMD:** Startet das Python-Script mit --all Flag, was wahrscheinlich alle Medien synchronisiert.
- **Potenzielle Verbesserungen:** Der Healthcheck ist grundlegend; für Produktion könnte ein echter Endpoint hinzugefügt werden. Der kommentierte --dry-run CMD ist für Tests nützlich.
