# Immich Backup Setup (LXC-optimiert)

## Übersicht

Dieses Setup ermöglicht vollständige Backups von Immich (Datenbank + Bilder) auf eine USB-Festplatte direkt aus dem `immich-metadata-sync` Container in einem Proxmox LXC-Container.

**Besonderheiten:**
- ✅ Nutzt vorhandene Immich-DB-Backups (schneller als pg_dump)
- ✅ Optimiert für Proxmox LXC mit Bind-Mounts
- ✅ Warnt automatisch bei veralteten Backups (>5 Tage)
- ✅ Kein Datenbank-Netzwerk nötig (nutzt Volume-Mounts)

## Architektur

```
Proxmox Host (pve3)
├── /mnt/immich-library/          ← Immich-Daten auf Host
│   ├── library/                  ← Alle Bilder
│   └── backups/                  ← Tägliche DB-Backups (Immich)
├── /mnt/usb-backup/              ← USB-Backup-Ziel
│
└── LXC Container
    └── Docker
        ├── Immich Container
        └── immich-metadata-sync  ← Backup-Container
            ├── /library          → gemountet von /mnt/immich-library/library
            ├── /immich-backups   → gemountet von /mnt/immich-library/backups
            └── /backup           → gemountet von /mnt/usb-backup
```

## Voraussetzungen

1. **Proxmox LXC-Container** mit Immich
2. **USB-Festplatte** formatiert als **ext4** (empfohlen)
3. Docker und docker-compose installiert im LXC
4. Immich läuft und erstellt tägliche Backups

## Installation

### Schritt 1: USB-Festplatte auf Proxmox-Host vorbereiten

```bash
# Auf Proxmox-Host (SSH)
ssh root@pve3

# Festplatte identifizieren
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE

# Prüfe Dateisystem (sollte ext4 sein)
blkid | grep -E "sdc1|sdb1"

# Falls NTFS: Auf ext4 umformatieren (LÖSCHT ALLE DATEN!)
# umount /dev/sdX1
# mkfs.ext4 -L "immich-backup" /dev/sdX1

# UUID ermitteln (für fstab)
blkid | grep ext4

# Mountpoint erstellen
mkdir -p /mnt/usb-backup

# Temporär mounten
mount /dev/sdX1 /mnt/usb-backup

# Prüfen
df -h | grep usb-backup
ls -la /mnt/usb-backup

# Rechte setzen (wichtig für LXC!)
chmod 777 /mnt/usb-backup
```

### Schritt 2: USB permanent mounten (fstab)

```bash
# Auf Proxmox-Host
nano /etc/fstab

# Am Ende hinzufügen (UUID von oben verwenden):
UUID=xxxx-xxxx-xxxx /mnt/usb-backup ext4 defaults,nofail 0 2

# Speichern: Ctrl+O, Enter, Ctrl+X

# Test
umount /mnt/usb-backup
mount -a
df -h | grep usb-backup
```

### Schritt 3: USB in LXC-Container durchreichen

```bash
# Auf Proxmox-Host
# LXC-Container-ID finden
pct list

# Beispiel-Ausgabe:
# VMID       Status     Name
# 100        running    immich

# LXC-Config bearbeiten (ANPASSEN: CT-ID)
CT_ID=100
nano /etc/pve/lxc/${CT_ID}.conf

# Am Ende hinzufügen:
mp0: /mnt/usb-backup,mp=/mnt/usb-backup
mp1: /mnt/immich-library,mp=/mnt/immich-library

# Speichern: Ctrl+O, Enter, Ctrl+X

# Container neu starten
pct stop $CT_ID
pct start $CT_ID

# Prüfen (in LXC einloggen)
pct enter $CT_ID
df -h | grep mnt
ls -la /mnt/usb-backup
ls -la /mnt/immich-library/backups
exit
```

**Falls Permission-Denied Fehler:**
```bash
# Auf Proxmox-Host
nano /etc/pve/lxc/${CT_ID}.conf

# Ändere die mp-Zeilen zu:
mp0: /mnt/usb-backup,mp=/mnt/usb-backup,shared=1
mp1: /mnt/immich-library,mp=/mnt/immich-library,shared=1

# Rechte anpassen (für unprivileged LXC)
chown -R 100000:100000 /mnt/usb-backup

# Container neu starten
pct restart $CT_ID
```

