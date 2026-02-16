# 📸 IMMICH ULTRA-SYNC 
*v1.5*  
**!** This tool requires the image editing program Immich.


> Versioning note: see CHANGELOG.

![Docker Pulls](https://img.shields.io/docker/pulls/germanlion67/immich-metadata-sync)

Syncing Immich metadata back into your original media files. 
## Table of Contents
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
  - [Web Interface](#-web-interface-new-in-v15)
  - [Command Line](#command-line-options)
- [Configuration](#configuration)
- [Album Synchronization](#album-synchronization)
- [Face Coordinates (MWG-RS)](#face-coordinates-mwg-rs)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Contributing](#contributing)

## Features

`immich-ultra-sync.py` connects to your Immich instance with an API key, fetches asset metadata, maps Immich paths to the mounted library, and writes values into EXIF/XMP:

- **People** → `XMP:Subject`, `IPTC:Keywords`, `XMP-iptcExt:PersonInImage`
- **GPS** → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`
- **Captions** → `XMP:Description`, `IPTC:Caption-Abstract`
- **Time** → `DateTimeOriginal`, `CreateDate`, `XMP:CreateDate`, `XMP-photoshop:DateCreated`
- **Favorites** → `Rating` (5 stars for favorites, 0 otherwise)
- **Albums** → `XMP-iptcExt:Event`, `XMP:HierarchicalSubject` and `EXIF:UserComment` → Windows "Kommentare" (when `--albums` flag is used)
- **Face Coordinates** → `RegionInfo` (MWG-RS XMP regions with bounding boxes, when `--face-coordinates` flag is used)

The `--only-new` mode compares desired EXIF values with what is already on disk and skips files with no changes to reduce disk I/O.

## Requirements

- Python 3.9 or higher
- ExifTool
- Required Python packages:
  - `requests`
  - `tqdm` (optional, for progress bars)
  - `flask` (optional, for web interface)
- Docker (optional, for containerized deployment)

## Installation

### 🐳 Using Docker

The pre-built Docker image is available on Docker Hub: [germanlion67/immich-metadata-sync](https://hub.docker.com/r/germanlion67/immich-metadata-sync)

**Pull the image:**
```bash
docker pull germanlion67/immich-metadata-sync:latest
```

### Local Installation

1. Clone the repository:
```bash
git clone https://github.com/germanlion67/immich-metadata-sync.git
cd immich-metadata-sync
```

2. Install ExifTool:
```bash
# On Ubuntu/Debian
sudo apt-get install libimage-exiftool-perl

# On macOS
brew install exiftool

# On Windows
# Download from https://exiftool.org/
```

3. Install Python dependencies:
```bash
pip install requests tqdm flask
```

## Usage

### 🌐 Web Interface (New in v1.5!)

The easiest way to manage sync operations is through the web interface:

```bash
python3 web_interface.py
```

Then open http://localhost:5000 in your browser. The web interface provides:
- Visual status monitoring
- One-click sync with configurable options
- Real-time log viewing
- Sync history tracking

Configure the web server with environment variables:
- `FLASK_PORT` - Port to run on (default: 5000)
- `FLASK_HOST` - Host to bind to (default: 127.0.0.1 for localhost only)
- `FLASK_DEBUG` - Enable debug mode (default: false)
- `FLASK_SECRET_KEY` - Secret key for session security (recommended for production)

**Security Notes:**
- The web interface has no authentication - use only on trusted networks
- Defaults to localhost (127.0.0.1) for security
- For production use, consider running behind a reverse proxy with authentication
- Sync operations run synchronously - best suited for smaller libraries or testing

### Quick Start

1. Build and run the Docker image as described in the [runbook](runbook.md).  
2. Mount your Immich library into the container at `/library` (or set `PHOTO_DIR`).  
3. Run the sync:  
   ```bash
   python3 script/immich-ultra-sync.py --all --only-new
   ```
4. Trigger an "Offline Assets Scan" in Immich to re-index updated files.

### Using Docker Run

Run the container directly with Docker:

```bash
docker run -d \
  --name immich-metadata-sync \
  -v /path/to/your/immich-library:/library \
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
      - /path/to/your/immich-library:/library
      - ./logs:/app/logs
    environment:
      - IMMICH_INSTANCE_URL=http://your-immich-instance:2283
      - IMMICH_API_KEY=your-api-key-here
      - TZ=Europe/Berlin
      - LOG_FILE=/app/logs/immich_ultra_sync.txt
    restart: unless-stopped
```

If you need to set the environment variable yourself, the block `environment`containing must be replaced with `stack.env`
```diff
-    environment:
-      - IMMICH_INSTANCE_URL=http://your-immich-instance:2283
-      - IMMICH_API_KEY=your-api-key-here
-      - TZ=Europe/Berlin
-      - LOG_FILE=/app/logs/immich_ultra_sync.txt

+    env_file:
+      - stack.env
```


```yaml
#Environment variables - Advanced Mode
IMMICH_INSTANCE_URL=http://your-immich-instance:2283
IMMICH_API_KEY=your-api-key-here
LOG_FILE=/app/logs/immich_ultra_sync.txt
IMMICH_PHOTO_DIR=/library
IMMICH_PATH_SEGMENTS=4
TZ=Europe/Berlin
```

Then run:
```bash
docker-compose up -d
```

### Command Line Options

```bash
# Sync all metadata including albums
python3 immich-ultra-sync.py --all --albums

# Sync only people and albums
python3 immich-ultra-sync.py --people --albums

# Preview what would be synced (dry-run)
python3 immich-ultra-sync.py --all --albums --dry-run --only-new

# Sync people names and face coordinates
python3 immich-ultra-sync.py --people --face-coordinates

# Resume from previous run
python3 immich-ultra-sync.py --all --resume

# Export statistics
python3 immich-ultra-sync.py --all --export-stats json
```

Common flags:
- `--all` - Enable all modules (`people`, `gps`, `caption`, `time`, `rating`)
- `--albums` - Sync album information to XMP metadata (opt-in, not included in `--all`)
- `--face-coordinates` - Sync face bounding boxes as MWG-RS regions to XMP (opt-in, not included in `--all`)
- `--dry-run` - Preview without writing
- `--only-new` - Skip files that already have metadata
- `--resume` / `--clear-checkpoint` - Continue or reset progress
- `--clear-album-cache` - Clear the album cache before running (forces fresh fetch from API)
- `--export-stats json|csv` - Capture run statistics
- `--log-level {DEBUG,INFO,WARNING,ERROR}` - Set logging verbosity

## Configuration

Set these environment variables (or provide a config file via `--config`). Supported config formats are:
- INI (default `immich-sync.conf`)
- `.env` files with `KEY=value` lines
- JSON objects with keys matching the environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `IMMICH_INSTANCE_URL` | **Required**. URL to your Immich instance (e.g., `http://immich:2283`) | - |
| `IMMICH_API_KEY` | **Required**. API key from Immich user settings | - |
| `IMMICH_PHOTO_DIR` | Path where the photo library is mounted inside the container | `/library` |
| `TZ` | Timezone for correct date handling | `Europe/Berlin` |
| `IMMICH_LOG_FILE` | Path to the log file | `immich_ultra_sync.txt` |
| `CAPTION_MAX_LEN` | Max length for captions before truncation | `2000` |
| `IMMICH_ALBUM_CACHE_TTL` | Album cache lifetime in seconds | `86400` (24 hours) |
| `IMMICH_ALBUM_CACHE_MAX_STALE` | Maximum age for stale cache fallback in seconds | `604800` (7 days) |
| `IMMICH_LOG_FORMAT` / `IMMICH_STRUCTURED_LOGS` | Set to `json` or `true` to emit structured JSON log lines (key/value) | text |

## Album Synchronization

The `--albums` flag enables syncing of Immich album assignments into XMP metadata fields. This allows you to preserve your album organization when exporting photos or using other tools that support XMP metadata.

**XMP Fields Used:**
- `XMP-iptcExt:Event` - Primary album name (IPTC Extension standard)
- `XMP:HierarchicalSubject` - All albums as hierarchical keywords (e.g., `Albums|Summer 2024`)
- `EXIF:UserComment` → Windows "Kommentare"

**Performance:** Album information is fetched once at startup via a single API call (`GET /albums`), ensuring minimal performance impact even for large libraries. The album data is cached on disk with a configurable TTL (Time To Live) to avoid repeated API calls on subsequent runs.

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

## Face Coordinates (MWG-RS)

The `--face-coordinates` flag enables syncing of Immich face detection bounding boxes into XMP metadata as MWG-RS (Metadata Working Group Region Structure) regions. This allows tools like Lightroom, digiKam, and other MWG-RS-aware applications to display face regions.

**How it works:**
- Immich provides pixel bounding boxes (X1/Y1/X2/Y2) and image dimensions for each detected face
- The script converts these to normalized MWG-RS coordinates (center X/Y, width, height in 0–1 range)
- Each region is written with `Type=Face` and `Name=<person name>`

**Notes:**
- `--face-coordinates` is opt-in and not included in `--all`
- Requires Immich API to return face bounding box data in the asset details (available in recent Immich versions)
- Unnamed persons are skipped

## Documentation

- **Docker environment setup:** [runbook.md](runbook.md)  
- **Script reference:** [doc/immich-metadata-sync.md](doc/immich-metadata-sync.md)  
- **German documentation:** see [doc/de](doc/de/)

## Troubleshooting

### Common Issues

**ExifTool not found:**
- Make sure ExifTool is installed and in your PATH
- Run `exiftool -ver` to verify

**API connection errors:**
- Verify `IMMICH_INSTANCE_URL` and `IMMICH_API_KEY` are correct
- Check network connectivity between the script and Immich instance

**Files not found:**
- The script now performs automatic validation of `IMMICH_PHOTO_DIR` at startup
- If the directory doesn't exist or is empty, the script will exit with helpful error messages
- During processing, if >90% of assets have "file not found" errors, the script will log warnings about potential mount/configuration issues
- Ensure `PHOTO_DIR` points to the correct library mount
- Check path segments configuration (`IMMICH_PATH_SEGMENTS`)
- Verify Docker volume mounts match your `IMMICH_PHOTO_DIR` configuration
- Example: If Immich stores files in `/mnt/media/library` on the host, use volume mount `/mnt/media/library:/library` and set `IMMICH_PHOTO_DIR=/library`

**Path segment mismatches:**
- If >50% of assets have path segment mismatches, the script will log detailed troubleshooting hints
- Check the structure of `originalPath` in Immich (visible in asset details)
- Set `IMMICH_PATH_SEGMENTS` to match the number of path components after your mount point
- Example: For path `library/user/2024/photo.jpg` with `IMMICH_PHOTO_DIR=/library`, set `IMMICH_PATH_SEGMENTS=3`

**Performance issues:**
- Use `--only-new` to skip already-synced files
- Enable album cache to reduce API calls
- Adjust batch size via `IMMICH_ASSET_BATCH_SIZE`

## Development

### Project Structure

The project has been refactored into modules for better maintainability:

```
script/
├── immich-ultra-sync.py  # Main orchestration script
├── utils.py              # Utility functions and constants
├── api.py                # API-related functions and RateLimiter
└── exif.py               # EXIF/XMP metadata handling
```

### Running Tests

```bash
# Run with pytest
pytest tests/ -v

# Run with unittest
python -m unittest discover -s tests -p "test_*.py" -v
```

### Maintenance Notes

- ExifTool stay-open mode and rate limiting keep performance high while avoiding API overload
- Logs are written to `immich_ultra_sync.txt` in the script directory
- Use `--only-new` for repeat runs to minimize disk writes
- The codebase follows modular design for easier maintenance and testing

## Contributing

We welcome contributions from the community! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Code of conduct and contribution guidelines
- Development setup instructions
- Testing requirements
- Pull request process
- Coding standards

Whether it's bug reports, feature suggestions, or code contributions, your input helps make IMMICH ULTRA-SYNC better for everyone!
