#!/usr/bin/env python3
"""
Integrationstest-Script für Immich-Metadaten-Sync.
Testet Feld-zu-Feld-Mapping durch Ausführen des Sync-Scripts und Prüfen mit ExifTool.
Setze Testwerte manuell in Immich, bevor du Tests ausführst.
Verwende --all für alle Felder, --field für einzeln.
"""

import argparse
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
import pytest


# Hardcoded Pfade für den Container
PROJECT_ROOT = Path("/app")
SYNC_SCRIPT = PROJECT_ROOT / "immich-ultra-sync.py"

# Konstanten für Normalisierung
GPS_COORDINATE_PRECISION = 6
GPS_ALTITUDE_PRECISION = 1

# Test-Konfiguration: Feld -> (Sync-Flag, ExifTool-Tags, Erwarteter Wert)
TESTS = {
    "people": ("--people", ["-XMP:Subject", "-IPTC:Keywords", "-XMP-iptcExt:PersonInImage"], "TEST_PEOPLE"),
    "gps": ("--gps", ["-GPSLatitude", "-GPSLongitude", "-GPSAltitude"], "51.14221"),  # Passe an
    "caption": ("--caption", ["-XMP:Description", "-IPTC:Caption-Abstract"], "TEST_CAPTION"),
    "time": ("--time", ["-DateTimeOriginal"], "2024:01:15 10:30:45"),
    "rating": ("--rating", ["-Rating"], "5"),
    "albums": ("--albums", ["-EXIF:UserComment"], "TEST_ALBUM"),  # Geändert für Windows Kommentare
}

DEFAULT_LOG_FILE = PROJECT_ROOT / "test_metadata_sync.log"

