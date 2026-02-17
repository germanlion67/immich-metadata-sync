import sys
import os
import json
import tempfile
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PROJECT_ROOT / "script"

# Add script directory to path
sys.path.insert(0, str(SCRIPT_DIR))

# Import modules
import utils
import exif
import api

# Import main script functions
import importlib.util
spec = importlib.util.spec_from_file_location("immich_ultra_sync_main", SCRIPT_DIR / "immich-ultra-sync.py")
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load module from {SCRIPT_DIR / 'immich-ultra-sync.py'}")
main_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_module)


class ModuleLoaderMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a mock module that combines all submodules
        class CombinedModule:
            pass
        
        module = CombinedModule()
        # Copy attributes from utils (including private ones for testing)
        for attr in dir(utils):
            if not attr.startswith('__'):  # Copy private attributes too
                setattr(module, attr, getattr(utils, attr))
        # Copy attributes from exif
        for attr in dir(exif):
            if not attr.startswith('__'):
                setattr(module, attr, getattr(exif, attr))
        # Copy attributes from api
        for attr in dir(api):
            if not attr.startswith('__'):
                setattr(module, attr, getattr(api, attr))
        # Copy attributes from main module
        for attr in dir(main_module):
            if not attr.startswith('__'):
                setattr(module, attr, getattr(main_module, attr))
        
        cls.module = module


class BuildExifArgsTests(ModuleLoaderMixin):
    def test_caption_respects_max_length(self):
        long_caption = "a" * 2100
        asset = {"isFavorite": False}
        details = {"exifInfo": {"description": long_caption}}

        args, changes = self.module.build_exif_args(asset, details, ["caption"], caption_max_len=50)

        desc_arg = next(a for a in args if a.startswith("-XMP:Description="))
        value = desc_arg.split("=", 1)[1]
        self.assertEqual(len(value), 50)
        self.assertIn("Caption", changes)

    def test_caption_limit_has_minimum(self):
        asset = {"isFavorite": False}
        details = {"exifInfo": {"description": "abcd"}}

        args, _ = self.module.build_exif_args(asset, details, ["caption"], caption_max_len=0)

        desc_arg = next(a for a in args if a.startswith("-XMP:Description="))
        value = desc_arg.split("=", 1)[1]
        self.assertEqual(len(value), self.module.MIN_CAPTION_MAX_LEN)
        self.assertEqual(value, "abcd"[: self.module.MIN_CAPTION_MAX_LEN])

    def test_default_caption_limit_used(self):
        long_caption = "b" * 2101
        asset = {"isFavorite": False}
        details = {"exifInfo": {"description": long_caption}}

        args, _ = self.module.build_exif_args(asset, details, ["caption"])

        desc_arg = next(a for a in args if a.startswith("-XMP:Description="))
        value = desc_arg.split("=", 1)[1]
        self.assertEqual(len(value), self.module.DEFAULT_CAPTION_MAX_LEN)

    def test_people_and_rating_are_mapped(self):
        asset = {"isFavorite": True}
        details = {"people": [{"name": "Alice"}, {"name": "Bob"}], "exifInfo": {}}

        args, changes = self.module.build_exif_args(asset, details, ["people", "rating"])

        self.assertIn("People", changes)
        self.assertIn("-Rating=5", args)
        self.assertIn("-XMP:Subject=Alice,Bob", args)
        self.assertIn("-IPTC:Keywords=Alice,Bob", args)


class ChangeDetectionTests(ModuleLoaderMixin):
    def test_extract_desired_values(self):
        exif_args = [
            "-XMP:Subject=Alice,Bob",
            "-IPTC:Keywords=Alice,Bob",
            "-Rating=5",
            "-GPSLatitude=51.5",
            "-GPSLongitude=-0.1",
        ]
        
        desired = self.module.extract_desired_values(exif_args)
        
        self.assertEqual(desired["Subject"], "Alice,Bob")
        self.assertEqual(desired["Keywords"], "Alice,Bob")
        self.assertEqual(desired["Rating"], "5")
        self.assertEqual(desired["GPSLatitude"], "51.5")
        self.assertEqual(desired["GPSLongitude"], "-0.1")

    def test_normalize_exif_value_gps(self):
        # Test GPS coordinate normalization
        self.assertEqual(
            self.module.normalize_exif_value("51 deg 30' 15.00\" N", "GPSLatitude"),
            "51.0"
        )
        self.assertEqual(
            self.module.normalize_exif_value("51.504167", "GPSLatitude"),
            "51.504167"
        )
        self.assertEqual(
            self.module.normalize_exif_value("-0.127758", "GPSLongitude"),
            "-0.127758"
        )

    def test_normalize_exif_value_altitude(self):
        # Test altitude normalization
        self.assertEqual(
            self.module.normalize_exif_value("123.5", "GPSAltitude"),
            "123.5"
        )
        self.assertEqual(
            self.module.normalize_exif_value("0 m", "GPSAltitude"),
            "0"
        )
        self.assertEqual(
            self.module.normalize_exif_value("0", "GPSAltitude"),
            "0"
        )

    def test_normalize_exif_value_rating(self):
        # Test rating normalization
        self.assertEqual(self.module.normalize_exif_value("5", "Rating"), "5")
        self.assertEqual(self.module.normalize_exif_value("0", "Rating"), "0")

    def test_normalize_exif_value_datetime(self):
        # Test datetime normalization
        self.assertEqual(
            self.module.normalize_exif_value("2024:01:15 10:30:45", "DateTimeOriginal"),
            "2024:01:15 10:30:45"
        )
        self.assertEqual(
            self.module.normalize_exif_value("2024-01-15T10:30:45Z", "DateTimeOriginal"),
            "2024:01:15 10:30:45"
        )
        self.assertEqual(
            self.module.normalize_exif_value("2024-01-15 10:30:45", "CreateDate"),
            "2024:01:15 10:30:45"
        )
        # Test XMP:CreateDate normalization (same format as DateTimeOriginal/CreateDate)
        self.assertEqual(
            self.module.normalize_exif_value("2024:01:15 10:30:45", "XMP:CreateDate"),
            "2024:01:15 10:30:45"
        )
        self.assertEqual(
            self.module.normalize_exif_value("2024-01-15T10:30:45Z", "XMP:CreateDate"),
            "2024:01:15 10:30:45"
        )
        # Test XMP-photoshop:DateCreated normalization (ISO date format YYYY-MM-DD)
        self.assertEqual(
            self.module.normalize_exif_value("2024-01-15", "Photoshop:DateCreated"),
            "2024-01-15"
        )
        self.assertEqual(
            self.module.normalize_exif_value("2024:01:15", "Photoshop:DateCreated"),
            "2024-01-15"
        )



