#!/bin/bash
# Führt Backup im Container aus

CONTAINER_NAME="immich-metadata-sync"

echo "Starte Immich Backup..."

# Prüfe ob Container läuft
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Container '$CONTAINER_NAME' läuft nicht!"
    echo "Starte Container mit: docker-compose up -d"
    exit 1
fi

# Führe Backup-Script im Container aus
docker exec "$CONTAINER_NAME" /app/script/immich-backup.sh

echo ""
echo "✅ Backup abgeschlossen!"
echo "Logs: docker exec $CONTAINER_NAME cat /backup/backup.log"
