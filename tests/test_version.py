import json
import os
import re
import unittest

from storage_viewer import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class VersionTests(unittest.TestCase):
    """version.json is the source of truth; scripts/sync-version.sh copies it."""

    def setUp(self):
        self.version = json.loads(read("version.json"))["version"]

    def test_version_json_is_semver(self):
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+")

    def test_package_matches(self):
        self.assertEqual(__version__, self.version)

    def test_manifest_matches(self):
        self.assertEqual(json.loads(read("manifest.json"))["version"], self.version)

    def test_pyproject_matches(self):
        found = re.search(r'^version = "([^"]*)"', read("pyproject.toml"), re.MULTILINE)
        self.assertEqual(found.group(1), self.version)

    def test_changelog_has_current_version(self):
        self.assertIn("## [%s]" % self.version, read("CHANGELOG.md"))


if __name__ == "__main__":
    unittest.main()
