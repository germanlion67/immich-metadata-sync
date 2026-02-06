## Immich Metadata Exif-Sync Tool
This runbook shows how to build and run the Docker environment for **immich-ultra-sync**, which writes Immich metadata (people, GPS, captions, ratings, timestamps) back into the original media files.

## 🛠️ 1. Host preparation
Create a working directory on the host (for example `/home/user/immich-tools`) that will hold the script and any optional config files.

## 🐳 2. Build the image (Portainer or Docker CLI)
Build an image named `immich-metadata-sync:latest` using the following Dockerfile:
```bash
FROM python:3.11-slim

# Install ExifTool and dependencies
RUN apt-get update && apt-get install -y exiftool curl nano && \
    pip install --no-cache-dir requests && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
CMD ["sleep", "infinity"]
```

## 📦 3. Deploy the container
Start a container with these settings:

| Setting | Value |
|---------|-------|
| **Image** | `immich-metadata-sync:latest` |
| **Network** | `immich_default` (must be in the same network as Immich) |
| **Env: `IMMICH_INSTANCE_URL`** | `http://immich_server:2283` (without trailing `/api`) |
| **Env: `IMMICH_API_KEY`** | API key from Immich user settings |
| **Env: `TZ`** | Optional timezone, e.g. `Europe/Berlin` |

### Volume mappings (bind mounts)
- `Host: /home/user/immich-tools` → `Container: /app`
- `Host: /path/to/immich/library/UUID` → `Container: /library`

> The `/library` mount must contain the original photo library so the script can write EXIF/XMP data back into the files.

## 🖥️ 4. Usage and validation
Open a shell in the container (Portainer console or `docker exec -it <container> /bin/sh`).

### A. API connectivity check
```bash
curl -I -H "x-api-key: $IMMICH_API_KEY" "$IMMICH_INSTANCE_URL/asset"
```
Expected: `HTTP/1.1 200 OK`.

### B. Library visibility
```bash
ls -la /library
```

### C. Run the sync
- Dry run:
  ```bash
  python3 immich-ultra-sync.py --all --dry-run
  ```
- Full run:
  ```bash
  python3 immich-ultra-sync.py --all
  ```
- Recommended (skip unchanged files):
  ```bash
  python3 immich-ultra-sync.py --all --only-new
  ```

## ⚠️ Operational notes
1. **Immich refresh:** After the script finishes, trigger an “Offline Assets Scan” in Immich (Administration → Library) so changes are re-indexed.
2. **Correct host name:** `IMMICH_INSTANCE_URL` must use the Immich server container name reachable from the sync container (e.g. `http://immich_server:2283`).
3. **Logging:** Runtime output is written to `/app/immich_ultra_sync.txt` by default; mount it if you want to persist logs.
