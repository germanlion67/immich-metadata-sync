#!/usr/bin/env python3
"""
Integrationstest-Script für Immich-Metadaten-Sync.
Testet Feld-zu-Feld-Mapping durch Ausführen des Sync-Scripts und Prüfen mit ExifTool.
Setze Testwerte manuell in Immich, bevor du Tests ausführst.

Wie du es verwendest
Speichere die Datei: Als tests/test_metadata_sync.py im Projekt.
Mache es ausführbar: chmod +x tests/test_metadata_sync.py
Einzelnes Feld testen:
Setze Testwert in Immich (z.B. Person "TEST_PEOPLE").
Rufe auf: python3 tests/test_metadata_sync.py --field people --image /library/test_image.jpg
Alle Felder testen:
Setze alle Werte in Immich.
Rufe auf: python3 tests/test_metadata_sync.py --all --image /library/test_image.jpg
Echten Sync (nicht dry-run): Füge --no-dry-run hinzu, aber lösche vorher Metadaten aus dem Bild.
Logs: Schau in test_metadata_sync.log für Details.
"""

import argparse
import subprocess
import os
from pathlib import Path

# Projekt-Root ermitteln (angenommen, Script liegt in tests/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = PROJECT_ROOT / "script" / "immich-ultra-sync.py"

# Test-Konfiguration: Feld -> (Sync-Flag, ExifTool-Tags, Erwarteter Wert)
TESTS = {
    "people": ("--people", ["-XMP:Subject", "-IPTC:Keywords", "-XMP-iptcExt:PersonInImage"], "TEST_PEOPLE"),
    "gps": ("--gps", ["-GPSLatitude", "-GPSLongitude", "-GPSAltitude"], "12.345678"),  # Setze in Immich
    "caption": ("--caption", ["-XMP:Description", "-IPTC:Caption-Abstract"], "TEST_CAPTION"),
    "time": ("--time", ["-DateTimeOriginal"], "TEST_TIME"),  # Setze Datum in Immich
    "rating": ("--rating", ["-Rating"], "5"),  # Setze als Favorit
    "albums": ("--albums", ["-XMP-iptcExt:Event", "-XMP:HierarchicalSubject"], "TEST_ALBUM"),
}

DEFAULT_LOG_FILE = PROJECT_ROOT / "test_metadata_sync.log"

def log(message: str, log_file: Path = DEFAULT_LOG_FILE):
    """Einfache Logging-Funktion."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{ts}] {message}"
    print(msg)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def run_exiftool(tags: list, image_path: str) -> dict:
    """Führt ExifTool aus und extrahiert Werte."""
    results = {}
    for tag in tags:
        try:
            cmd = ["exiftool", tag, image_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
            output = result.stdout.strip()
            if output:
                # Wert extrahieren (z.B. "Subject: TEST_PEOPLE" -> "TEST_PEOPLE")
                parts = output.split(": ", 1)
                results[tag] = parts[1] if len(parts) > 1 else output
            else:
                results[tag] = "NOT_FOUND"
        except subprocess.CalledProcessError:
            results[tag] = "ERROR"
    return results

def test_field(field: str, image_path: str, dry_run: bool = True):
    """Testet ein einzelnes Feld."""
    if field not in TESTS:
        log(f"ERROR: Unbekanntes Feld '{field}'. Verfügbare: {list(TESTS.keys())}")
        return False
    
    flag, tags, expected = TESTS[field]
    log(f"Starte Test für Feld '{field}' mit Flag '{flag}' auf Bild '{image_path}' (dry_run={dry_run})")
    
    # 1. Sync ausführen
    cmd = ["python3", str(SYNC_SCRIPT), flag]
    if dry_run:
        cmd.append("--dry-run")
    log(f"Führe Sync aus: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        log(f"ERROR: Sync fehlgeschlagen: {result.stderr}")
        return False
    log("Sync erfolgreich.")
    
    # 2. Mit ExifTool prüfen
    values = run_exiftool(tags, image_path)
    log(f"ExifTool-Ergebnisse: {values}")
    
    # 3. Prüfen
    success = all(expected in str(value) for value in values.values() if value not in ["NOT_FOUND", "ERROR"])
    if success:
        log(f"SUCCESS: Feld '{field}' korrekt geschrieben.")
    else:
        log(f"FAIL: Feld '{field}' nicht gefunden. Erwartet: '{expected}', Gefunden: {values}")
    
    return success

def main():
    parser = argparse.ArgumentParser(description="Integrationstest für Immich-Metadaten-Sync pro Feld.")
    parser.add_argument("--field", choices=list(TESTS.keys()), help="Einzelnes Feld testen.")
    parser.add_argument("--all", action="store_true", help="Alle Felder testen.")
    parser.add_argument("--image", required=True, help="Pfad zum Test-Bild (z.B. /library/test_image.jpg).")
    parser.add_argument("--no-dry-run", action="store_true", help="Echten Sync ausführen (nicht dry-run).")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE, help="Log-Datei.")
    
    args = parser.parse_args()
    
    log(f"Starte Session. Bild: {args.image}, Dry-run: {not args.no_dry_run}", args.log_file)
    
    if args.field:
        test_field(args.field, args.image, dry_run=not args.no_dry_run)
    elif args.all:
        for field in TESTS:
            test_field(field, args.image, dry_run=not args.no_dry_run)
            log("-" * 50, args.log_file)
    else:
        parser.error("Verwende --field oder --all.")
    
    log("Session beendet.", args.log_file)

if __name__ == "__main__":
    main()