class ArgparseTests(ModuleLoaderMixin):
    def test_parse_all_sets_all_modes(self):
        parsed, modes = self.module.parse_cli_args(["--all"])
        self.assertTrue(parsed.all)
        # Note: --all does NOT include albums - albums must be explicitly enabled
        self.assertEqual(set(modes), {"people", "gps", "caption", "time", "rating"})

    def test_parse_requires_mode(self):
        with self.assertRaises(SystemExit):
            self.module.parse_cli_args([])
    
    def test_log_level_default(self):
        parsed, modes = self.module.parse_cli_args(["--all"])
        self.assertEqual(parsed.log_level, "INFO")
    
    def test_log_level_custom(self):
        parsed, modes = self.module.parse_cli_args(["--all", "--log-level", "DEBUG"])
        self.assertEqual(parsed.log_level, "DEBUG")
    
    def test_resume_flag(self):
        parsed, modes = self.module.parse_cli_args(["--all", "--resume"])
        self.assertTrue(parsed.resume)
    
    def test_export_stats_flag(self):
        parsed, modes = self.module.parse_cli_args(["--all", "--export-stats", "json"])
        self.assertEqual(parsed.export_stats, "json")
    
    def test_albums_flag(self):
        parsed, modes = self.module.parse_cli_args(["--albums"])
        self.assertTrue(parsed.albums)
        self.assertIn("albums", modes)
    
    def test_all_with_albums_flag(self):
        parsed, modes = self.module.parse_cli_args(["--all", "--albums"])
        self.assertTrue(parsed.all)
        self.assertTrue(parsed.albums)
        # --all gives us the basic 5 modes, plus albums is explicitly added
        self.assertEqual(set(modes), {"people", "gps", "caption", "time", "rating", "albums"})


class AlbumSyncTests(ModuleLoaderMixin):
    def test_build_asset_album_map(self):
        # Mock album data
        mock_albums = [
            {
                "albumName": "Summer 2024",
                "assets": [
                    {"id": "asset1"},
                    {"id": "asset2"}
                ]
            },
            {
                "albumName": "Vacation",
                "assets": [
                    {"id": "asset1"},
                    {"id": "asset3"}
                ]
            },
            {
                "albumName": "",  # Empty album name should be skipped
                "assets": [
                    {"id": "asset4"}
                ]
            },
            {
                # Missing albumName key (None) should be skipped
                "assets": [
                    {"id": "asset5"}
                ]
            }
        ]
        
        # Create a mock api_call function
        import unittest.mock as mock
        with mock.patch('api.api_call', return_value=mock_albums):
            album_map = self.module.build_asset_album_map({}, "http://test", "test.log")
        
        # asset1 should be in two albums
        self.assertEqual(len(album_map["asset1"]), 2)
        self.assertIn("Summer 2024", album_map["asset1"])
        self.assertIn("Vacation", album_map["asset1"])
        
        # asset2 should be in one album
        self.assertEqual(album_map["asset2"], ["Summer 2024"])
        
        # asset3 should be in one album
        self.assertEqual(album_map["asset3"], ["Vacation"])
        
        # asset4 should not be in the map (empty album name)
        self.assertNotIn("asset4", album_map)
        
        # asset5 should not be in the map (missing albumName key)
        self.assertNotIn("asset5", album_map)
    
    def test_build_exif_args_with_albums(self):
        asset = {"id": "test-asset-id", "isFavorite": False}
        details = {"exifInfo": {}}
        album_map = {
            "test-asset-id": ["Album1", "Album2", "Album3"]
        }
        
        args, changes = self.module.build_exif_args(
            asset, details, ["albums"], album_map=album_map
        )
        
        # Check that Albums is in changes
        self.assertIn("Albums", changes)
        
        # Check Event field (first album)
        event_arg = next((a for a in args if a.startswith("-XMP-iptcExt:Event=")), None)
        self.assertIsNotNone(event_arg)
        self.assertEqual(event_arg, "-XMP-iptcExt:Event=Album1")
        
        # Check HierarchicalSubject field (all albums)
        hierarchical_arg = next((a for a in args if a.startswith("-XMP:HierarchicalSubject=")), None)
        self.assertIsNotNone(hierarchical_arg)
        self.assertEqual(hierarchical_arg, "-XMP:HierarchicalSubject=Albums|Album1,Albums|Album2,Albums|Album3")
    
    def test_build_exif_args_without_albums(self):
        asset = {"id": "test-asset-id", "isFavorite": False}
        details = {"exifInfo": {}}
        album_map = {}  # Asset not in any albums
        
        args, changes = self.module.build_exif_args(
            asset, details, ["albums"], album_map=album_map
        )
        
        # No changes should be made if asset not in any albums
        self.assertNotIn("Albums", changes)
        self.assertEqual(args, [])


