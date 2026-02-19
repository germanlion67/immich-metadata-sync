# Immich Backup Setup

## Übersicht

Dieses Setup ermöglicht vollständige Backups von Immich (Datenbank + Bilder) auf eine USB-Festplatte direkt aus dem `immich-metadata-sync` Container.

## Voraussetzungen

1. USB-Festplatte formatiert (ext4 empfohlen)
2. Docker und docker-compose installiert
3. Immich läuft und ist erreichbar

## Installation

### 1. USB-Festplatte vorbereiten

```bash
# Festplatte identifizieren
lsblk

# UUID ermitteln
sudo blkid

# Mountpoint erstellen
sudo mkdir -p /mnt/usb-backup

# USB-Festplatte mounten
sudo mount /dev/sdX1 /mnt/usb-backup

# Optional: Automount einrichten
sudo ./setup-usb-automount.sh
```

### 2. Container bauen und starten

```bash
# Angepasstes Dockerfile verwenden
docker-compose build

# Container starten
docker-compose up -d

# Prüfen ob Container läuft
docker ps | grep immich-metadata-sync
```

### 3. Konfiguration anpassen

Bearbeite `docker-compose.yml` und setze:

- ✅ Korrekten Pfad zu deinem Immich-Library
- ✅ Korrekten Pfad zur USB-Festplatte
- ✅ Immich API-Key
- ✅ Datenbank-Credentials

### 4. Erstes Backup testen

```bash
# Manuelles Backup ausführen
./run-backup.sh

# Oder direkt im Container:
docker exec immich-metadata-sync /app/script/immich-backup.sh

# Backup-Logs prüfen
docker exec immich-metadata-sync cat /backup/backup.log
```

### 5. Automatische Backups einrichten

```bash
# Cron-Job installieren
sudo ./setup-cron-backup.sh

# Prüfen
crontab -l
```

## Backup-Struktur

```
/mnt/usb-backup/
├── 20260219_030000/          # Backup vom 19.02.2026 03:00
│   ├── database/
│   │   └── immich_db_*.sql.gz
│   ├── library/              # Alle Bilder
│   ├── metadata/
│   │   ├── backup_manifest.txt
│   │   ├── immich_version.json
│   │   └── immich_statistics.json
│   ├── logs/
│   │   ├── pg_dump.log
│   │   └── rsync.log
│   └── RESTORE_INSTRUCTIONS.txt
├── 20260220_030000/
├── latest -> 20260220_030000/  # Symlink zum neuesten
└── backup.log
```

## Wiederherstellung

Siehe `RESTORE_INSTRUCTIONS.txt` im jeweiligen Backup-Verzeichnis.

Schnellanleitung:

```bash
# 1. Container stoppen
docker-compose down

# 2. Datenbank wiederherstellen
gunzip -c /mnt/usb-backup/latest/database/*.sql.gz | \
  docker exec -i immich_postgres psql -U postgres -d immich

# 3. Library wiederherstellen
rsync -avh /mnt/usb-backup/latest/library/ /pfad/zu/immich/library/

# 4. Immich neu starten und Library scannen
docker-compose up -d
```

## Fehlerbehebung

### Container läuft nicht
```bash
docker-compose logs immich-metadata-sync
```

### Backup schlägt fehl
```bash
# Prüfe Logs im Container
docker exec immich-metadata-sync cat /backup/backup.log

# Prüfe Mountpoints
docker exec immich-metadata-sync df -h
docker exec immich-metadata-sync ls -la /library /backup
```

### Datenbank nicht erreichbar
```bash
# Teste Verbindung
docker exec immich-metadata-sync ping immich_postgres

# Prüfe Netzwerk
docker network ls
docker network inspect immich_default
```

### USB-Festplatte nicht gemountet
```bash
# Prüfe Mount
mountpoint /mnt/usb-backup

# Mount manuell
sudo mount /dev/sdX1 /mnt/usb-backup
```

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `BACKUP_TARGET` | Zielverzeichnis für Backups | `/backup` |
| `IMMICH_PHOTO_DIR` | Immich Library im Container | `/library` |
| `DB_HOST` | PostgreSQL Hostname | `immich_postgres` |
| `DB_USERNAME` | Datenbank-Benutzer | `postgres` |
| `DB_PASSWORD` | Datenbank-Passwort | `postgres` |
| `DB_NAME` | Datenbank-Name | `immich` |
| `KEEP_BACKUPS` | Anzahl zu behaltender Backups | `7` |

## Tipps

- 🔒 **Sicherheit**: Library wird read-only gemountet
- ⏱️ **Timing**: Backups nachts laufen lassen (geringe Last)
- 💾 **Speicher**: Plane 2-3x die Library-Größe für Backups ein
- 🔄 **Rotation**: Alte Backups werden automatisch gelöscht
- 📊 **Monitoring**: Prüfe regelmäßig `/var/log/immich-backup-cron.log`
