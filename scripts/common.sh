# Shared helpers for install.sh, update.sh and uninstall.sh. Sourced, not run.
# shellcheck disable=SC2034  # variables are consumed by the scripts that source this file
# shellcheck shell=bash

APP_NAME="storage-viewer"
PLUGIN_ID="devinblack001.storage-viewer"
MIN_PY_MAJOR=3
MIN_PY_MINOR=9

say()  { printf '%s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# An XDG variable only counts when it is an absolute path; otherwise the spec
# says to use the default.
xdg_dir() { # <env value> <default>
  case "${1:-}" in /*) printf '%s' "$1" ;; *) printf '%s' "$2" ;; esac
}

[ -n "${HOME:-}" ] || die "HOME is not set"
XDG_DATA="$(xdg_dir "${XDG_DATA_HOME:-}" "$HOME/.local/share")"
XDG_CONFIG="$(xdg_dir "${XDG_CONFIG_HOME:-}" "$HOME/.config")"
XDG_CACHE="$(xdg_dir "${XDG_CACHE_HOME:-}" "$HOME/.cache")"
USER_BIN="$(xdg_dir "${XDG_BIN_HOME:-}" "$HOME/.local/bin")"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

DRY_RUN=0
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi
}

# Resolve every install location from the chosen mode. Sets: APP_DIR BIN_DIR
# DESKTOP_DIR ICON_DIR MANIFEST. $1 is "user" or "system", $2 an optional prefix.
resolve_layout() {
  local mode="$1" prefix="${2:-}"
  if [ "$mode" = system ]; then
    prefix="${prefix:-/usr/local}"
    APP_DIR="$prefix/share/$APP_NAME"
    BIN_DIR="$prefix/bin"
    DESKTOP_DIR="$prefix/share/applications"
    ICON_DIR="$prefix/share/icons/hicolor/scalable/apps"
  elif [ -n "$prefix" ]; then
    APP_DIR="$prefix/share/$APP_NAME"
    BIN_DIR="$prefix/bin"
    DESKTOP_DIR="$prefix/share/applications"
    ICON_DIR="$prefix/share/icons/hicolor/scalable/apps"
  else
    APP_DIR="$XDG_DATA/$APP_NAME"
    BIN_DIR="$USER_BIN"
    DESKTOP_DIR="$XDG_DATA/applications"
    ICON_DIR="$XDG_DATA/icons/hicolor/scalable/apps"
  fi
  MANIFEST="$APP_DIR/install-manifest"
}

check_python() {
  command -v python3 >/dev/null 2>&1 || die "python3 is required (>= $MIN_PY_MAJOR.$MIN_PY_MINOR)"
  python3 - "$MIN_PY_MAJOR" "$MIN_PY_MINOR" <<'PY' || die "Python $MIN_PY_MAJOR.$MIN_PY_MINOR or newer is required"
import sys
sys.exit(0 if sys.version_info >= (int(sys.argv[1]), int(sys.argv[2])) else 1)
PY
  python3 -c 'import curses' 2>/dev/null \
    || die "Python's curses module is missing (Debian/Ubuntu: apt install python3-curses is not needed on most distros, but your Python was built without it)"
}

detect_omarchy()   { [ -d "$XDG_CONFIG/omarchy" ] || command -v omarchy-shell >/dev/null 2>&1; }
detect_quickshell() { command -v qs >/dev/null 2>&1 || command -v quickshell >/dev/null 2>&1; }

# ---- install manifest -------------------------------------------------------
# One record per line: "file|dir|link <absolute path>" plus "option <flag>"
# lines so update.sh can repeat the same install. Uninstall removes only what
# is listed here.
record() { [ "$DRY_RUN" = 1 ] || printf '%s %s\n' "$1" "$2" >> "$MANIFEST.new"; }
