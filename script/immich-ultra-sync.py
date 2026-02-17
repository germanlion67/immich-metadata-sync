#!/usr/bin/env python3
"""
IMMICH ULTRA-SYNC - Sync metadata from Immich back to original media files.

This is the main orchestration script that coordinates fetching metadata from
Immich API and writing it to EXIF/XMP tags in media files.
"""

import argparse
import os
from pathlib import Path
import signal
import sys
from typing import Any, Dict, List, Optional, Tuple

# Add script directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import from local modules
from utils import (
    log, LogLevel, set_log_level, signal_handler,
    load_config, save_checkpoint, load_checkpoint, export_statistics,
    sanitize_path, validate_path_in_boundary, chunked,
    get_env_int, normalize_caption_limit,
    load_album_cache, load_stale_album_cache, save_album_cache, clear_album_cache,
    validate_photo_directory, check_mount_issues,
    DEFAULT_PHOTO_DIR, DEFAULT_LOG_FILE, DEFAULT_PATH_SEGMENTS, MAX_PATH_SEGMENTS,
    DEFAULT_BATCH_SIZE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE,
    DEFAULT_CAPTION_MAX_LEN, DEFAULT_ALBUM_CACHE_TTL, DEFAULT_ALBUM_CACHE_MAX_STALE,
    CHECKPOINT_FILE, _shutdown_requested
)
from api import (
    fetch_assets, fetch_asset_details_batch, build_asset_album_map
)
from exif import (
    ExifToolHelper, check_exiftool,
    build_exif_args, get_current_exif_values, extract_desired_values, normalize_exif_value
)

# ==============================================================================
# TQDM PROGRESS BAR
# ==============================================================================
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


# ==============================================================================
# CORE PROCESSING LOGIC
# ==============================================================================
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
        log(
            f'HINT: Adjust IMMICH_PATH_SEGMENTS to {parts_count} or verify your mount structure matches the expected path depth.',
            log_file,
            LogLevel.DEBUG,
        )
        return "path_segment_mismatch"

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
        log(f"HINT: Verify IMMICH_PHOTO_DIR is set correctly (current: {photo_dir})", log_file, LogLevel.DEBUG)
        return "file_not_found"

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


# ==============================================================================
# CLI ARGUMENT PARSING
# ==============================================================================
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
    parser.add_argument("--face-coordinates", action="store_true", help="Sync face bounding boxes as MWG-RS regions to XMP metadata.")
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
    
    # Add face-coordinates if explicitly enabled
    if args.face_coordinates:
        active_modes.append("face-coordinates")
    
    if not active_modes:
        parser.error("No mode selected. Use --all or individual module flags.")
    return args, active_modes


# ==============================================================================
# MAIN FUNCTION
# ==============================================================================
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

    # Validate photo directory before starting
    log(f"Validating photo directory: {photo_dir}", log_file, LogLevel.INFO)
    if not validate_photo_directory(photo_dir, log_file):
        log("ABORT: Photo directory validation failed. Please check your configuration.", log_file, LogLevel.ERROR)
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
        extra={
            "modes": active_modes,
            "dry_run": dry_run,
            "only_new": only_new,
            "batch_size": batch_size,
            "path_segments": path_segments,
            "caption_max_len": caption_max_len,
        },
    )

    assets = fetch_assets(headers, base_url, page_size, log_file)
    statistics = {
        "total": len(assets),
        "updated": 0,
        "simulated": 0,
        "skipped": 0,
        "file_not_found": 0,
        "path_segment_mismatch": 0,
        "errors": 0
    }
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

    # Check for potential mount/path configuration issues
    check_mount_issues(statistics, log_file, photo_dir, path_segments)

    log(
        f"FINISH: Total:{statistics['total']} Updated:{statistics['updated']} "
        f"Simulated:{statistics['simulated']} Skipped:{statistics['skipped']} "
        f"FileNotFound:{statistics['file_not_found']} PathMismatch:{statistics['path_segment_mismatch']} "
        f"Errors:{statistics['errors']}",
        log_file,
        LogLevel.INFO,
        extra={"statistics": statistics},
    )
    
    # Export statistics if requested
    if args.export_stats:
        export_statistics(statistics, log_file, args.export_stats)


if __name__ == "__main__":
    main()
