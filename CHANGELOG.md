# Changelog

All notable changes to IMMICH ULTRA-SYNC will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-02-05

### Added
- **Comprehensive change detection** for all sync modes (not just rating)
- `get_current_exif_values()` function to read current EXIF values from files using JSON parsing
- `extract_desired_values()` function to extract tag-value pairs from ExifTool arguments
- `normalize_exif_value()` function to normalize EXIF values for accurate comparison across different formats
- `values_need_update()` function to intelligently compare current vs desired metadata values
- Support for format normalization:
  - GPS coordinates (handles various formats like "51 deg 30' 15.00\" N" and "51.504167")
  - DateTime fields (normalizes different date/time formats and separators)
  - Altitude values (extracts numeric values with/without units)
  - Rating values (extracts numeric ratings)

### Changed
- **Extended `--only-new` flag** to check all metadata types, not just rating
  - Now checks: People (XMP:Subject, IPTC:Keywords), GPS (Lat/Lon/Alt), Caption (Description), Time (DateTimeOriginal, CreateDate), and Rating
- Replaced old rating-only check with comprehensive metadata comparison
- Changed log message format: "UPDATE:" prefix for files being modified, "SKIP:" prefix for unchanged files
- Improved EXIF reading to use JSON output format for reliable tag-value pairing (prevents misalignment issues)
- Fixed regex patterns for GPS/altitude extraction to prevent matching incomplete numbers

### Fixed
- Log message language consistency (changed from German "Keine Änderungen nötig" to English "No changes needed")
- Regex pattern vulnerability for GPS coordinate and altitude extraction

### Performance
- **Significantly faster** repeated synchronizations by avoiding unnecessary file writes
- Reduced disk I/O operations when metadata hasn't changed
- Less wear on storage devices

### Testing
- Added 9 comprehensive unit tests for change detection functionality
- All tests pass (15 total: 6 existing + 9 new)
- Tests cover: value extraction, normalization, comparison logic

### Security
- CodeQL security analysis: 0 alerts found
- Improved input validation for EXIF value extraction

## Notes
This is the first official release implementing issue #14: "Änderungsdetektion für ExifTool-Sync in immich-ultra-sync.py integrieren"

The change detection feature provides significant performance improvements and reduces unnecessary disk writes, making the script more efficient for repeated synchronizations.