class RateLimiterTests(ModuleLoaderMixin):
    def test_rate_limiter_initialization(self):
        limiter = self.module.RateLimiter(calls_per_second=5.0)
        self.assertEqual(limiter.calls_per_second, 5.0)
        self.assertEqual(limiter.min_interval, 0.2)
    
    def test_rate_limiter_wait(self):
        import time
        limiter = self.module.RateLimiter(calls_per_second=10.0)
        start = time.time()
        limiter.wait()
        limiter.wait()
        elapsed = time.time() - start
        # Should have waited at least min_interval
        self.assertGreaterEqual(elapsed, 0.09)  # Allow some margin


class ExifToolHelperTests(ModuleLoaderMixin):
    def test_exiftool_helper_initialization(self):
        helper = self.module.ExifToolHelper()
        self.assertIsNone(helper.process)


class LogLevelTests(ModuleLoaderMixin):
    def test_log_level_enum(self):
        self.assertEqual(self.module.LogLevel.DEBUG.value, 10)
        self.assertEqual(self.module.LogLevel.INFO.value, 20)
        self.assertEqual(self.module.LogLevel.WARNING.value, 30)
        self.assertEqual(self.module.LogLevel.ERROR.value, 40)
    
    def test_set_log_level(self):
        import utils
        original = utils._LOG_LEVEL
        self.module.set_log_level("DEBUG")
        self.assertEqual(utils._LOG_LEVEL, self.module.LogLevel.DEBUG)
        self.module.set_log_level("ERROR")
        self.assertEqual(utils._LOG_LEVEL, self.module.LogLevel.ERROR)
        # Restore original
        utils._LOG_LEVEL = original


