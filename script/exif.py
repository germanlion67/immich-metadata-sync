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
        tags_to_read.extend(["DateTimeOriginal", "CreateDate", "DateCreated"])  # ← FIX: DateCreated statt XMP-photoshop
    if "rating" in active_modes:
        tags_to_read.extend(["Rating"])  # ← FIX: Removed MicrosoftPhoto
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

    # 7. FACE COORDINATES SYNC (MWG-RS regions)
    if "face-coordinates" in active_modes:
        people_data = details.get("people", [])
        region_found = False
        
        # Clean existing regions first
        args.append("-XMP-mwg-rs:RegionInfo=")
        
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
                    # Real fields for ExifTool execution
                    args.extend([
                        f"-XMP-mwg-rs:RegionName+={name}",
                        "-XMP-mwg-rs:RegionType+=Face",
                        f"-XMP-mwg-rs:RegionAreaX+={area['X']}",
                        f"-XMP-mwg-rs:RegionAreaY+={area['Y']}",
                        f"-XMP-mwg-rs:RegionAreaW+={area['W']}",
                        f"-XMP-mwg-rs:RegionAreaH+={area['H']}",
                        "-XMP-mwg-rs:RegionAreaUnit+=normalized"
                    ])
                    # Structure for virtual comparison
                    region_list.append({
                        "Area": {**area, "Unit": "normalized"},
                        "Name": name, "Type": "Face"
                    })

        if region_found:
            first_f = next((p["faces"][0] for p in people_data if p.get("faces")), {})
            dims = {"W": first_f.get("imageWidth"), "H": first_f.get("imageHeight"), "Unit": "pixel"}
            args.extend([
                f"-XMP-mwg-rs:RegionAppliedToDimensionsW={dims['W']}",
                f"-XMP-mwg-rs:RegionAppliedToDimensionsH={dims['H']}",
                "-XMP-mwg-rs:RegionAppliedToDimensionsUnit=pixel"
            ])
            # The virtual tag: Used by extract_desired_values, but filtered out in execute()
            regions = {"AppliedToDimensions": dims, "RegionList": region_list}
            args.append(f"-XMP-mwg-rs:RegionInfo={json.dumps(regions)}")
            changes.append("FaceCoordinates")

    return args, changes
