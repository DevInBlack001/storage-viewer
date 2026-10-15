import json
import os
import tempfile
import unittest
from unittest import mock

from storage_viewer import config, disks, report, tui
from storage_viewer.util import human_size, safe_text


class UtilTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(human_size(0), "0B")
        self.assertEqual(human_size(1536), "1.5K")
        self.assertEqual(human_size(5 * 1024**3), "5.0G")
        self.assertEqual(human_size(500 * 1024**2), "500M")

    def test_safe_text_strips_controls_and_clips(self):
        self.assertEqual(safe_text("a\x1b[2Jb"), "a?[2Jb")
        self.assertEqual(len(safe_text("x" * 1000)), 240)


class DiskTests(unittest.TestCase):
    def test_mount_unescape(self):
        self.assertEqual(disks._unescape_mount_field("/mnt/my\\040disk"), "/mnt/my disk")

    def test_lists_real_filesystem(self):
        found, _ = disks.list_disks()
        self.assertTrue(found)
        self.assertTrue(all(d.total >= d.used >= 0 for d in found))

    def test_unreadable_mount_table_falls_back(self):
        with mock.patch.object(disks, "_read_mounts", side_effect=OSError(13, "denied")):
            found, notes = disks.list_disks()
        self.assertTrue(notes)
        self.assertEqual(found[0].mount, "/")


class ConfigTests(unittest.TestCase):
    def _load(self, text, mode="w"):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "c.json")
        with open(path, mode) as fh:
            fh.write(text)
        return config.load_settings({"STORAGE_VIEWER_CONFIG": path})

    def test_defaults_when_missing(self):
        s = config.load_settings({"STORAGE_VIEWER_CONFIG": "/nonexistent/x.json"})
        self.assertEqual(s.top_n, 10)
        self.assertEqual(s.warnings, [])

    def test_values_are_clamped(self):
        s = self._load(json.dumps({"top_n": 9999, "warn_percent": -5}))
        self.assertEqual((s.top_n, s.warn_percent), (50, 1.0))

    def test_invalid_json_warns_and_uses_defaults(self):
        s = self._load("{nope")
        self.assertTrue(s.warnings)
        self.assertEqual(s.top_n, 10)

    def test_wrong_types_ignored(self):
        s = self._load(json.dumps({"top_n": "ten", "rules": "x", "age_buckets_days": [0, "a"]}))
        self.assertEqual(s.top_n, 10)
        self.assertTrue(s.warnings)

    def test_symlinked_config_is_refused(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        real = os.path.join(d.name, "real.json")
        with open(real, "w") as fh:
            fh.write('{"top_n": 3}')
        link = os.path.join(d.name, "link.json")
        os.symlink(real, link)
        s = config.load_settings({"STORAGE_VIEWER_CONFIG": link})
        self.assertEqual(s.top_n, 10)


class CacheTests(unittest.TestCase):
    def test_roundtrip_and_staleness_and_root_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": d}):
                import time
                payload = {"scanned_at": int(time.time()), "total": 1}
                report.write_cache(payload, "/r")
                self.assertEqual(report.read_cache("/r", 60)["total"], 1)
                self.assertIsNone(report.read_cache("/other", 60))
                payload["scanned_at"] -= 1000
                report.write_cache(payload, "/r")
                self.assertIsNone(report.read_cache("/r", 60))
                self.assertEqual(oct(os.stat(report.cache_path()).st_mode & 0o777), "0o600")

    def test_symlinked_cache_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": d}):
                os.makedirs(os.path.dirname(report.cache_path()))
                target = os.path.join(d, "t.json")
                with open(target, "w") as fh:
                    fh.write("{}")
                os.symlink(target, report.cache_path())
                self.assertIsNone(report.read_cache("/r", 60))


class DonutTests(unittest.TestCase):
    def test_donut_uses_every_segment_and_leaves_hole(self):
        cells = tui.donut_cells(9, 20, [0.5, 0.25, 0.25])
        segs = {seg for row in cells for _, seg in row}
        self.assertTrue({0, 1, 2} <= segs)
        centre = cells[4][10]
        self.assertEqual(centre[1], -1)

    def test_fmt_days(self):
        self.assertEqual(tui.fmt_days(3), "3d")
        self.assertEqual(tui.fmt_days(30), "4w")
        self.assertEqual(tui.fmt_days(400), "13mo")
        self.assertEqual(tui.fmt_days(1000), "2y")


if __name__ == "__main__":
    unittest.main()