class AlbumCacheTests(ModuleLoaderMixin):
    def setUp(self):
        """Set up test environment with temporary directory."""
        import tempfile
        self.test_dir = tempfile.mkdtemp()
        self.original_cache_file = self.module.ALBUM_CACHE_FILE
        self.original_lock_file = self.module.ALBUM_CACHE_LOCK_FILE
        # Override cache paths to use test directory
        self.module.ALBUM_CACHE_FILE = f"{self.test_dir}/test_cache.json"
        self.module.ALBUM_CACHE_LOCK_FILE = f"{self.test_dir}/test_cache.lock"
    
    def tearDown(self):
        """Clean up test directory and restore original cache paths."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.module.ALBUM_CACHE_FILE = self.original_cache_file
        self.module.ALBUM_CACHE_LOCK_FILE = self.original_lock_file
    
    def test_save_and_load_cache(self):
        """Test saving and loading cache within TTL."""
        log_file = f"{self.test_dir}/test.log"
        
        # Create test album map
        test_map = {
            "asset1": ["Album A", "Album B"],
            "asset2": ["Album C"]
        }
        
        # Save cache
        result = self.module.save_album_cache(test_map, log_file)
        self.assertTrue(result)
        
        # Load cache with generous TTL
        loaded_map = self.module.load_album_cache(ttl=3600, log_file=log_file)
        self.assertIsNotNone(loaded_map)
        self.assertEqual(loaded_map, test_map)
    
    def test_load_cache_respects_ttl(self):
        """Test that cache is not loaded when TTL is exceeded."""
        log_file = f"{self.test_dir}/test.log"
        
        # Create and save test album map
        test_map = {"asset1": ["Album A"]}
        self.module.save_album_cache(test_map, log_file)
        
        # Try to load with TTL of 0 seconds (should fail)
        loaded_map = self.module.load_album_cache(ttl=0, log_file=log_file)
        self.assertIsNone(loaded_map)
    
    def test_load_cache_nonexistent(self):
        """Test that loading nonexistent cache returns None."""
        log_file = f"{self.test_dir}/test.log"
        loaded_map = self.module.load_album_cache(ttl=3600, log_file=log_file)
        self.assertIsNone(loaded_map)
    
    def test_clear_cache(self):
        """Test clearing the cache."""
        log_file = f"{self.test_dir}/test.log"
        
        # Create and save cache
        test_map = {"asset1": ["Album A"]}
        self.module.save_album_cache(test_map, log_file)
        
        # Clear cache
        result = self.module.clear_album_cache(log_file)
        self.assertTrue(result)
        
        # Verify cache is gone
        import os
        self.assertFalse(os.path.exists(self.module.get_album_cache_path()))
    
    def test_clear_cache_nonexistent(self):
        """Test clearing nonexistent cache."""
        log_file = f"{self.test_dir}/test.log"
        result = self.module.clear_album_cache(log_file)
        self.assertFalse(result)
    
    def test_stale_cache_within_max_stale(self):
        """Test loading stale cache within max_stale limit."""
        log_file = f"{self.test_dir}/test.log"
        
        # Create and save test album map
        test_map = {"asset1": ["Album A"]}
        self.module.save_album_cache(test_map, log_file)
        
        # Load as stale cache with generous max_stale
        loaded_map = self.module.load_stale_album_cache(max_stale=3600, log_file=log_file)
        self.assertIsNotNone(loaded_map)
        self.assertEqual(loaded_map, test_map)
    
    def test_stale_cache_exceeds_max_stale(self):
        """Test that stale cache is not loaded when exceeding max_stale."""
        log_file = f"{self.test_dir}/test.log"
        
        # Create and save test album map
        test_map = {"asset1": ["Album A"]}
        self.module.save_album_cache(test_map, log_file)
        
        # Try to load with max_stale of 0 (should fail)
        loaded_map = self.module.load_stale_album_cache(max_stale=0, log_file=log_file)
        self.assertIsNone(loaded_map)
    
    def test_lock_acquire_and_release(self):
        """Test that lock can be acquired and released."""
        lock_path = self.module.get_album_cache_lock_path()
        
        # Acquire lock
        lock_handle = self.module.acquire_lock(lock_path, timeout=5.0)
        self.assertIsNotNone(lock_handle)
        
        # Release lock
        self.module.release_lock(lock_handle)
        
        # Should be able to acquire again
        lock_handle2 = self.module.acquire_lock(lock_path, timeout=5.0)
        self.assertIsNotNone(lock_handle2)
        self.module.release_lock(lock_handle2)
    
    def test_cache_file_permissions(self):
        """Test that cache file has restrictive permissions on POSIX systems."""
        import os
        import stat
        log_file = f"{self.test_dir}/test.log"
        
        # Create and save cache
        test_map = {"asset1": ["Album A"]}
        self.module.save_album_cache(test_map, log_file)
        
        # Check permissions on POSIX systems
        cache_path = self.module.get_album_cache_path()
        if os.name == 'posix':
            file_stats = os.stat(cache_path)
            file_mode = stat.S_IMODE(file_stats.st_mode)
            # Should be 0o600 (read/write for owner only)
            self.assertEqual(file_mode, 0o600)
    
    def test_parse_clear_album_cache_flag(self):
        """Test that --clear-album-cache flag is parsed correctly."""
        parsed, modes = self.module.parse_cli_args(["--albums", "--clear-album-cache"])
        self.assertTrue(parsed.clear_album_cache)
        self.assertIn("albums", modes)


class ConfigLoaderTests(ModuleLoaderMixin):
    def test_load_config_missing_file(self):
        config = self.module.load_config("/nonexistent/file.conf")
        self.assertIn('IMMICH_INSTANCE_URL', config)
        self.assertEqual(config['IMMICH_INSTANCE_URL'], '')
        self.assertEqual(config['IMMICH_PHOTO_DIR'], self.module.DEFAULT_PHOTO_DIR)

    def test_load_config_env_file(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".env") as tmp:
            tmp.write("IMMICH_INSTANCE_URL=https://demo.invalid\n")
            tmp.write("IMMICH_API_KEY=abc123\n")
            tmp.flush()
            config = self.module.load_config(tmp.name)
            self.assertEqual(config["IMMICH_INSTANCE_URL"], "https://demo.invalid")
            self.assertEqual(config["IMMICH_API_KEY"], "abc123")

    def test_load_config_json_file(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as tmp:
            json.dump({"IMMICH_INSTANCE_URL": "https://json.invalid", "IMMICH_LOG_FILE": "test.log"}, tmp)
            tmp.flush()
            config = self.module.load_config(tmp.name)
            self.assertEqual(config["IMMICH_INSTANCE_URL"], "https://json.invalid")
            self.assertEqual(config["IMMICH_LOG_FILE"], "test.log")


class FaceCoordinatesTests(ModuleLoaderMixin):
    def test_convert_bbox_to_mwg_rs_basic(self):
        """Test basic bounding box to MWG-RS conversion."""
        result = self.module.convert_bbox_to_mwg_rs(100, 200, 300, 400, 4000, 3000)
        self.assertIsNotNone(result)
        # Center X = (100 + 200 / 2) / 4000 = 200 / 4000 = 0.05
        self.assertAlmostEqual(result["X"], 0.05, places=6)
        # Center Y = (200 + 200 / 2) / 3000 = 300 / 3000 = 0.1
        self.assertAlmostEqual(result["Y"], 0.1, places=6)
        # W = 200 / 4000 = 0.05
        self.assertAlmostEqual(result["W"], 0.05, places=6)
        # H = 200 / 3000 ≈ 0.066667
        self.assertAlmostEqual(result["H"], 0.066667, places=5)

    def test_convert_bbox_to_mwg_rs_full_image(self):
        """Test conversion covering the full image."""
        result = self.module.convert_bbox_to_mwg_rs(0, 0, 4000, 3000, 4000, 3000)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["X"], 0.5, places=6)
        self.assertAlmostEqual(result["Y"], 0.5, places=6)
        self.assertAlmostEqual(result["W"], 1.0, places=6)
        self.assertAlmostEqual(result["H"], 1.0, places=6)

    def test_convert_bbox_to_mwg_rs_invalid_dimensions(self):
        """Test conversion with invalid image dimensions."""
        self.assertIsNone(self.module.convert_bbox_to_mwg_rs(0, 0, 100, 100, 0, 0))
        self.assertIsNone(self.module.convert_bbox_to_mwg_rs(0, 0, 100, 100, -1, 100))

    def test_convert_bbox_to_mwg_rs_invalid_bbox(self):
        """Test conversion with invalid bounding box (x2 <= x1)."""
        self.assertIsNone(self.module.convert_bbox_to_mwg_rs(300, 200, 100, 400, 4000, 3000))
        self.assertIsNone(self.module.convert_bbox_to_mwg_rs(100, 400, 300, 200, 4000, 3000))

    def test_build_exif_args_face_coordinates(self):
        """Test that face coordinates generate MWG-RS region args."""
        import json
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {},
            "people": [
                {
                    "name": "Alice",
                    "faces": [
                        {
                            "boundingBoxX1": 100,
                            "boundingBoxY1": 200,
                            "boundingBoxX2": 300,
                            "boundingBoxY2": 400,
                            "imageWidth": 4000,
                            "imageHeight": 3000,
                        }
                    ],
                }
            ],
        }

        args, changes = self.module.build_exif_args(asset, details, ["face-coordinates"])

        self.assertIn("FaceCoordinates", changes)
        self.assertIn("-struct", args)
        region_arg = next((a for a in args if a.startswith("-RegionInfo=")), None)
        self.assertIsNotNone(region_arg)

        region_json = json.loads(region_arg.split("=", 1)[1])
        self.assertEqual(region_json["AppliedToDimensions"]["W"], 4000)
        self.assertEqual(region_json["AppliedToDimensions"]["H"], 3000)
        self.assertEqual(len(region_json["RegionList"]), 1)
        self.assertEqual(region_json["RegionList"][0]["Name"], "Alice")
        self.assertEqual(region_json["RegionList"][0]["Type"], "Face")

    def test_build_exif_args_face_coordinates_multiple_people(self):
        """Test MWG-RS with multiple people."""
        import json
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {},
            "people": [
                {
                    "name": "Alice",
                    "faces": [
                        {
                            "boundingBoxX1": 100,
                            "boundingBoxY1": 200,
                            "boundingBoxX2": 300,
                            "boundingBoxY2": 400,
                            "imageWidth": 4000,
                            "imageHeight": 3000,
                        }
                    ],
                },
                {
                    "name": "Bob",
                    "faces": [
                        {
                            "boundingBoxX1": 500,
                            "boundingBoxY1": 600,
                            "boundingBoxX2": 700,
                            "boundingBoxY2": 800,
                            "imageWidth": 4000,
                            "imageHeight": 3000,
                        }
                    ],
                },
            ],
        }

        args, changes = self.module.build_exif_args(asset, details, ["face-coordinates"])

        self.assertIn("FaceCoordinates", changes)
        region_arg = next(a for a in args if a.startswith("-RegionInfo="))
        region_json = json.loads(region_arg.split("=", 1)[1])
        self.assertEqual(len(region_json["RegionList"]), 2)
        names = [r["Name"] for r in region_json["RegionList"]]
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)

    def test_build_exif_args_face_coordinates_no_faces(self):
        """Test that no args are generated when people have no face data."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {},
            "people": [{"name": "Alice"}],  # No faces array
        }

        args, changes = self.module.build_exif_args(asset, details, ["face-coordinates"])
        self.assertNotIn("FaceCoordinates", changes)
        self.assertEqual(args, [])

    def test_build_exif_args_face_coordinates_unnamed_person(self):
        """Test that unnamed persons are skipped."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {},
            "people": [
                {
                    "name": "",
                    "faces": [
                        {
                            "boundingBoxX1": 100,
                            "boundingBoxY1": 200,
                            "boundingBoxX2": 300,
                            "boundingBoxY2": 400,
                            "imageWidth": 4000,
                            "imageHeight": 3000,
                        }
                    ],
                }
            ],
        }

        args, changes = self.module.build_exif_args(asset, details, ["face-coordinates"])
        self.assertNotIn("FaceCoordinates", changes)
        self.assertEqual(args, [])

    def test_normalize_exif_value_regioninfo(self):
        """Test normalization of RegionInfo for comparison."""
        import json
        region = {
            "AppliedToDimensions": {"W": 4000, "H": 3000, "Unit": "pixel"},
            "RegionList": [
                {
                    "Area": {"X": 0.05, "Y": 0.1, "W": 0.05, "H": 0.066667, "Unit": "normalized"},
                    "Name": "Alice",
                    "Type": "Face",
                }
            ],
        }
        value = json.dumps(region)
        result = self.module.normalize_exif_value(value, "RegionInfo")
        self.assertIn("Alice:", result)
        self.assertIn("0.05", result)

    def test_normalize_exif_value_regioninfo_sorted(self):
        """Test that region normalization sorts by name."""
        import json
        region = {
            "RegionList": [
                {"Area": {"X": 0.5, "Y": 0.5, "W": 0.1, "H": 0.1}, "Name": "Zoe"},
                {"Area": {"X": 0.3, "Y": 0.3, "W": 0.1, "H": 0.1}, "Name": "Alice"},
            ]
        }
        value = json.dumps(region)
        result = self.module.normalize_exif_value(value, "RegionInfo")
        # Alice should come before Zoe
        alice_pos = result.index("Alice")
        zoe_pos = result.index("Zoe")
        self.assertLess(alice_pos, zoe_pos)

    def test_face_coordinates_cli_flag(self):
        """Test that --face-coordinates flag is parsed correctly."""
        parsed, modes = self.module.parse_cli_args(["--face-coordinates"])
        self.assertTrue(parsed.face_coordinates)
        self.assertIn("face-coordinates", modes)

    def test_face_coordinates_not_in_all(self):
        """Test that --all does NOT include face-coordinates."""
        parsed, modes = self.module.parse_cli_args(["--all"])
        self.assertNotIn("face-coordinates", modes)

    def test_all_with_face_coordinates_flag(self):
        """Test --all combined with --face-coordinates."""
        parsed, modes = self.module.parse_cli_args(["--all", "--face-coordinates"])
        self.assertIn("face-coordinates", modes)
        self.assertEqual(
            set(modes),
            {"people", "gps", "caption", "time", "rating", "face-coordinates"},
        )


class DirectoryValidationTests(ModuleLoaderMixin):
    """Tests for directory validation and mount error detection."""
    
    def test_validate_photo_directory_exists(self):
        """Test validation of an existing directory with contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file in the directory
            test_file = Path(tmpdir) / "test.jpg"
            test_file.write_text("test")
            
            result = self.module.validate_photo_directory(tmpdir, "test.log")
            self.assertTrue(result)
    
    def test_validate_photo_directory_nonexistent(self):
        """Test validation fails for non-existent directory."""
        result = self.module.validate_photo_directory("/nonexistent/path/xyz", "test.log")
        self.assertFalse(result)
    
    def test_validate_photo_directory_empty(self):
        """Test validation warns for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.module.validate_photo_directory(tmpdir, "test.log")
            self.assertFalse(result)
    
    def test_validate_photo_directory_not_a_directory(self):
        """Test validation fails when path is a file, not a directory."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            result = self.module.validate_photo_directory(tmpfile.name, "test.log")
            self.assertFalse(result)
    
    def test_check_mount_issues_high_file_not_found(self):
        """Test mount issue detection when >90% files not found."""
        stats = {
            'total': 100,
            'file_not_found': 95,
            'path_segment_mismatch': 0
        }
        # Should not raise, just log warnings
        self.module.check_mount_issues(stats, "test.log", "/library", 3)
    
    def test_check_mount_issues_high_path_mismatch(self):
        """Test detection when >50% have path segment mismatches."""
        stats = {
            'total': 100,
            'file_not_found': 0,
            'path_segment_mismatch': 60
        }
        # Should not raise, just log warnings
        self.module.check_mount_issues(stats, "test.log", "/library", 3)
    
    def test_check_mount_issues_low_errors(self):
        """Test no warnings when error rates are low."""
        stats = {
            'total': 100,
            'file_not_found': 10,
            'path_segment_mismatch': 5
        }
        # Should not raise, should not log warnings
        self.module.check_mount_issues(stats, "test.log", "/library", 3)
    
    def test_check_mount_issues_zero_total(self):
        """Test that function handles zero total gracefully."""
        stats = {
            'total': 0,
            'file_not_found': 0,
            'path_segment_mismatch': 0
        }
        # Should not raise
        self.module.check_mount_issues(stats, "test.log", "/library", 3)


