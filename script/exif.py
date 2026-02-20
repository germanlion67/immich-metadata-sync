"""EXIF/XMP metadata handling for Immich Ultra-Sync."""

import datetime
import json
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import sys
import os
# Add script directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (
    log, LogLevel, extract_error_message,
    DEFAULT_LOG_FILE, DEFAULT_CAPTION_MAX_LEN, VALID_RATING_VALUES,
    GPS_COORDINATE_PRECISION, GPS_ALTITUDE_PRECISION,
    MWGRS_COORDINATE_PRECISION, MWGRS_COMPARE_PRECISION,
    normalize_caption_limit
)


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
        """Execute ExifTool command and return (stdout, stderr)."""
        if not self.process:
            self.start()
            
        # Filter ONLY the virtual tag with JSON data (used for internal comparison)
        # Keep "-XMP-mwg-rs:RegionInfo=" (empty) because it's used to clear old metadata
        real_args = [a for a in args if not (a.startswith("-XMP-mwg-rs:RegionInfo=") and len(a) > 23)]
        
        command = "\n".join(real_args) + "\n-execute\n"
        self.process.stdin.write(command)
        self.process.stdin.flush()
        
        output = []
        while True:
            line = self.process.stdout.readline()
            if not line or line.strip() == "{ready}":
                break
            output.append(line)
        
        # Optional: Hier könnte man stderr separat auslesen, 
        # aber meistens reicht stdout für die Fehlerdiagnose bei ExifTool
        return "".join(output), ""
    
    def close(self):
        """Close ExifTool process."""
        if self.process:
            self.process.stdin.write("-stay_open\nFalse\n")
            self.process.stdin.flush()
            self.process.wait()

