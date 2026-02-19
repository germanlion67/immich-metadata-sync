# Runtime-Stage: Schlankes finales Image
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \
    rsync \
    postgresql-client \
    gzip \
    coreutils \
    findutils \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

# Installiere Python-Abhängigkeiten (ohne Cache für Sicherheit)
RUN pip install --no-cache-dir requests tqdm

# Arbeitsverzeichnis setzen
WORKDIR /app

# Kopiere das GESAMTE script-Verzeichnis, damit alle Module (api.py, utils.py, etc.) da sind
COPY script/ /app/


# Sicherstellen, dass die Dateien dem User 'app' gehören
RUN chmod +x /app/*.py

# Erweiterter Healthcheck: Prüft API-Konnektivität zu Immich
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \ 
  CMD python /app/healthcheck.py

# Immer nur EIN CMD-Befehl. 
# Standard-Command: Starte das Script mit Default-Args (Simulation)
# CMD ["python", "/app/immich-ultra-sync.py", "--all", "--dry-run"]

# Standard-Command: Starte das Script mit Default-Args
# CMD ["python", "/app/immich-ultra-sync.py", "--all"]

# Command: hält den Container am laufen für inbound Debuging, tests oder manuellem ausführen
CMD ["sleep", "infinity"]
