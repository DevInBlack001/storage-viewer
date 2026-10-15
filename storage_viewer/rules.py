"""Removability rules: which home-directory items are safe to delete.

Tiers, from most to least removable:

  safe    regenerates on demand (caches, build output, trash)
  review  probably removable, but only the user knows (downloads, VMs, games)
  keep    personal data, settings, keys or source code

A rule is a path relative to the home directory, one glob per segment, with an
optional leading XDG token such as `$XDG_CACHE_HOME` (see xdg.py) so relocated
or localized folders still match. A rule also covers everything beneath its
path. User rules from the config file are checked first, then these defaults;
first match wins. Anything unmatched is "review": the tool never silently calls
an unknown item safe.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Mapping

from .config import Settings
from .xdg import resolve_tokens

SAFE = "safe"
REVIEW = "review"
KEEP = "keep"
TIERS = (SAFE, REVIEW, KEEP)
TIER_ORDER = {SAFE: 0, REVIEW: 1, KEEP: 2}

GIT_REASON = "Git repository, your source code"
DEFAULT_REASON = "Unrecognised, check it before deleting"

CACHE = "$XDG_CACHE_HOME"
DATA = "$XDG_DATA_HOME"
CONF = "$XDG_CONFIG_HOME"

# (path, tier, reason)
DEFAULT_RULES: list[tuple[str, str, str]] = [
    # ---- safe: caches and trash -------------------------------------------
    (f"{DATA}/Trash", SAFE, "Trash, already deleted by you"),
    (f"{CACHE}/yay", SAFE, "AUR helper build cache, rebuilt on demand"),
    (f"{CACHE}/paru", SAFE, "AUR helper build cache, rebuilt on demand"),
    (f"{CACHE}/debuginfod_client", SAFE, "Downloaded debug symbols, fetched again when needed"),
    (f"{CACHE}/thumbnails", SAFE, "Thumbnail cache, regenerated"),
    (f"{CACHE}/pip", SAFE, "pip download cache"),
    (f"{CACHE}/*", SAFE, "Application cache, rebuilt on demand"),
    (".npm", SAFE, "npm download cache"),
    (".gradle/caches", SAFE, "Gradle cache, re-downloaded when needed"),
    (".cargo/registry", SAFE, "Downloaded crates, re-fetched on the next build"),
    (".cargo/git", SAFE, "Cargo git checkouts, re-fetched on the next build"),
    (".var/app/*/cache", SAFE, "Flatpak app cache"),
    (f"{CONF}/*/*[Cc]ache*", SAFE, "Application cache"),
    (f"{CONF}/*/logs", SAFE, "Application logs"),
    # ---- keep: secrets, settings, personal documents ----------------------
    (".ssh", KEEP, "SSH keys and known hosts"),
    (".gnupg", KEEP, "GPG keys"),
    (f"{DATA}/keyrings", KEEP, "Saved passwords"),
    (".password-store", KEEP, "Password store"),
    ("$XDG_DOCUMENTS_DIR", KEEP, "Your documents"),
    (f"{CONF}/*", KEEP, "Application settings"),
    # ---- review: big things only you can judge ----------------------------
    (f"{DATA}/Steam", REVIEW, "Steam games and runtimes (uninstall unused games from Steam)"),
    (f"{DATA}/mise", REVIEW, "Toolchains installed by mise (reinstallable)"),
    (f"{DATA}/flatpak", REVIEW, "Flatpak apps and runtimes"),
    (f"{DATA}/containers", REVIEW, "Podman images and containers"),
    (f"{DATA}/docker", REVIEW, "Docker data"),
    (f"{DATA}/libvirt/images", REVIEW, "Virtual machine disks, delete only if unused"),
    (".steam", REVIEW, "Steam client data"),
    (".minecraft", REVIEW, "Minecraft worlds and assets"),
    (".vscode", REVIEW, "Editor extensions (reinstalled on demand)"),
    (".vscode-server", REVIEW, "Remote editor server (reinstalled on demand)"),
    (".docker", REVIEW, "Docker client data"),
    ("snap", REVIEW, "Snap application data"),
    ("$XDG_DOWNLOAD_DIR/*", REVIEW, "Downloaded file, check it before deleting"),
    ("vmware/*", REVIEW, "Virtual machine, delete only if you no longer use it"),
    ("VirtualBox VMs/*", REVIEW, "Virtual machine, delete only if you no longer use it"),
    (".vmware", REVIEW, "VMware data"),
    ("$XDG_VIDEOS_DIR", REVIEW, "Personal videos"),
    ("$XDG_MUSIC_DIR", REVIEW, "Personal music"),
    ("$XDG_PICTURES_DIR", REVIEW, "Personal pictures"),
]

# Directories that only organise other things. When one is large, the scanner
# looks inside it so the list names the real culprits.
DEFAULT_EXPAND: list[str] = [
    CACHE,
    ".local",
    DATA,
    CONF,
    f"{CONF}/*",
    ".var",
    ".var/app",
    ".var/app/*",
    "$XDG_DOWNLOAD_DIR",
    "vmware",
    "VirtualBox VMs",
]

# Rebuildable directories found anywhere under home. `markers` means the name
# only counts when a sibling file proves it is build output (a plain directory
# called "build" or "target" could be anything).
DEFAULT_ARTIFACTS: dict[str, dict] = {
    "node_modules": {"tier": SAFE, "reason": "JavaScript dependencies, restored by npm/pnpm install"},
    "__pycache__": {"tier": SAFE, "reason": "Python bytecode cache"},
    ".pytest_cache": {"tier": SAFE, "reason": "pytest cache"},
    ".mypy_cache": {"tier": SAFE, "reason": "mypy cache"},
    ".tox": {"tier": SAFE, "reason": "tox environments, recreated on demand"},
    "target": {
        "tier": SAFE,
        "reason": "Rust/Java build output, rebuilt by cargo/maven",
        "markers": ["Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts"],
    },
    "build": {
        "tier": SAFE,
        "reason": "Build output, regenerated by the build",
        "markers": ["CMakeLists.txt", "package.json", "setup.py", "pyproject.toml", "build.gradle", "Makefile"],
    },
    "dist": {
        "tier": SAFE,
        "reason": "Build output, regenerated by the build",
        "markers": ["package.json", "setup.py", "pyproject.toml"],
    },
    ".venv": {"tier": REVIEW, "reason": "Python virtual environment (recreate with pip/uv)"},
    "venv": {"tier": REVIEW, "reason": "Python virtual environment (recreate with pip/uv)", "markers": ["pyvenv.cfg"]},
}


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
        if base is None or not base:  # outside home, or home itself
            return None
        return tuple(base) + tuple(segments[1:])
    if first.startswith("/") or ".." in segments:
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
        self.warnings: list[str] = []
        tokens = resolve_tokens(home, environ)

        self.rules: list[tuple[tuple[str, ...], str, str]] = []
        user = [(r.get("path", ""), r.get("tier"), str(r.get("reason") or "Matched by your own rule")) for r in settings.user_rules]
        for path, tier, reason in user + DEFAULT_RULES:
            if tier not in TIERS:
                self.warnings.append(f"rule for {path!r} skipped: tier must be one of {', '.join(TIERS)}")
                continue
            compiled = _compile_path(path, tokens)
            if compiled is not None:
                self.rules.append((compiled, tier, reason))

        self.expand: list[tuple[str, ...]] = []
        for path in list(settings.user_expand) + DEFAULT_EXPAND:
            compiled = _compile_path(path, tokens)
            if compiled is not None:
                self.expand.append(compiled)

        self.artifacts: dict[str, tuple[str, str, frozenset[str]]] = {}
        merged = dict(DEFAULT_ARTIFACTS)
        merged.update(settings.user_artifacts)
        for name, spec in merged.items():
            tier = spec.get("tier")
            if tier not in TIERS or "/" in name:
                self.warnings.append(f"artifact {name!r} skipped: needs a plain name and a valid tier")
                continue
            markers = spec.get("markers") or []
            self.artifacts[name] = (
                tier,
                str(spec.get("reason") or "Rebuildable output"),
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
            return KEEP, GIT_REASON, True
        return REVIEW, DEFAULT_REASON, False

    def artifact_info(self, name: str, sibling_names: set[str]) -> tuple[str, str] | None:
        """Return (tier, reason) if a directory called `name` is rebuildable output."""
        info = self.artifacts.get(name)
        if info is None:
            return None
        tier, reason, markers = info
        if markers and not (markers & sibling_names):
            return None
        return tier, reason
