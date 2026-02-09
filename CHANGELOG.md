# Changelog

All notable changes to IMMICH ULTRA-SYNC will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