# overwride sidcar
def execute_with_sidecar_and_msphoto(args: list, full_path: str, exif_tool_helper: ExifToolHelper, log_file: str) -> tuple:
    """
    Execute ExifTool write with sidecar-awareness and MicrosoftPhoto:Rating fallback.

    - If a .xmp sidecar exists it will be read and its previous rating logged.
    - JPG and sidecar are written together to keep metadata consistent.
    - If ExifTool reports MicrosoftPhoto:Rating not writable, retry without that tag.
    - Returns (stdout, stderr) combined from attempts.
    """
    targets = [full_path]
    sidecar_path = f"{full_path}.xmp"

    # Read & log sidecar previous rating (if present) and add it to targets
    if os.path.exists(sidecar_path):
        try:
            proc = subprocess.run(
                ["exiftool", "-json", "-n", "-Rating", "-XMP:Rating", "-RatingPercent", sidecar_path],
                capture_output=True, text=True, check=True
            )
            side_info = json.loads(proc.stdout)[0] if proc.stdout else {}
            prev_rating = side_info.get("Rating", side_info.get("XMP:Rating", None))
            prev_percent = side_info.get("RatingPercent", None)

            if prev_rating is not None or prev_percent is not None:
                log(
                    f"[SIDE-CAR] {sidecar_path} previous rating: Rating={prev_rating} RatingPercent={prev_percent}",
                    log_file, LogLevel.INFO
                )
            else:
                log(f"[SIDE-CAR] {sidecar_path} previous rating: (not set)", log_file, LogLevel.DEBUG)

            targets.append(sidecar_path)
        except Exception as e:
            log(f"Failed to read sidecar {sidecar_path}: {e}", log_file, LogLevel.DEBUG)

    # Optional: read and log in-file previous rating for audit (debug level)
    try:
        proc_file = subprocess.run(
            ["exiftool", "-json", "-n", "-Rating", "-XMP:Rating", "-RatingPercent", full_path],
            capture_output=True, text=True, check=True
        )
        file_info = json.loads(proc_file.stdout)[0] if proc_file.stdout else {}
        file_prev_rating = file_info.get("Rating", file_info.get("XMP:Rating", None))
        file_prev_percent = file_info.get("RatingPercent", None)
        if file_prev_rating is not None or file_prev_percent is not None:
            log(
                f"[FILE-BEFORE] {full_path} previous rating: Rating={file_prev_rating} RatingPercent={file_prev_percent}",
                log_file, LogLevel.DEBUG
            )
    except Exception:
        # ignore read failures here
        pass

    # First write attempt (JPG [+ sidecar if present])
    stdout, stderr = exif_tool_helper.execute(args + targets)
    combined_out = (stdout or "") + (stderr or "")

    # If ExifTool complains about MicrosoftPhoto:Rating not writable, retry without that tag
    ms_tag = "MicrosoftPhoto:Rating"
    if any(keyword in combined_out for keyword in ["MicrosoftPhoto:Rating", "MicrosoftPhoto:Rating' doesn't exist", "not writable", "Sorry"]):
        # Filter out MicrosoftPhoto:Rating entries (they look like "-MicrosoftPhoto:Rating=...")
        filtered_args = [a for a in args if not a.startswith(f"-{ms_tag}")]
        log(f"[MSPHOTO] {full_path}: MicrosoftPhoto:Rating not writable; retrying without {ms_tag}", log_file, LogLevel.WARNING)
        stdout2, stderr2 = exif_tool_helper.execute(filtered_args + targets)
        combined_stdout = (stdout or "") + (stdout2 or "")
        combined_stderr = (stderr or "") + (stderr2 or "")
        return combined_stdout, combined_stderr

    return stdout, stderr

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
        tags_to_read.extend([
            "DateTimeOriginal", "CreateDate", "ModifyDate", "DateCreated",
            "XMP:CreateDate", "XMP:ModifyDate", "XMP:MetadataDate",
            "IPTC:DateCreated", "IPTC:TimeCreated",
            "QuickTime:CreateDate", "QuickTime:ModifyDate",
            "FileCreateDate", "FileModifyDate"
        ])
    if "rating" in active_modes:
        tags_to_read.extend(["Rating", "XMP:Rating", "MicrosoftPhoto:Rating", "RatingPercent",
                             "XMP:Label"])
    if "albums" in active_modes:
        tags_to_read.extend(["Event", "HierarchicalSubject", "UserComment"])
    if "face-coordinates" in active_modes:
        tags_to_read.extend(["XMP-mwg-rs:RegionInfo"]) # Expliziter Namespace
    
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
            # Try full tag name first, then short name (without namespace)
            tag_short = tag.split(":")[-1]
            value = file_data.get(tag, file_data.get(tag_short))
            
            if value is not None and value != "" and value != "-":
                # Handle structs (RegionInfo is a dict)
                if isinstance(value, dict):
                    values[tag] = json.dumps(value, sort_keys=True)
                # Handle arrays (Subject is an array)
                elif isinstance(value, list):
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
            # Skip individual structural parts for comparison to avoid false positives
            # We only want to compare the composite RegionInfo tag
            if any(x in tag for x in ["RegionName", "RegionType", "RegionArea", "RegionApplied"]):
                continue
            # Strip trailing plus from tag name for comparison
            tag = tag.rstrip('+')
            # Normalize tag to short name (without namespace prefix)
            tag_short = tag.split(":")[-1]
            desired[tag_short] = value
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
    if tag in ["Rating", "XMP:Rating", "MicrosoftPhoto:Rating"] or tag_short == "Rating":
        match = re.search(r"\d", value)
        if match:
            return match.group(0)

    # RatingPercent: extract number
    if tag == "RatingPercent" or tag_short == "RatingPercent":
        match = re.search(r"\d+", value)
        if match:
            return match.group(0)

    # XMP:Label: normalize to string
    if tag == "XMP:Label" or tag_short == "Label":
        return value.strip()


    # DateTime fields: normalize separators
    if tag in ["DateTimeOriginal", "CreateDate", "ModifyDate"] or tag_short in [
        "DateTimeOriginal", "CreateDate", "ModifyDate", "XMP:CreateDate",
        "XMP:ModifyDate", "XMP:MetadataDate", "MetadataDate",
        "QuickTime:CreateDate", "QuickTime:ModifyDate"
    ]:
        # Convert "YYYY:MM:DD HH:MM:SS" format variations
        normalized = value.replace("-", ":").replace("T", " ")
        # Remove trailing 'Z' if present
        normalized = normalized.rstrip('Z').strip()
        # Take first 19 characters (YYYY:MM:DD HH:MM:SS)
        if len(normalized) >= 19:
            return normalized[:19]
        return normalized
    
    # Photoshop:DateCreated: ISO date format (YYYY-MM-DD only, no time)
    if tag_short == "DateCreated":  # ← FIX: ohne Namespace
        # Normalize to YYYY-MM-DD format
        normalized = value.replace(":", "-")
        # Take first 10 characters (YYYY-MM-DD)
        if len(normalized) >= 10:
            return normalized[:10]
    # IPTC:TimeCreated: normalize time
    if tag == "IPTC:TimeCreated" or tag_short == "TimeCreated":
        # Normalize to HH:MM:SS format
        normalized = value.strip()
        if len(normalized) >= 8:
            return normalized[:8]
        return normalized
    # File timestamps: normalize ISO format
    if tag_short in ["FileCreateDate", "FileModifyDate"]:
        normalized = value.replace("-", ":").replace("T", " ")
        normalized = normalized.rstrip('Z').strip()
        if len(normalized) >= 19:
            return normalized[:19]
        return normalized
    # MWG-RS RegionInfo: normalize to canonical name:coordinates representation
    if tag_short == "RegionInfo":
        try:
            # If it's already a dict from JSON, use it, otherwise parse it
            data = json.loads(value) if isinstance(value, str) else value
            if isinstance(data, dict):
                regions = data.get("RegionList", [])
                # Ensure it's a list even if only one region exists
                if isinstance(regions, dict): regions = [regions]
                canonical = []
                for r in sorted(regions, key=lambda r: str(r.get("Name", ""))):
                    area = r.get("Area", {})
                    canonical.append(
                        f"{r.get('Name', '')}:"
                        f"{round(float(area.get('X', 0)), MWGRS_COMPARE_PRECISION)},"
                        f"{round(float(area.get('Y', 0)), MWGRS_COMPARE_PRECISION)},"
                        f"{round(float(area.get('W', 0)), MWGRS_COMPARE_PRECISION)},"
                        f"{round(float(area.get('H', 0)), MWGRS_COMPARE_PRECISION)}"
                    )
                return "|".join(canonical)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    
    return value