class RatingFavoriteTests(ModuleLoaderMixin):
    """Tests for Issue #24: Improved rating and favorite sync."""

    def test_favorite_only_sets_rating_5_and_favorite_tags(self):
        """Favorite with no explicit rating → fallback to 5 stars + Favorite label."""
        asset = {"isFavorite": True}
        details = {"exifInfo": {}}
        args, changes = self.module.build_exif_args(asset, details, ["rating"])

        self.assertIn("Rating", changes)
        self.assertIn("-Rating=5", args)
        self.assertIn("-XMP:Rating=5", args)
        self.assertIn("-MicrosoftPhoto:Rating=5", args)
        self.assertIn("-RatingPercent=100", args)
        self.assertIn("-XMP:Label=Favorite", args)
        self.assertIn("-XMP:Favorite=1", args)

    def test_star_rating_only_no_favorite(self):
        """Explicit star rating, not a favorite."""
        asset = {"isFavorite": False}
        details = {"exifInfo": {"rating": 3}}
        args, changes = self.module.build_exif_args(asset, details, ["rating"])

        self.assertIn("Rating", changes)
        self.assertIn("-Rating=3", args)
        self.assertIn("-XMP:Rating=3", args)
        self.assertIn("-MicrosoftPhoto:Rating=3", args)
        self.assertIn("-RatingPercent=60", args)
        self.assertIn("-XMP:Label=", args)
        self.assertIn("-XMP:Favorite=0", args)

    def test_star_rating_and_favorite(self):
        """Both star rating and favorite set."""
        asset = {"isFavorite": True}
        details = {"exifInfo": {"rating": 4}}
        args, changes = self.module.build_exif_args(asset, details, ["rating"])

        self.assertIn("-Rating=4", args)
        self.assertIn("-RatingPercent=80", args)
        self.assertIn("-XMP:Label=Favorite", args)
        self.assertIn("-XMP:Favorite=1", args)

    def test_no_rating_no_favorite(self):
        """Neither star rating nor favorite → 0."""
        asset = {"isFavorite": False}
        details = {"exifInfo": {}}
        args, changes = self.module.build_exif_args(asset, details, ["rating"])

        self.assertIn("-Rating=0", args)
        self.assertIn("-XMP:Rating=0", args)
        self.assertIn("-MicrosoftPhoto:Rating=0", args)
        self.assertIn("-RatingPercent=0", args)
        self.assertIn("-XMP:Favorite=0", args)

    def test_rating_zero_stars(self):
        """Explicit 0-star rating."""
        asset = {"isFavorite": False}
        details = {"exifInfo": {"rating": 0}}
        args, changes = self.module.build_exif_args(asset, details, ["rating"])

        self.assertIn("-Rating=0", args)
        self.assertIn("-RatingPercent=0", args)

    def test_normalize_xmp_rating(self):
        """Normalize XMP:Rating values."""
        self.assertEqual(self.module.normalize_exif_value("3", "XMP:Rating"), "3")

    def test_normalize_microsoft_rating(self):
        """Normalize MicrosoftPhoto:Rating values."""
        self.assertEqual(self.module.normalize_exif_value("5", "MicrosoftPhoto:Rating"), "5")

    def test_normalize_rating_percent(self):
        """Normalize RatingPercent values."""
        self.assertEqual(self.module.normalize_exif_value("80", "RatingPercent"), "80")

    def test_normalize_xmp_label(self):
        """Normalize XMP:Label values."""
        self.assertEqual(self.module.normalize_exif_value("Favorite", "XMP:Label"), "Favorite")

    def test_normalize_xmp_favorite(self):
        """Normalize XMP:Favorite values."""
        self.assertEqual(self.module.normalize_exif_value("1", "XMP:Favorite"), "1")


