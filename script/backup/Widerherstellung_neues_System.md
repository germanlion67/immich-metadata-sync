 # Checkliste — Immich Restore auf neuen Proxmox-Host (unprivileged LXC) + DB Restore via `psql`
**Ziel:** Immich (v2.5.0) auf neuem Proxmoxhost wiederherstellen inkl. Datenbank + kompletter Datenstruktur  
**DB-Container-Name:** `immich_postgres` (bestätigt)  
**USB-Backup-Device:** `/dev/sdb2` (ext4)  
**LXC:** unprivileged


## 0) Vorher festlegen (1x entscheiden)
- [ ] Immich am Ziel auf **Version 2.5.0** setzen (mindestens für den Restore).
- [ ] Zielpfade (empfohlen identisch zur Quelle) werden angelegt unter:
  - [ ] `/home/immich/immich-library/library`
  - [ ] `/home/immich/immich-library/upload`
  - [ ] `/home/immich/immich-library/thumbs`
  - [ ] `/home/immich/immich-library/encoded-video`
  - [ ] `/home/immich/immich-library/profile`
  - [ ] `/home/immich/immich-library/backups`
- [ ] Freier Speicher am Ziel: mind. **~140–160GB** (Library ~110GB + Puffer + Overhead).

---

## Schritt 1 — USB-SSD am neuen Proxmox-Host mounten (root@pveX)

### 1.1 Device/UUID prüfen
```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT /dev/sdb /dev/sdb2
blkid /dev/sdb2
```
- UUID notieren (z.B. `UUID="xxxx-xxxx"`).

### 1.2 Mountpoint erstellen + Test-Mount
```bash
mkdir -p /mnt/usb-backup

mount /dev/sdb2 /mnt/usb-backup

df -h /mnt/usb-backup
ls -la /mnt/usb-backup | head -50
```

### 1.3 Permanent mounten (fstab)
`/etc/fstab` ergänzen (UUID anpassen):

```fstab
UUID=DEINE-UUID  /mnt/usb-backup  ext4  defaults,nofail  0  2
```
Test:

```bash
umount /mnt/usb-backup
systemctl daemon-reload
mount -a
df -h | grep usb-backup
```

### 1.4 Rechte für unprivileged LXC “robust” setzen
```bash
chmod 777 /mnt/usb-backup
```
---

## Schritt 2 — USB-SSD in den unprivileged LXC durchreichen (root@pveX)
### 2.1 LXC Config anpassen
```bash
CT_ID=<DEINE_CTID>
nano /etc/pve/lxc/${CT_ID}.conf
```
Eintragen:

```Text
mp0: /mnt/usb-backup,mp=/mnt/usb-backup,shared=1
```
### 2.2 LXC neu starten + prüfen
```bash
pct stop ${CT_ID}

pct start ${CT_ID}

pct enter ${CT_ID}

df -h | grep usb-backup

ls -la /mnt/usb-backup | head -50
```
---

## Schritt 3 — Backup-Struktur prüfen (im LXC)
```bash
ls -la /mnt/usb-backup | head -50
ls -l /mnt/usb-backup/latest
```
- [ ]Timestamp-Ordner vorhanden (`YYYYMMDD_HHMMSS/`)
- [ ]`latest -> YYYYMMDD_HHMMSS` (relativ ist ideal)
 ---

## Schritt 4 — Zielverzeichnisse anlegen (im LXC)
```bash
mkdir -p /home/immich/immich-library/{library,upload,thumbs,encoded-video,profile,backups}
```
Optional:

```bash
chmod -R 775 /home/immich/immich-library
```
---

## Schritt 5 — rsync nachinstallieren + in Backup-Ordner `latest` wechseln (im LXC)
> rsync ist auf minimalen LXC-Setups nicht immer vorinstalliert.

### 5.1 rsync installieren
Debian/Ubuntu:

```bash
apt update
apt install -y rsync
```

### 5.2 In `latest` wechseln (Symlink prüfen)
```bash
cd /mnt/usb-backup/latest

# Wenn Symlink nicht funktioniert kann auch direkt ins neuste Backupverzeichnis gewechselt werden
cd /mnt/usb-backup/........

ls -la
```

---


## Schritt 6 — Daten kopieren (im LXC)
> Empfehlung: Immich am Ziel während des Kopierens gestoppt lassen.

### 6.1 Library kopieren
```bash
rsync -aH --info=progress2 ./library/ /home/immich/immich-library/library/
```

### 6.2 Upload kopieren
```bash
rsync -aH --info=progress2 ./upload/ /home/immich/immich-library/upload/
```

### 6.3 Thumbs kopieren (optional, spart Recompute)
```bash
rsync -aH --info=progress2 ./thumbs/ /home/immich/immich-library/thumbs/
```

### 6.4 Encoded Video kopieren (optional, spart Transcoding)
```bash
rsync -aH --info=progress2 ./encoded-video/ /home/immich/immich-library/encoded-video/
```

### 6.5 Profile kopieren (optional)
```bash
rsync -aH --info=progress2 ./profile/ /home/immich/immich-library/profile/
```

### 6.6 DB-Backup-Datei(en) bereitstellen
Falls im Backup-Ordner `database/` existiert:

```bash
rsync -a --info=progress2 ./database/ /home/immich/immich-library/backups/
```
---
## Schritt 7 — Ownership/Permissions setzen (im LXC)
> Häufig schreiben Immich-Container mit UID/GID 1000:1000. Falls bei dir anders, anpassen.

Optional prüfen:

```bash
docker exec -it immich_server id
docker exec -it immich_microservices id
```
Dann setzen (Beispiel 1000:1000):

```bash
chown -R 1000:1000 /home/immich/immich-library
```
---
## Schritt 8 — DB Restore klassisch via psql (im LXC)
### 8.1 Immich stoppen, nur Postgres starten
Im Immich-Stack-Verzeichnis:

```bash
docker compose down
docker compose up -d immich_postgres
```
### 8.2 Dump auswählen
```bash
ls -lh /home/immich/immich-library/backups/*.sql.gz | head
```
> Falls mehrere Dumps vorhanden sind: nimm den neuesten (oder den gewünschten).

### 8.3 Datenbank neu anlegen + Restore (Streaming, ohne Temp-Datei)
```bash
docker exec immich_postgres psql -U postgres -c "DROP DATABASE IF EXISTS immich;"
docker exec immich_postgres psql -U postgres -c "CREATE DATABASE immich;"

gunzip -c /home/immich/immich-library/backups/*.sql.gz | 
  docker exec -i immich_postgres psql -U postgres -d immich
```
---
## Schritt 9 — Immich starten + Validierung
### 9.1 Immich komplett starten
```bash
docker compose up -d
```
### 9.2 Logs prüfen
```bash
docker compose logs -f --tail=200 immich_server
docker compose logs -f --tail=200 immich_microservices
```

### 9.3 UI prüfen
- [ ] Login klappt
- [ ] Assets/Alben vorhanden
- [ ] Admin → Jobs: ggf. **Scan All Libraries** starten, falls Pfade/Index noch nicht sauber sind
---

## Schritt 10 — Cutover / Alt-System abschalten
- [ ] Alte Instanz stoppen, bevor neue produktiv genutzt wird
- [ ] DNS / Reverse Proxy auf neue IP/Host umstellen
---


## Troubleshooting Quick Checks
### A) Pfade/Mounts
```bash
ls -la /home/immich/immich-library
df -h
```
### B) DB erreichbar
```bash
docker exec -it immich_postgres psql -U postgres -c "\l"
```
### C) Rechte
```bash
ls -ld /home/immich/immich-library /home/immich/immich-library/library
```
