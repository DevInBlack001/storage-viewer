"""Removability rules: which home-directory items are safe to delete.

Tiers, from most to least removable:

  safe    regenerates on demand (caches, build output, trash)
  review  probably removable, but only the user knows (downloads, VMs, games)
  keep    personal data, settings, keys or source code

The built-in rule tables live in defaults.json next to this file. A rule is a
path relative to the home directory, one glob per segment, with an optional
leading XDG token such as `$XDG_CACHE_HOME` (see xdg.py) so relocated or
localized folders still match. A rule also covers everything beneath its path.
User rules from the config file are checked first, then the defaults; first
match wins. An item nothing matches is "review", never "safe".
"""

from __future__ import annotations

import json
import os
from fnmatch import fnmatchcase
from typing import Mapping

from .config import Settings
from .xdg import resolve_tokens

SAFE = "safe"
REVIEW = "review"
KEEP = "keep"
TIERS = (SAFE, REVIEW, KEEP)
TIER_ORDER = {SAFE: 0, REVIEW: 1, KEEP: 2}

DEFAULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults.json")
_MAX_DEFAULTS_BYTES = 512 * 1024


def load_defaults(path: str = DEFAULTS_PATH) -> dict:
    """Read the shipped rule tables. A damaged install fails with a clear message."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_MAX_DEFAULTS_BYTES + 1)
        if len(raw) > _MAX_DEFAULTS_BYTES:
            raise ValueError("file is too large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
        return data
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot load the built-in rules from {path}: {exc}") from exc


def _compile_path(path: str, tokens: Mapping[str, tuple[str, ...] | None]) -> tuple[str, ...] | None:
    """Turn a rule path into home-relative segments, or None if it can't apply."""
    path = path.strip()
    if path.startswith("~/"):
        path = path[2:]
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    first = segments[0]
    if first.startswith("$"):
        base = tokens.get(first[1:])
        if not base:  # unknown token, outside home, or home itself
            return None
        return tuple(base) + tuple(segments[1:])
    if path.startswith("/") or ".." in segments:
        return None
    return tuple(segments)


def _match(pattern: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    if len(parts) < len(pattern):
        return False
    return all(fnmatchcase(part, pat) for pat, part in zip(pattern, parts))


class RuleSet:
    """Rules resolved against one home directory and environment."""

    def __init__(self, home: str, settings: Settings | None = None, environ: Mapping[str, str] | None = None) -> None:
        settings = settings or Settings()
        defaults = load_defaults()
        self.git_reason = str(defaults.get("git_reason", "Git repo"))
        self.default_reason = str(defaults.get("default_reason", "Unclassified"))
        self.warnings: list[str] = []
        tokens = resolve_tokens(home, environ)

        user = [(r.get("path", ""), r.get("tier"), str(r.get("reason") or "Your rule")) for r in settings.user_rules]
        shipped = [(r.get("path", ""), r.get("tier"), str(r.get("reason", ""))) for r in defaults.get("rules", [])]
        self.rules: list[tuple[tuple[str, ...], str, str]] = []
        for path, tier, reason in user + shipped:
            if tier not in TIERS:
                self.warnings.append(f"rule for {path!r} skipped: tier must be one of {', '.join(TIERS)}")
                continue
            compiled = _compile_path(path, tokens)
            if compiled is not None:
                self.rules.append((compiled, tier, reason))

        self.expand: list[tuple[str, ...]] = []
        for path in list(settings.user_expand) + list(defaults.get("expand", [])):
            compiled = _compile_path(path, tokens)
            if compiled is not None:
                self.expand.append(compiled)

        self.artifacts: dict[str, tuple[str, str, frozenset[str]]] = {}
        merged = dict(defaults.get("artifacts", {}))
        merged.update(settings.user_artifacts)
        for name, spec in merged.items():
            tier = spec.get("tier")
            if tier not in TIERS or "/" in name:
                self.warnings.append(f"artifact {name!r} skipped: needs a plain name and a valid tier")
                continue
            markers = spec.get("markers") or []
            self.artifacts[name] = (
                tier,
                str(spec.get("reason") or "Rebuildable"),
                frozenset(m for m in markers if isinstance(m, str)),
            )

    def is_expandable(self, parts: tuple[str, ...]) -> bool:
        return any(len(pat) == len(parts) and _match(pat, parts) for pat in self.expand)

    def classify(self, parts: tuple[str, ...], is_git_repo: bool = False) -> tuple[str, str, bool]:
        """Return (tier, reason, matched) for a path relative to home."""
        for pattern, tier, reason in self.rules:
            if _match(pattern, parts):
                return tier, reason, True
        if is_git_repo:
            return KEEP, self.git_reason, True
        return REVIEW, self.default_reason, False

    def artifact_info(self, name: str, sibling_names: set[str]) -> tuple[str, str] | None:
        """Return (tier, reason) if a directory called `name` is rebuildable output."""
        info = self.artifacts.get(name)
        if info is None:
            return None
        tier, reason, markers = info
        if markers and not (markers & sibling_names):
            return None
        return tier, reason
