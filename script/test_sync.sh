#!/bin/bash

# Farben für bessere Lesbarkeit
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Statistik-Variablen
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Test-Ergebnis Funktion
test_result() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ PASS${NC}: $2"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}❌ FAIL${NC}: $2"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

# Header Funktion
print_header() {
    echo ""
    echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  $1${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Section Funktion
print_section() {
    echo ""
    echo -e "${BOLD}${BLUE}━━━ $1 ━━━${NC}"
    echo ""
}

# Speichere Logs
TEST_LOG="/tmp/test_sync_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$TEST_LOG") 2>&1

print_header "IMMICH METADATA SYNC - COMPREHENSIVE TEST SUITE"
echo "Test Log: $TEST_LOG"
echo "Started: $(date)"

# ============================================================================
# PHASE 0: ENVIRONMENT CHECK
# ============================================================================
print_section "Phase 0: Environment Check"

echo "Checking environment variables..."
[ -n "$IMMICH_INSTANCE_URL" ] && echo "  ✓ IMMICH_INSTANCE_URL: $IMMICH_INSTANCE_URL" || echo "  ✗ IMMICH_INSTANCE_URL not set"
[ -n "$IMMICH_API_KEY" ] && echo "  ✓ IMMICH_API_KEY: ${IMMICH_API_KEY:0:10}..." || echo "  ✗ IMMICH_API_KEY not set"

echo ""
echo "Checking required files..."
[ -f "exif.py" ] && echo "  ✓ exif.py exists" || { echo "  ✗ exif.py not found"; exit 1; }
[ -f "immich-ultra-sync.py" ] && echo "  ✓ immich-ultra-sync.py exists" || { echo "  ✗ immich-ultra-sync.py not found"; exit 1; }

echo ""
echo "Checking ExifTool..."
EXIFTOOL_VERSION=$(exiftool -ver 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "  ✓ ExifTool version: $EXIFTOOL_VERSION"
else
    echo "  ✗ ExifTool not found"
    exit 1
fi

# ============================================================================
# PHASE 1: CODE VALIDATION
# ============================================================================
print_section "Phase 1: Code Validation"

echo "1.1 Checking for XMP:Favorite references..."
FAVORITE_COUNT=$(grep -c "XMP:Favorite" exif.py 2>/dev/null || echo "0")
if [ "$FAVORITE_COUNT" -eq 0 ]; then
    test_result 0 "XMP:Favorite removed from code"
else
    test_result 1 "XMP:Favorite still present ($FAVORITE_COUNT occurrences)"
    echo "  Found at:"
    grep -n "XMP:Favorite" exif.py | head -5
fi

echo ""
echo "1.2 Checking XMP:Label in tags_to_read..."
if grep -q '"XMP:Label"' exif.py; then
    test_result 0 "XMP:Label present in tags_to_read"
else
    test_result 1 "XMP:Label missing in tags_to_read"
fi

echo ""
echo "1.3 Checking Label write/delete logic..."
if grep -A3 "if is_favorite:" exif.py | grep -q "else:"; then
    test_result 0 "Label has else-block for deletion"
else
    test_result 1 "Label missing else-block"
fi

echo ""
echo "1.4 Python syntax check..."
python3 -m py_compile exif.py immich-ultra-sync.py 2>&1
if [ $? -eq 0 ]; then
    test_result 0 "Python syntax valid"
else
    test_result 1 "Python syntax errors found"
fi

echo ""
echo "1.5 Checking --only-new logic..."
if grep -q "if only_new and current_values:" immich-ultra-sync.py; then
    test_result 1 "Incorrect --only-new pre-check still present"
else
    test_result 0 "Incorrect --only-new pre-check removed"
fi

# ============================================================================
# PHASE 2: IMMICH API CHECK
# ============================================================================
print_section "Phase 2: Immich API Status"

echo "2.1 Testing API connection..."
API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$IMMICH_INSTANCE_URL/api/server-info/ping" -H "x-api-key: $IMMICH_API_KEY")
if [ "$API_RESPONSE" = "200" ]; then
    test_result 0 "API connection successful"
else
    test_result 1 "API connection failed (HTTP $API_RESPONSE)"
fi

echo ""
echo "2.2 Fetching asset information..."
python3 << 'EOFPYTHON'
import os, requests, json

url = os.environ.get('IMMICH_INSTANCE_URL')
api_key = os.environ.get('IMMICH_API_KEY')

if not url or not api_key:
    print("  ⚠️  API credentials not set, skipping")
    exit(0)

try:
    response = requests.get(f"{url}/api/assets", headers={'x-api-key': api_key}, params={'take': 1000}, timeout=10)
    
    if response.status_code == 200:
        assets = response.json()
        print(f"  Total assets: {len(assets)}")
        
        # Count favorites
        favorites = [a for a in assets if a.get('isFavorite')]
        print(f"  Favorites: {len(favorites)}")
        
        # Show test files
        test_files = ['IMG-20250614-WA0007', 'image1118', 'P1040360']
        print("\n  Test files status:")
        for search in test_files:
            found = False
            for asset in assets:
                path = asset.get('originalPath', '')
                if search in path:
                    filename = path.split('/')[-1]
                    is_fav = asset.get('isFavorite', False)
                    rating = asset.get('rating', 'None')
                    exif_rating = asset.get('exifInfo', {}).get('rating', 'None')
                    print(f"    {filename:40s} isFavorite={is_fav:5s} rating={rating} exifRating={exif_rating}")
                    found = True
                    break
            if not found:
                print(f"    {search:40s} NOT FOUND")
    else:
        print(f"  ⚠️  API error: {response.status_code}")
except Exception as e:
    print(f"  ⚠️  API request failed: {e}")
EOFPYTHON

# ============================================================================
# PHASE 3: INITIAL EXIF STATE
# ============================================================================
print_section "Phase 3: Initial EXIF State"

TEST_FILES=(
    "/library/admin/2026/2026-02/IMG-20250614-WA0007.jpg"
    "/library/admin/2026/2026-02/image1118_20210714_103120.jpg"
    "/library/admin/2015/2015-09/P1040360.jpg"
    "/library/admin/2025/2025-06/20250614_113931.jpg"
)

echo "3.1 Checking EXIF values (Rating, Label, RatingPercent)..."
for file in "${TEST_FILES[@]}"; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        echo ""
        echo "  📄 $filename"
        
        # Main file
        rating=$(exiftool -s3 -XMP:Rating "$file" 2>/dev/null || echo "")
        label=$(exiftool -s3 -XMP:Label "$file" 2>/dev/null || echo "")
        percent=$(exiftool -s3 -RatingPercent "$file" 2>/dev/null || echo "")
        
        echo "     JPG: Rating=${rating:-none} Label=${label:-none} Percent=${percent:-none}"
        
        # Sidecar
        if [ -f "${file}.xmp" ]; then
            rating_xmp=$(exiftool -s3 -XMP:Rating "${file}.xmp" 2>/dev/null || echo "")
            label_xmp=$(exiftool -s3 -XMP:Label "${file}.xmp" 2>/dev/null || echo "")
            percent_xmp=$(exiftool -s3 -RatingPercent "${file}.xmp" 2>/dev/null || echo "")
            echo "     XMP: Rating=${rating_xmp:-none} Label=${label_xmp:-none} Percent=${percent_xmp:-none}"
        else
            echo "     XMP: (no sidecar)"
        fi
    fi
done

# ============================================================================
# PHASE 4: DRY-RUN TEST
# ============================================================================
print_section "Phase 4: Dry-Run Test"

echo "4.1 Running dry-run sync..."
DRY_OUTPUT=$(python3 immich-ultra-sync.py --rating --only-new --dry-run 2>&1)
echo "$DRY_OUTPUT" | grep -E "\[INFO\]|\[WARN\]|\[ERROR\]"

echo ""
echo "4.2 Analyzing dry-run results..."
DRY_SIMULATED=$(echo "$DRY_OUTPUT" | grep "FINISH:" | grep -oP 'Simulated:\K\d+' || echo "0")
DRY_SKIPPED=$(echo "$DRY_OUTPUT" | grep "FINISH:" | grep -oP 'Skipped:\K\d+' || echo "0")
echo "  Simulated updates: $DRY_SIMULATED"
echo "  Skipped files: $DRY_SKIPPED"

if [ "$DRY_SIMULATED" -gt 0 ]; then
    echo ""
    echo "  Files that would be updated:"
    echo "$DRY_OUTPUT" | grep "\[DRY\].*Would update" | sed 's/^/    /'
fi

# ============================================================================
# PHASE 5: FIRST SYNC
# ============================================================================
print_section "Phase 5: First Sync"

echo "5.1 Running first sync..."
SYNC1_OUTPUT=$(python3 immich-ultra-sync.py --rating --only-new 2>&1)
echo "$SYNC1_OUTPUT" | tail -20

echo ""
echo "5.2 Analyzing first sync results..."
SYNC1_UPDATED=$(echo "$SYNC1_OUTPUT" | grep "FINISH:" | grep -oP 'Updated:\K\d+' || echo "0")
SYNC1_SKIPPED=$(echo "$SYNC1_OUTPUT" | grep "FINISH:" | grep -oP 'Skipped:\K\d+' || echo "0")
SYNC1_ERRORS=$(echo "$SYNC1_OUTPUT" | grep "FINISH:" | grep -oP 'Errors:\K\d+' || echo "0")

echo "  Updated: $SYNC1_UPDATED"
echo "  Skipped: $SYNC1_SKIPPED"
echo "  Errors: $SYNC1_ERRORS"

test_result $([ "$SYNC1_ERRORS" -eq 0 ] && echo 0 || echo 1) "First sync completed without errors"

if [ "$SYNC1_UPDATED" -gt 0 ]; then
    echo ""
    echo "  Updated files:"
    echo "$SYNC1_OUTPUT" | grep "UPDATE:" | sed 's/^/    /'
fi

# ============================================================================
# PHASE 6: POST-SYNC EXIF VERIFICATION
# ============================================================================
print_section "Phase 6: Post-Sync EXIF Verification"

echo "6.1 Checking EXIF values after first sync..."
for file in "${TEST_FILES[@]}"; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        echo ""
        echo "  📄 $filename"
        
        rating=$(exiftool -s3 -XMP:Rating "$file" 2>/dev/null || echo "")
        label=$(exiftool -s3 -XMP:Label "$file" 2>/dev/null || echo "")
        percent=$(exiftool -s3 -RatingPercent "$file" 2>/dev/null || echo "")
        
        echo "     JPG: Rating=${rating:-none} Label=${label:-none} Percent=${percent:-none}"
        
        if [ -f "${file}.xmp" ]; then
            rating_xmp=$(exiftool -s3 -XMP:Rating "${file}.xmp" 2>/dev/null || echo "")
            label_xmp=$(exiftool -s3 -XMP:Label "${file}.xmp" 2>/dev/null || echo "")
            percent_xmp=$(exiftool -s3 -RatingPercent "${file}.xmp" 2>/dev/null || echo "")
            echo "     XMP: Rating=${rating_xmp:-none} Label=${label_xmp:-none} Percent=${percent_xmp:-none}"
        fi
    fi
done

# ============================================================================
# PHASE 7: SECOND SYNC (CRITICAL!)
# ============================================================================
print_section "Phase 7: Second Sync - Idempotency Test"

echo "7.1 Waiting 2 seconds before second sync..."
sleep 2

echo ""
echo "7.2 Running second sync (should skip all files)..."
SYNC2_OUTPUT=$(python3 immich-ultra-sync.py --rating --only-new 2>&1)
echo "$SYNC2_OUTPUT" | tail -20

echo ""
echo "7.3 Analyzing second sync results..."
SYNC2_UPDATED=$(echo "$SYNC2_OUTPUT" | grep "FINISH:" | grep -oP 'Updated:\K\d+' || echo "0")
SYNC2_SKIPPED=$(echo "$SYNC2_OUTPUT" | grep "FINISH:" | grep -oP 'Skipped:\K\d+' || echo "0")
SYNC2_TOTAL=$(echo "$SYNC2_OUTPUT" | grep "FINISH:" | grep -oP 'Total:\K\d+' || echo "0")

echo "  Updated: $SYNC2_UPDATED"
echo "  Skipped: $SYNC2_SKIPPED"
echo "  Total: $SYNC2_TOTAL"

# CRITICAL TEST
if [ "$SYNC2_UPDATED" -eq 0 ] && [ "$SYNC2_SKIPPED" -eq "$SYNC2_TOTAL" ]; then
    test_result 0 "Idempotency test PASSED (no updates on second sync)"
else
    test_result 1 "Idempotency test FAILED (files still being updated)"
    if [ "$SYNC2_UPDATED" -gt 0 ]; then
        echo ""
        echo "  ${YELLOW}⚠️  Files updated in second sync (should be 0):${NC}"
        echo "$SYNC2_OUTPUT" | grep "UPDATE:" | sed 's/^/    /'
    fi
fi

# ============================================================================
# PHASE 8: CHANGE DETECTION TEST
# ============================================================================
print_section "Phase 8: Change Detection Test"

echo "8.1 Testing Rating change detection..."
TEST_FILE="/library/admin/2025/2025-06/20250614_113931.jpg"

if [ -f "$TEST_FILE" ]; then
    echo "  Using test file: $(basename "$TEST_FILE")"
    
    # Get current rating
    CURRENT_RATING=$(exiftool -s3 -XMP:Rating "$TEST_FILE" 2>/dev/null || echo "0")
    echo "  Current rating: $CURRENT_RATING"
    
    # Manually change rating
    NEW_RATING=3
    echo "  Manually setting rating to $NEW_RATING..."
    exiftool -overwrite_original -XMP:Rating=$NEW_RATING "$TEST_FILE" > /dev/null 2>&1
    
    # Verify change
    CHANGED_RATING=$(exiftool -s3 -XMP:Rating "$TEST_FILE" 2>/dev/null || echo "0")
    echo "  Verified rating: $CHANGED_RATING"
    
    # Sync should detect the change
    echo ""
    echo "8.2 Running sync (should detect and fix rating)..."
    SYNC3_OUTPUT=$(python3 immich-ultra-sync.py --rating --only-new 2>&1)
    
    if echo "$SYNC3_OUTPUT" | grep -q "$(basename "$TEST_FILE")"; then
        test_result 0 "Change detection works (file detected and updated)"
        echo "$SYNC3_OUTPUT" | grep "$(basename "$TEST_FILE")"
    else
        test_result 1 "Change detection failed (file not updated)"
    fi
    
    # Verify it's back to original
    FINAL_RATING=$(exiftool -s3 -XMP:Rating "$TEST_FILE" 2>/dev/null || echo "0")
    echo "  Final rating: $FINAL_RATING"
else
    echo "  ⚠️  Test file not found, skipping change detection test"
fi

# ============================================================================
# PHASE 9: SIDECAR SYNC TEST
# ============================================================================
print_section "Phase 9: Sidecar Synchronization Test"

SIDECAR_FILES=(
    "/library/admin/2026/2026-02/image1118_20210714_103120.jpg"
    "/library/admin/2015/2015-09/P1040360.jpg"
)

echo "9.1 Checking sidecar synchronization..."
for file in "${SIDECAR_FILES[@]}"; do
    if [ -f "$file" ] && [ -f "${file}.xmp" ]; then
        filename=$(basename "$file")
        echo ""
        echo "  📄 $filename"
        
        # Compare JPG vs XMP values
        jpg_rating=$(exiftool -s3 -XMP:Rating "$file" 2>/dev/null || echo "")
        xmp_rating=$(exiftool -s3 -XMP:Rating "${file}.xmp" 2>/dev/null || echo "")
        
        jpg_label=$(exiftool -s3 -XMP:Label "$file" 2>/dev/null || echo "")
        xmp_label=$(exiftool -s3 -XMP:Label "${file}.xmp" 2>/dev/null || echo "")
        
        echo "     JPG Rating: $jpg_rating | XMP Rating: $xmp_rating"
        echo "     JPG Label: $jpg_label | XMP Label: $xmp_label"
        
        # Test if they match
        if [ "$jpg_rating" = "$xmp_rating" ] && [ "$jpg_label" = "$xmp_label" ]; then
            test_result 0 "Sidecar in sync for $filename"
        else
            test_result 1 "Sidecar NOT in sync for $filename"
        fi
    fi
done

# ============================================================================
# PHASE 10: PERFORMANCE METRICS
# ============================================================================
print_section "Phase 10: Performance Metrics"

echo "10.1 Running performance test..."
TIME_START=$(date +%s.%N)
PERF_OUTPUT=$(python3 immich-ultra-sync.py --rating --only-new 2>&1)
TIME_END=$(date +%s.%N)
DURATION=$(echo "$TIME_END - $TIME_START" | bc)

PERF_TOTAL=$(echo "$PERF_OUTPUT" | grep "FINISH:" | grep -oP 'Total:\K\d+' || echo "0")
PERF_UPDATED=$(echo "$PERF_OUTPUT" | grep "FINISH:" | grep -oP 'Updated:\K\d+' || echo "0")
PERF_SKIPPED=$(echo "$PERF_OUTPUT" | grep "FINISH:" | grep -oP 'Skipped:\K\d+' || echo "0")

echo "  Duration: ${DURATION}s"
echo "  Total files: $PERF_TOTAL"
echo "  Updated: $PERF_UPDATED"
echo "  Skipped: $PERF_SKIPPED"

if [ "$PERF_TOTAL" -gt 0 ]; then
    FILES_PER_SEC=$(echo "scale=2; $PERF_TOTAL / $DURATION" | bc)
    echo "  Throughput: ${FILES_PER_SEC} files/sec"
fi

# ============================================================================
# PHASE 11: FINAL SUMMARY
# ============================================================================
print_section "Final Summary"

echo -e "${BOLD}Test Statistics:${NC}"
echo "  Total tests: $TOTAL_TESTS"
echo -e "  ${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "  ${RED}Failed: $FAILED_TESTS${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo ""
    echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║  ✅ ALL TESTS PASSED - READY FOR PRODUCTION!              ║${NC}"
    echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    EXIT_CODE=0
else
    echo ""
    echo -e "${BOLD}${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${RED}║  ❌ SOME TESTS FAILED - REVIEW REQUIRED                    ║${NC}"
    echo -e "${BOLD}${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    EXIT_CODE=1
fi

echo ""
echo "Full log saved to: $TEST_LOG"
echo "Completed: $(date)"

exit $EXIT_CODE
