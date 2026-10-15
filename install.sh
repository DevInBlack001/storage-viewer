#!/usr/bin/env bash
# Install Storage Viewer: the CLI/TUI, a desktop entry and icon, and (when the
# matching shell is present) the Omarchy bar plugin and a standalone Quickshell
# config. Per-user by default; no root needed.
set -euo pipefail
# shellcheck source=scripts/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/scripts/common.sh"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

  --system            install for all users (needs root; default prefix /usr/local)
  --prefix DIR        install under DIR (bin/ and share/ inside it)
  --omarchy           install the Omarchy bar plugin even if Omarchy is not detected
  --no-omarchy        never install the Omarchy plugin
  --quickshell        install the standalone Quickshell config even if qs is not detected
  --no-quickshell     never install the standalone Quickshell config
  --no-desktop        skip the desktop entry and icon
  --dry-run           show what would happen, change nothing
  -h, --help          this help

Locations follow XDG_DATA_HOME, XDG_CONFIG_HOME and XDG_BIN_HOME when set.
USAGE
}

MODE=user PREFIX="" OMARCHY=auto QS=auto DESKTOP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --system) MODE=system ;;
    --prefix) [ $# -ge 2 ] || die "--prefix needs a directory"; PREFIX="$2"; shift ;;
    --omarchy) OMARCHY=yes ;;
    --no-omarchy) OMARCHY=no ;;
    --quickshell) QS=yes ;;
    --no-quickshell) QS=no ;;
    --no-desktop) DESKTOP=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

case "$PREFIX" in ""|/*) ;; *) die "--prefix must be an absolute path" ;; esac
if [ "$MODE" = system ] && [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" = 0 ]; then
  die "--system needs root (try: sudo ./install.sh --system)"
fi

check_python
resolve_layout "$MODE" "$PREFIX"

# Shell plugins live in the invoking user's config, so a system install (often
# run through sudo, where HOME is not the user's) leaves them to a per-user run.
if [ "$MODE" = system ]; then
  [ "$OMARCHY" = yes ] || OMARCHY=no
  [ "$QS" = yes ] || QS=no
fi
[ "$OMARCHY" = auto ] && { detect_omarchy && OMARCHY=yes || OMARCHY=no; }
[ "$QS" = auto ] && { detect_quickshell && QS=yes || QS=no; }

say "Installing Storage Viewer ($MODE)"
info "app:      $APP_DIR"
info "command:  $BIN_DIR/$APP_NAME"
[ "$OMARCHY" = yes ] && info "omarchy:  $XDG_CONFIG/omarchy/plugins/$PLUGIN_ID"
[ "$QS" = yes ] && info "quickshell: $XDG_CONFIG/quickshell/$APP_NAME"

# Start a fresh manifest; if one exists, remove its old files first so files
# dropped by a newer version don't linger.
if [ -f "$MANIFEST" ]; then
  say "Replacing existing installation"
  if [ "$DRY_RUN" = 0 ]; then "$SRC_DIR/uninstall.sh" --quiet --keep-config --manifest "$MANIFEST" || warn "old install could not be fully removed"; fi
fi
[ "$DRY_RUN" = 1 ] || { mkdir -p "$APP_DIR"; : > "$MANIFEST.new"; }

copy_file() { # <src> <dest> [mode]
  run install -D -m "${3:-644}" "$1" "$2"
  record file "$2"
  # Directories we own (inside our app dir or a plugin dir) are removed again
  # on uninstall once empty; shared ones like ~/.local/bin are never recorded.
  case "$2" in
    "$APP_DIR"/*|*/"$PLUGIN_ID"/*|*/quickshell/"$APP_NAME"/*) record dir "$(dirname "$2")" ;;
  esac
}
make_link() { # <target> <link>
  run mkdir -p "$(dirname "$2")"
  run ln -sfn "$1" "$2"
  record link "$2"
}

# ---- the program ------------------------------------------------------------
record dir "$APP_DIR"
while IFS= read -r -d '' f; do
  rel="${f#"$SRC_DIR"/}"
  copy_file "$f" "$APP_DIR/$rel"
done < <(find "$SRC_DIR/storage_viewer" -type f -name '*.py' -print0)
copy_file "$SRC_DIR/bin/$APP_NAME" "$APP_DIR/bin/$APP_NAME" 755
make_link "$APP_DIR/bin/$APP_NAME" "$BIN_DIR/$APP_NAME"

# ---- desktop entry + icon ---------------------------------------------------
if [ "$DESKTOP" = 1 ]; then
  copy_file "$SRC_DIR/assets/$APP_NAME.svg" "$ICON_DIR/$APP_NAME.svg"
  if [ "$DRY_RUN" = 0 ]; then
    mkdir -p "$DESKTOP_DIR"
    sed "s|@BIN@|$BIN_DIR/$APP_NAME|g" "$SRC_DIR/packaging/$APP_NAME.desktop.in" > "$DESKTOP_DIR/$APP_NAME.desktop"
    record file "$DESKTOP_DIR/$APP_NAME.desktop"
  else
    info "[dry-run] write $DESKTOP_DIR/$APP_NAME.desktop"
  fi
fi

# ---- shell front ends -------------------------------------------------------
install_qml_dir() { # <dest dir> <entry files, relative to SRC_DIR...>
  local dest="$1" f; shift
  record dir "$dest"
  for f in "$@" Backend.qml Content.qml Donut.qml Model.js; do copy_file "$SRC_DIR/$f" "$dest/$(basename "$f")"; done
  make_link "$APP_DIR/bin/$APP_NAME" "$dest/bin/$APP_NAME"
  record dir "$dest/bin"
}
[ "$OMARCHY" = yes ] && install_qml_dir "$XDG_CONFIG/omarchy/plugins/$PLUGIN_ID" manifest.json Panel.qml
[ "$QS" = yes ] && install_qml_dir "$XDG_CONFIG/quickshell/$APP_NAME" "quickshell/$APP_NAME/shell.qml"

# ---- finish -----------------------------------------------------------------
if [ "$DRY_RUN" = 0 ]; then
  {
    [ "$MODE" != system ] || printf 'option --system\n'
    [ -z "$PREFIX" ] || printf 'option --prefix %s\n' "$PREFIX"
    printf 'option --%s\n' "$([ "$OMARCHY" = yes ] && echo omarchy || echo no-omarchy)"
    printf 'option --%s\n' "$([ "$QS" = yes ] && echo quickshell || echo no-quickshell)"
    [ "$DESKTOP" = 1 ] || printf 'option --no-desktop\n'
    cat "$MANIFEST.new"
  } > "$MANIFEST"
  rm -f "$MANIFEST.new"
fi

say "Done."
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH; add it to run '$APP_NAME' directly" ;; esac
if [ "$OMARCHY" = yes ]; then
  info "Omarchy: run 'omarchy plugin enable devinblack001.storage-viewer' (first install only),"
  info "         then 'omarchy-restart-shell' so the shell reloads the plugin."
fi
[ "$QS" = yes ] && info "Quickshell: run 'qs -c $APP_NAME' (toggle with: qs -c $APP_NAME ipc call $APP_NAME toggle)."
info "Terminal: run '$APP_NAME'."
