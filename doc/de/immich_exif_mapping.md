# Immich zu EXIF/XMP Feld-Mapping Tabelle

Diese zeigt die Zuordnung zwischen Immich-API-Feldern (aus Asset-Details und Album-Informationen) und den entsprechenden EXIF/XMP-Feldern, die in die Bilddateien geschrieben werden.
Sie ist erweiterbar – füge einfach neue Zeilen oder Spalten hinzu (z.B. für weitere Details wie "API-Endpunkt" oder "Test-Status").

| Immich-Feld | EXIF/XMP-Feld | Beschreibung | Beispiel | Status | Notizen |
|-------------|---------------|--------------|----------|--------|---------|
| `people[].name` (aus Asset-Details) | `XMP:Subject`<br>`IPTC:Keywords`<br>`XMP-iptcExt:PersonInImage` | Erkannte Personen werden als Keywords und Person-In-Image-Liste geschrieben. | Person: "Alice" → "Alice" in allen Feldern | Implementiert | Hochpriorität; unterstützt mehrere Personen pro Asset. |
| `exifInfo.latitude` | `GPSLatitude` | GPS-Breitengrad aus EXIF-Info. | 51.5074 | Implementiert | Präzision auf 6 Dezimalstellen gerundet. |
| `exifInfo.longitude` | `GPSLongitude` | GPS-Längengrad aus EXIF-Info. | -0.1278 | Implementiert | Präzision auf 6 Dezimalstellen gerundet. |
| `exifInfo.altitude` | `GPSAltitude` | Höhe über Meeresspiegel aus EXIF-Info. | 50 | Implementiert | Als Meter; Fallback auf 0, wenn nicht verfügbar. |
| `exifInfo.description` | `XMP:Description`<br>`IPTC:Caption-Abstract` | Beschreibung/Kaption des Assets. | "Sunset at the beach" | Implementiert | Max. Länge 2000 Zeichen; Zeilenumbrüche werden zu Leerzeichen. |
| `fileCreatedAt` oder `exifInfo.dateTimeOriginal` | `DateTimeOriginal`<br>`CreateDate`<br>`XMP:CreateDate`<br>`XMP-photoshop:DateCreated` | Zeitstempel der Dateierstellung oder EXIF-Aufnahmezeit. | 2023-10-01 15:30:00 (formatiert) | Implementiert | Robustes Parsing; Fallback auf String-Formatierung. |
| `isFavorite` (Asset) | `Rating` | Favoriten-Status als Stern-Rating (5 für Favorit, 0 sonst). | true → 5 | Implementiert | Nur 0 oder 5; keine Zwischenwerte. |
| Album-Name (aus Album-API) | `XMP-iptcExt:Event`<br>`XMP:HierarchicalSubject` | Album-Name als Event (primäres Album) und hierarchische Keywords (alle Alben). | Album: "Vacation" → "Vacation" in Event, "Albums|Vacation" in HierarchicalSubject | Implementiert (neu) | Erfordert separate API-Calls; Präfix "Albums|" für Hierarchie. |
| Album-Beschreibung (aus Album-API) | `XMP-iptcExt:Event` <br> `XMP:HierarchicalSubject` <br> `EXIF:UserComment` → Windows "Kommentare" | Potenziell in `XMP:Description` oder separates Feld. | "Testalbum Beschreibung" | Geplant | Zukünftig; vermeidet Konflikte mit Asset-Beschreibung. |
| Andere (z.B. Tags) | (noch nicht zugewiesen) | Platz für weitere Immich-Felder wie Tags oder Standort-Details. | - | Geplant | Abhängig von API-Verfügbarkeit und Nutzer-Feedback. |

## Die Spalten sind: 
- **Immich-Feld:** Das Feld aus der Immich-API (z.B. aus /assets/{id} oder Album-Details).
- **EXIF/XMP-Feld:** Das Ziel-Feld in der Bilddatei (wie von ExifTool verwendet).
- **Beschreibung:** Kurze Erklärung der Zuordnun
- **Beispiel:** Ein Beispielwert.
- **Status:** Zeigt an, ob das Mapping bereits implementiert ist (z.B. "Implementiert" oder "Geplant").
- **Notizen:** Platz für weitere Details, Prioritäten oder Erweiterungen (z.B. zukünftige Felder wie Album-Beschreibung).

***
## Hinweise zur Nutzung
- **Erweiterung**: Füge neue Zeilen hinzu, z.B. für zukünftige Felder. Neue Spalten können einfach hinzugefügt werden (z.B. `| Neue Spalte |` in Header und jede Zeile).
- **Quelle**: Basierend auf dem aktuellen Script-Code (`build_exif_args()`). Aktualisiere bei Code-Änderungen.
