import argparse
import configparser
import datetime
from enum import Enum
from functools import wraps
import json
import os
import pickle
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from itertools import islice
from typing import Any, Dict, Iterable, List, Optional, Tuple, IO
import requests

# Platform-specific locking imports
try:
    import fcntl
    FCNTL_AVAILABLE = True
except ImportError:
    FCNTL_AVAILABLE = False

try:
    import msvcrt
    MSVCRT_AVAILABLE = True
except ImportError:
    MSVCRT_AVAILABLE = False

# Lock size constant for Windows file locking
LOCK_SIZE = 1  # Minimal lock size required by msvcrt.locking

# ==============================================================================
# CONFIGURATION DEFAULTS
# ==============================================================================
# Globale Variable für Batch-Endpoint-Verfügbarkeit
_BATCH_ENDPOINT_AVAILABLE = None  # None = unbekannt, True = verfügbar, False = nicht verfügbar

DEFAULT_PHOTO_DIR = "/library"
DEFAULT_LOG_FILE = "immich_ultra_sync.txt"
DEFAULT_PATH_SEGMENTS = 3
MAX_PATH_SEGMENTS = 10  # Upper bound balances flexibility with security to avoid extreme depth abuse; typical date/album trees sit well below this
DEFAULT_BATCH_SIZE = 25
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 500  # Fetching can exceed processing batch size to reduce API calls; cap keeps responses within client memory constraints
VALID_RATING_VALUES = "012345"  # Immich favorites map to a 0-5 star scale
DEFAULT_CAPTION_MAX_LEN = 2000
MIN_CAPTION_MAX_LEN = 1
GPS_COORDINATE_PRECISION = 6  # Decimal places ≈11cm precision, sufficient for photos
GPS_ALTITUDE_PRECISION = 1    # Decimal places ≈10cm precision
CHECKPOINT_FILE = ".immich_sync_checkpoint.pkl"
ALBUM_CACHE_FILE = ".immich_album_cache.json"
ALBUM_CACHE_LOCK_FILE = ".immich_album_cache.lock"
DEFAULT_ALBUM_CACHE_TTL = 86400  # 24 hours
DEFAULT_ALBUM_CACHE_MAX_STALE = 604800  # 7 days


# ==============================================================================
# LOG LEVEL SYSTEM
# ==============================================================================
class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


_LOG_LEVEL = LogLevel.INFO
_shutdown_requested = False


# ==============================================================================
# RATE LIMITER
# ==============================================================================
class RateLimiter:
    """Simple rate limiter using token bucket algorithm."""
    def __init__(self, calls_per_second: float = 10.0):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0
        self.lock = threading.Lock()
    
    def wait(self):
        """Wait if necessary to respect rate limit."""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_call
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            self.last_call = time.time()


_rate_limiter = RateLimiter(calls_per_second=10.0)


