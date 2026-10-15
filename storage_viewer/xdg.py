"""Resolve XDG base and user directories without assuming their names.

Nothing here hardcodes `~/.cache` or `~/Downloads`: the environment and the
user's own `user-dirs.dirs` decide, and the conventional names are only the
fallback the XDG spec itself defines. Results are paths *relative to home*
(as tuples of segments); a location outside home resolves to None.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

_MAX_USER_DIRS_BYTES = 64 * 1024

# token -> (environment variable or None, fallback relative to home)
_BASE = {
    "XDG_CACHE_HOME": ("XDG_CACHE_HOME", ".cache"),
    "XDG_CONFIG_HOME": ("XDG_CONFIG_HOME", ".config"),
    "XDG_DATA_HOME": ("XDG_DATA_HOME", ".local/share"),
    "XDG_STATE_HOME": ("XDG_STATE_HOME", ".local/state"),
}
_USER = {
    "XDG_DOWNLOAD_DIR": "Downloads",
    "XDG_DOCUMENTS_DIR": "Documents",
    "XDG_VIDEOS_DIR": "Videos",
    "XDG_MUSIC_DIR": "Music",
    "XDG_PICTURES_DIR": "Pictures",
}
_LINE = re.compile(r'^\s*(XDG_[A-Z]+_DIR)\s*=\s*"?([^"\n]*)"?\s*$')


def _relative_to_home(path: str, home: str) -> tuple[str, ...] | None:
    path = os.path.normpath(path)
    home = os.path.normpath(home)
    if path == home:
        return ()
    prefix = home.rstrip(os.sep) + os.sep
    if not path.startswith(prefix):
        return None
    return tuple(p for p in path[len(prefix):].split(os.sep) if p)


def _read_user_dirs(config_home: str) -> dict[str, str]:
    path = os.path.join(config_home, "user-dirs.dirs")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return {}
    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(_MAX_USER_DIRS_BYTES).decode("utf-8", "replace")
    except OSError:
        return {}
    found: dict[str, str] = {}
    for line in data.splitlines():
        m = _LINE.match(line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def resolve_tokens(home: str, environ: Mapping[str, str] | None = None) -> dict[str, tuple[str, ...] | None]:
    """Map every supported `$XDG_*` token to home-relative path segments."""
    env = os.environ if environ is None else environ
    out: dict[str, tuple[str, ...] | None] = {}
    config_abs = ""
    for token, (var, fallback) in _BASE.items():
        value = env.get(var, "")
        absolute = value if value and os.path.isabs(value) else os.path.join(home, fallback)
        out[token] = _relative_to_home(absolute, home)
        if token == "XDG_CONFIG_HOME":
            config_abs = absolute
    declared = _read_user_dirs(config_abs)
    for token, fallback in _USER.items():
        raw = env.get(token) or declared.get(token) or ""
        raw = raw.replace("$HOME", home, 1) if raw.startswith("$HOME") else raw
        absolute = raw if raw and os.path.isabs(raw) else os.path.join(home, fallback)
        out[token] = _relative_to_home(absolute, home)
    return out
