"""Utility functions and constants for Immich Ultra-Sync."""

import configparser
import csv
import datetime
from enum import Enum
import json
import os
import pickle
from pathlib import Path
import signal
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, IO
from itertools import islice

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
MWGRS_COORDINATE_PRECISION = 6  # Decimal places for MWG-RS normalized coordinates (0-1)
MWGRS_COMPARE_PRECISION = 4    # Decimal places for MWG-RS comparison (avoids float drift)
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
# UTILITY FUNCTIONS
# ==============================================================================
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
    try:
        _LOG_LEVEL = LogLevel[level.upper()]
    except KeyError:
        # Fallback to INFO if invalid level provided
        _LOG_LEVEL = LogLevel.INFO

def _structured_logs_enabled() -> bool:
    """Return True when structured (JSON) logging is enabled via environment variables."""
    log_format = os.getenv("IMMICH_LOG_FORMAT", "").lower()
    if log_format == "json":
        return True
    flag = os.getenv("IMMICH_STRUCTURED_LOGS", "").lower()
    return flag in ("1", "true", "yes", "on")


def log(message: str, log_file: str = DEFAULT_LOG_FILE, level: LogLevel = LogLevel.INFO, extra: Optional[Dict[str, Any]] = None) -> None:
    """Log messages with level filtering and optional structured output."""
    if level.value < _LOG_LEVEL.value:
        return
    
    now = datetime.datetime.now()
    ts_plain = now.strftime("%Y-%m-%d %H:%M:%S")
    level_str = level.name.ljust(7)

    if _structured_logs_enabled():
        payload: Dict[str, Any] = {
            "timestamp": now.isoformat(timespec="seconds"),
            "level": level.name,
            "message": message,
        }
        if extra:
            payload["extra"] = extra
        msg = json.dumps(payload, ensure_ascii=False)
    else:
        msg = f"[{ts_plain}] [{level_str}] {message}"
        if extra:
            msg = f"{msg} | {json.dumps(extra, ensure_ascii=False)}"

    print(msg, flush=True)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except (IOError, OSError) as e:
        print(f"Logging error: {e}")


def retry_on_failure(max_retries: int = 3, delay: float = 2.0):
    """Decorator to retry function calls on failure with exponential backoff."""
    from functools import wraps
    import requests
    
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

    def _decode_value(raw: str) -> str:
        """Return a decoded config value with matching quotes stripped (dotenv-style)."""
        decoded = raw
        if "\\" in raw:
            escape_map = {
                "\\n": "\n",
                "\\t": "\t",
                "\\\\": "\\",
                '\\"': '"',
                "\\'": "'",
            }
            for k, v in escape_map.items():
                decoded = decoded.replace(k, v)
        if len(decoded) >= 2 and decoded[0] == decoded[-1] and decoded[0] in ("'", '"'):
            decoded = decoded[1:-1]
        return decoded

    cfg_path = Path(config_file)
    if not cfg_path.exists():
        return defaults

    suffix = cfg_path.suffix.lower()

    if suffix == ".json":
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(key, str):
                        defaults[key.upper()] = _decode_value(str(value))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            log(f"Failed to load JSON config {config_file}: {exc}", DEFAULT_LOG_FILE, LogLevel.WARNING)
        return defaults

    if suffix == ".env":
        # Simple .env parsing; for complex escaping or multiline values, prefer JSON/INI configs.
        try:
            for line in cfg_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                if stripped.startswith("export "):
                    stripped = stripped[len("export "):].strip()
                key_part, value_part = stripped.split("=", 1)
                key_clean = key_part.strip().upper()
                value_clean = _decode_value(value_part.strip())
                defaults[key_clean] = value_clean
        except (OSError, UnicodeDecodeError) as exc:
            log(f"Failed to load .env config {config_file}: {exc}", DEFAULT_LOG_FILE, LogLevel.WARNING)
        return defaults

    config = configparser.ConfigParser()
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


