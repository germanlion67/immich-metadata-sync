# 📸 IMMICH ULTRA-SYNC

Syncing Immich metadata back into your original media files.

## What this script does
`immich-ultra-sync.py` connects to your Immich instance with an API key, fetches asset metadata, maps Immich paths to the mounted library, and writes values into EXIF/XMP:

- People → `XMP:Subject`, `IPTC:Keywords`, `XMP-iptcExt:PersonInImage`
- GPS → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`
- Captions → `XMP:Description`, `IPTC:Caption-Abstract`
- Time → `DateTimeOriginal`, `CreateDate`, `XMP:CreateDate`, `XMP-photoshop:DateCreated`
- Favorites → `Rating` (5 stars for favorites, 0 otherwise)
- Albums → `XMP-iptcExt:Event`, `XMP:HierarchicalSubject` (when `--albums` flag is used)

The `--only-new` mode compares desired EXIF values with what is already on disk and skips files with no changes to reduce disk I/O.

## Quick start
1. Build and run the Docker image as described in the [runbook](runbook.md).  
2. Mount your Immich library into the container at `/library` (or set `PHOTO_DIR`).  
3. Run the sync:  
   ```bash
   python3 immich-ultra-sync.py --all --only-new
   ```
4. Trigger an “Offline Assets Scan” in Immich to re-index updated files.

## Album Synchronization
The `--albums` flag enables syncing of Immich album assignments into XMP metadata fields. This allows you to preserve your album organization when exporting photos or using other tools that support XMP metadata.

**XMP Fields Used:**
- `XMP-iptcExt:Event` - Primary album name (IPTC Extension standard)
- `XMP:HierarchicalSubject` - All albums as hierarchical keywords (e.g., `Albums|Summer 2024`)

**Usage Examples:**
```bash
# Sync all metadata including albums
python3 immich-ultra-sync.py --all --albums

# Sync only people and albums
python3 immich-ultra-sync.py --people --albums

# Preview what would be synced (dry-run)
python3 immich-ultra-sync.py --all --albums --dry-run --only-new
```

**Performance:** Album information is fetched once at startup via a single API call (`GET /albums`), ensuring minimal performance impact even for large libraries.


## Configuration
Set these environment variables (or provide a config file via `--config`):

| Variable | Description | Default |
| --- | --- | --- |
| `IMMICH_INSTANCE_URL` | Immich URL without `/api` (fallback will try `/api`) | `""` |
| `IMMICH_API_KEY` | Immich API key for the user running the sync | `None` |
| `PHOTO_DIR` | Path where the photo library is mounted inside the container | `/library` |
| `TZ` | Timezone for correct date handling | `Europe/Berlin` |
| `CAPTION_MAX_LEN` | Max length for captions before truncation | `2000` |

Common flags:
- `--all` enable all modules (`people`, `gps`, `caption`, `time`, `rating`)
- `--albums` sync album information to XMP metadata (opt-in, not included in `--all`)
- `--dry-run` to preview without writing
- `--resume` / `--clear-checkpoint` to continue or reset progress
- `--export-stats json|csv` to capture run statistics

## Documentation
- **Docker environment setup:** [runbook.md](runbook.md)  
- **Script reference:** [doc/immich-metadata-sync.md](doc/immich-metadata-sync.md)  
- **German documentation:** see [doc/de](doc/de/)

## Maintenance notes
- ExifTool stay-open mode and rate limiting keep performance high while avoiding API overload.
- Logs are written to `immich_ultra_sync.txt` in the script directory.
- Use `--only-new` for repeat runs to minimize disk writes.
