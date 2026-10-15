"""Mounted filesystem usage, read from /proc and statvfs (no subprocesses)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .util import safe_text

# Filesystems that are never "storage" in the sense this tool cares about.
_PSEUDO_FSTYPES = frozenset(
    {
        "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "ramfs", "cgroup",
        "cgroup2", "securityfs", "debugfs", "tracefs", "configfs", "fusectl",
        "pstore", "bpf", "autofs", "mqueue", "hugetlbfs", "binfmt_misc",
        "efivarfs", "overlay", "squashfs", "nsfs", "rpc_pipefs", "selinuxfs",
    }
)

# Bound how much of the mount table we are willing to read.
_MAX_MOUNT_LINES = 4096


@dataclass
class Disk:
    device: str
    mount: str
    fstype: str
    total: int
    used: int
    free: int

    @property
    def percent_used(self) -> float:
        return 0.0 if self.total <= 0 else self.used * 100.0 / self.total

    def as_dict(self) -> dict:
        return {
            "device": safe_text(self.device),
            "mount": safe_text(self.mount),
            "fstype": safe_text(self.fstype),
            "total": self.total,
            "used": self.used,
            "free": self.free,
            "percent": round(self.percent_used, 1),
        }


def _unescape_mount_field(field: str) -> str:
    """/proc/mounts encodes space, tab, newline and backslash as octal."""
    out = []
    i = 0
    while i < len(field):
        ch = field[i]
        if ch == "\\" and i + 3 < len(field) and field[i + 1 : i + 4].isdigit():
            try:
                out.append(chr(int(field[i + 1 : i + 4], 8)))
                i += 4
                continue
            except ValueError:
                pass
        out.append(ch)
        i += 1
    return "".join(out)


def _read_mounts(path: str = "/proc/self/mounts") -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            if n >= _MAX_MOUNT_LINES:
                break
            parts = line.split()
            if len(parts) < 3:
                continue
            rows.append(
                (
                    _unescape_mount_field(parts[0]),
                    _unescape_mount_field(parts[1]),
                    parts[2],
                )
            )
    return rows


def _statvfs_disk(device: str, mount: str, fstype: str) -> Disk | None:
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return None
    free = st.f_bavail * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return Disk(device, mount, fstype, total, used, free)


def list_disks() -> tuple[list[Disk], list[str]]:
    """Return (disks, notes). Never raises; problems are reported as notes."""
    notes: list[str] = []
    try:
        rows = _read_mounts()
    except OSError as exc:
        notes.append(f"could not read the mount table ({exc.strerror or exc}); showing / only")
        disk = _statvfs_disk("/", "/", "unknown")
        return ([disk] if disk else []), notes

    best: dict[tuple[str, int], Disk] = {}
    for device, mount, fstype in rows:
        if fstype in _PSEUDO_FSTYPES:
            continue
        # Real block-backed filesystems have a device path. Skips fuse/portal
        # helpers, network shares and container overlays, which would only add noise.
        if not device.startswith("/dev/") or device.startswith("/dev/loop"):
            continue
        disk = _statvfs_disk(device, mount, fstype)
        if disk is None:
            continue
        # One filesystem often appears several times (btrfs subvolumes, bind
        # mounts). Keep the shortest mount point for each device/size pair.
        key = (device, disk.total)
        current = best.get(key)
        if current is None or len(mount) < len(current.mount):
            best[key] = disk

    disks = sorted(best.values(), key=lambda d: (d.mount != "/", d.mount))
    if not disks:
        fallback = _statvfs_disk("/", "/", "unknown")
        if fallback:
            disks.append(fallback)
            notes.append("no block-backed mounts found; showing / only")
    return disks, notes
