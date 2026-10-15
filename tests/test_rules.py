import os
import tempfile
import unittest

from storage_viewer import rules
from storage_viewer.config import Settings
from storage_viewer.rules import RuleSet


class RuleTokenTests(unittest.TestCase):
    def test_all_default_rules_compile_with_default_xdg_layout(self):
        with tempfile.TemporaryDirectory() as home:
            rs = RuleSet(home, environ={})
            self.assertEqual(len(rs.rules), len(rules.DEFAULT_RULES))
            self.assertEqual(rs.warnings, [])

    def test_relocated_cache_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as home:
            rs = RuleSet(home, environ={"XDG_CACHE_HOME": os.path.join(home, "var", "cache")})
            tier, _, matched = rs.classify(("var", "cache", "thing"))
            self.assertEqual((tier, matched), (rules.SAFE, True))
            self.assertFalse(rs.classify((".cache", "thing"))[2] and rs.classify((".cache", "thing"))[0] == rules.SAFE)

    def test_localized_user_dirs_file(self):
        with tempfile.TemporaryDirectory() as home:
            cfg = os.path.join(home, ".config")
            os.makedirs(cfg)
            with open(os.path.join(cfg, "user-dirs.dirs"), "w") as fh:
                fh.write('XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
            rs = RuleSet(home, environ={})
            self.assertEqual(rs.classify(("Telechargements", "x.iso"))[0], rules.REVIEW)
            self.assertTrue(rs.classify(("Telechargements", "x.iso"))[2])
            self.assertTrue(rs.is_expandable(("Telechargements",)))

    def test_xdg_dir_outside_home_never_matches(self):
        with tempfile.TemporaryDirectory() as home:
            rs = RuleSet(home, environ={"XDG_CACHE_HOME": "/somewhere/else"})
            self.assertFalse(rs.is_expandable((".cache",)))

    def test_user_rule_wins_over_default(self):
        with tempfile.TemporaryDirectory() as home:
            s = Settings(user_rules=[{"path": "$XDG_CACHE_HOME/precious", "tier": "keep", "reason": "mine"}])
            rs = RuleSet(home, s, environ={})
            self.assertEqual(rs.classify((".cache", "precious"))[:2], (rules.KEEP, "mine"))

    def test_bad_tier_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            s = Settings(user_rules=[{"path": "x", "tier": "nuke"}, {"path": "../etc", "tier": "safe"}])
            rs = RuleSet(home, s, environ={})
            self.assertTrue(rs.warnings)
            self.assertEqual(rs.classify(("x",))[0], rules.REVIEW)

    def test_unmatched_is_review_never_safe(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(RuleSet(home, environ={}).classify(("mystery",)), (rules.REVIEW, rules.DEFAULT_REASON, False))

    def test_artifact_needs_marker(self):
        with tempfile.TemporaryDirectory() as home:
            rs = RuleSet(home, environ={})
            self.assertIsNone(rs.artifact_info("target", {"notes.txt"}))
            self.assertEqual(rs.artifact_info("target", {"Cargo.toml"})[0], rules.SAFE)
            self.assertEqual(rs.artifact_info("node_modules", set())[0], rules.SAFE)


if __name__ == "__main__":
    unittest.main()