class TimestampOldestDateTests(ModuleLoaderMixin):
    """Tests for Issue #26: Deterministic oldest-date selection and broad timestamp writing."""

    def test_select_oldest_date_dateTimeOriginal_earliest(self):
        """dateTimeOriginal is earliest → should be selected."""
        asset = {
            "exifInfo": {
                "dateTimeOriginal": "2021-06-15T10:00:00Z",
                "dateTimeCreated": "2022-01-01T12:00:00Z",
            },
            "fileCreatedAt": "2023-01-01T00:00:00Z",
        }
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)

    def test_select_oldest_date_fileCreatedAt_earliest(self):
        """fileCreatedAt is earliest → should be selected."""
        asset = {
            "exifInfo": {
                "dateTimeOriginal": "2023-06-15T10:00:00Z",
            },
            "fileCreatedAt": "2020-01-01T00:00:00Z",
            "fileModifiedAt": "2023-06-20T00:00:00Z",
        }
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2020)

    def test_select_oldest_date_no_exif_only_file(self):
        """No EXIF dates, only file dates."""
        asset = {
            "exifInfo": {},
            "fileCreatedAt": "2021-03-15T08:30:00Z",
            "fileModifiedAt": "2021-04-20T10:00:00Z",
        }
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.month, 3)

    def test_select_oldest_date_filename_fallback(self):
        """No metadata dates → extract from filename."""
        asset = {
            "exifInfo": {},
            "originalFileName": "IMG_20210615_1234.jpg",
        }
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)

    def test_select_oldest_date_no_data(self):
        """No dates available at all → None."""
        asset = {"exifInfo": {}}
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNone(result)

    def test_select_oldest_date_tz_aware(self):
        """tz-aware ISO timestamps are parsed correctly."""
        asset = {
            "exifInfo": {
                "dateTimeOriginal": "2026-02-11T09:44:27.476+02:00",
            },
        }
        result = self.module.select_oldest_date_from_asset(asset)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 44)

    def test_extract_date_from_filename_yyyymmdd(self):
        """Extract date from YYYYMMDD filename."""
        result = self.module.extract_date_from_filename("IMG_20210615.jpg")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)

    def test_extract_date_from_filename_yyyy_mm_dd(self):
        """Extract date from YYYY-MM-DD filename."""
        result = self.module.extract_date_from_filename("photo_2021-06-15_sunset.jpg")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.month, 6)

    def test_extract_date_from_filename_with_time(self):
        """Extract date+time from filename like IMG_20210615_123456."""
        result = self.module.extract_date_from_filename("IMG_20210615_123456.jpg")
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2021)
        self.assertEqual(result.hour, 12)
        self.assertEqual(result.minute, 34)
        self.assertEqual(result.second, 56)

    def test_extract_date_from_filename_invalid(self):
        """No date pattern in filename → None."""
        result = self.module.extract_date_from_filename("random_photo.jpg")
        self.assertIsNone(result)

    def test_extract_date_from_filename_empty(self):
        """Empty filename → None."""
        result = self.module.extract_date_from_filename("")
        self.assertIsNone(result)

    def test_build_exif_args_time_writes_all_tags(self):
        """Time sync should write to AllDates, XMP, IPTC, QuickTime, File tags."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {"dateTimeOriginal": "2024-01-15T10:30:45Z"},
            "fileCreatedAt": "2024-02-01T00:00:00Z",
        }
        args, changes = self.module.build_exif_args(asset, details, ["time"])

        self.assertIn("Time", changes)
        self.assertIn("-AllDates=2024:01:15 10:30:45", args)
        self.assertIn("-XMP:CreateDate=2024:01:15 10:30:45", args)
        self.assertIn("-XMP:ModifyDate=2024:01:15 10:30:45", args)
        self.assertIn("-XMP:MetadataDate=2024:01:15 10:30:45", args)
        self.assertIn("-IPTC:DateCreated=2024-01-15", args)
        self.assertIn("-IPTC:TimeCreated=10:30:45", args)
        self.assertIn("-QuickTime:CreateDate=2024-01-15T10:30:45", args)
        self.assertIn("-QuickTime:ModifyDate=2024-01-15T10:30:45", args)
        self.assertIn("-FileCreateDate=2024-01-15T10:30:45", args)
        self.assertIn("-FileModifyDate=2024-01-15T10:30:45", args)
        self.assertIn("-XMP-photoshop:DateCreated=2024-01-15", args)

    def test_build_exif_args_time_uses_oldest_date(self):
        """Time sync should select the oldest date from multiple sources."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {"dateTimeOriginal": "2024-06-15T10:00:00Z"},
            "fileCreatedAt": "2023-01-01T00:00:00Z",
        }
        args, changes = self.module.build_exif_args(asset, details, ["time"])

        self.assertIn("Time", changes)
        # Should use fileCreatedAt (2023) since it's older
        self.assertIn("-AllDates=2023:01:01 00:00:00", args)

    def test_build_exif_args_time_filename_fallback(self):
        """Time sync fallback to filename date when no metadata dates."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {},
            "originalFileName": "IMG_20210615_1234.jpg",
        }
        args, changes = self.module.build_exif_args(asset, details, ["time"])

        self.assertIn("Time", changes)
        self.assertIn("-AllDates=2021:06:15 12:34:00", args)

    def test_build_exif_args_time_no_date(self):
        """Time sync with no dates → no time args."""
        asset = {"isFavorite": False}
        details = {"exifInfo": {}}
        args, changes = self.module.build_exif_args(asset, details, ["time"])

        self.assertNotIn("Time", changes)
        self.assertEqual(args, [])

    def test_build_exif_args_time_tz_formatting(self):
        """tz-aware EXIF → EXIF fields as YYYY:MM:DD HH:MM:SS (no TZ), QuickTime as ISO."""
        asset = {"isFavorite": False}
        details = {
            "exifInfo": {"dateTimeOriginal": "2026-02-11T09:44:27.476+02:00"},
        }
        args, changes = self.module.build_exif_args(asset, details, ["time"])

        self.assertIn("Time", changes)
        # AllDates → EXIF format (no TZ)
        self.assertIn("-AllDates=2026:02:11 09:44:27", args)
        # QuickTime → ISO format
        self.assertIn("-QuickTime:CreateDate=2026-02-11T09:44:27", args)

    def test_parse_datetime_str_various_formats(self):
        """Test the internal datetime parser with various formats."""
        parse = self.module._parse_datetime_str
        # ISO with Z
        dt = parse("2024-01-15T10:30:45Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 10)
        # ISO with offset
        dt = parse("2024-01-15T10:30:45+02:00")
        self.assertIsNotNone(dt)
        # EXIF format
        dt = parse("2024:01:15 10:30:45")
        self.assertIsNotNone(dt)
        # ISO with microseconds
        dt = parse("2024-01-15T10:30:45.123456Z")
        self.assertIsNotNone(dt)
        # Invalid
        dt = parse("not-a-date")
        self.assertIsNone(dt)
        # Empty
        dt = parse("")
        self.assertIsNone(dt)
        dt = parse(None)
        self.assertIsNone(dt)
        
class SidecarAndMsPhotoTests(ModuleLoaderMixin):
    """Tests for sidecar-aware write executor and MicrosoftPhoto fallback."""

    def test_execute_with_sidecar_reads_and_logs_previous_value_and_appends_target(self):
        import unittest.mock as mock
        # Pfad-Setup
        full_path = "/tmp/test/IMG-0001.jpg"
        sidecar_path = full_path + ".xmp"

        # 1) Mock: sidecar existiert
        with mock.patch("exif.os.path.exists", return_value=True):
            # 2) Mock: subprocess.run für sidecar-read -> gibt JSON mit XMP:Rating zurück
            fake_sidecar_json = '[{"SourceFile":"%s","XMP:Rating":2,"RatingPercent":40}]' % sidecar_path
            mock_proc = mock.Mock()
            mock_proc.stdout = fake_sidecar_json
            with mock.patch("exif.subprocess.run", return_value=mock_proc) as mock_run:
                # 3) Mock: ExifToolHelper.execute => simuliert erfolgreichen Write (keine MSPHOTO-Warnung)
                helper = self.module.ExifToolHelper()
                with mock.patch.object(helper, "execute", return_value=("", "")) as mock_execute:
                    # Call the helper function from the exif module (available via combined module)
                    stdout, stderr = self.module.execute_with_sidecar_and_msphoto(
                        ["-overwrite_original", "-XMP:Rating=2", "-MicrosoftPhoto:Rating=2", "-Rating=2", "-RatingPercent=40"],
                        full_path,
                        helper,
                        "test.log"
                    )

                    # subprocess.run wurde zum Lesen der Sidecar aufgerufen
                    mock_run.assert_called()
                    # ExifToolHelper.execute wurde genau einmal aufgerufen (kein MSPHOTO-Retry nötig)
                    self.assertEqual(mock_execute.call_count, 1)

    def test_execute_with_sidecar_retries_when_msphoto_not_writable(self):
        import unittest.mock as mock
        full_path = "/tmp/test/IMG-0002.jpg"
        sidecar_path = full_path + ".xmp"

        # Sidecar existiert
        with mock.patch("exif.os.path.exists", return_value=True):
            # subprocess.run returns sidecar JSON
            fake_sidecar_json = '[{"SourceFile":"%s","XMP:Rating":2,"RatingPercent":40}]' % sidecar_path
            mock_proc = mock.Mock()
            mock_proc.stdout = fake_sidecar_json
            with mock.patch("exif.subprocess.run", return_value=mock_proc):
                helper = self.module.ExifToolHelper()

                # Prepare execute behavior: first call returns a combined output containing MS PHOTO warning,
                # second call returns success.
                def fake_execute_first(args):
                    # simulate exiftool stdout containing a MicrosoftPhoto warning string
                    return ("Warning: Sorry, MicrosoftPhoto:Rating doesn't exist or isn't writable\n", "")

                def fake_execute_second(args):
                    return ("", "")

                with mock.patch.object(helper, "execute", side_effect=[fake_execute_first([]), fake_execute_second([])]) as mock_execute:
                    stdout, stderr = self.module.execute_with_sidecar_and_msphoto(
                        ["-overwrite_original", "-XMP:Rating=2", "-MicrosoftPhoto:Rating=2", "-Rating=2", "-RatingPercent=40"],
                        full_path,
                        helper,
                        "test.log"
                    )

                    # execute wurde zweimal aufgerufen: erster Versuch (mit MSPHOTO), zweiter Versuch (ohne MSPHOTO)
                    self.assertEqual(mock_execute.call_count, 2)

if __name__ == "__main__":
    unittest.main()