# ==============================================================================
# EXIFTOOL STAY-OPEN MODE
# ==============================================================================
class ExifToolHelper:
    """ExifTool wrapper using stay-open mode for better performance."""
    def __init__(self):
        self.process = None
    
    def start(self):
        """Start ExifTool in stay-open mode."""
        self.process = subprocess.Popen(
            ["exiftool", "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    
    def execute(self, args: List[str]) -> tuple:
        """Execute ExifTool command."""
        if not self.process:
            self.start()
        
        command = "\n".join(args) + "\n-execute\n"
        self.process.stdin.write(command)
        self.process.stdin.flush()
        
        output = []
        while True:
            line = self.process.stdout.readline()
            if line.strip() == "{ready}":
                break
            output.append(line)
        
        return "".join(output), ""
    
    def close(self):
        """Close ExifTool process."""
        if self.process:
            self.process.stdin.write("-stay_open\nFalse\n")
            self.process.stdin.flush()
            self.process.wait()


# ==============================================================================
# TQDM PROGRESS BAR
# ==============================================================================
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


def get_env_int(name: str, default: int) -> int:
    """Read integer environment variable `name`, returning `default` when missing or invalid."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def normalize_caption_limit(value: int) -> int:
    """Ensure caption limit respects the configured minimum."""
    return max(MIN_CAPTION_MAX_LEN, value)


def set_log_level(level: str):
    """Set global log level from string."""
    global _LOG_LEVEL
    _LOG_LEVEL = LogLevel[level.upper()]


def log(message: str, log_file: str = DEFAULT_LOG_FILE, level: LogLevel = LogLevel.INFO) -> None:
    """Log messages with level filtering."""
    if level.value < _LOG_LEVEL.value:
        return
    
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_str = level.name.ljust(7)
    msg = f"[{ts}] [{level_str}] {message}"
    print(msg, flush=True)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except (IOError, OSError) as e:
        print(f"Logging error: {e}")


def retry_on_failure(max_retries: int = 3, delay: float = 2.0):
    """Decorator to retry function calls on failure with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.ConnectionError, 
                        requests.exceptions.Timeout) as e:
                    if attempt == max_retries - 1:
                        raise
                    wait_time = delay * (2 ** attempt)
                    log_file = kwargs.get('log_file', DEFAULT_LOG_FILE)
                    log(f"Retry {attempt + 1}/{max_retries} after {wait_time}s due to: {e}", log_file, LogLevel.WARNING)
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    log(f"Received signal {signum}, finishing current batch and shutting down...", 
        DEFAULT_LOG_FILE, LogLevel.WARNING)
    _shutdown_requested = True


def save_checkpoint(processed_ids: set, log_file: str):
    """Save checkpoint of processed asset IDs."""
    try:
        with open(CHECKPOINT_FILE, 'wb') as f:
            pickle.dump(processed_ids, f)
        log(f"Checkpoint saved: {len(processed_ids)} assets processed", log_file, LogLevel.DEBUG)
    except Exception as e:
        log(f"Failed to save checkpoint: {e}", log_file, LogLevel.WARNING)


def load_checkpoint(log_file: str) -> set:
    """Load checkpoint of already processed asset IDs."""
    if not Path(CHECKPOINT_FILE).exists():
        return set()
    try:
        with open(CHECKPOINT_FILE, 'rb') as f:
            processed = pickle.load(f)
        log(f"Resuming from checkpoint: {len(processed)} assets already processed", log_file, LogLevel.INFO)
        return processed
    except Exception as e:
        log(f"Failed to load checkpoint: {e}", log_file, LogLevel.WARNING)
        return set()


def load_config(config_file: str = "immich-sync.conf") -> dict:
    """Load configuration from file."""
    config = configparser.ConfigParser()
    defaults = {
        'IMMICH_INSTANCE_URL': '',
        'IMMICH_API_KEY': '',
        'IMMICH_PHOTO_DIR': DEFAULT_PHOTO_DIR,
        'IMMICH_LOG_FILE': DEFAULT_LOG_FILE,
        'IMMICH_PATH_SEGMENTS': str(DEFAULT_PATH_SEGMENTS),
        'IMMICH_ASSET_BATCH_SIZE': str(DEFAULT_BATCH_SIZE),
        'IMMICH_SEARCH_PAGE_SIZE': str(DEFAULT_PAGE_SIZE),
        'CAPTION_MAX_LEN': str(DEFAULT_CAPTION_MAX_LEN),
    }
    
    if Path(config_file).exists():
        config.read(config_file)
        if 'immich' in config:
            for key, value in config['immich'].items():
                defaults[key.upper()] = value
    
    return defaults


def export_statistics(statistics: dict, log_file: str, format: str = "json"):
    """Export statistics to file."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if format == "json":
        stats_file = f"immich_sync_stats_{timestamp}.json"
        with open(stats_file, 'w') as f:
            json.dump({
                'timestamp': timestamp,
                'statistics': statistics
            }, f, indent=2)
    elif format == "csv":
        import csv
        stats_file = f"immich_sync_stats_{timestamp}.csv"
        with open(stats_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Metric', 'Value'])
            for key, value in statistics.items():
                writer.writerow([timestamp, key, value])
    
    log(f"Statistics exported to {stats_file}", log_file)


def extract_error_message(exc: BaseException) -> str:
    """Return best-effort error message from a subprocess exception."""
    stderr = getattr(exc, "stderr", None)
    stdout = getattr(exc, "stdout", None)
    if stderr and stderr.strip():
        return stderr.strip()
    if stdout and stdout.strip():
        return stdout.strip()
    return str(exc)


def check_exiftool(log_file: str) -> bool:
    """Verify ExifTool availability with robust error handling."""
    try:
        result = subprocess.run(
            ["exiftool", "-ver"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        version = result.stdout.strip()
        log(f"ExifTool detected: Version {version}", log_file, LogLevel.INFO)
        return True
    except FileNotFoundError:
        log("ERROR: ExifTool is not installed. Please install ExifTool to continue.", log_file, LogLevel.ERROR)
        return False
    except subprocess.TimeoutExpired:
        log("ERROR: ExifTool check timed out.", log_file, LogLevel.ERROR)
        return False
    except subprocess.CalledProcessError as e:
        log(f"ERROR: ExifTool check failed: {extract_error_message(e)}", log_file, LogLevel.ERROR)
        return False
    except subprocess.SubprocessError:
        log("ERROR: ExifTool verification failed due to subprocess error.", log_file, LogLevel.ERROR)
        return False

def sanitize_path(path: str) -> str:
    """Validate and sanitize paths to prevent traversal attacks."""
    if not path:
        return ""
    # Normalize the path and drop dangerous components
    # Convert to string and replace backslashes (Windows) with forward slashes
    path_str = str(path).replace('\\', '/')
    # Manually remove ".." and "." components
    path_parts = []
    for part in path_str.split('/'):
        if part and part != '..' and part != '.':
            path_parts.append(part)
    return '/'.join(path_parts)

def validate_path_in_boundary(full_path: str, base_dir: str) -> bool:
    """Check whether the resolved path stays inside the expected directory boundary."""
    try:
        # Resolve symlinks and normalize paths
        resolved_path = os.path.realpath(full_path)
        resolved_base = os.path.realpath(base_dir)
        # Use commonpath for robust verification across platforms
        common = os.path.commonpath([resolved_path, resolved_base])
        return common == resolved_base
    except (OSError, ValueError):
        return False

@retry_on_failure(max_retries=3, delay=2.0)
def api_call(
    method: str,
    endpoint: str,
    headers: Dict[str, str],
    base_url: str,
    log_file: str,
    json_data: Optional[Dict[str, Any]] = None,
    silent_on_404: bool = False,
) -> Optional[Any]:
    """Perform API calls robustly (with/without /api prefix)."""
    _rate_limiter.wait()
    
    for path in [f"{base_url}/api{endpoint}", f"{base_url}{endpoint}"]:
        try:
            if method == "POST":
                r = requests.post(path, headers=headers, json=json_data, timeout=30)
            else:
                r = requests.get(path, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            if not silent_on_404:
                log(f"API timeout at {path}", log_file, LogLevel.WARNING)
            continue
        except requests.exceptions.HTTPError as e:
            # Nur loggen wenn NICHT (silent_on_404 UND Status ist 404)
            is_404 = hasattr(e.response, 'status_code') and e.response.status_code == 404
            if not (silent_on_404 and is_404):
                log(f"HTTP error at {path}: {e.response.status_code}", log_file, LogLevel.WARNING)
            continue
        except requests.exceptions.RequestException as exc:
            if not silent_on_404:
                log(f"API request error at {path}: {exc}", log_file, LogLevel.WARNING)
            continue
        except ValueError:
            if not silent_on_404:
                log(f"JSON parsing error at {path}", log_file, LogLevel.WARNING)
            continue
    if not silent_on_404:
        log(f"API call failed for {endpoint} after all attempts", log_file, LogLevel.ERROR)
    return None


def build_asset_album_map(headers: Dict, base_url: str, log_file: str) -> Dict[str, List[str]]:
    all_albums = api_call("GET", "/albums", headers, base_url, log_file)
    
    asset_to_albums = {}
    for album in all_albums or []:
        album_id = album.get("id")
        album_name = album.get("albumName")
        if not album_id or not album_name:
            continue
        
        # Fetch assets for this album
        album_details = api_call("GET", f"/albums/{album_id}", headers, base_url, log_file)
        if album_details:
            for asset in album_details.get("assets", []):
                asset_id = asset.get("id")
                if asset_id:
                    if asset_id not in asset_to_albums:
                        asset_to_albums[asset_id] = []
                    asset_to_albums[asset_id].append(album_name)
    
    return asset_to_albums


# ==============================================================================
# ALBUM CACHE HELPERS
# ==============================================================================
def get_album_cache_path() -> str:
    """Return the path to the album cache file."""
    return ALBUM_CACHE_FILE


def get_album_cache_lock_path() -> str:
    """Return the path to the album cache lock file."""
    return ALBUM_CACHE_LOCK_FILE


def acquire_lock(lock_file_path: str, timeout: float = 10.0) -> Optional[IO]:
    """
    Acquire a file lock (cross-platform).
    Returns a lock handle on success or None on failure.
    The caller is responsible for releasing the lock and closing the file.
    """
    try:
        lock_file = open(lock_file_path, "w")
        # Set restrictive permissions immediately after creation
        try:
            os.chmod(lock_file_path, 0o600)
        except Exception:
            pass  # Ignore permission errors on platforms that don't support it
        
        start_time = time.time()
        
        while True:
            try:
                if FCNTL_AVAILABLE:
                    # POSIX systems (Linux, macOS)
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return lock_file
                elif MSVCRT_AVAILABLE:
                    # Windows - use LOCK_SIZE constant for clarity
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, LOCK_SIZE)
                    return lock_file
                else:
                    # No locking available, return file anyway
                    return lock_file
            except (IOError, OSError):
                if time.time() - start_time >= timeout:
                    lock_file.close()
                    return None
                time.sleep(0.1)
    except Exception:
        return None


def release_lock(lock_handle: Optional[IO]) -> None:
    """Release a file lock acquired with acquire_lock."""
    if lock_handle is None:
        return
    try:
        if FCNTL_AVAILABLE:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        elif MSVCRT_AVAILABLE:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, LOCK_SIZE)
        lock_handle.close()
    except Exception:
        pass


def load_album_cache(ttl: int, log_file: str) -> Optional[Dict[str, List[str]]]:
    """
    Load the album cache from disk if it exists and is within TTL.
    Returns None if cache doesn't exist, is expired, or can't be loaded.
    """
    cache_path = get_album_cache_path()
    if not os.path.exists(cache_path):
        return None
    
    lock_path = get_album_cache_lock_path()
    lock_handle = acquire_lock(lock_path, timeout=5.0)
    if lock_handle is None:
        log("Failed to acquire lock for reading album cache", log_file, LogLevel.WARNING)
        return None
    
    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
        
        timestamp = data.get("timestamp", 0)
        cache_age = time.time() - timestamp
        
        if cache_age > ttl:
            log(f"Album cache expired (age: {int(cache_age)}s, TTL: {ttl}s)", log_file, LogLevel.DEBUG)
            return None
        
        log(f"Loaded album cache from disk (age: {int(cache_age)}s)", log_file, LogLevel.INFO)
        return data.get("data", {})
    except Exception as e:
        log(f"Failed to load album cache: {e}", log_file, LogLevel.WARNING)
        return None
    finally:
        release_lock(lock_handle)


def load_stale_album_cache(max_stale: int, log_file: str) -> Optional[Dict[str, List[str]]]:
    """
    Load the album cache even if expired, up to max_stale seconds.
    Used as a fallback when build_asset_album_map fails.
    Returns None if cache doesn't exist, is too old, or can't be loaded.
    """
    cache_path = get_album_cache_path()
    if not os.path.exists(cache_path):
        return None
    
    lock_path = get_album_cache_lock_path()
    lock_handle = acquire_lock(lock_path, timeout=5.0)
    if lock_handle is None:
        log("Failed to acquire lock for reading stale album cache", log_file, LogLevel.WARNING)
        return None
    
    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
        
        timestamp = data.get("timestamp", 0)
        cache_age = time.time() - timestamp
        
        if cache_age > max_stale:
            log(f"Album cache too old (age: {int(cache_age)}s, max_stale: {max_stale}s)", log_file, LogLevel.DEBUG)
            return None
        
        log(f"Loaded STALE album cache as fallback (age: {int(cache_age)}s)", log_file, LogLevel.WARNING)
        return data.get("data", {})
    except Exception as e:
        log(f"Failed to load stale album cache: {e}", log_file, LogLevel.WARNING)
        return None
    finally:
        release_lock(lock_handle)


def save_album_cache(album_map: Dict[str, List[str]], log_file: str) -> bool:
    """
    Save the album cache to disk atomically with locking.
    Returns True on success, False on failure.
    """
    cache_path = get_album_cache_path()
    lock_path = get_album_cache_lock_path()
    
    lock_handle = acquire_lock(lock_path, timeout=10.0)
    if lock_handle is None:
        log("Failed to acquire lock for writing album cache", log_file, LogLevel.WARNING)
        return False
    
    try:
        # Create cache data structure
        cache_data = {
            "timestamp": time.time(),
            "data": album_map
        }
        
        # Write atomically using tempfile + os.replace
        cache_dir = os.path.dirname(os.path.abspath(cache_path)) or "."
        with tempfile.NamedTemporaryFile(mode="w", dir=cache_dir, delete=False, suffix=".tmp") as tmp_file:
            json.dump(cache_data, tmp_file, indent=2)
            tmp_path = tmp_file.name
        
        # Try to set restrictive permissions (0o600)
        try:
            os.chmod(tmp_path, 0o600)
        except Exception:
            pass  # Ignore permission errors on platforms that don't support it
        
        # Atomic replace
        os.replace(tmp_path, cache_path)
        
        log(f"Saved album cache to disk ({len(album_map)} assets)", log_file, LogLevel.INFO)
        return True
    except Exception as e:
        log(f"Failed to save album cache: {e}", log_file, LogLevel.ERROR)
        return False
    finally:
        release_lock(lock_handle)


def clear_album_cache(log_file: str) -> bool:
    """
    Clear the album cache file.
    Returns True on success, False if cache didn't exist or couldn't be removed.
    """
    cache_path = get_album_cache_path()
    if not os.path.exists(cache_path):
        log("Album cache does not exist, nothing to clear", log_file, LogLevel.INFO)
        return False
    
    try:
        os.remove(cache_path)
        log("Album cache cleared", log_file, LogLevel.INFO)
        return True
    except Exception as e:
        log(f"Failed to clear album cache: {e}", log_file, LogLevel.ERROR)
        return False


def extract_asset_items(raw: Any) -> List[Dict[str, Any]]:
    """Return assets.items list from a search response or an empty list when absent."""
    return raw.get("assets", {}).get("items", []) if isinstance(raw, dict) else []


def chunked(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    """Yield successive chunks (lists) from any iterable; `size` must be >= 1."""
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            break
        yield chunk


def fetch_assets(headers: Dict[str, str], base_url: str, page_size: int, log_file: str) -> List[Dict[str, Any]]:
    """Fetch assets using pagination when supported; returns a list and falls back to a single call on failure."""
    assets: List[Dict[str, Any]] = []
    page = 1
    tried_zero_page = False
    while True:
        payload = {"withArchived": True, "page": page, "size": page_size}
        raw = api_call("POST", "/search/metadata", headers, base_url, log_file, json_data=payload)
        if not raw:
            if page == 1 and not tried_zero_page:
                page = 0
                tried_zero_page = True
                continue
            break
        page_assets = extract_asset_items(raw)
        if not page_assets:
            if page == 1 and not tried_zero_page:
                page = 0
                tried_zero_page = True
                continue
            break
        assets.extend(page_assets)

        next_page = raw.get("assets", {}).get("nextPage")
        has_more = next_page is not None
        if not has_more and len(page_assets) == page_size:
            has_more = True
        if not has_more:
            break
        if isinstance(next_page, int) and next_page >= page:
            page = next_page
        else:
            page += 1

    if not assets:
        raw = api_call("POST", "/search/metadata", headers, base_url, log_file, json_data={"withArchived": True})
        assets = extract_asset_items(raw)
    return assets


def fetch_asset_details_batch(
    asset_batch: List[Dict[str, Any]],
    headers: Dict[str, str],
    base_url: str,
    log_file: str,
) -> Dict[str, Dict[str, Any]]:
    """Fetch asset details in batches with bulk endpoint fallback, returning a mapping of asset_id -> detail."""
    global _BATCH_ENDPOINT_AVAILABLE
    
    asset_ids = [a.get("id") for a in asset_batch if a.get("id")]
    details_by_id: Dict[str, Dict[str, Any]] = {}
    if not asset_ids:
        return details_by_id

    # Attempt batch endpoint only if status is unknown or confirmed available
    bulk_items: List[Dict[str, Any]] = []
    if _BATCH_ENDPOINT_AVAILABLE is not False:
        bulk_response = api_call("POST", "/assets/batch", headers, base_url, log_file, json_data={"ids": asset_ids}, silent_on_404=True)
        
        if bulk_response is None and _BATCH_ENDPOINT_AVAILABLE is None:
            # Erster Versuch fehlgeschlagen - Endpoint nicht verfügbar
            _BATCH_ENDPOINT_AVAILABLE = False
            log("INFO: Batch endpoint not available, falling back to individual asset requests", log_file, LogLevel.INFO)
        elif bulk_response is not None:
            # Batch-Endpoint funktioniert
            if _BATCH_ENDPOINT_AVAILABLE is None:
                _BATCH_ENDPOINT_AVAILABLE = True
                log("INFO: Using batch endpoint for efficient asset fetching", log_file, LogLevel.INFO)
            
            if isinstance(bulk_response, list):
                bulk_items = bulk_response
            elif isinstance(bulk_response, dict):
                bulk_items = bulk_response.get("items") or bulk_response.get("assets") or []

    for item in bulk_items:
        aid = item.get("id")
        if aid:
            details_by_id[aid] = item

    # Fehlende Assets einzeln abrufen
    for asset_id in asset_ids:
        if asset_id in details_by_id:
            continue
        detail = api_call("GET", f"/assets/{asset_id}", headers, base_url, log_file)
        if detail:
            details_by_id[asset_id] = detail
    return details_by_id

# ← VERBESSERUNG 7: Funktion als "derzeit ungenutzt" markiert
def parse_rating_output(output: str) -> str:
    """Extract numeric rating value from an ExifTool output string.
    
    NOTE: This function is currently unused but kept for potential future use
    or legacy compatibility. It was used in earlier versions for rating extraction.
    """
    if not output:
        return ""
    lines = output.strip().splitlines()
    if not lines:
        return ""
    first_line = lines[0]
    match = re.search(r"\b(\d+)\b", first_line)
    if match:
        return match.group(1)
    digits = "".join(ch for ch in first_line if ch.isdigit())
    return digits[0] if digits and digits[0] in VALID_RATING_VALUES else ""


def get_current_exif_values(full_path: str, active_modes: List[str]) -> Dict[str, Any]:
    """Read current EXIF values from file based on active modes using JSON output for reliable parsing."""
    tags_to_read = []
    
    if "people" in active_modes:
        tags_to_read.extend(["Subject", "Keywords", "PersonInImage"])  # ← FIX: Kein Namespace
    if "gps" in active_modes:
        tags_to_read.extend(["GPSLatitude", "GPSLongitude", "GPSAltitude"])
    if "caption" in active_modes:
        tags_to_read.extend(["Description", "Caption-Abstract"])
    if "time" in active_modes:
        tags_to_read.extend(["DateTimeOriginal", "CreateDate", "DateCreated"])  # ← FIX: DateCreated statt XMP-photoshop
    if "rating" in active_modes:
        tags_to_read.extend(["Rating"])  # ← FIX: Removed MicrosoftPhoto
    if "albums" in active_modes:
        tags_to_read.extend(["Event", "HierarchicalSubject", "UserComment"])
    
    if not tags_to_read:
        return {}
    
    try:
        # ← VERBESSERUNG 1: import json entfernt (jetzt oben)
        cmd = ["exiftool", "-json", "-n", "-struct"] + [f"-{tag}" for tag in tags_to_read] + [full_path]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        
        data = json.loads(result.stdout)
        if not data or not isinstance(data, list) or len(data) == 0:
            return {}
        
        file_data = data[0]
        values = {}
        
        for tag in tags_to_read:
            if tag in file_data:
                value = file_data[tag]
                if value is not None and value != "" and value != "-":
                    # Handle arrays (Subject is an array)
                    if isinstance(value, list):
                        # Join array elements, or take first element if it's already comma-separated
                        if len(value) == 1:
                            values[tag] = str(value[0])
                        else:
                            values[tag] = ",".join(str(v) for v in value)
                    else:
                        values[tag] = str(value)
        
        return values
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, subprocess.SubprocessError, ValueError, KeyError):
        return {}


def extract_desired_values(exif_args: List[str]) -> Dict[str, str]:
    """Extract tag-value pairs from ExifTool arguments for comparison."""
    desired = {}
    for arg in exif_args:
        if arg.startswith("-") and "=" in arg:
            tag_value = arg[1:]  # Remove leading dash
            tag, value = tag_value.split("=", 1)
            # Keep full tag name with namespace for proper comparison
            desired[tag] = value
    return desired


def normalize_exif_value(value: str, tag: str) -> str:
    """Normalize EXIF values for comparison."""
    if not value:
        return ""
    
    value = str(value).strip()
    tag_short = tag.split(":")[-1]  # ← NEU: Extrahiere kurzen Namen für Vergleiche
    
    # GPS coordinates: normalize format and round to configured precision
    if tag in ["GPSLatitude", "GPSLongitude"]:
        # Extract numeric value from various formats like "51 deg 30' 15.00\" N" or "51.504167"
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            try:
                # ← VERBESSERUNG 5: Konstante verwenden
                return str(round(float(match.group(0)), GPS_COORDINATE_PRECISION))
            except ValueError:
                return match.group(0)
    
    # GPS Altitude: extract numeric value and round to configured precision
    if tag == "GPSAltitude":
        # ExifTool might return "0" as default - check first
        if value == "0" or value == "0 m":
            return "0"
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            try:
                return str(round(float(match.group(0)), GPS_ALTITUDE_PRECISION))
            except ValueError:
                return match.group(0)
    
    # Rating: extract digit
    if tag == "Rating":
        match = re.search(r"\d", value)
        if match:
            return match.group(0)
    
        
    # DateTime fields: normalize separators
    if tag in ["DateTimeOriginal", "CreateDate"]:
        # Convert "YYYY:MM:DD HH:MM:SS" format variations
        normalized = value.replace("-", ":").replace("T", " ")
        # Take first 19 characters (YYYY:MM:DD HH:MM:SS)
        if len(normalized) >= 19:
            return normalized[:19]
    
    # Photoshop:DateCreated: ISO date format (YYYY-MM-DD only, no time)
    if tag_short == "DateCreated":  # ← FIX: ohne Namespace
        # Normalize to YYYY-MM-DD format
        normalized = value.replace(":", "-")
        # Take first 10 characters (YYYY-MM-DD)
        if len(normalized) >= 10:
            return normalized[:10]
    
    return value


# ← VERBESSERUNG 6: Funktion entfernt, da sie nicht mehr verwendet wird
# Die Logik wurde direkt in process_asset() integriert für bessere Performance


def build_exif_args(
    asset: Dict[str, Any],
    details: Dict[str, Any],
    active_modes: List[str],
    caption_max_len: int = DEFAULT_CAPTION_MAX_LEN,
    album_map: Optional[Dict[str, List[str]]] = None,
) -> Tuple[List[str], List[str]]:
    """Build ExifTool arguments based on selected modes. Populates XMP (modern) and IPTC fields simultaneously."""
    args: List[str] = []
    changes: List[str] = []
    exif = details.get("exifInfo", {}) or {}

    # 1. PEOPLE SYNC (face recognition)
    if "people" in active_modes:
        people = [p["name"] for p in details.get("people", []) if p.get("name")]
        if people:
            val = ",".join(people)
            args.extend([
                f"-XMP:Subject={val}", 
                f"-IPTC:Keywords={val}",
                f"-XMP-iptcExt:PersonInImage={val}"  # ← NEW: IPTC Extension standard
            ])
            changes.append("People")

    # 2. LOCATION SYNC (GPS & altitude)
    if "gps" in active_modes:
        lat, lon = exif.get("latitude"), exif.get("longitude")
        if lat is not None and lon is not None:
            alt = exif.get("altitude", 0) or 0
            args.extend([f"-GPSLatitude={lat}", f"-GPSLongitude={lon}", f"-GPSAltitude={alt}"])
            changes.append("GPS")

    # 3. CAPTION SYNC
    if "caption" in active_modes:
        cap = exif.get("description")
        if cap:
            safe_limit = normalize_caption_limit(caption_max_len)
            clean_cap = str(cap).replace("\n", " ").strip()[:safe_limit]
            args.extend([f"-XMP:Description={clean_cap}", f"-IPTC:Caption-Abstract={clean_cap}"])
            changes.append("Caption")

    # 4. TIME SYNC (timestamp corrections)
    if "time" in active_modes:
        date_raw = details.get("fileCreatedAt") or exif.get("dateTimeOriginal")
        if date_raw:
            # Use datetime for robust parsing
            date_str = str(date_raw)
            parsed_date = None
            
            # Try common ISO 8601 formats
            for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", 
                       "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                       "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
                try:
                    parsed_date = datetime.datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            
            # Fallback to fromisoformat when patterns fail
            if not parsed_date:
                try:
                    # Strip timezone information when present
                    # Robust for positive (+) and negative (-) offsets
                    clean_str = date_str.replace("Z", "")
                    # Strip timezone offsets in ±HH:MM or ±HHMM formats before ISO parsing
                    clean_str = re.sub(r"[+-]\d{2}:?\d{2}$", "", clean_str)
                    parsed_date = datetime.datetime.fromisoformat(clean_str)
                except (ValueError, AttributeError):
                    pass
            
            if parsed_date:
                # Format to EXIF: YYYY:MM:DD HH:MM:SS
                clean_date = parsed_date.strftime("%Y:%m:%d %H:%M:%S")
                iso_date = parsed_date.strftime("%Y-%m-%d")
                args.extend([
                    f"-DateTimeOriginal={clean_date}", 
                    f"-CreateDate={clean_date}",
                    f"-XMP:CreateDate={clean_date}",  # ← NEW: XMP standard
                    f"-XMP-photoshop:DateCreated={iso_date}"  # ← NEW: Photoshop compatibility (ISO date only)
                ])
                changes.append("Time")
            else:
                # Final fallback when parsing fails
                clean_date = str(date_raw).replace("-", ":").replace("T", " ")[:19]
                iso_date = str(date_raw)[:10]  # Extract YYYY-MM-DD
                args.extend([
                    f"-DateTimeOriginal={clean_date}", 
                    f"-CreateDate={clean_date}",
                    f"-XMP:CreateDate={clean_date}",
                    f"-XMP-photoshop:DateCreated={iso_date}"
                ])
                changes.append("Time")

    # 5. FAVORITE SYNC (Immich heart -> 5 stars, else 0)
    if "rating" in active_modes:
        rating = "5" if asset.get("isFavorite") else "0"
        args.append(f"-Rating={rating}")
        changes.append("Rating")

    # 6. ALBUM SYNC (new section after rating)
    if "albums" in active_modes and album_map:
        album_names = album_map.get(asset.get("id"), [])
        if album_names:
            # Primary album as Event
            args.append(f"-XMP-iptcExt:Event={album_names[0]}")
            
            # All albums as hierarchical keywords
            hierarchical = [f"Albums|{name}" for name in album_names]
            args.append(f"-XMP:HierarchicalSubject={','.join(hierarchical)}")
            
            # NEW: Write album names to EXIF:UserComment (for Windows Comments)
            args.append(f"-EXIF:UserComment={','.join(album_names)}")
            
            changes.append("Albums")

    return args, changes


def create_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="IMMICH ULTRA-SYNC PRO – Sync people, GPS, captions, time, and rating from Immich into EXIF/XMP.",
    )
    parser.add_argument("--all", action="store_true", help="Enable all sync modules.")
    parser.add_argument("--people", action="store_true", help="Sync detected people.")
    parser.add_argument("--gps", action="store_true", help="Sync GPS data.")
    parser.add_argument("--caption", action="store_true", help="Sync descriptions/captions.")
    parser.add_argument("--time", action="store_true", help="Sync timestamps.")
    parser.add_argument("--rating", action="store_true", help="Sync favorites/ratings.")
    parser.add_argument("--albums", action="store_true", help="Sync album information to XMP metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Simulation: log planned changes without writing.")
    parser.add_argument("--only-new", action="store_true", help="Skip files that already have ANY EXIF metadata.")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], 
                       default="INFO", help="Set logging verbosity")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run")
    parser.add_argument("--clear-checkpoint", action="store_true", help="Clear checkpoint and start fresh")
    parser.add_argument("--clear-album-cache", action="store_true", help="Clear album cache before running")
    parser.add_argument("--config", help="Path to config file", default="immich-sync.conf")
    parser.add_argument("--export-stats", choices=["json", "csv"], 
                       help="Export statistics to file")
    return parser


def parse_cli_args(argv: Optional[List[str]] = None) -> Tuple[argparse.Namespace, List[str]]:
    """Parse CLI arguments and derive active modes."""
    parser = create_arg_parser()
    args = parser.parse_args(argv)
    # Note: 'albums' is explicitly opt-in and not included in --all by default
    modes = ["people", "gps", "caption", "time", "rating"]
    active_modes = modes if args.all else [m for m in modes if getattr(args, m)]
    
    # Add albums if explicitly enabled
    if args.albums:
        active_modes.append("albums")
    
    if not active_modes:
        parser.error("No mode selected. Use --all or individual module flags.")
    return args, active_modes


def process_asset(
    asset: Dict[str, Any],
    details: Optional[Dict[str, Any]],
    active_modes: List[str],
    dry_run: bool,
    only_new: bool,
    photo_dir: str,
    path_segments: int,
    caption_max_len: int,
    log_file: str,
    exiftool: ExifToolHelper,
    album_map: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    """Process a single asset and return a statistics key for the outcome."""
    if not details:
        return "errors"

    asset_id = asset.get("id")
    orig_path = details.get("originalPath", "")
    sanitized_path = sanitize_path(orig_path)
    if not sanitized_path:
        log(f"Invalid path for asset {asset_id}: {orig_path}", log_file, LogLevel.WARNING)
        return "errors"

    path_parts = sanitized_path.split('/')
    parts_count = len(path_parts)
    if parts_count < path_segments:
        log(
            f'Skipping asset {asset_id}: path "{sanitized_path}" has {parts_count} parts, expected at least {path_segments}',
            log_file,
            LogLevel.DEBUG,
        )
        return "skipped"

    if any(part.startswith('/') or part.startswith('\\') for part in path_parts):
        log(f"SECURITY ERROR: Absolute path component detected for asset {asset_id}", log_file, LogLevel.ERROR)
        return "errors"

    try:
        clean_rel = os.path.join(*path_parts[-path_segments:])
        full_path = os.path.join(photo_dir, clean_rel)
    except (IndexError, TypeError):
        log(f"Path mapping error for asset {asset_id}", log_file, LogLevel.ERROR)
        return "errors"

    if not validate_path_in_boundary(full_path, photo_dir):
        log(f"SECURITY ERROR: Path outside allowed boundaries for asset {asset_id}", log_file, LogLevel.ERROR)
        return "errors"

    if not os.path.exists(full_path):
        log(f"Skipping asset {asset_id}: file not found at {full_path}", log_file, LogLevel.DEBUG)
        return "skipped"

    exif_args, change_list = build_exif_args(asset, details, active_modes, caption_max_len, album_map)
    if not change_list:
        return None

    # ALWAYS check if update is needed by comparing current vs desired values
    current_values = get_current_exif_values(full_path, active_modes)
    desired_values = extract_desired_values(exif_args)

    # Determine which fields actually need updating
    fields_to_update = []
    for tag, desired in desired_values.items():
        # For comparison, try both full tag name and short name (without namespace)
        tag_short = tag.split(":")[-1]
        current = current_values.get(tag, current_values.get(tag_short, ""))
        normalized_current = normalize_exif_value(current, tag)
        normalized_desired = normalize_exif_value(desired, tag)
        
        if normalized_current != normalized_desired:
            # DEBUG: Uncomment for troubleshooting
            # log(f"DEBUG {clean_rel}: Tag={tag} | Current='{normalized_current}' | Desired='{normalized_desired}'", log_file, LogLevel.DEBUG)
            fields_to_update.append(tag)

    # For --only-new mode: skip if ANY value already exists
    if only_new and current_values:
        log(f"SKIP: {clean_rel} - Already has EXIF data (--only-new mode)", log_file, LogLevel.DEBUG)
        return "skipped"

    # Standard mode: skip if no updates needed
    if not fields_to_update:
        log(f"SKIP: {clean_rel} - Already up to date", log_file, LogLevel.DEBUG)
        return "skipped"

    if dry_run:
        log(f"[DRY] {clean_rel} - Would update: {', '.join(fields_to_update)}", log_file, LogLevel.INFO)
        return "simulated"

    try:
        log(f"UPDATE: {clean_rel} - Changing: {', '.join(fields_to_update)}", log_file, LogLevel.INFO)
        stdout, stderr = exiftool.execute(["-overwrite_original"] + exif_args + [full_path])
        if stderr:
            log(f"ExifTool warning for {clean_rel}: {stderr}", log_file, LogLevel.WARNING)
        return "updated"
    except Exception as e:
        log(f"ERROR: ExifTool failed for {clean_rel}: {e}", log_file, LogLevel.ERROR)
        return "errors"


def main() -> None:
    args, active_modes = parse_cli_args()

    # Set log level early
    set_log_level(args.log_level)
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Load config file if exists
    config = load_config(args.config) if Path(args.config).exists() else {}
    
    base_url = os.getenv("IMMICH_INSTANCE_URL") or config.get('IMMICH_INSTANCE_URL', '').rstrip("/")
    api_key = os.getenv("IMMICH_API_KEY") or config.get('IMMICH_API_KEY')
    photo_dir = os.getenv("IMMICH_PHOTO_DIR") or config.get('IMMICH_PHOTO_DIR', DEFAULT_PHOTO_DIR)
    log_file = os.getenv("IMMICH_LOG_FILE") or config.get('IMMICH_LOG_FILE', DEFAULT_LOG_FILE)
    path_segments_raw = get_env_int("IMMICH_PATH_SEGMENTS", int(config.get('IMMICH_PATH_SEGMENTS', DEFAULT_PATH_SEGMENTS)))
    path_segments = min(MAX_PATH_SEGMENTS, max(1, path_segments_raw))
    batch_size = max(1, get_env_int("IMMICH_ASSET_BATCH_SIZE", int(config.get('IMMICH_ASSET_BATCH_SIZE', DEFAULT_BATCH_SIZE))))
    page_size_raw = get_env_int("IMMICH_SEARCH_PAGE_SIZE", int(config.get('IMMICH_SEARCH_PAGE_SIZE', DEFAULT_PAGE_SIZE)))
    caption_max_len_raw = get_env_int("CAPTION_MAX_LEN", int(config.get('CAPTION_MAX_LEN', DEFAULT_CAPTION_MAX_LEN)))
    caption_max_len = normalize_caption_limit(caption_max_len_raw)
    # Align fetch size with processing throughput while keeping pagination bounded (at least batch_size, capped by MAX_PAGE_SIZE)
    page_size = min(MAX_PAGE_SIZE, max(batch_size, page_size_raw))

    # Handle checkpoint operations
    if args.clear_checkpoint and Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()
        log("Checkpoint cleared", log_file, LogLevel.INFO)

    # Validate credentials before creating headers
    if not base_url or not api_key:
        log("ERROR: IMMICH_INSTANCE_URL or IMMICH_API_KEY missing.", log_file, LogLevel.ERROR)
        sys.exit(1)

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if path_segments != path_segments_raw:
        log(f"Adjusted path_segments to {path_segments} (requested {path_segments_raw})", log_file, LogLevel.INFO)
    if page_size != page_size_raw:
        log(f"Adjusted search page size to {page_size} (requested {page_size_raw}, batch size {batch_size})", log_file, LogLevel.INFO)
    if caption_max_len != caption_max_len_raw:
        log(f"Adjusted caption max length to {caption_max_len} (requested {caption_max_len_raw})", log_file, LogLevel.INFO)

    if not check_exiftool(log_file):
        log("ABORT: ExifTool is not available. Please install ExifTool.", log_file, LogLevel.ERROR)
        sys.exit(1)

    # Initialize ExifTool in stay-open mode
    exiftool = ExifToolHelper()
    exiftool.start()
    log("ExifTool started in stay-open mode for better performance", log_file, LogLevel.DEBUG)

    dry_run = args.dry_run
    only_new = args.only_new
    
    # Load checkpoint if resuming
    processed_ids = load_checkpoint(log_file) if args.resume else set()

    log(
        f"START: modes={active_modes} | dry={dry_run} | only_new={only_new} | "
        f"batch_size={batch_size} | path_segments={path_segments} | caption_max_len={caption_max_len}",
        log_file,
        LogLevel.INFO,
    )

    assets = fetch_assets(headers, base_url, page_size, log_file)
    statistics = {"total": len(assets), "updated": 0, "simulated": 0, "skipped": 0, "errors": 0}
    log(f"{statistics['total']} assets loaded. Starting synchronization...", log_file, LogLevel.INFO)

    # Build album map if needed (before processing assets) with caching
    album_map = {}
    if "albums" in active_modes:
        # Get cache TTL and max_stale from environment
        cache_ttl = get_env_int("IMMICH_ALBUM_CACHE_TTL", DEFAULT_ALBUM_CACHE_TTL)
        cache_max_stale = get_env_int("IMMICH_ALBUM_CACHE_MAX_STALE", DEFAULT_ALBUM_CACHE_MAX_STALE)
        
        # Clear cache if requested
        if args.clear_album_cache:
            clear_album_cache(log_file)
        
        # Try to load from cache
        log("Checking album cache...", log_file, LogLevel.DEBUG)
        album_map = load_album_cache(cache_ttl, log_file)
        
        if album_map is None:
            # Cache miss or expired - fetch from API
            log("Fetching album information from API...", log_file, LogLevel.INFO)
            try:
                album_map = build_asset_album_map(headers, base_url, log_file)
                log(f"Loaded {len(album_map)} assets with album assignments", log_file, LogLevel.INFO)
                
                # Save to cache
                save_album_cache(album_map, log_file)
            except Exception as e:
                log(f"Failed to fetch album information: {e}", log_file, LogLevel.ERROR)
                
                # Try to load stale cache as fallback
                log("Attempting to use stale cache as fallback...", log_file, LogLevel.WARNING)
                album_map = load_stale_album_cache(cache_max_stale, log_file)
                
                if album_map is None:
                    log("No fallback cache available, continuing without album sync", log_file, LogLevel.WARNING)
                    album_map = {}
        else:
            log(f"Using cached album data ({len(album_map)} assets with album assignments)", log_file, LogLevel.INFO)

    # Initialize progress bar if available
    if TQDM_AVAILABLE and not dry_run:
        progress = tqdm(total=len(assets), desc="Syncing", unit="file")
    else:
        progress = None

    total_batches = (len(assets) + batch_size - 1) // batch_size
    for batch_num, asset_batch in enumerate(chunked(assets, batch_size), start=1):
        # Check for graceful shutdown
        if _shutdown_requested:
            log("Shutdown requested, stopping gracefully...", log_file, LogLevel.WARNING)
            break
        
        if total_batches > 1:
            log(f"Processing batch {batch_num}/{total_batches} ({len(asset_batch)} assets)...", log_file, LogLevel.DEBUG)
        
        detail_map = fetch_asset_details_batch(asset_batch, headers, base_url, log_file)
        for asset in asset_batch:
            asset_id = asset.get("id")
            
            # Skip already processed assets when resuming
            if asset_id in processed_ids:
                statistics['skipped'] += 1
                if progress:
                    progress.update(1)
                continue
            
            status_key = process_asset(
                asset,
                detail_map.get(asset_id),
                active_modes,
                dry_run,
                only_new,
                photo_dir,
                path_segments,
                caption_max_len,
                log_file,
                exiftool,
                album_map,
            )
            if status_key and status_key in statistics:
                statistics[status_key] += 1
            
            # Add to processed set
            processed_ids.add(asset_id)
            
            # Update progress bar
            if progress:
                progress.update(1)
                progress.set_postfix({
                    'Updated': statistics['updated'],
                    'Skipped': statistics['skipped'],
                    'Errors': statistics['errors']
                })
            
            # Save checkpoint every 100 assets
            if len(processed_ids) % 100 == 0:
                save_checkpoint(processed_ids, log_file)

    # Close progress bar
    if progress:
        progress.close()

    # Close ExifTool
    exiftool.close()
    log("ExifTool stay-open mode closed", log_file, LogLevel.DEBUG)
    
    # Remove checkpoint after successful completion
    if args.resume and Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()
        log("Checkpoint removed after successful completion", log_file, LogLevel.INFO)

    log(
        f"FINISH: Total:{statistics['total']} Updated:{statistics['updated']} "
        f"Simulated:{statistics['simulated']} Skipped:{statistics['skipped']} Errors:{statistics['errors']}",
        log_file,
        LogLevel.INFO,
    )
    
    # Export statistics if requested
    if args.export_stats:
        export_statistics(statistics, log_file, args.export_stats)


if __name__ == "__main__":
    main()