def convert_bbox_to_mwg_rs(
    x1: int, y1: int, x2: int, y2: int,
    image_width: int, image_height: int,
) -> Optional[Dict[str, float]]:
    """Convert pixel bounding box (X1/Y1/X2/Y2) to MWG-RS normalized region coordinates.

    Returns dict with X, Y (center), W, H as values in [0..1] or None on invalid input.
    """
    if image_width <= 0 or image_height <= 0:
        return None
    bbox_w = x2 - x1
    bbox_h = y2 - y1
    if bbox_w <= 0 or bbox_h <= 0:
        return None
    center_x = x1 + bbox_w / 2
    center_y = y1 + bbox_h / 2
    return {
        "X": round(center_x / image_width, MWGRS_COORDINATE_PRECISION),
        "Y": round(center_y / image_height, MWGRS_COORDINATE_PRECISION),
        "W": round(bbox_w / image_width, MWGRS_COORDINATE_PRECISION),
        "H": round(bbox_h / image_height, MWGRS_COORDINATE_PRECISION),
    }


def extract_date_from_filename(filename: str) -> Optional[datetime.datetime]:
    """Extract a date from a filename using common patterns.

    Supports patterns like YYYYMMDD, YYYY-MM-DD, YYYY_MM_DD, IMG_YYYYMMDD_HHMM, etc.
    Returns a naive datetime or None if no pattern matches.
    """
    if not filename:
        return None
    # Strip directory and extension
    basename = os.path.splitext(os.path.basename(filename))[0]
    # Try various patterns in order of specificity
    patterns = [
        # YYYYMMDD_HHMMSS or YYYYMMDD-HHMMSS
        (r"(\d{4})[\-_]?(\d{2})[\-_]?(\d{2})[\-_](\d{2})[\-_]?(\d{2})[\-_]?(\d{2})",
         lambda m: datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                     int(m.group(4)), int(m.group(5)), int(m.group(6)))),
        # YYYYMMDD_HHMM (no seconds)
        (r"(\d{4})[\-_]?(\d{2})[\-_]?(\d{2})[\-_](\d{2})[\-_]?(\d{2})(?!\d)",
         lambda m: datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                     int(m.group(4)), int(m.group(5)))),
        # YYYY-MM-DD or YYYY_MM_DD or YYYYMMDD
        (r"(\d{4})[\-_]?(\d{2})[\-_]?(\d{2})",
         lambda m: datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    ]
    for pattern, builder in patterns:
        match = re.search(pattern, basename)
        if match:
            try:
                dt = builder(match)
                # Basic sanity check
                if 1900 <= dt.year <= 2100 and 1 <= dt.month <= 12 and 1 <= dt.day <= 31:
                    return dt
            except (ValueError, OverflowError):
                continue
    return None


