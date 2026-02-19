#!/bin/bash
################################################################################
# Setup automatischer Backups via Cron (Host-System)
################################################################################

SCRIPT_DIR="/opt/immich-backup"
CRON_SCHEDULE="0 3 * * *"  # Täglich um 3:00 Uhr

echo "Richte automatisches Immich-Backup ein..."

# Erstelle Script-Verzeichnis
mkdir -p "$SCRIPT_DIR"

# Erstelle Wrapper-Script
cat > "${SCRIPT_DIR}/run-backup.sh" << 'EOF'
#!/bin/bash
CONTAINER="immich-metadata-sync"
LOG_FILE="/var/log/immich-backup-cron.log"

{
    echo "========================================"
    echo "Backup gestartet: $(date)"
    echo "========================================"
    
    if docker ps | grep -q "$CONTAINER"; then
        docker exec "$CONTAINER" /app/script/immich-backup.sh
        EXIT_CODE=$?
        
        if [ $EXIT_CODE -eq 0 ]; then
            echo "✅ Backup erfolgreich"
        else
            echo "❌ Backup fehlgeschlagen (Exit Code: $EXIT_CODE)"
        fi
    else
        echo "❌ Container '$CONTAINER' läuft nicht"
        EXIT_CODE=1
    fi
    
    echo "Beendet: $(date)"
    echo ""
    
    exit $EXIT_CODE
} >> "$LOG_FILE" 2>&1
EOF

chmod +x "${SCRIPT_DIR}/run-backup.sh"

# Füge Cron-Job hinzu (als root)
CRON_ENTRY="$CRON_SCHEDULE ${SCRIPT_DIR}/run-backup.sh"

# Prüfe ob Eintrag bereits existiert
if ! crontab -l 2>/dev/null | grep -qF "$SCRIPT_DIR/run-backup.sh"; then
    (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
    echo "✅ Cron-Job hinzugefügt"
else
    echo "ℹ️  Cron-Job existiert bereits"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ Setup abgeschlossen!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Script:       ${SCRIPT_DIR}/run-backup.sh"
echo "Zeitplan:     $CRON_SCHEDULE (täglich um 3:00 Uhr)"
echo "Log-Datei:    /var/log/immich-backup-cron.log"
echo ""
echo "Verwaltung:"
echo "  • Cron-Jobs anzeigen:     crontab -l"
echo "  • Cron-Job bearbeiten:    crontab -e"
echo "  • Manuelles Backup:       ${SCRIPT_DIR}/run-backup.sh"
echo "  • Logs ansehen:           tail -f /var/log/immich-backup-cron.log"
echo ""
