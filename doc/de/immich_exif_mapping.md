# Immich zu EXIF/XMP Feld-Mapping Tabelle

Diese zeigt die Zuordnung zwischen Immich-API-Feldern (aus Asset-Details und Album-Informationen) und den entsprechenden EXIF/XMP-Feldern, die in die Bilddateien geschrieben werden.
Sie ist erweiterbar – füge einfach neue Zeilen oder Spalten hinzu (z.B. für weitere Details wie "API-Endpunkt" oder "Test-Status").

| Immich-Feld | EXIF/XMP-Feld | Beschreibung | Beispiel | Datei (Win11) | XnView MP |
|-------------|---------------|--------------|----------|--------|---------|
| `people[].name` (aus Asset-Details) | `XMP:Subject`<br>`IPTC:Keywords`<br>`XMP-iptcExt:PersonInImage` | Erkannte Personen werden als Keywords und Person-In-Image-Liste geschrieben. Unterstützt mehrere Personen pro Asset | Person: "Alice" → "Alice" in allen Feldern | Markierung | ja |
| `exifInfo.latitude` | `GPSLatitude` | GPS-Breitengrad aus EXIF-Info. auf 6 Dezimalstellen gerundet  | 51.5074 | Breitengrad | Ja |
| `exifInfo.longitude` | `GPSLongitude` | GPS-Längengrad aus EXIF-Info. | -0.1278 | Längengrad | Ja |
| `exifInfo.altitude` | `GPSAltitude` | Höhe über Meeresspiegel aus EXIF-Info. | 50 | Höhe über Normal-Null | Ja |
| `exifInfo.description` | `XMP:Description`<br>`IPTC:Caption-Abstract` | Beschreibung/Kaption des Assets. Max. Länge 2000 Zeichen; Zeilenumbrüche werden zu Leerzeichen. | "Sunset at the beach" | Titel | Ja |
| Ältestes Datum aus: `exifInfo.dateTimeOriginal`, `exifInfo.dateTimeCreated`, `exifInfo.modifyDate`, `fileCreatedAt`, `fileModifiedAt`, Dateiname-Fallback | `AllDates` (DateTimeOriginal/CreateDate/ModifyDate)<br>`XMP:CreateDate`<br>`XMP:ModifyDate`<br>`XMP:MetadataDate`<br>`IPTC:DateCreated`<br>`IPTC:TimeCreated`<br>`QuickTime:CreateDate`<br>`QuickTime:ModifyDate`<br>`FileCreateDate`<br>`FileModifyDate`<br>`XMP-photoshop:DateCreated` | Deterministische Auswahl: Das älteste (früheste) Datum aus allen verfügbaren Quellen wird geschrieben. Fallback auf Datum aus Dateiname. | `2024:01:15 10:30:45` (EXIF), `2024-01-15` (IPTC), `2024-01-15T10:30:45` (QuickTime/File) | Implementiert | Ja |
| `exifInfo.rating` oder `asset.rating` (Fallback: `isFavorite` → 5) | `XMP:Rating`<br>`MicrosoftPhoto:Rating`<br>`Rating`<br>`RatingPercent` | Stern-Rating (0–5). RatingPercent = Rating × 20. Wenn kein explizites Rating vorhanden und Favorit → Fallback auf 5 Sterne. | Rating 3 → `Rating=3`, `RatingPercent=60` | Implementiert | Ja |
| `isFavorite` (Asset) | `XMP:Label`<br>`XMP:Favorite` | Favoriten-Status unabhängig vom Stern-Rating. `XMP:Label=Favorite` und `XMP:Favorite=1` bei Favoriten, sonst leer/0. | Favorit → `Label=Favorite`, `Favorite=1` | Implementiert | Ja |
| Album-Name (aus Album-API) | `XMP-iptcExt:Event`<br>`XMP:HierarchicalSubject` | Album-Name als Event (primäres Album) und hierarchische Keywords (alle Alben). | Album: "Vacation" → "Vacation" in Event, "Albums|Vacation" in HierarchicalSubject | Implementiert (neu) | Erfordert separate API-Calls; Präfix "Albums|" für Hierarchie. |
| Album-Beschreibung (aus Album-API) | `XMP-iptcExt:Event` <br> `XMP:HierarchicalSubject` <br> `EXIF:UserComment`| Potenziell in `XMP:Description` oder separates Feld. | "Testalbum Beschreibung" | Kommentare | Ja |
| `people[].faces[].boundingBox*` + `imageWidth/imageHeight` (aus Asset-Details) | `RegionInfo` (MWG-RS XMP Region Structure) | Gesichtserkennungs-Koordinaten als MWG-RS-Regionen (Typ=Face). Bounding-Box wird auf normalisierte Koordinaten (X/Y-Mittelpunkt, W/H) konvertiert. | BBox (100,200,300,400) bei 4000×3000 → X=0.05, Y=0.1, W=0.05, H=0.067 | Implementiert | Opt-in via `--face-coordinates`; kompatibel mit Lightroom, digiKam u.a. |
| Andere (z.B. Tags) | (noch nicht zugewiesen) | Platz für weitere Immich-Felder wie Tags oder Standort-Details. | - | Geplant | Abhängig von API-Verfügbarkeit und Nutzer-Feedback. |
| leere Felder | | | | Betreff, Autoren, Copyright | |

