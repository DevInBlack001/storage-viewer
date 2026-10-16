#!/usr/bin/env bash
# Publish a GitHub release for the version in version.json (the single source
# of truth). The tag is always v<version.json>, so release and version agree.
#
# Checks first: every copy of the version is in sync, CHANGELOG.md has a
# section for it, the tree is clean and pushed, and the tag is new. The release
# notes are that CHANGELOG section.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

DRY_RUN=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  -h|--help) printf 'Usage: %s [--dry-run]\n' "$0"; exit 0 ;;
  *) printf 'error: unknown option: %s\n' "$1" >&2; exit 1 ;;
esac

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
for tool in python3 git gh; do command -v "$tool" >/dev/null 2>&1 || die "$tool is required"; done

VERSION="$(python3 -c 'import json; print(json.load(open("version.json"))["version"])')"
TAG="v$VERSION"
printf 'Releasing %s\n' "$TAG"

# 1. Every copy of the version agrees with version.json.
./scripts/sync-version.sh >/dev/null
git diff --quiet -- manifest.json pyproject.toml storage_viewer/__init__.py \
  || die "version files were out of sync and have been updated; review, commit, then rerun"

# 2. The changelog has a section for this version.
NOTES="$(awk -v v="$VERSION" '
  $0 ~ "^## \\[" v "\\]" { found = 1; next }
  found && /^## \[/ { exit }
  found { print }' CHANGELOG.md)"
[ -n "$(printf '%s' "$NOTES" | tr -d '[:space:]')" ] || die "CHANGELOG.md has no entry for $VERSION"

# 3. Clean tree, pushed branch, new tag.
[ -z "$(git status --porcelain)" ] || die "working tree has uncommitted changes"
git fetch --quiet origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] || die "HEAD is not the same as its upstream; push or pull first"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists; bump version.json for a new release"
fi

if [ "$DRY_RUN" = 1 ]; then
  printf 'Dry run: would tag and publish %s with these notes:\n\n%s\n' "$TAG" "$NOTES"
  exit 0
fi

NOTES_FILE="$(mktemp)"
trap 'rm -f "$NOTES_FILE"' EXIT
printf '%s\n' "$NOTES" > "$NOTES_FILE"

git tag -a "$TAG" -m "$TAG"
git push --quiet origin "$TAG"
gh release create "$TAG" --title "$TAG" --notes-file "$NOTES_FILE" --verify-tag
printf 'Published %s\n' "$TAG"
