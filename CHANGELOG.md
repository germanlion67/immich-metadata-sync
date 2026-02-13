# Changelog

All notable changes to IMMICH ULTRA-SYNC will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-02-13

### Added
- **Flask web interface** for sync management
  - Simple web UI to trigger sync operations
  - Real-time status monitoring with auto-refresh
  - Configurable sync options through web interface (dry-run, only-new, albums, face-coordinates)
  - Live log viewing and sync history
  - Health check endpoint for monitoring
  - Run with `python3 web_interface.py` (access at http://localhost:5000)
- **CONTRIBUTING.md** file with contribution guidelines for the community
  - Development setup instructions
  - Code style guidelines
  - Testing requirements
  - Pull request process documentation
- **Consolidated runbook.md** with both English and German versions
  - Uses collapsible sections for easy navigation
  - Maintains all original content from both language versions
  - Improved organization and readability

### Changed
- Updated `requirements.txt` to include Flask dependency (flask>=3.0.0)
- Documentation improvements across multiple files

### Technical Details
- Web interface is fully backward compatible - CLI usage remains unchanged
- Flask app runs on port 5000 by default (configurable via `FLASK_PORT` environment variable)
- Web interface supports all major sync options available in CLI
- Security: Web interface includes basic validation and error handling

## [1.4.0] - 2026-02-12

### Added
- Support for `.env` and JSON configuration files via `--config` (alongside existing INI support)
- Optional structured JSON log output via `IMMICH_LOG_FORMAT=json` or `IMMICH_STRUCTURED_LOGS=true`, including contextual metrics

### Notes
- Closes Issue #13: Code- und Wartbarkeits-Optimierungen (refactoring, tests/CI, extended logging, flexible configuration)
- Version 1.3 was used in documentation; semantic versioning continues with 1.4.0 for the feature-complete release.

## [1.3.0] - 2026-02-11

### Notes
- Documentation-only version marker (no code changes; aligned documentation with v1.3 label)

## [1.2.0] - 2026-02-10

### Added
- **Face coordinate sync (MWG-RS regions):**
  - New `--face-coordinates` CLI flag to write face bounding boxes as MWG-RS XMP regions
  - `convert_bbox_to_mwg_rs()` function converts pixel bounding box (X1/Y1/X2/Y2) to normalized MWG-RS center/size coordinates
  - Writes `RegionInfo` struct via ExifTool `-struct` mode, compatible with Lightroom, digiKam, and other MWG-RS-aware tools
  - Supports multiple faces per image, each with person name and area
  - Change detection for MWG-RS regions using canonical name:coordinates normalization
  - `MWGRS_COORDINATE_PRECISION` (6 decimals) for writing, `MWGRS_COMPARE_PRECISION` (4 decimals) for comparison
- **New CLI flag:** `--face-coordinates` to enable face coordinate sync (opt-in, not included in `--all`)
- **13 new unit tests** for face coordinate functionality

### Changed
- Extended `build_exif_args()` with MWG-RS region generation from Immich face data
- Extended `get_current_exif_values()` to read `RegionInfo` structs (dict handling)
- Extended `normalize_exif_value()` with canonical region comparison logic
- Updated `immich-sync.conf.example` with album cache TTL settings

### Technical Details
- Face data is read from `details["people"][].faces[]` in the existing asset detail response (no additional API calls needed)
- MWG-RS regions use `Unit=normalized` for area and `Unit=pixel` for AppliedToDimensions
- The `-struct` flag is added to ExifTool args only when face coordinates are being written
- Backward compatible: existing functionality unchanged, `--face-coordinates` is entirely opt-in

## [1.1.0] - 2026-02-09

### Added
- **Persistent album cache with TTL and locking:**
  - Album data is now cached on disk (`.immich_album_cache.json`) to avoid repeated API calls
  - Configurable cache TTL via `IMMICH_ALBUM_CACHE_TTL` environment variable (default: 24 hours)
  - Stale cache fallback via `IMMICH_ALBUM_CACHE_MAX_STALE` (default: 7 days) when API fetch fails
  - Cross-platform file locking (fcntl on POSIX, msvcrt on Windows) to prevent cache corruption
  - Atomic writes using tempfile + os.replace for cache safety
  - Cache file permissions set to 0o600 (owner read/write only) for security
- **New CLI flag:** `--clear-album-cache` to force fresh fetch from API, ignoring cache
- **Extended XMP metadata fields for better interoperability:**
  - `XMP-iptcExt:PersonInImage` for IPTC Extension standard compliance (people tagging)
  - `XMP:CreateDate` for XMP standard date field
  - `XMP-photoshop:DateCreated` for Adobe Photoshop compatibility
- **Improved change detection** to include new metadata fields

### Changed
- Extended people sync to write IPTC Extension PersonInImage field
- Extended time sync to write XMP and Photoshop date fields
- Updated documentation to reflect new metadata fields and album cache behavior
- Album sync now uses persistent cache for improved performance on repeat runs

### Technical Details
- No API changes required - all changes are in ExifTool argument generation
- Backward compatible - existing functionality unchanged
- Change detection automatically handles new fields with `--only-new` flag
- Album cache uses only Python standard library (no new dependencies)
- Comprehensive unit tests for cache functionality included

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