def _parse_datetime_str(date_str: str) -> Optional[datetime.datetime]:
    """Parse a datetime string tolerantly, returning a naive datetime or None."""
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    if not date_str:
        return None

    # Try common ISO 8601 formats
    for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Fallback: strip timezone offsets and try fromisoformat
    try:
        clean_str = date_str.replace("Z", "")
        clean_str = re.sub(r"[+-]\d{2}:?\d{2}$", "", clean_str)
        return datetime.datetime.fromisoformat(clean_str)
    except (ValueError, AttributeError):
        return None


def select_oldest_date_from_asset(asset: Dict[str, Any], log_file: str = DEFAULT_LOG_FILE) -> Optional[datetime.datetime]:
    """Select the oldest (earliest) date from an asset's metadata fields.

    Priority order:
      1. exifInfo.dateTimeOriginal
      2. exifInfo.dateTimeCreated (CreateDate)
      3. exifInfo.modifyDate
      4. fileCreatedAt
      5. fileModifiedAt
      6. Fallback: date from filename (originalPath / originalFileName)

    Returns a naive datetime (timezone stripped) or None.
    """
    details = asset if "exifInfo" in asset else {}
    exif = details.get("exifInfo", {}) or {}

    candidates: List[Tuple[str, Optional[str]]] = [
        ("exifInfo.dateTimeOriginal", exif.get("dateTimeOriginal")),
        ("exifInfo.dateTimeCreated", exif.get("dateTimeCreated")),
        ("exifInfo.modifyDate", exif.get("modifyDate")),
        ("fileCreatedAt", asset.get("fileCreatedAt") or details.get("fileCreatedAt")),
        ("fileModifiedAt", asset.get("fileModifiedAt") or details.get("fileModifiedAt")),
    ]

    valid_dates: List[Tuple[str, datetime.datetime]] = []
    for source_name, raw_value in candidates:
        if raw_value:
            parsed = _parse_datetime_str(str(raw_value))
            if parsed:
                valid_dates.append((source_name, parsed))

    if valid_dates:
        source, oldest = min(valid_dates, key=lambda x: x[1])
        log(f"Selected date from {source}: {oldest.isoformat()}", log_file, LogLevel.DEBUG)
        return oldest

    # Fallback: extract date from filename
    original_path = asset.get("originalPath") or details.get("originalPath") or ""
    original_filename = asset.get("originalFileName") or details.get("originalFileName") or ""
    filename = original_filename or os.path.basename(original_path)
    if filename:
        dt = extract_date_from_filename(filename)
        if dt:
            log(f"Selected date from filename '{filename}': {dt.isoformat()}", log_file, LogLevel.DEBUG)
            return dt

    return None


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
            # Sortiere Namen alphabetisch für konsistente Reihenfolge
            people_sorted = sorted(people)
            val = ",".join(people_sorted)
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

    # 4. TIME SYNC (deterministic oldest-date selection and broad timestamp writing)
    if "time" in active_modes:
        # Combine asset-level and detail-level data for select_oldest_date_from_asset
        combined = {**asset}
        combined["exifInfo"] = exif
        if "fileCreatedAt" not in combined and "fileCreatedAt" in details:
            combined["fileCreatedAt"] = details["fileCreatedAt"]
        if "fileModifiedAt" not in combined and "fileModifiedAt" in details:
            combined["fileModifiedAt"] = details["fileModifiedAt"]
        if "originalPath" not in combined and "originalPath" in details:
            combined["originalPath"] = details["originalPath"]
        if "originalFileName" not in combined and "originalFileName" in details:
            combined["originalFileName"] = details["originalFileName"]

        parsed_date = select_oldest_date_from_asset(combined)

        if parsed_date:
            # Format to EXIF: YYYY:MM:DD HH:MM:SS (no timezone)
            clean_date = parsed_date.strftime("%Y:%m:%d %H:%M:%S")
            iso_date = parsed_date.strftime("%Y-%m-%d")
            iso_time = parsed_date.strftime("%H:%M:%S")
            iso_datetime = parsed_date.strftime("%Y-%m-%dT%H:%M:%S")
            args.extend([
                f"-AllDates={clean_date}",
                f"-XMP:CreateDate={clean_date}",
                f"-XMP:ModifyDate={clean_date}",
                f"-XMP:MetadataDate={clean_date}",
                f"-IPTC:DateCreated={iso_date}",
                f"-IPTC:TimeCreated={iso_time}",
                f"-QuickTime:CreateDate={iso_datetime}",
                f"-QuickTime:ModifyDate={iso_datetime}",
                f"-FileCreateDate={iso_datetime}",
                f"-FileModifyDate={iso_datetime}",
                f"-XMP-photoshop:DateCreated={iso_date}",
            ])
            changes.append("Time")

    # 5. RATING & FAVORITE SYNC (independent tracking)
    if "rating" in active_modes:
        # Star rating: from exifInfo.rating or asset.rating, fallback favorite → 5
        star_rating = exif.get("rating")
        if star_rating is None:
            star_rating = asset.get("rating")
        is_favorite = asset.get("isFavorite", False)

        # === TEMPORARY DEBUG - Remove after testing ===
        #orig_path = asset.get("originalPath", "unknown")
        #exif_rating = exif.get("rating")
        #asset_rating = asset.get("rating")
        #log(f"[RATING-DEBUG] File: {orig_path}", log_file, LogLevel.INFO)
        #log(f"[RATING-DEBUG]   exif.rating={exif_rating}, asset.rating={asset_rating}, isFavorite={is_favorite}", log_file, LogLevel.INFO)
        #if star_rating is None:
            #log(f"[RATING-DEBUG]   → star_rating=None, will calculate below", log_file, LogLevel.INFO)
        #else:
            #log(f"[RATING-DEBUG]   → star_rating={star_rating}", log_file, LogLevel.INFO)
        # === END DEBUG ===


        if star_rating is not None:
            star_rating = int(star_rating)
        elif is_favorite:
            star_rating = 5
        else:
            star_rating = 0

        rating_percent = star_rating * 20
        args.extend([
            f"-XMP:Rating={star_rating}",
            f"-MicrosoftPhoto:Rating={star_rating}",
            f"-Rating={star_rating}",
            f"-RatingPercent={rating_percent}",
        ])

        # Favorite: only SET the label when favorite
        # Note: We don't delete Label when not favorite because:
        # 1. ExifTool might not support deletion for all file types
        # 2. Label can be used for other purposes (color coding, etc.)
        # 3. This prevents update loops when Label can't be removed
        if is_favorite:
            args.append("-XMP:Label=Favorite")
            changes.append("Label")
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

    # 7. FACE COORDINATES SYNC (MWG-RS regions)
    if "face-coordinates" in active_modes:
        people_data = details.get("people", [])
        region_found = False
        
        region_list = [] # For the virtual comparison tag
        for person in people_data:
            name = person.get("name")
            if not name: continue
            for face in person.get("faces", []):
                area = convert_bbox_to_mwg_rs(
                    face.get("boundingBoxX1"), face.get("boundingBoxY1"),
                    face.get("boundingBoxX2"), face.get("boundingBoxY2"),
                    face.get("imageWidth"), face.get("imageHeight")
                )
                if area:
                    region_found = True
                    # Structure for virtual comparison
                    region_list.append({
                        "Area": {**area, "Unit": "normalized"},
                        "Name": name, "Type": "Face"
                    })

        if region_found:
            # Add -struct flag for proper structure handling
            args.append("-struct")
            
            # Clean existing regions first
            args.append("-XMP-mwg-rs:RegionInfo=")
            
            # Add real fields for ExifTool execution
            for region in region_list:
                name = region["Name"]
                area = region["Area"]
                args.extend([
                    f"-XMP-mwg-rs:RegionName+={name}",
                    "-XMP-mwg-rs:RegionType+=Face",
                    f"-XMP-mwg-rs:RegionAreaX+={area['X']}",
                    f"-XMP-mwg-rs:RegionAreaY+={area['Y']}",
                    f"-XMP-mwg-rs:RegionAreaW+={area['W']}",
                    f"-XMP-mwg-rs:RegionAreaH+={area['H']}",
                    "-XMP-mwg-rs:RegionAreaUnit+=normalized"
                ])
            
            first_f = next((p["faces"][0] for p in people_data if p.get("faces")), {})
            dims = {"W": first_f.get("imageWidth"), "H": first_f.get("imageHeight"), "Unit": "pixel"}
            args.extend([
                f"-XMP-mwg-rs:RegionAppliedToDimensionsW={dims['W']}",
                f"-XMP-mwg-rs:RegionAppliedToDimensionsH={dims['H']}",
                "-XMP-mwg-rs:RegionAppliedToDimensionsUnit=pixel"
            ])
            # The virtual tag: Used by extract_desired_values, but filtered out in execute()
            regions = {"AppliedToDimensions": dims, "RegionList": region_list}
            args.append(f"-RegionInfo={json.dumps(regions)}")
            changes.append("FaceCoordinates")

    return args, changes
