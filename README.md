# 📸 IMMICH ULTRA-SYNC
*v1.1*

![Docker Pulls](https://img.shields.io/docker/pulls/germanlion67/immich-metadata-sync)

Syncing Immich metadata back into your original media files.

## 🐳 Docker Hub

The pre-built Docker image is available on Docker Hub: [germanlion67/immich-metadata-sync](https://hub.docker.com/r/germanlion67/immich-metadata-sync)

**Pull the image:**
```bash
docker pull germanlion67/immich-metadata-sync:latest
```

## What this script does
`immich-ultra-sync.py` connects to your Immich instance with an API key, fetches asset metadata, maps Immich paths to the mounted library, and writes values into EXIF/XMP:

- People → `XMP:Subject`, `IPTC:Keywords`, `XMP-iptcExt:PersonInImage`
- GPS → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`
- Captions → `XMP:Description`, `IPTC:Caption-Abstract`
- Time → `DateTimeOriginal`, `CreateDate`, `XMP:CreateDate`, `XMP-photoshop:DateCreated`
- Favorites → `Rating` (5 stars for favorites, 0 otherwise)
- Albums → `XMP-iptcExt:Event`, `XMP:HierarchicalSubject` und `EXIF:UserComment` → Windows "Kommentare" (when `--albums` flag is used)
- Face Coordinates → `RegionInfo` (MWG-RS XMP regions with bounding boxes, when `--face-coordinates` flag is used)

The `--only-new` mode compares desired EXIF values with what is already on disk and skips files with no changes to reduce disk I/O.

## Quick start
1. Build and run the Docker image as described in the [runbook](runbook.md).  
2. Mount your Immich library into the container at `/library` (or set `PHOTO_DIR`).  
3. Run the sync:  
   ```bash
   python3 immich-ultra-sync.py --all --only-new
   ```
4. Trigger an “Offline Assets Scan” in Immich to re-index updated files.

## 🚀 Usage Examples

### Using Docker Run

Run the container directly with Docker:

```bash
docker run -d \
  --name immich-metadata-sync \
  -v /path/to/your/immich-library:/app/library \
  -v /path/to/logs:/app/logs \
  -e IMMICH_INSTANCE_URL=http://your-immich-instance:2283 \
  -e IMMICH_API_KEY=your-api-key-here \
  -e TZ=Europe/Berlin \
  germanlion67/immich-metadata-sync:latest
```

### Using Docker Compose

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  immich-metadata-sync:
    image: germanlion67/immich-metadata-sync:latest
    container_name: immich-metadata-sync
    volumes:
      - /path/to/your/immich-library:/app/library
      - ./logs:/app/logs
    environment:
      - IMMICH_INSTANCE_URL=http://your-immich-instance:2283
      - IMMICH_API_KEY=your-api-key-here
      - TZ=Europe/Berlin
      - LOG_FILE=/app/logs/immich_ultra_sync.txt
    restart: unless-stopped
```

Then run:
```bash
docker-compose up -d
```

### Environment Variables

The following environment variables are required or recommended:

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `IMMICH_INSTANCE_URL` | **Yes** | URL to your Immich instance (e.g., `http://immich:2283`) | `""` |
| `IMMICH_API_KEY` | **Yes** | API key from Immich user settings | `None` |
| `PHOTO_DIR` | No | Path where the photo library is mounted inside the container | `/library` |
| `TZ` | No | Timezone for correct date handling | `Europe/Berlin` |
| `LOG_FILE` | No | Path to the log file | `/app/logs/immich_ultra_sync.txt` |
| `CAPTION_MAX_LEN` | No | Max length for captions before truncation | `2000` |
| `IMMICH_ALBUM_CACHE_TTL` | No | Album cache lifetime in seconds | `86400` (24 hours) |
| `IMMICH_ALBUM_CACHE_MAX_STALE` | No | Maximum age for stale cache fallback in seconds | `604800` (7 days) |

## Album Synchronization
The `--albums` flag enables syncing of Immich album assignments into XMP metadata fields. This allows you to preserve your album organization when exporting photos or using other tools that support XMP metadata.

**XMP Fields Used:**
- `XMP-iptcExt:Event` - Primary album name (IPTC Extension standard)
- `XMP:HierarchicalSubject` - All albums as hierarchical keywords (e.g., `Albums|Summer 2024`)
- `EXIF:UserComment` → Windows "Kommentare"

**Usage Examples:**
```bash
# Sync all metadata including albums
python3 immich-ultra-sync.py --all --albums

# Sync only people and albums
python3 immich-ultra-sync.py --people --albums

# Preview what would be synced (dry-run)
python3 immich-ultra-sync.py --all --albums --dry-run --only-new
```

**Performance:** Album information is fetched once at startup via a single API call (`GET /albums`), ensuring minimal performance impact even for large libraries. The album data is cached on disk with a configurable TTL (Time To Live) to avoid repeated API calls on subsequent runs.

## Face Coordinates (MWG-RS)
The `--face-coordinates` flag enables syncing of Immich face detection bounding boxes into XMP metadata as MWG-RS (Metadata Working Group Region Structure) regions. This allows tools like Lightroom, digiKam, and other MWG-RS-aware applications to display face regions.

**How it works:**
- Immich provides pixel bounding boxes (X1/Y1/X2/Y2) and image dimensions for each detected face
- The script converts these to normalized MWG-RS coordinates (center X/Y, width, height in 0–1 range)
- Each region is written with `Type=Face` and `Name=<person name>`

**Usage Examples:**
```bash
# Sync people names and face coordinates
python3 immich-ultra-sync.py --people --face-coordinates

# Sync all metadata plus face coordinates
python3 immich-ultra-sync.py --all --face-coordinates

# Preview what would be synced (dry-run)
python3 immich-ultra-sync.py --all --face-coordinates --dry-run
```

**Notes:**
- `--face-coordinates` is opt-in and not included in `--all`
- Requires Immich API to return face bounding box data in the asset details (available in recent Immich versions)
- Unnamed persons are skipped


## Configuration
Set these environment variables (or provide a config file via `--config`):

| Variable | Description | Default |
| --- | --- | --- |
| `IMMICH_INSTANCE_URL` | Immich URL without `/api` (fallback will try `/api`) | `""` |
| `IMMICH_API_KEY` | Immich API key for the user running the sync | `None` |
| `PHOTO_DIR` | Path where the photo library is mounted inside the container | `/library` |
| `TZ` | Timezone for correct date handling | `Europe/Berlin` |
| `CAPTION_MAX_LEN` | Max length for captions before truncation | `2000` |
| `IMMICH_ALBUM_CACHE_TTL` | Album cache lifetime in seconds | `86400` (24 hours) |
| `IMMICH_ALBUM_CACHE_MAX_STALE` | Maximum age for stale cache fallback in seconds | `604800` (7 days) |

Common flags:
- `--all` enable all modules (`people`, `gps`, `caption`, `time`, `rating`)
- `--albums` sync album information to XMP metadata (opt-in, not included in `--all`)
- `--face-coordinates` sync face bounding boxes as MWG-RS regions to XMP (opt-in, not included in `--all`)
- `--dry-run` to preview without writing
- `--resume` / `--clear-checkpoint` to continue or reset progress
- `--clear-album-cache` clear the album cache before running (forces fresh fetch from API)
- `--export-stats json|csv` to capture run statistics

### Album Cache Behavior
When `--albums` is enabled, the script maintains a persistent cache of album assignments:
- **Cache TTL**: By default, the cache is valid for 24 hours (`IMMICH_ALBUM_CACHE_TTL`). Within this period, the script uses the cached data instead of fetching from the API.
- **Stale Fallback**: If the API fetch fails, the script attempts to use stale cache data up to 7 days old (`IMMICH_ALBUM_CACHE_MAX_STALE`) as a fallback.
- **Cache Location**: The cache is stored as `.immich_album_cache.json` in the current directory with file permissions set to `0o600` (owner read/write only).
- **Clearing Cache**: Use `--clear-album-cache` to force a fresh fetch from the API, ignoring any existing cache.

**Example:**
```bash
# First run fetches from API and caches the result
python3 immich-ultra-sync.py --all --albums

# Subsequent runs within 24 hours use the cache (much faster)
python3 immich-ultra-sync.py --all --albums

# Force fresh fetch by clearing the cache
python3 immich-ultra-sync.py --all --albums --clear-album-cache
```

## Documentation
- **Docker environment setup:** [runbook.md](runbook.md)  
- **Script reference:** [doc/immich-metadata-sync.md](doc/immich-metadata-sync.md)  
- **German documentation:** see [doc/de](doc/de/)

## Maintenance notes
- ExifTool stay-open mode and rate limiting keep performance high while avoiding API overload.
- Logs are written to `immich_ultra_sync.txt` in the script directory.
- Use `--only-new` for repeat runs to minimize disk writes.