### Schritt 4: Container bauen und starten

```bash
# Im LXC-Container (pct enter [CT-ID])
cd /pfad/zu/immich-metadata-sync

# Prüfe ob Dockerfile angepasst ist (rsync, pg-client)
cat Dockerfile | grep -E "rsync|postgresql-client"

# Falls nicht vorhanden, Dockerfile anpassen!

# Container bauen
docker-compose build --no-cache

# Container starten
docker-compose up -d

# Prüfen
docker ps | grep immich-metadata-sync
```

### Schritt 5: Mounts im Container verifizieren

```bash
# Im LXC-Container

# Prüfe Library-Mount
docker exec immich-metadata-sync ls -lh /library | head -n 5

# Prüfe Immich-Backup-Mount
docker exec immich-metadata-sync ls -lh /immich-backups

# Sollte zeigen: immich-db-backup-*.sql.gz Dateien

# Prüfe USB-Mount
docker exec immich-metadata-sync ls -lh /backup
docker exec immich-metadata-sync touch /backup/test.txt
docker exec immich-metadata-sync rm /backup/test.txt
```

### Schritt 6: Erstes Backup ausführen

```bash
# Im LXC-Container

# Variante A: Mit run-backup.sh (vom Host)
chmod +x script/backup/run-backup.sh
./script/backup/run-backup.sh

# Variante B: Direkt im Container
docker exec immich-metadata-sync /app/script/backup/immich-backup.sh

# Logs live verfolgen
docker exec immich-metadata-sync tail -f /backup/backup.log

# ODER
tail -f /mnt/usb-backup/backup.log  # Auf Proxmox-Host
```

### Schritt 7: Backup-Ergebnis prüfen

```bash
# Im LXC oder auf Proxmox-Host

# Struktur ansehen
ls -lh /mnt/usb-backup/

# Sollte zeigen:
# 20260219_143000/
# latest -> 20260219_143000/
# backup.log

# Backup-Details
ls -lh /mnt/usb-backup/latest/
cat /mnt/usb-backup/latest/metadata/backup_manifest.txt

# Größe prüfen
du -sh /mnt/usb-backup/latest/

# Neuestes DB-Backup prüfen
ls -lh /mnt/usb-backup/latest/database/
```

## Backup-Struktur

```
/mnt/usb-backup/
├── 20260219_143000/          # Backup vom 19.02.2026 14:30
│   ├── database/
│   │   └── immich-db-backup-20260219T020000-v2.4.1-pg14.17.sql.gz
│   ├── library/              # Alle Bilder (rsync)
│   │   ├── user1/
│   │   ├── user2/
│   │   └── ...
│   ├── metadata/
│   │   ├── backup_manifest.txt        # Backup-Info + Checksummen
│   │   ├── immich_version.json        # Immich-Version
│   │   └── immich_statistics.json     # Asset-Statistiken
│   ├── logs/
│   │   └── rsync.log                  # rsync-Output
│   └── RESTORE_INSTRUCTIONS.txt       # Wiederherstellungs-Anleitung
├── 20260220_030000/          # Nächstes Backup
├── latest -> 20260220_030000/          # Symlink zum neuesten
└── backup.log                # Globales Log (alle Backups)
```

## Backup-Script Verhalten

### Intelligente DB-Backup-Nutzung

Das Script prüft automatisch vorhandene Immich-Backups:

```
[Script] 🗄️  Starte Datenbank-Backup...
[Script]    📂 Prüfe Immich-Backup-Verzeichnis: /immich-backups
[Script]    📋 Immich-Backup gefunden: immich-db-backup-20260219T020000.sql.gz
[Script]    📅 Backup-Datum:  2026-02-19 02:00:00
[Script]    ⏱️  Alter:         12h 30m (0 Tage)
[Script]    💾 Größe:         16M
[Script]    ✅ Backup ist aktuell (< 5 Tage)
[Script]    📦 Kopiere vorhandenes Immich-Backup...
[Script] ✅ Datenbank-Backup abgeschlossen (aus Immich-Backup)
```

