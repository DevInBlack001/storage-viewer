import os
import tempfile
import time
import unittest

from storage_viewer import rules
from storage_viewer.config import Settings
from storage_viewer.rules import RuleSet
from storage_viewer.scanner import Scanner

MIB = 1024 * 1024


def write(path, size, age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(os.urandom(size))
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))


def make_scanner(root, **overrides):
    s = Settings(min_item_bytes=1, min_artifact_bytes=MIB, **overrides)
    return Scanner(root, settings=s, ruleset=RuleSet(root, s, environ={}))


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        for dirpath, dirs, _ in os.walk(self.root):
            for d in dirs:
                try:
                    os.chmod(os.path.join(dirpath, d), 0o755)
                except OSError:
                    pass
        self.tmp.cleanup()

    def test_ranks_by_tier_then_size(self):
        write(f"{self.root}/.cache/big/blob", 3 * MIB)
        write(f"{self.root}/.cache/small/blob", 1 * MIB)
        write(f"{self.root}/Documents/doc.bin", 5 * MIB)
        write(f"{self.root}/Downloads/movie.mkv", 4 * MIB)
        res = make_scanner(self.root).run()
        order = [(i.tier, i.rel) for i in res.items]
        tiers = [t for t, _ in order]
        self.assertEqual(tiers, sorted(tiers, key=rules.TIER_ORDER.get))
        self.assertEqual(order[0], (rules.SAFE, ".cache/big"))
        self.assertEqual(order[-1][0], rules.KEEP)

    def test_symlinks_are_not_followed_or_counted(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        write(f"{outside.name}/huge", 8 * MIB)
        write(f"{self.root}/real/a", MIB)
        os.symlink(outside.name, f"{self.root}/link")
        os.symlink(f"{outside.name}/huge", f"{self.root}/real/filelink")
        res = make_scanner(self.root).run()
        self.assertLess(res.total, 3 * MIB)

    def test_hard_links_counted_once(self):
        write(f"{self.root}/a/file", 2 * MIB)
        os.link(f"{self.root}/a/file", f"{self.root}/a/twin")
        res = make_scanner(self.root).run()
        self.assertLess(res.total, 3 * MIB)

    def test_build_output_is_separate_and_not_double_counted(self):
        write(f"{self.root}/proj/Cargo.toml", 10)
        write(f"{self.root}/proj/src/main.rs", 100)
        write(f"{self.root}/proj/target/debug/bin", 4 * MIB)
        res = make_scanner(self.root).run()
        rels = {i.rel: i for i in res.items}
        self.assertEqual(rels["proj/target"].tier, rules.SAFE)
        self.assertLess(rels["proj"].size, MIB)
        self.assertGreaterEqual(res.total, 4 * MIB)

    def test_plain_target_dir_without_marker_is_not_build_output(self):
        write(f"{self.root}/notes/target/data", 3 * MIB)
        res = make_scanner(self.root).run()
        self.assertTrue(all(i.rel != "notes/target" for i in res.items))

    @unittest.skipIf(os.geteuid() == 0, "root can read everything")
    def test_unreadable_dir_is_blocked_not_missing(self):
        write(f"{self.root}/locked/secret", MIB)
        write(f"{self.root}/open/file", MIB)
        os.chmod(f"{self.root}/locked", 0o000)
        res = make_scanner(self.root).run()
        self.assertEqual(len(res.blocked), 1)
        self.assertTrue(res.blocked[0].endswith("locked"))
        self.assertFalse(res.truncated)

    def test_entry_limit_truncates_and_flags_partial_result(self):
        for i in range(2400):
            write(f"{self.root}/d{i % 8}/f{i}", 10)
        s = Settings(max_entries=1000, min_item_bytes=1)
        res = Scanner(self.root, settings=s, ruleset=RuleSet(self.root, s, environ={})).run()
        self.assertTrue(res.truncated)
        self.assertEqual(res.truncated_reason, "entry limit reached")
        self.assertLess(res.entries, 2400)

    def test_age_buckets_sum_to_total_file_bytes(self):
        write(f"{self.root}/new/f", 1 * MIB, age_days=1)
        write(f"{self.root}/old/f", 2 * MIB, age_days=400)
        res = make_scanner(self.root).run()
        self.assertEqual(res.age_bounds_days, [7, 30, 90, 365])
        self.assertGreater(res.age_bytes[0], 0)
        self.assertGreater(res.age_bytes[-1], 0)
        self.assertEqual(sum(res.age_bytes), res.total)

    def test_item_mtime_is_newest_file(self):
        write(f"{self.root}/Downloads/a/old", MIB, age_days=300)
        write(f"{self.root}/Downloads/a/new", MIB, age_days=2)
        res = make_scanner(self.root).run()
        item = next(i for i in res.items if i.rel == "Downloads/a")
        self.assertLess(time.time() - item.mtime, 3 * 86400)

    def test_hostile_filename_is_sanitised(self):
        name = "evil\x1b[31mred\x07"
        write(f"{self.root}/Downloads/{name}/f", MIB)
        res = make_scanner(self.root).run()
        for item in res.items:
            self.assertTrue(item.rel.isprintable())
            self.assertTrue(item.path.isprintable())

    def test_missing_root_raises(self):
        with self.assertRaises(FileNotFoundError):
            make_scanner(f"{self.root}/nope").run()


if __name__ == "__main__":
    unittest.main()
