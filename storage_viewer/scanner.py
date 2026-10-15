"""Bounded, read-only scan of a directory tree (normally the home directory).

Safety properties:
  * symlinks are never followed (and never counted)
  * the scan stays on the filesystem it started on
  * hard links are counted once
  * entry count, per-directory width, recursion depth and wall-clock time are
    all capped, so a huge or hostile tree degrades to a partial result that is
    flagged `truncated` instead of exhausting memory or hanging
  * an unreadable directory is recorded as `blocked`, which is reported
    separately from paths that simply do not exist
"""

from __future__ import annotations

import os
import sys
import threading
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import islice
from typing import Callable

from . import rules
from .config import Settings
from .util import safe_text

MIB = 1024 * 1024

MAX_PER_DIR = 500_000
MAX_DEPTH = 200
# Directory nodes are only retained near the top of the tree; deeper levels
# are summed and discarded. Four levels reaches e.g. ~/.local/share/Steam.
KEEP_NODE_DEPTH = 4
MAX_FILES_PER_NODE = 200


@dataclass
class Item:
    path: str  # absolute, display-safe
    rel: str  # relative to the scan root, display-safe
    size: int
    is_dir: bool
    tier: str
    reason: str
    blocked: bool = False
    mtime: float = 0.0  # newest file modification time inside, 0 if unknown

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "rel": self.rel,
            "size": self.size,
            "is_dir": self.is_dir,
            "tier": self.tier,
            "reason": self.reason,
            "blocked": self.blocked,
            "mtime": int(self.mtime),
        }


@dataclass
class Node:
    name: str
    parts: tuple[str, ...]
    size: int = 0  # bytes on disk, excluding separately reported artifacts
    total: int = 0  # bytes on disk, including them
    is_git: bool = False
    blocked: bool = False
    newest: float = 0.0
    dirs: list["Node"] = field(default_factory=list)
    files: list[tuple[str, int, float]] = field(default_factory=list)


@dataclass
class ScanResult:
    root: str
    total: int = 0
    breakdown: list[tuple[str, int]] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    entries: int = 0
    seconds: float = 0.0
    truncated: bool = False
    truncated_reason: str = ""
    age_bounds_days: list[int] = field(default_factory=list)
    age_bytes: list[int] = field(default_factory=list)


class _Stop(Exception):
    pass