### Warnung bei altem Backup (>5 Tage)

```
[Script]    ⏱️  Alter:         6d 12h (6 Tage)
[Script]    ⚠️  WARNUNG: Backup ist älter als 5 Tage!
[Script]    ⚠️  Empfehlung: Prüfe ob Immich-Backups noch laufen
[Script]    ⚠️  Nutze vorhandenes Backup trotz Alter (5-10 Tage)
```

### Fallback bei sehr altem Backup (>10 Tage)

```
[Script]    ⏱️  Alter:         11d 5h (11 Tage)
[Script]    ❌ Backup ist zu alt (>10 Tage), erstelle neues pg_dump...
[Script]    ⚠️  Kann nicht mit Datenbank verbinden (kein Netzwerk konfiguriert)
[Script]    ❌ FEHLER: Kein aktuelles DB-Backup verfügbar
```

**Lösung:** Entweder Immich-Backup-Job reparieren oder Netzwerk in docker-compose.yml aktivieren.

## Automatische Backups (Cron)

### Option 1: Cron im LXC-Container

```bash
# Im LXC-Container
crontab -e

# Täglich um 3:00 Uhr
0 3 * * * cd /pfad/zu/immich-metadata-sync && docker exec immich-metadata-sync /app/script/backup/immich-backup.sh >> /var/log/immich-backup-cron.log 2>&1
```

### Option 2: Cron auf Proxmox-Host (empfohlen)

```bash
# Auf Proxmox-Host
nano /opt/immich-backup-cron.sh
```

Inhalt:
```bash
#!/bin/bash
CT_ID=100  # ANPASSEN!
LOG_FILE="/var/log/immich-backup-cron.log"

{
    echo "========================================"
    echo "Backup gestartet: $(date)"
    echo "========================================"
    
    pct exec $CT_ID -- docker exec immich-metadata-sync /app/script/backup/immich-backup.sh
    
    echo "Beendet: $(date)"
    echo ""
} >> "$LOG_FILE" 2>&1
```

```bash
# Ausführbar machen
chmod +x /opt/immich-backup-cron.sh

# Cron einrichten
crontab -e

# Täglich um 3:00 Uhr
0 3 * * * /opt/immich-backup-cron.sh
```

## Wiederherstellung

### Schnellanleitung

```bash
# 1. Im LXC-Container: Immich stoppen
cd /pfad/zu/immich
docker-compose down

# 2. Datenbank wiederherstellen
gunzip -c /mnt/usb-backup/latest/database/*.sql.gz > /tmp/immich_restore.sql

docker-compose up -d immich_postgres
sleep 10

docker exec immich_postgres psql -U postgres -c "DROP DATABASE IF EXISTS immich;"
docker exec immich_postgres psql -U postgres -c "CREATE DATABASE immich;"
docker exec -i immich_postgres psql -U postgres -d immich < /tmp/immich_restore.sql

rm /tmp/immich_restore.sql

# 3. Auf Proxmox-Host: Library wiederherstellen
mv /mnt/immich-library/library /mnt/immich-library/library.backup.$(date +%Y%m%d)
mkdir -p /mnt/immich-library/library
rsync -avh /mnt/usb-backup/latest/library/ /mnt/immich-library/library/
chown -R 1000:1000 /mnt/immich-library/library

# 4. Im LXC: Immich starten
docker-compose up -d

# 5. In Immich Web-UI: Library-Scan durchführen
# Administration -> Jobs -> Library -> Scan All Libraries
```

Siehe auch `RESTORE_INSTRUCTIONS.txt` im jeweiligen Backup-Verzeichnis für detaillierte Anweisungen.

## Fehlerbehebung

### Container läuft nicht
```bash
docker-compose logs immich-metadata-sync
docker ps -a | grep immich-metadata-sync
```

### Backup schlägt fehl
```bash
# Logs prüfen
docker exec immich-metadata-sync cat /backup/backup.log
tail -50 /mnt/usb-backup/backup.log

# Mounts prüfen
docker exec immich-metadata-sync df -h
docker exec immich-metadata-sync ls -la /library /backup /immich-backups
```

