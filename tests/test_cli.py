import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "bin", "storage-viewer")


def run(args, home, extra_env=None):
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, LAUNCHER, *args], env=env, capture_output=True, text=True, timeout=60)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(f"{self.home}/.cache/thing")
        with open(f"{self.home}/.cache/thing/blob", "wb") as fh:
            fh.write(os.urandom(3 * 1024 * 1024))

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_report_shape(self):
        out = run(["--json", "--refresh", "--root", self.home], self.home)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertIn("disks", data)
        self.assertEqual(data["home"]["items"][0]["tier"], "safe")
        self.assertEqual(data["home"]["items"][0]["rel"], ".cache/thing")
        self.assertEqual(len(data["home"]["age"]["bytes"]), len(data["home"]["age"]["bounds_days"]) + 1)

    def test_disks_only_skips_scan(self):
        out = run(["--json", "--disks-only"], self.home)
        self.assertIsNone(json.loads(out.stdout)["home"])

    def test_second_call_uses_cache(self):
        run(["--json", "--refresh", "--root", self.home], self.home)
        os.remove(f"{self.home}/.cache/thing/blob")
        out = run(["--json", "--root", self.home], self.home)
        self.assertEqual(json.loads(out.stdout)["home"]["items"][0]["rel"], ".cache/thing")
        out = run(["--json", "--refresh", "--root", self.home], self.home)
        self.assertEqual(json.loads(out.stdout)["home"]["items"], [])

    def test_text_report_and_config_top_n(self):
        cfg = os.path.join(self.home, "c.json")
        with open(cfg, "w") as fh:
            json.dump({"top_n": 1, "rules": [{"path": ".cache/thing", "tier": "keep", "reason": "custom reason"}]}, fh)
        out = run(["--text", "--root", self.home], self.home, {"STORAGE_VIEWER_CONFIG": cfg})
        self.assertIn("custom reason", out.stdout)
        self.assertIn("[KEEP  ]", out.stdout)

    def test_missing_root_exits_nonzero(self):
        out = run(["--json", "--root", f"{self.home}/nope"], self.home)
        self.assertEqual(out.returncode, 2)

    def test_bad_config_warns_but_still_works(self):
        cfg = os.path.join(self.home, "bad.json")
        with open(cfg, "w") as fh:
            fh.write("{broken")
        out = run(["--json", "--root", self.home], self.home, {"STORAGE_VIEWER_CONFIG": cfg})
        self.assertEqual(out.returncode, 0)
        self.assertIn("invalid JSON", out.stderr)


if __name__ == "__main__":
    unittest.main()