class Scanner:
    def __init__(
        self,
        root: str,
        *,
        settings: Settings | None = None,
        ruleset: rules.RuleSet | None = None,
        max_seconds: float | None = None,
        progress: Callable[[int, float], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        self.root = os.path.abspath(root)
        self.settings = settings or Settings()
        self.rules = ruleset or rules.RuleSet(os.path.expanduser("~"), self.settings)
        self.max_entries = self.settings.max_entries
        self.max_seconds = max_seconds if max_seconds is not None else self.settings.max_seconds
        self.progress = progress
        self.cancel = cancel
        self.entries = 0
        self.blocked: list[str] = []
        self.artifacts: list[Item] = []
        self.truncated = False
        self.truncated_reason = ""
        self._start = 0.0
        self._dev = 0
        self._seen_links: set[tuple[int, int]] = set()
        self._age_bounds = list(self.settings.age_buckets_days)
        self._age_bytes = [0] * (len(self._age_bounds) + 1)
        self._now = time.time()
        if sys.getrecursionlimit() < MAX_DEPTH * 3:
            sys.setrecursionlimit(MAX_DEPTH * 3)

    # ------------------------------------------------------------------ walk

    def _tick(self) -> None:
        self.entries += 1
        if self.entries % 2000:
            return
        elapsed = time.monotonic() - self._start
        if self.progress:
            self.progress(self.entries, elapsed)
        if self.cancel is not None and self.cancel.is_set():
            self._truncate("cancelled")
        if self.entries >= self.max_entries:
            self._truncate("entry limit reached")
        if elapsed >= self.max_seconds:
            self._truncate("time limit reached")

    def _truncate(self, reason: str) -> None:
        self.truncated = True
        self.truncated_reason = reason
        raise _Stop()

    def _walk(self, path: str, parts: tuple[str, ...], depth: int, in_artifact: bool) -> Node:
        node = Node(name=parts[-1] if parts else path, parts=parts)
        if depth > MAX_DEPTH:
            self.truncated = True
            self.truncated_reason = self.truncated_reason or "directory nesting too deep"
            return node
        try:
            with os.scandir(path) as it:
                entries = list(islice(it, MAX_PER_DIR + 1))
        except PermissionError:
            node.blocked = True
            self.blocked.append(path)
            return node
        except OSError:
            return node  # vanished or not a directory: not the same as blocked
        if len(entries) > MAX_PER_DIR:
            entries = entries[:MAX_PER_DIR]
            self.truncated = True
            self.truncated_reason = self.truncated_reason or "very large directory clipped"

        names = {e.name for e in entries}
        node.is_git = ".git" in names
        keep_nodes = depth < KEEP_NODE_DEPTH

        for entry in entries:
            self._tick()
            try:
                if entry.is_symlink():
                    continue
                st = entry.stat(follow_symlinks=False)
                if st.st_dev != self._dev:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    child_parts = parts + (entry.name,)
                    art = None if in_artifact else self.rules.artifact_info(entry.name, names)
                    child = self._walk(entry.path, child_parts, depth + 1, in_artifact or art is not None)
                    node.total += child.total
                    node.newest = max(node.newest, child.newest)
                    if art is not None and child.total >= self.settings.min_artifact_bytes:
                        self.artifacts.append(
                            Item(
                                path=safe_text(entry.path),
                                rel=safe_text("/".join(child_parts)),
                                size=child.total,
                                is_dir=True,
                                tier=art[0],
                                reason=art[1],
                                blocked=child.blocked,
                                mtime=child.newest,
                            )
                        )
                    else:
                        node.size += child.size
                        if keep_nodes:
                            node.dirs.append(child)
                else:
                    if st.st_nlink > 1:
                        key = (st.st_dev, st.st_ino)
                        if key in self._seen_links:
                            continue
                        self._seen_links.add(key)
                    size = st.st_blocks * 512
                    node.size += size
                    node.total += size
                    if st.st_mtime > node.newest:
                        node.newest = st.st_mtime
                    self._age_bytes[bisect_right(self._age_bounds, (self._now - st.st_mtime) / 86400.0)] += size
                    if keep_nodes and size >= self.settings.min_item_bytes and len(node.files) < MAX_FILES_PER_NODE:
                        node.files.append((entry.name, size, st.st_mtime))
            except OSError:
                continue
        return node

    # ----------------------------------------------------------------- items

    def _item_for(self, node: Node) -> Item:
        tier, reason, _ = self.rules.classify(node.parts, node.is_git)
        rel = "/".join(node.parts)
        return Item(
            path=safe_text(os.path.join(self.root, rel)),
            rel=safe_text(rel),
            size=node.size,
            is_dir=True,
            tier=tier,
            reason=reason,
            blocked=node.blocked,
            mtime=node.newest,
        )

    def _collect(self, node: Node, out: list[Item]) -> None:
        if self.rules.is_expandable(node.parts) and (node.dirs or node.files):
            for child in node.dirs:
                self._collect(child, out)
            self._add_files(node, out)
            return
        # An unclassified, non-repo folder directly under the root that mostly
        # holds other folders (~/Projects, ~/dev) is a container as well.
        if len(node.parts) == 1 and len(node.dirs) >= 2 and not node.is_git:
            _, _, matched = self.rules.classify(node.parts, node.is_git)
            if not matched:
                for child in node.dirs:
                    self._collect(child, out)
                self._add_files(node, out)
                return
        out.append(self._item_for(node))

    def _add_files(self, node: Node, out: list[Item]) -> None:
        for name, size, mtime in node.files:
            parts = node.parts + (name,)
            tier, reason, _ = self.rules.classify(parts)
            rel = "/".join(parts)
            out.append(
                Item(
                    path=safe_text(os.path.join(self.root, rel)),
                    rel=safe_text(rel),
                    size=size,
                    is_dir=False,
                    tier=tier,
                    reason=reason,
                    mtime=mtime,
                )
            )

    # ------------------------------------------------------------------- run

    def run(self, top_n: int | None = None) -> ScanResult:
        top_n = top_n or self.settings.top_n
        self._start = time.monotonic()
        result = ScanResult(root=self.root)
        try:
            st = os.stat(self.root)
        except OSError as exc:
            raise FileNotFoundError(f"cannot scan {self.root}: {exc.strerror or exc}") from exc
        self._dev = st.st_dev

        root = Node(name="", parts=())
        try:
            root = self._walk(self.root, (), 0, False)
        except _Stop:
            pass  # partial result; flags already set

        candidates: list[Item] = []
        for child in root.dirs:
            self._collect(child, candidates)
        self._add_files(root, candidates)
        candidates.extend(self.artifacts)
        candidates = [c for c in candidates if c.size >= self.settings.min_item_bytes]
        candidates.sort(key=lambda i: i.size, reverse=True)
        top = candidates[:top_n]
        # Most removable first; within a tier the biggest win comes first.
        top.sort(key=lambda i: (rules.TIER_ORDER[i.tier], -i.size))

        sized = sorted(((c.name, c.total) for c in root.dirs), key=lambda p: p[1], reverse=True)
        breakdown = [(safe_text(n, 60), t) for n, t in sized[:7]]
        other = root.total - sum(t for _, t in breakdown)
        if other > 0:
            breakdown.append(("(everything else)", other))

        result.total = root.total
        result.breakdown = breakdown
        result.items = top
        result.blocked = [safe_text(p) for p in self.blocked[:50]]
        result.entries = self.entries
        result.age_bounds_days = list(self._age_bounds)
        result.age_bytes = list(self._age_bytes)
        result.seconds = time.monotonic() - self._start
        result.truncated = self.truncated
        result.truncated_reason = self.truncated_reason
        return result


def scan(root: str, top_n: int | None = None, **kwargs) -> ScanResult:
    return Scanner(root, **kwargs).run(top_n)
