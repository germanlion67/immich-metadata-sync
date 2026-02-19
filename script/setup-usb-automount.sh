#!/bin/bash
################################################################################
# Setup USB-Automount für Backup-Festplatte
################################################################################

USB_DEVICE="/dev/disk/by-uuid/0AACAB5AACAB3F57"  # Anpassen!
MOUNT_POINT="/mnt/usb-backup"

echo "Richte USB-Automount ein..."

# UUID ermitteln
echo ""
echo "Verfügbare Festplatten:"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,UUID
echo ""
read -p "UUID der USB-Festplatte eingeben: " USB_UUID

if [ -z "$USB_UUID" ]; then
    echo "❌ Keine UUID eingegeben"
    exit 1
fi

# Erstelle Mountpoint
mkdir -p "$MOUNT_POINT"

# Erstelle fstab-Eintrag
FSTAB_ENTRY="UUID=$USB_UUID $MOUNT_POINT ext4 defaults,nofail,x-systemd.device-timeout=10 0 2"

if ! grep -qF "$USB_UUID" /etc/fstab; then
    echo "$FSTAB_ENTRY" | sudo tee -a /etc/fstab
    echo "✅ fstab-Eintrag hinzugefügt"
else
    echo "ℹ️  fstab-Eintrag existiert bereits"
fi

# Mounte Festplatte
sudo mount -a

if mountpoint -q "$MOUNT_POINT"; then
    echo "✅ USB-Festplatte erfolgreich gemountet"
else
    echo "❌ Mount fehlgeschlagen"
    exit 1
fi

echo ""
echo "USB-Automount eingerichtet!"
echo "Mountpoint: $MOUNT_POINT"
