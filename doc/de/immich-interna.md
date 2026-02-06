
## Reihenfolge der Beachtung beim Datumsfeld

Immich verwendet eine klare Prioritätenliste, um das „Aufnahmedatum“ für die Timeline zu bestimmen. Dabei werden primär eingebettete EXIF-Metadaten ausgelesen, bevor auf Dateisystem-Attribute zurückgegriffen wird. 
Die Reihenfolge der Beachtung ist laut Immich-Dokumentation und Community-Beiträgen wie folgt:

### 1. EXIF-Metadaten (Höchste Priorität)
Immich sucht in den Bild- oder Videodateien nach diesen Feldern (in absteigender Priorität):
- **SubSecDateTimeOriginal / DateTimeOriginal:** Das präziseste Datum, wann der Auslöser gedrückt wurde.
- **SubSecCreateDate / CreateDate:** Oft von Kameras verwendet, um den Zeitpunkt der Dateierstellung auf dem Medium zu markieren.
- **CreationDate / DateTimeCreated:** Häufig bei mobil aufgenommenen Medien oder Scans zu finden.
- **MediaCreateDate:** Speziell bei Videodateien (MP4/MOV). 

### 2. Dateisystem-Attribute (Fallback)
Wenn keine EXIF-Daten vorhanden sind (z. B. bei exportierten WhatsApp-Bildern oder Screenshots), nutzt Immich: 
- **File Creation Date:** Das Datum, an dem die Datei auf dem aktuellen Betriebssystem erstellt wurde.
- **File Modification Date:** Das Datum der letzten Änderung der Datei. 

### 3. Upload-Zeitpunkt (Letzter Ausweg)
Sollten überhaupt keine Zeitstempel in der Datei oder dem Dateisystem auffindbar sein, wird das Bild oft dem Zeitpunkt des Uploads zugeordnet. 
Wichtige Besonderheiten:
- **Zeitzonen:** Immich beachtet vorhandene Offset-Informationen (z. B. OffsetTimeOriginal). Fehlen diese, wird oft die Serverzeit oder eine in der .env-Datei konfigurierte Zeitzone angenommen.
- **Sidecar-Dateien:** Falls du .xmp-Dateien (z. B. aus Lightroom oder DigiKam) mit hochlädst, werden diese ebenfalls zur Bestimmung des korrekten Datums herangezogen.
- **Manuelle Korrektur:** Du kannst das Datum jedes Assets direkt in der Immich Web-Oberfläche oder App über das „Info“-Symbol (i) und dann „Datum bearbeiten“ manuell anpassen.