### "Immich-Backup-Verzeichnis nicht gefunden"
```bash
# Prüfe Mount im LXC
ls -la /mnt/immich-library/backups

# Prüfe Mount im Container
docker exec immich-metadata-sync ls -la /immich-backups

# Falls leer: Prüfe ob Immich-Backups laufen
docker logs immich_postgres | grep backup
```

### "Permission denied" auf USB
```bash
# Auf Proxmox-Host
ls -ld /mnt/usb-backup

# Rechte setzen
chmod 777 /mnt/usb-backup

# Falls unprivileged LXC:
chown -R 100000:100000 /mnt/usb-backup

# LXC-Config prüfen
cat /etc/pve/lxc/[CT-ID].conf | grep shared

# Falls nicht vorhanden, hinzufügen:
mp0: /mnt/usb-backup,mp=/mnt/usb-backup,shared=1

# Container neu starten
pct restart [CT-ID]
```

### "rsync" oder "pg_dump" nicht gefunden
```bash
# Prüfe Dockerfile
docker exec immich-metadata-sync which rsync
docker exec immich-metadata-sync which pg_dump

# Falls nicht vorhanden: Dockerfile anpassen und neu bauen
# Dockerfile muss enthalten:
# RUN apt-get update && apt-get install -y rsync postgresql-client

docker-compose build --no-cache
docker-compose up -d
```

### USB-Festplatte nach Reboot nicht gemountet
```bash
# Auf Proxmox-Host
mountpoint /mnt/usb-backup

# Manuell mounten
mount -a

# fstab prüfen
cat /etc/fstab | grep usb-backup

# Falls fehlt, hinzufügen (siehe Schritt 2)
```

### Immich-Backups älter als 5 Tage
```bash
# Prüfe wann letztes Backup erstellt wurde
ls -lht /mnt/immich-library/backups/ | head

# Prüfe Immich-Backup-Job
cd /pfad/zu/immich
docker-compose logs immich_postgres | grep -i backup

# Prüfe ob Backup-Job aktiviert ist (docker-compose.yml)
cat docker-compose.yml | grep -A 5 "backup"

# Manuell Backup triggern
docker exec immich_postgres pg_dump -U postgres immich | gzip > /mnt/immich-library/backups/manual-backup-$(date +%Y%m%d).sql.gz
```

## Umgebungsvariablen

| Variable | Beschreibung | Standard | Benötigt |
|----------|--------------|----------|----------|
| `BACKUP_TARGET` | Zielverzeichnis für Backups | `/backup` | ✅ Ja |
| `IMMICH_PHOTO_DIR` | Immich Library im Container | `/library` | ✅ Ja |
| `IMMICH_DB_BACKUP_DIR` | Immich-DB-Backups im Container | `/immich-backups` | ✅ Ja |
| `KEEP_BACKUPS` | Anzahl zu behaltender Backups | `7` | ⚪ Optional |
| `DB_BACKUP_MAX_AGE_DAYS` | Warnschwelle für Backup-Alter | `5` | ⚪ Optional |
| `IMMICH_INSTANCE_URL` | Immich API (für Metadaten) | - | ⚪ Optional |
| `IMMICH_API_KEY` | Immich API-Key | - | ⚪ Optional |
| `DB_HOST` | PostgreSQL Host (Fallback) | `immich_postgres` | ❌ Nur mit Netzwerk |
| `DB_USERNAME` | Datenbank-Benutzer (Fallback) | `postgres` | ❌ Nur mit Netzwerk |
| `DB_PASSWORD` | Datenbank-Passwort (Fallback) | `postgres` | ❌ Nur mit Netzwerk |
| `DB_NAME` | Datenbank-Name (Fallback) | `immich` | ❌ Nur mit Netzwerk |
| `TZ` | Timezone | `Europe/Berlin` | ⚪ Optional |

## Performance & Tipps

### Backup-Geschwindigkeit
- **Erstes Backup:** 10-30 Min (je nach Library-Größe)
- **Folge-Backups:** 2-5 Min (nur geänderte Dateien via rsync)
- **DB-Backup-Kopieren:** < 10 Sekunden
- **pg_dump (Fallback):** 1-3 Min

