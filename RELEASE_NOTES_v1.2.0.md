# IMMICH ULTRA-SYNC Version 1.2.0 - Release Notes

## 🎭 Major Feature: Face Coordinate Sync (MWG-RS Regions)

**Release Date:** 2026-02-10  
**Issue:** #3 - Gesichtserkennung Koordinaten (mwg-rs)

### 🚀 What's New

Version 1.2.0 introduces **face coordinate synchronization** using the MWG-RS (Metadata Working Group Region Structure) standard. Face bounding boxes detected by Immich are now written as XMP region metadata, compatible with tools like Lightroom, digiKam, and other MWG-RS-aware applications.

### ✨ Key Features

#### 1. MWG-RS Region Writing
The `--face-coordinates` flag enables writing face regions to XMP metadata:
- Each detected face is stored as a region with `Type=Face` and `Name=<person name>`
- Pixel bounding boxes (X1/Y1/X2/Y2) are converted to normalized MWG-RS coordinates
- Image dimensions are stored in `AppliedToDimensions` for reference

#### 2. Coordinate Normalization
Immich provides pixel-based bounding boxes; MWG-RS uses normalized coordinates (0–1):
- **X** = Center X / Image Width
- **Y** = Center Y / Image Height
- **W** = Bbox Width / Image Width
- **H** = Bbox Height / Image Height

#### 3. Change Detection for Regions
The change detection system has been extended:
- Reads existing `RegionInfo` from files via ExifTool `-struct -json`
- Normalizes regions to canonical `Name:X,Y,W,H` representation for comparison
- Only updates when regions actually differ (reduces unnecessary writes)

#### 4. Opt-in Design
- `--face-coordinates` is completely opt-in and NOT included in `--all`
- Can be combined with any other sync mode
- Unnamed persons are automatically skipped

### 🔧 Usage

```bash
# Sync people names and face coordinates
python3 immich-ultra-sync.py --people --face-coordinates

# Sync all metadata plus face coordinates
python3 immich-ultra-sync.py --all --face-coordinates

# Preview what would be synced (dry-run)
python3 immich-ultra-sync.py --all --face-coordinates --dry-run --only-new
```

### 📝 MWG-RS Example Output

After running with `--face-coordinates`, ExifTool shows:
```
Region Info:
  Applied To Dimensions: W=4000, H=3000, Unit=pixel
  Region List:
    Area: X=0.05, Y=0.1, W=0.05, H=0.066667, Unit=normalized
    Name: Alice
    Type: Face
```

### 🧪 Testing

- **13 new unit tests** for face coordinate functionality
- Tests cover: coordinate conversion, edge cases, CLI flags, ExifTool arg generation, normalization
- All new tests pass (49 total)

### 🔒 Security & Quality

- **CodeQL Security Scan**: Clean
- **Code Review**: All feedback addressed
- **Input Validation**: Invalid bounding boxes and dimensions are safely skipped
- No new dependencies required

### 🛠️ Technical Details

#### New Functions
1. **`convert_bbox_to_mwg_rs()`**
   - Converts pixel bounding box to normalized MWG-RS coordinates
   - Validates input dimensions and bounding box validity
   - Returns `None` on invalid input for safe handling

#### Modified Functions
- **`build_exif_args()`**: New section #7 for face coordinate region generation
- **`get_current_exif_values()`**: Reads `RegionInfo` structs, handles dict values
- **`normalize_exif_value()`**: Canonical region comparison with sorted names and rounded coordinates
- **`create_arg_parser()`**: New `--face-coordinates` CLI flag
- **`parse_cli_args()`**: Adds `face-coordinates` mode when flag is set

#### New Constants
- `MWGRS_COORDINATE_PRECISION = 6` - Decimal places for writing region coordinates
- `MWGRS_COMPARE_PRECISION = 4` - Decimal places for comparison (avoids float drift)

### 📚 Documentation

- **README.md**: Updated with face coordinates section and usage examples
- **CHANGELOG.md**: Complete change log for version 1.2.0
- **VERSION**: Updated to 1.2.0
- **immich-sync.conf.example**: Updated with album cache settings
- **doc/de/immich-metadata-sync.md**: Updated German technical documentation
- **doc/de/immich_exif_mapping.md**: Added MWG-RS field mapping entry

### 🔄 Backwards Compatibility

✅ **Fully backwards compatible**
- All existing features work as before
- `--face-coordinates` is entirely opt-in
- All existing tests pass
- No new dependencies required

### 💡 Upgrade Notes

No special upgrade steps required. Simply update to v1.2.0 and use `--face-coordinates` to enable face coordinate sync.

### 🔗 Links

- Issue: #3
- MWG Spec: https://www.metadataworkinggroup.org/specs/
- Immich API: https://api.immich.app/endpoints/faces
- ExifTool MWG: https://exiftool.org/TagNames/MWG.html
