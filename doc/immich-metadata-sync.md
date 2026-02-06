# Immich Metadata Sync – Technical Reference

This document describes how the `immich-ultra-sync.py` script reads metadata from an Immich instance and writes it back into the original media files using EXIF/XMP tags.

## Architecture and data flow
1. **Configuration & CLI flags**  
   - Environment variables:  
     - `IMMICH_INSTANCE_URL` (without trailing `/api`; the script falls back to `/api` if needed)  
     - `IMMICH_API_KEY`  
     - `PHOTO_DIR` (default `/library`)  
     - `TZ` for timezone handling  
   - CLI flags: `--all`, `--people`, `--gps`, `--caption`, `--time`, `--rating`, `--dry-run`, `--only-new`, `--resume`, `--clear-checkpoint`, `--config`, `--export-stats`, `--log-level`.

2. **Asset discovery**  
   - POST `/{api}/search/metadata` to collect asset IDs.  
   - GET `/assets/{id}` for per-asset details (EXIF, people, favorite state).

3. **Path mapping**  
   - Immich `originalPath` is mapped to the mounted library path (`PHOTO_DIR/<year>/<month>/<file>` using the last three path segments).  
   - Missing files are skipped safely.

4. **Building EXIF arguments** (`build_exif_args`)  
   - People → `XMP:Subject`, `IPTC:Keywords`  
   - GPS → `GPSLatitude`, `GPSLongitude`, `GPSAltitude`  
   - Caption → `XMP:Description`, `IPTC:Caption-Abstract`  
   - Time → `DateTimeOriginal`, `CreateDate`  
   - Rating → `Rating` (Immich favorite → `5`, otherwise `0`)  
   - Captions are trimmed to `CAPTION_MAX_LEN` (default 2000, minimum enforced).

5. **Execution**  
   - `--dry-run` logs planned changes without writing.  
   - Normal mode uses `exiftool -overwrite_original <args> <file>`.  
   - `--only-new` compares desired EXIF values (people, GPS, caption, time, rating) with current file values and skips if identical to avoid unnecessary writes.

6. **Logging & checkpoints**  
   - Default log file: `immich_ultra_sync.txt` in the script directory.  
   - Checkpoints enable `--resume` to continue after interruptions; `--clear-checkpoint` resets progress.

## Deployment guidance
- Base image installs Python 3.11, `requests`, and `exiftool` (see `runbook.md` for Docker instructions).
- Container must reach the Immich API over the configured network.
- Mount the photo library into the container at `/library` (or the value of `PHOTO_DIR`) with write access.

## Usage examples
- All modules:  
  ```bash
  python3 immich-ultra-sync.py --all
  ```
- People + GPS, skip unchanged files:  
  ```bash
  python3 immich-ultra-sync.py --people --gps --only-new
  ```
- Dry run:  
  ```bash
  python3 immich-ultra-sync.py --all --dry-run
  ```
- Resume after an interruption:  
  ```bash
  python3 immich-ultra-sync.py --all --resume
  ```

## Performance and reliability features
- **ExifTool stay-open** mode for 3–10x faster processing.  
- **Rate limiting** (10 req/s default) with retries and exponential backoff to protect the Immich server.  
- **Change detection** normalizes EXIF values (people, GPS, caption, time, rating) before comparing.  
- **Progress export** via `--export-stats json|csv`.  
- **Graceful shutdown** on SIGINT/SIGTERM completes the current batch before exiting.

## Troubleshooting
- **HTTP errors**: verify `IMMICH_INSTANCE_URL`, API key, and network connectivity; the script tries both `/api` and root paths.  
- **File not found**: ensure the mount mirrors Immich’s library path structure (`/library/<year>/<month>/<file>`).  
- **Slow runs**: prefer `--only-new` and enable the stay-open ExifTool helper.  
- **Immich not showing updates**: run “Offline Assets Scan” in Immich after syncing so changes are indexed.
