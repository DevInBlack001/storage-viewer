#!/usr/bin/env bash
# Copies the version in version.json (the single source of truth) into the
# files that need a literal version string: manifest.json (Omarchy plugin),
# pyproject.toml and storage_viewer/__init__.py. Run after bumping
# version.json, before tagging a release. update.sh runs it too.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || { echo "python3 is required but was not found on PATH" >&2; exit 1; }

python3 - "$REPO_DIR" <<'PY'
import json
import os
import re
import sys

repo = sys.argv[1]

with open(os.path.join(repo, "version.json"), encoding="utf-8") as fh:
    version = json.load(fh)["version"]
if not re.fullmatch(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?", version):
    sys.exit("version.json holds %r, which is not a semantic version" % version)


def report(name, changed):
    print("%s %s %s" % (name, "set to" if changed else "already at", version))


# manifest.json
path = os.path.join(repo, "manifest.json")
with open(path, encoding="utf-8") as fh:
    manifest = json.load(fh)
changed = manifest.get("version") != version
if changed:
    manifest["version"] = version
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
report("manifest.json", changed)


def rewrite(relpath, pattern, replacement):
    path = os.path.join(repo, relpath)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        sys.exit("could not find the version line in %s" % relpath)
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    report(relpath, new != text)


rewrite("pyproject.toml", r'^version = "[^"]*"', 'version = "%s"' % version)
rewrite("storage_viewer/__init__.py", r'^__version__ = "[^"]*"', '__version__ = "%s"' % version)
PY
