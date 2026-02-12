"""API-related functions and RateLimiter for Immich Ultra-Sync."""

import threading
import time
from typing import Any, Dict, List, Optional
import requests

import sys
import os
# Add script directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    log, LogLevel, retry_on_failure, chunked, extract_asset_items
)

# Globale Variable für Batch-Endpoint-Verfügbarkeit
_BATCH_ENDPOINT_AVAILABLE = None  # None = unbekannt, True = verfügbar, False = nicht verfügbar


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
# API FUNCTIONS
# ==============================================================================
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
    """Build a mapping of asset IDs to album names."""
    all_albums = api_call("GET", "/albums", headers, base_url, log_file)
    
    asset_to_albums = {}
    for album in all_albums or []:
        album_name = album.get("albumName")
        # Skip albums without a name or with empty name
        if not album_name:
            continue
        
        # Check if assets are already in the album object (for testing or API responses that include them)
        assets = album.get("assets", [])
        
        # If assets not included, fetch album details
        if not assets:
            album_id = album.get("id")
            if not album_id:
                continue
            album_details = api_call("GET", f"/albums/{album_id}", headers, base_url, log_file)
            if album_details:
                assets = album_details.get("assets", [])
        
        # Map each asset to this album
        for asset in assets:
            asset_id = asset.get("id")
            if asset_id:
                if asset_id not in asset_to_albums:
                    asset_to_albums[asset_id] = []
                asset_to_albums[asset_id].append(album_name)
    
    return asset_to_albums


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
