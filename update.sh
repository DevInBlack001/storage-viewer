#!/usr/bin/env bash
# Update Storage Viewer from its git checkout and reinstall with the options of
# the existing installation. This is the only script that touches the network
# (a `git pull`); the program itself never does.
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/scripts/common.sh"

usage() {
  cat <<USAGE
Usage: ./update.sh [options] [-- install.sh options]

  --no-pull     reinstall from the current checkout without running git pull
  --dry-run     show what would happen
  -h, --help    this help

Reuses the options recorded by the previous install. Anything after -- is
passed to install.sh instead (for example to switch modes).
USAGE
}

PULL=1
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-pull) PULL=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; PASS=("$@"); break ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

if [ "$PULL" = 1 ]; then
  [ -d "$SRC_DIR/.git" ] || die "not a git checkout; download a new release and run its install.sh, or use --no-pull"
  command -v git >/dev/null 2>&1 || die "git is required to pull updates (or use --no-pull)"
  before="$(git -C "$SRC_DIR" rev-parse --short HEAD)"
  say "Pulling latest changes"
  run git -C "$SRC_DIR" pull --ff-only
  after="$(git -C "$SRC_DIR" rev-parse --short HEAD)"
  if [ "$before" = "$after" ]; then say "Already up to date ($after)"; else say "Updated $before -> $after"; fi
fi

# version.json is the source of truth; make sure every copy of it agrees.
run "$SRC_DIR/scripts/sync-version.sh" >/dev/null

if [ "${#PASS[@]}" -eq 0 ]; then
  # Replay the recorded options from whichever layout is installed.
  for mode in user system; do
    resolve_layout "$mode" ""
    [ -f "$MANIFEST" ] && break
    MANIFEST=""
  done
  if [ -n "$MANIFEST" ]; then
    while IFS= read -r line; do
      case "$line" in "option "*) read -r -a parts <<< "${line#option }"; PASS+=("${parts[@]}") ;; esac
    done < "$MANIFEST"
  else
    warn "no existing installation found; installing with default options"
  fi
fi

[ "$DRY_RUN" = 1 ] && PASS+=(--dry-run)
exec "$SRC_DIR/install.sh" "${PASS[@]}"