## Die Spalten sind: 
- **Immich-Feld:** Das Feld aus der Immich-API (z.B. aus /assets/{id} oder Album-Details).
- **EXIF/XMP-Feld:** Das Ziel-Feld in der Bilddatei (wie von ExifTool verwendet).
- **Beschreibung:** Kurze Erklärung der Zuordnung
- **Beispiel:** Ein Beispielwert.
- **Status:** Zeigt an, ob das Mapping bereits implementiert ist (z.B. "Implementiert" oder "Geplant").
- **Notizen:** Platz für weitere Details, Prioritäten oder Erweiterungen (z.B. zukünftige Felder wie Album-Beschreibung).

***
## Hinweise zur Nutzung
- **Erweiterung**: Füge neue Zeilen hinzu, z.B. für zukünftige Felder. Neue Spalten können einfach hinzugefügt werden (z.B. `| Neue Spalte |` in Header und jede Zeile).
- **Quelle**: Basierend auf dem aktuellen Script-Code (`build_exif_args()`). Aktualisiere bei Code-Änderungen.

***
## Timestamps: Ältestes-Datum-Auswahl & Mapping

Die Zeitstempel-Synchronisation wählt deterministisch das **älteste (früheste)** Datum aus mehreren Metadatenquellen und schreibt es in eine breite Menge von Ziel-Feldern.

### Quell-Priorität (ältestes gewinnt)
1. `EXIF:DateTimeOriginal` (API: `exifInfo.dateTimeOriginal`)
2. `EXIF:CreateDate` (API: `exifInfo.dateTimeCreated`)
3. `EXIF:ModifyDate` (API: `exifInfo.modifyDate`)
4. `File:FileCreateDate` (API: `fileCreatedAt`)
5. `File:FileModifyDate` (API: `fileModifiedAt`)
6. **Fallback:** Datum aus Dateiname (Muster: `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD`, `IMG_YYYYMMDD_HHMMSS`, etc.)

### Ziel-Felder und Formate

| Ziel-Tag | Format | Beispiel |
|---|---|---|
| `AllDates` (DateTimeOriginal / CreateDate / ModifyDate) | `YYYY:MM:DD HH:MM:SS` | `2024:01:15 10:30:45` |
| `XMP:CreateDate` | `YYYY:MM:DD HH:MM:SS` | `2024:01:15 10:30:45` |
| `XMP:ModifyDate` | `YYYY:MM:DD HH:MM:SS` | `2024:01:15 10:30:45` |
| `XMP:MetadataDate` | `YYYY:MM:DD HH:MM:SS` | `2024:01:15 10:30:45` |
| `IPTC:DateCreated` | `YYYY-MM-DD` | `2024-01-15` |
| `IPTC:TimeCreated` | `HH:MM:SS` | `10:30:45` |
| `QuickTime:CreateDate` | ISO 8601 | `2024-01-15T10:30:45` |
| `QuickTime:ModifyDate` | ISO 8601 | `2024-01-15T10:30:45` |
| `FileCreateDate` | ISO 8601 | `2024-01-15T10:30:45` |
| `FileModifyDate` | ISO 8601 | `2024-01-15T10:30:45` |
| `XMP-photoshop:DateCreated` | `YYYY-MM-DD` | `2024-01-15` |

### Dateiname-Fallback Muster
- `IMG_20210615_123456.jpg` → `2021-06-15 12:34:56`
- `photo_2021-06-15.jpg` → `2021-06-15 00:00:00`
- `20210615.jpg` → `2021-06-15 00:00:00`

### Hinweise zu Zeitzonen
- EXIF-Felder (`AllDates`, `XMP:CreateDate` etc.) werden **ohne Zeitzone** geschrieben (`YYYY:MM:DD HH:MM:SS`), da EXIF keine Zeitzonen-Information speichert.
- QuickTime- und File-Felder verwenden ISO 8601 Format.
- tz-aware Timestamps werden vor dem Schreiben in naive Datetimes konvertiert (Zeitzone wird gestripped, Lokalzeit bleibt erhalten).

***
## Rating & Favoriten: Unabhängiges Mapping

Stern-Rating und Favoriten-Status werden **unabhängig voneinander** in die Metadaten geschrieben, für maximale Kompatibilität mit Drittanbieter-Tools (Windows Explorer, Lightroom, digiKam, Darktable, XnView, etc.).

### Stern-Rating (0–5)

| Ziel-Tag | Beschreibung |
|---|---|
| `XMP:Rating` | XMP-Standard Stern-Rating |
| `MicrosoftPhoto:Rating` | Windows Explorer Kompatibilität |
| `Rating` | Generisches EXIF-Rating (breite Kompatibilität) |
| `RatingPercent` | Prozentwert (Rating × 20, z.B. 3 Sterne = 60%) |

**Rating-Logik:**
- Wenn `exifInfo.rating` vorhanden → direkt verwenden
- Sonst wenn `asset.rating` vorhanden → verwenden
- Sonst wenn Favorit → Fallback auf 5 Sterne
- Andernfalls → 0 Sterne

### Favorit/Herz (unabhängig vom Rating)

| Ziel-Tag | Wert |
|---|---|
| `XMP:Label` | `Favorite` (bei Favorit), leer (sonst) |
| `XMP:Favorite` | `1` (bei Favorit), `0` (sonst) |

**Wichtig:** Favorit ≠ 5 Sterne. Ein Foto kann Favorit sein, ohne 5 Sterne zu haben, und umgekehrt. Der Fallback "Favorit → 5 Sterne" greift nur, wenn kein explizites Rating gesetzt ist.
