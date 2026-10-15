"""Assemble scan + disk data into one report, as JSON, plain text, or a cache file."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from dataclasses import asdict

from . import __version__
from .disks import Disk, list_disks
from .rules import KEEP, REVIEW, SAFE
from .scanner import ScanResult
from .util import human_size, safe_text

# The cache holds one small report; refuse to parse anything bigger.
MAX_CACHE_BYTES = 2 * 1024 * 1024
TIER_LABEL = {SAFE: "SAFE", REVIEW: "REVIEW", KEEP: "KEEP"}


def disks_payload() -> dict:
    disks, notes = list_disks()
    return {"disks": [d.as_dict() for d in disks], "notes": notes}


def scan_payload(result: ScanResult) -> dict:
    return {
        "root": safe_text(result.root),
        "total": result.total,
        "breakdown": [{"name": n, "size": s} for n, s in result.breakdown],
        "items": [i.as_dict() for i in result.items],
        "blocked": result.blocked,
        "age": {"bounds_days": result.age_bounds_days, "bytes": result.age_bytes},
        "entries": result.entries,
        "seconds": round(result.seconds, 2),
        "truncated": result.truncated,
        "truncated_reason": result.truncated_reason,
        "scanned_at": int(time.time()),
    }


def full_payload(result: ScanResult | None) -> dict:
    payload = {"version": __version__, "generated_at": int(time.time())}
    payload.update(disks_payload())
    payload["home"] = scan_payload(result) if result is not None else None
    return payload


# ------------------------------------------------------------------- cache

def cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "storage-viewer", "scan.json")


def write_cache(home_payload: dict, root: str) -> None:
    """Best effort. A failure to cache must never break the report itself."""
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".scan-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"root": root, "home": home_payload}, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass


def read_cache(root: str, max_age: float) -> dict | None:
    """Return the cached home payload if fresh and for the same root, else None."""
    path = cache_path()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CACHE_BYTES:
            return None
        if info.st_uid != os.getuid():
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict) or data.get("root") != root:
        return None
    home = data.get("home")
    if not isinstance(home, dict):
        return None
    scanned = home.get("scanned_at")
    if not isinstance(scanned, int) or time.time() - scanned > max_age or scanned > time.time() + 60:
        return None
    return home


# --------------------------------------------------------------- plain text

def _bar(fraction: float, width: int = 30) -> str:
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "#" * filled + "-" * (width - filled)


def text_report(payload: dict) -> str:
    lines: list[str] = ["Storage Viewer", ""]
    for d in payload.get("disks", []):
        lines.append(
            f"{d['mount']:<12} [{_bar(d['percent'] / 100)}] {d['percent']:>5.1f}%  "
            f"{human_size(d['used'])} used, {human_size(d['free'])} free of {human_size(d['total'])}"
        )
    for note in payload.get("notes", []):
        lines.append(f"note: {note}")
    home = payload.get("home")
    if home:
        lines += ["", f"{home['root']} uses {human_size(home['total'])}", ""]
        top = max((b["size"] for b in home["breakdown"]), default=0) or 1
        for b in home["breakdown"]:
            lines.append(f"  {b['name'][:28]:<28} [{_bar(b['size'] / top, 20)}] {human_size(b['size']):>7}")
        lines += ["", "Top items, most removable first:", ""]
        for n, i in enumerate(home["items"], 1):
            lines.append(f"{n:>2}. [{TIER_LABEL.get(i['tier'], '?'):<6}] {human_size(i['size']):>7}  {i['rel']}")
            lines.append(f"              {i['reason']}")
        if home["blocked"]:
            lines += ["", f"{len(home['blocked'])} directories could not be read (permission denied)."]
        if home["truncated"]:
            lines += ["", f"Partial result: {home['truncated_reason']}."]
    return "\n".join(lines) + "\n"
