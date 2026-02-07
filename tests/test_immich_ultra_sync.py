import importlib.util
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_FILE_PATH = PROJECT_ROOT / "script" / "immich-ultra-sync.py"
_MODULE_CACHE = None


def load_module():
    global _MODULE_CACHE
    if _MODULE_CACHE is None:
        spec = importlib.util.spec_from_file_location("immich_ultra_sync_mod", MODULE_FILE_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module from {MODULE_FILE_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE_CACHE = module
    return _MODULE_CACHE


class ModuleLoaderMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()


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
        # Test Photoshop:DateCreated normalization (ISO date format YYYY-MM-DD)
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
        original = self.module._LOG_LEVEL
        self.module.set_log_level("DEBUG")
        self.assertEqual(self.module._LOG_LEVEL, self.module.LogLevel.DEBUG)
        self.module.set_log_level("ERROR")
        self.assertEqual(self.module._LOG_LEVEL, self.module.LogLevel.ERROR)
        # Restore original
        self.module._LOG_LEVEL = original


class ConfigLoaderTests(ModuleLoaderMixin):
    def test_load_config_missing_file(self):
        config = self.module.load_config("/nonexistent/file.conf")
        self.assertIn('IMMICH_INSTANCE_URL', config)
        self.assertEqual(config['IMMICH_INSTANCE_URL'], '')
        self.assertEqual(config['IMMICH_PHOTO_DIR'], self.module.DEFAULT_PHOTO_DIR)


if __name__ == "__main__":
    unittest.main()