def log(message: str, log_file: Path = DEFAULT_LOG_FILE):
    """Einfache Logging-Funktion."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{ts}] {message}"
    print(msg)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def dms_to_decimal(dms: str) -> float:
    """Konvertiert DMS in Dezimalgrad."""
    match = re.match(r"(\d+) deg (\d+)' ([\d.]+)\"", dms)
    if match:
        deg, min, sec = map(float, match.groups())
        return deg + min / 60 + sec / 3600
    return float(dms)

def normalize_exif_value(value: str, tag: str) -> str:
    """Normalisiert EXIF-Werte für Vergleich."""
    if not value:
        return ""
    
    value = str(value).strip()
    
    # GPS-Koordinaten
    if tag in ["GPSLatitude", "GPSLongitude"]:
        try:
            decimal = dms_to_decimal(value)
            return str(round(decimal, GPS_COORDINATE_PRECISION))
        except ValueError:
            pass
    
    # GPS-Altitude
    if tag == "GPSAltitude":
        if value in ["0", "0 m"]:
            return "0"
        match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
        if match:
            try:
                return str(round(float(match.group(0)), GPS_ALTITUDE_PRECISION))
            except ValueError:
                return match.group(0)
    
    # Rating
    if tag == "Rating":
        match = re.search(r"\d", value)
        if match:
            return match.group(0)
    
    # DateTime
    if tag in ["DateTimeOriginal", "CreateDate"]:
        normalized = value.replace("-", ":").replace("T", " ")
        if len(normalized) >= 19:
            return normalized[:19]
    
    return value

def check_time_with_timezone_hint(expected: str, found: str) -> bool:
    """Prüft Time mit Zeitzonen-Hinweis für exakte +1h oder -1h Versatz."""
    try:
        fmt = "%Y:%m:%d %H:%M:%S"
        expected_dt = datetime.strptime(expected, fmt)
        found_dt = datetime.strptime(found, fmt)
        
        # Exakte Übereinstimmung
        if expected_dt == found_dt:
            return True
        
        # Prüfe exakt +1h oder -1h (Zeitzonen-Anpassung)
        if found_dt == expected_dt + timedelta(hours=1) or found_dt == expected_dt - timedelta(hours=1):
            direction = "+" if found_dt > expected_dt else "-"
            log(f"HINWEIS: Zeitzonen-Anpassung erkannt ({direction}1h: {expected} -> {found})")
            return True
    except ValueError:
        pass
    return False

def run_exiftool(tags: list, image_path: str) -> dict:
    """Führt ExifTool aus und extrahiert/normalisiert Werte."""
    results = {}
    for tag in tags:
        try:
            cmd = ["exiftool", tag, image_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
            output = result.stdout.strip()
            if output:
                parts = output.split(": ", 1)
                raw_value = parts[1] if len(parts) > 1 else output
                normalized_value = normalize_exif_value(raw_value, tag.lstrip('-'))
                results[tag] = normalized_value
            else:
                results[tag] = "NOT_FOUND"
        except subprocess.CalledProcessError:
            results[tag] = "ERROR"
    return results

def perform_field_sync_test(field: str, image_path: str, dry_run: bool = True, expected_override: str = None):
    """Testet ein einzelnes Feld. Gibt (success, found_value) zurück."""
    if field not in TESTS:
        log(f"ERROR: Unbekanntes Feld '{field}'. Verfügbare: {list(TESTS.keys())}")
        return False, ""
    
    flag, tags, default_expected = TESTS[field]
    expected = expected_override or default_expected
    log(f"Starte Test für Feld '{field}' mit Flag '{flag}' auf Bild '{image_path}' (dry_run={dry_run}, erwartet='{expected}')")
    
    # 1. Sync ausführen
    cmd = ["python3", str(SYNC_SCRIPT), flag]
    if dry_run:
        cmd.append("--dry-run")
        log("WARN: Dry-run aktiviert – nichts wird geschrieben.")
    log(f"Führe Sync aus: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        log(f"ERROR: Sync fehlgeschlagen: {result.stderr}")
        return False, ""
    log("Sync erfolgreich.")
    
    # 2. Mit ExifTool prüfen
    values = run_exiftool(tags, image_path)
    log(f"ExifTool-Ergebnisse (normalisiert): {values}")
    
    # 3. Prüfen
    valid_values = [v for v in values.values() if v not in ["NOT_FOUND", "ERROR"]]
    found_value = valid_values[0] if valid_values else ""
    if field == "time":
        # Spezielle Prüfung für Time mit Zeitzonen-Hinweis
        success = any(check_time_with_timezone_hint(expected, v) for v in valid_values)
    else:
        success = len(valid_values) > 0 and any(expected in str(v) for v in valid_values)
    
    if success:
        log(f"SUCCESS: Feld '{field}' korrekt geschrieben.")
    else:
        log(f"FAIL: Feld '{field}' nicht gefunden. Erwartet: '{expected}', Gültige Werte: {valid_values}")
    
    return success, found_value

def main():
    parser = argparse.ArgumentParser(description="Integrationstest für Immich-Metadaten-Sync pro Feld.")
    parser.add_argument("--field", choices=list(TESTS.keys()), help="Einzelnes Feld testen.")
    parser.add_argument("--all", action="store_true", help="Alle Felder testen und Summary ausgeben.")
    parser.add_argument("--image", required=True, help="Pfad zum Test-Bild.")
    parser.add_argument("--no-dry-run", action="store_true", help="Echten Sync ausführen.")
    parser.add_argument("--expected", help="Erwarteten Wert überschreiben.")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE, help="Log-Datei.")
    
    args = parser.parse_args()
    
    log(f"Starte Session. Bild: {args.image}, Dry-run: {not args.no_dry_run}", args.log_file)
    
    if args.field:
        success, found_value = perform_field_sync_test(args.field, args.image, dry_run=not args.no_dry_run, expected_override=args.expected)
        status = f"PASS ({found_value})" if success else "FAIL"
        log(f"Test-Ergebnis: {status}", args.log_file)
    elif args.all:
        results = {}
        total = len(TESTS)
        passed = 0
        for field in TESTS:
            success, found_value = perform_field_sync_test(field, args.image, dry_run=not args.no_dry_run, expected_override=args.expected if field == args.field else None)
            results[field] = (success, found_value)
            if success:
                passed += 1
            log("-" * 50, args.log_file)
        log(f"SUMMARY: {passed} von {total} Tests erfolgreich.", args.log_file)
        for field, (success, found_value) in results.items():
            status = f"PASS ({found_value})" if success else "FAIL"
            log(f"  {field}: {status}", args.log_file)
        overall_success = passed == total
        log(f"Gesamt-Ergebnis: {'SUCCESS' if overall_success else 'FAIL'}", args.log_file)
    else:
        parser.error("Verwende --field oder --all.")
    
    log("Session beendet.", args.log_file)

if __name__ == "__main__":
    main()
