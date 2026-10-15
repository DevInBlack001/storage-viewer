#!/usr/bin/env bash
# Remove Storage Viewer. Only paths recorded in the install manifest are
# touched, so nothing else in your home directory can be deleted by mistake.
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/scripts/common.sh"

usage() {
  cat <<USAGE
Usage: ./uninstall.sh [options]

  --purge        also delete your config and cached scan
  --yes          do not ask for confirmation
  --dry-run      show what would be removed
  --system       target a system-wide install
  --prefix DIR   target an install made with --prefix DIR
  -h, --help     this help
USAGE
}

MODE=user PREFIX="" PURGE=0 YES=0 QUIET=0 KEEP_CONFIG=0 EXPLICIT_MANIFEST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --system) MODE=system ;;
    --prefix) [ $# -ge 2 ] || die "--prefix needs a directory"; PREFIX="$2"; shift ;;
    --quiet) QUIET=1; YES=1 ;;          # used by install.sh when replacing an install
    --keep-config) KEEP_CONFIG=1 ;;
    --manifest) EXPLICIT_MANIFEST="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

resolve_layout "$MODE" "$PREFIX"
[ -z "$EXPLICIT_MANIFEST" ] || MANIFEST="$EXPLICIT_MANIFEST"
[ -f "$MANIFEST" ] || die "no install manifest at $MANIFEST (was Storage Viewer installed with install.sh? pass --system or --prefix if it was)"

say_q() { [ "$QUIET" = 1 ] || say "$@"; }

mapfile -t ENTRIES < <(grep -E '^(file|link|dir) /' "$MANIFEST" || true)
say_q "This will remove:"
for e in "${ENTRIES[@]}"; do [ "$QUIET" = 1 ] || info "${e#* }"; done
[ "$PURGE" = 1 ] && say_q "  and your config ($XDG_CONFIG/$APP_NAME) and cache ($XDG_CACHE/$APP_NAME)"

if [ "$YES" = 0 ] && [ "$DRY_RUN" = 0 ]; then
  printf 'Continue? [y/N] '
  read -r answer
  case "$answer" in y|Y|yes|YES) ;; *) say "Cancelled."; exit 0 ;; esac
fi

# Files and links first, then directories deepest-first, and only if empty.
for e in "${ENTRIES[@]}"; do
  kind="${e%% *}" path="${e#* }"
  case "$kind" in
    file|link)
      if [ -e "$path" ] || [ -L "$path" ]; then run rm -f -- "$path"; fi ;;
  esac
done
run rm -f -- "$MANIFEST"
mapfile -t DIRS < <(printf '%s\n' "${ENTRIES[@]}" | grep '^dir ' | sed 's/^dir //' | sort -u | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-)
for d in "${DIRS[@]}"; do
  [ -d "$d" ] || continue
  # Python may have cached bytecode inside our own app directory.
  if [ "$DRY_RUN" = 0 ]; then find "$d" -type d -name __pycache__ -prune -exec rm -rf -- {} + 2>/dev/null || true; fi
  run rmdir -- "$d" 2>/dev/null || [ "$DRY_RUN" = 1 ] || warn "kept $d (not empty)"
done
if [ "$PURGE" = 1 ] && [ "$KEEP_CONFIG" = 0 ]; then
  for d in "$XDG_CONFIG/$APP_NAME" "$XDG_CACHE/$APP_NAME"; do
    [ -d "$d" ] && run rm -rf -- "$d"
  done
fi
say_q "Storage Viewer removed."
