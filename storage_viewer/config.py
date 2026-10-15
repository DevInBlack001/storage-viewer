"""User settings, read from an optional JSON file.

Lookup order for the file: $STORAGE_VIEWER_CONFIG, then
$XDG_CONFIG_HOME/storage-viewer/config.json (or the XDG default). A missing
file is normal. A broken file never stops the tool: it is reported as a warning
and the defaults are used. The file is read with O_NOFOLLOW, size-bounded and
parsed as plain JSON only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

MIB = 1024 * 1024
MAX_CONFIG_BYTES = 256 * 1024
MAX_USER_RULES = 2000


@dataclass
class Settings:
    top_n: int = 10
    max_seconds: float = 120.0
    max_entries: int = 5_000_000
    min_item_bytes: int = 1 * MIB
    min_artifact_bytes: int = 20 * MIB
    warn_percent: float = 75.0
    critical_percent: float = 90.0
    cache_max_age: float = 600.0
    age_buckets_days: list[int] = field(default_factory=lambda: [7, 30, 90, 365])
    user_rules: list[dict] = field(default_factory=list)
    user_expand: list[str] = field(default_factory=list)
    user_artifacts: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


_NUMERIC = {
    "top_n": (int, 1, 50),
    "max_seconds": (float, 1.0, 3600.0),
    "max_entries": (int, 1000, 100_000_000),
    "min_item_bytes": (int, 0, 1 << 40),
    "min_artifact_bytes": (int, 0, 1 << 40),
    "warn_percent": (float, 1.0, 100.0),
    "critical_percent": (float, 1.0, 100.0),
    "cache_max_age": (float, 0.0, 86400.0 * 30),
}


def config_path(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    explicit = env.get("STORAGE_VIEWER_CONFIG")
    if explicit:
        return explicit
    base = env.get("XDG_CONFIG_HOME")
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "storage-viewer", "config.json")


def _read_json(path: str, warnings: list[str]) -> Any:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except PermissionError:
        warnings.append(f"config {path} exists but is not readable (permission denied); using defaults")
        return None
    except OSError as exc:
        warnings.append(f"config {path} ignored: {exc.strerror or exc}")
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            raw = fh.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        warnings.append(f"config {path} ignored: {exc.strerror or exc}")
        return None
    if len(raw) > MAX_CONFIG_BYTES:
        warnings.append(f"config {path} ignored: larger than {MAX_CONFIG_BYTES} bytes")
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        warnings.append(f"config {path} ignored: invalid JSON ({exc})")
        return None


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    settings = Settings()
    data = _read_json(config_path(environ), settings.warnings)
    if data is None:
        return settings
    if not isinstance(data, dict):
        settings.warnings.append("config ignored: top level must be a JSON object")
        return settings

    for key, (kind, lo, hi) in _NUMERIC.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            settings.warnings.append(f"config: {key} must be a number; using the default")
            continue
        setattr(settings, key, kind(min(max(value, lo), hi)))

    ages = data.get("age_buckets_days")
    if isinstance(ages, list) and 1 <= len(ages) <= 8 and all(
        isinstance(a, (int, float)) and not isinstance(a, bool) and a > 0 for a in ages
    ):
        settings.age_buckets_days = sorted({int(a) for a in ages if int(a) > 0}) or settings.age_buckets_days
    elif ages is not None:
        settings.warnings.append("config: age_buckets_days must be 1 to 8 positive numbers; using the default")

    rules = data.get("rules", [])
    if isinstance(rules, list):
        for entry in rules[:MAX_USER_RULES]:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                settings.user_rules.append(entry)
            else:
                settings.warnings.append("config: a rule without a string 'path' was skipped")
    expand = data.get("expand", [])
    if isinstance(expand, list):
        settings.user_expand = [e for e in expand if isinstance(e, str)][:MAX_USER_RULES]
    artifacts = data.get("artifacts", {})
    if isinstance(artifacts, dict):
        settings.user_artifacts = {k: v for k, v in artifacts.items() if isinstance(k, str) and isinstance(v, dict)}
    return settings