### Speicherplatzbedarf
- **Minimal:** 1x Library-Größe + 200MB (DB)
- **Empfohlen:** 3x Library-Größe (für mehrere Backups)
- **Beispiel:** 500GB Library → 1.5TB USB empfohlen

### Best Practices
- 🔒 **Sicherheit:** Library wird read-only gemountet (`:ro`)
- ⏱️ **Timing:** Backups nachts laufen lassen (geringe Last, nach Immich-Backup um 02:00)
- 💾 **Speicher:** Prüfe regelmäßig USB-Speicherplatz: `df -h /mnt/usb-backup`
- 🔄 **Rotation:** Script löscht automatisch alte Backups (behalte `KEEP_BACKUPS=7`)
- 📊 **Monitoring:** 
  ```bash
  # Backup-Größen anzeigen
  du -sh /mnt/usb-backup/*/ | sort -h
  
  # Letztes Backup-Datum
  ls -ldt /mnt/usb-backup/[0-9]* | head -1
  ```
- 🧪 **Testen:** Führe regelmäßig Test-Restores durch!

### Optimierungen
```bash
# rsync-Optionen für schnellere Backups (in immich-backup.sh anpassen)
# Statt: rsync -ah --info=progress2 --delete --checksum
# Nutze: rsync -ah --info=progress2 --delete --size-only  # Schneller, weniger sicher

# Nur neue/geänderte Dateien (kein --delete)
# rsync -ah --info=progress2 --checksum

# Immich-Backup-Alter erhöhen (weniger Warnungen)
# In docker-compose.yml:
- DB_BACKUP_MAX_AGE_DAYS=10  # Statt 5
```

## Überwachung & Wartung

### Regelmäßige Checks (monatlich)

```bash
# 1. Backup-Alter prüfen
ls -lt /mnt/usb-backup/[0-9]* | head -5

# 2. Speicherplatz prüfen
df -h /mnt/usb-backup

# 3. Letzte 5 Backup-Logs prüfen
tail -100 /mnt/usb-backup/backup.log

# 4. Backup-Integrität prüfen
gunzip -t /mnt/usb-backup/latest/database/*.sql.gz && echo "✅ DB-Backup OK"

# 5. Immich-Backup-Job Status
ls -lht /mnt/immich-library/backups/ | head -3
```

### Alarme einrichten (optional)

```bash
# Simple E-Mail-Benachrichtigung bei Fehlern
# In Cron-Script nach Backup-Ausführung:

if ! grep -q "✅ BACKUP ERFOLGREICH" /mnt/usb-backup/backup.log | tail -50; then
    echo "Immich Backup fehlgeschlagen!" | mail -s "ALARM: Backup Error" admin@example.com
fi
```

## Upgrade-Pfad

### Von alter Setup-Version upgraden

```bash
# 1. Backup des Backup-Scripts ;-)
cp script/backup/immich-backup.sh script/backup/immich-backup.sh.backup

# 2. Neue Version pullen
git pull origin main

# 3. Container neu bauen
docker-compose build --no-cache
docker-compose up -d

# 4. Test-Backup
docker exec immich-metadata-sync /app/script/backup/immich-backup.sh
```

## Support & Links

- **Immich Dokumentation:** https://immich.app/docs
- **Immich Discord:** https://discord.gg/immich
- **Repository:** https://github.com/germanlion67/immich-metadata-sync
- **Issues:** https://github.com/germanlion67/immich-metadata-sync/issues

## Changelog

### Version 2.0 (2026-02-19)
- ✅ Intelligente Nutzung vorhandener Immich-Backups
- ✅ Warnungen bei veralteten Backups (>5 Tage)
- ✅ Optimiert für LXC mit Bind-Mounts
- ✅ Kein Datenbank-Netzwerk mehr nötig
- ✅ Detaillierte Backup-Manifeste mit Quellenangabe
- ✅ Verbesserte Fehlerbehandlung und Logging

### Version 1.0 (Initial)
- Basis-Backup-Funktionalität
- pg_dump für Datenbank
- rsync für Library