def chunked(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    """Yield successive chunks (lists) from any iterable; `size` must be >= 1."""
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            break
        yield chunk


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


def validate_photo_directory(photo_dir: str, log_file: str) -> bool:
    """
    Validate that the photo directory exists and is not empty.
    Returns True if valid, False if issues detected.
    Logs helpful hints for common configuration problems.
    """
    # Check if directory exists
    if not os.path.exists(photo_dir):
        log(f"ERROR: Photo directory does not exist: {photo_dir}", log_file, LogLevel.ERROR)
        log(
            f"HINT: Check if IMMICH_PHOTO_DIR is correctly set and matches the Docker mount point.",
            log_file,
            LogLevel.ERROR
        )
        log(
            f"HINT: If running in Docker, ensure the library volume is properly mounted (e.g., '/path/to/library:/library').",
            log_file,
            LogLevel.ERROR
        )
        return False
    
    # Check if directory is actually a directory
    if not os.path.isdir(photo_dir):
        log(f"ERROR: Photo directory path exists but is not a directory: {photo_dir}", log_file, LogLevel.ERROR)
        return False
    
    # Check if directory is empty (potential mount issue)
    try:
        contents = os.listdir(photo_dir)
        if not contents:
            log(f"WARNING: Photo directory is empty: {photo_dir}", log_file, LogLevel.WARNING)
            log(
                f"HINT: This might indicate a mount problem. Verify that your library is properly mounted in the container.",
                log_file,
                LogLevel.WARNING
            )
            log(
                f"HINT: Check Docker volume configuration and ensure the host path contains your photo library.",
                log_file,
                LogLevel.WARNING
            )
            return False
    except PermissionError:
        log(f"ERROR: No permission to read photo directory: {photo_dir}", log_file, LogLevel.ERROR)
        log(f"HINT: Check file permissions and ensure the container user has read access.", log_file, LogLevel.ERROR)
        return False
    except (OSError, IOError) as e:
        log(f"ERROR: I/O error while checking photo directory: {e}", log_file, LogLevel.ERROR)
        log(f"HINT: This may indicate filesystem issues or network mount problems.", log_file, LogLevel.ERROR)
        return False
    except Exception as e:
        log(f"ERROR: Failed to check photo directory contents: {e}", log_file, LogLevel.ERROR)
        return False
    
    log(f"Photo directory validated: {photo_dir} ({len(contents)} items)", log_file, LogLevel.INFO)
    return True


def check_mount_issues(statistics: dict, log_file: str, photo_dir: str, path_segments: int) -> None:
    """
    Analyze statistics to detect potential mount or path configuration issues.
    Logs helpful hints if high percentage of file-not-found errors detected.
    """
    total = statistics.get('total', 0)
    file_not_found = statistics.get('file_not_found', 0)
    path_segment_mismatch = statistics.get('path_segment_mismatch', 0)
    
    if total == 0:
        return
    
    # Calculate percentages
    file_not_found_pct = (file_not_found / total) * 100
    path_mismatch_pct = (path_segment_mismatch / total) * 100
    
    # Check for high rate of file-not-found errors (>90%)
    if file_not_found_pct > 90:
        log(
            f"WARNING: {file_not_found_pct:.1f}% of assets ({file_not_found}/{total}) were skipped due to files not being found.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"SUSPECTED ISSUE: Library might not be properly mounted or IMMICH_PHOTO_DIR is incorrectly configured.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"TROUBLESHOOTING STEPS:",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  1. Verify IMMICH_PHOTO_DIR is set to: {photo_dir}",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  2. Check if files exist in this directory on the host system.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  3. If running in Docker, verify volume mount matches IMMICH_PHOTO_DIR.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  4. Example: If Immich uses '/mnt/media/library' on the host, mount it as '-v /mnt/media/library:/library' and set IMMICH_PHOTO_DIR=/library in the container",
            log_file,
            LogLevel.WARNING
        )
    elif file_not_found_pct > 50:
        log(
            f"WARNING: {file_not_found_pct:.1f}% of assets ({file_not_found}/{total}) were not found.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"HINT: Check IMMICH_PHOTO_DIR configuration and Docker mount settings.",
            log_file,
            LogLevel.WARNING
        )
    
    # Check for high rate of path segment mismatches (>50%)
    if path_mismatch_pct > 50:
        log(
            f"WARNING: {path_mismatch_pct:.1f}% of assets ({path_segment_mismatch}/{total}) have path segment mismatches.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"SUSPECTED ISSUE: IMMICH_PATH_SEGMENTS might be incorrectly configured.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"TROUBLESHOOTING STEPS:",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  1. Current IMMICH_PATH_SEGMENTS is set to: {path_segments}",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  2. Check the structure of originalPath in Immich (e.g., 'library/user/2024/photo.jpg').",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  3. Set IMMICH_PATH_SEGMENTS to match the number of path components after the mount point.",
            log_file,
            LogLevel.WARNING
        )
        log(
            f"  4. Example: For 'library/user/2024/photo.jpg', if IMMICH_PHOTO_DIR=/library, set IMMICH_PATH_SEGMENTS=3 (user/2024/photo.jpg).",
            log_file,
            LogLevel.WARNING
        )
