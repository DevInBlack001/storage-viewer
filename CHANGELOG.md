# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.1] - 2026-10-15

### Fixed

- Omarchy plugin failed to load with "IpcHandler is not a type": `Panel.qml` was missing `import Quickshell.Io`, so the bar widget never appeared

### Changed

- The installer now reminds Omarchy users to run `omarchy-restart-shell` after installing or updating, because the shell caches compiled plugin QML

## [1.0.0] - 2026-10-15

### Added

- Terminal UI (Python standard library only, `curses`): donut charts for the main disk and the home directory breakdown, bars for every mounted filesystem, and a ranked list of the 10 biggest items in the home directory
- Removability ranking: each item is tagged SAFE (regenerates on its own), REVIEW (only you can judge) or KEEP (personal data or code), with a one-line reason, ordered most removable first
- Size by last modified: a histogram of bytes per age bucket and a size-versus-age scatter plot of the listed items
- Build output detection anywhere under home (`target/`, `node_modules/`, `__pycache__/`, `build/`, `dist/`, virtual environments), reported as its own item and not double counted
- Colors taken from the terminal's own ANSI palette, so the TUI follows the system theme
- `--json` and `--text` modes, with a short-lived scan cache so shell panels open instantly
- Omarchy bar plugin and a standalone Quickshell config (floating icon plus panel) sharing one QML body, themed from the Omarchy palette or the Qt system palette
- `install.sh`, `update.sh` and `uninstall.sh`, driven by an install manifest so only installed files are ever removed
- Optional JSON config: custom rules, extra container folders, extra build-output names, thresholds, age buckets
- XDG-aware rules: cache, data and config locations and the localized user folders (Downloads, Videos, ...) come from the environment and `user-dirs.dirs`, never from fixed names

### Security

- Read-only and local-only: no deletion, no network calls, no subprocesses
- Symlinks are never followed, scans stay on one filesystem, hard links are counted once
- Entry, time, depth and per-directory limits keep a huge tree from exhausting memory; partial results are flagged
- Unreadable directories are reported as blocked, which is distinct from missing
- File names are sanitised before display and rendered as plain text
- Config and cache files are opened without following symlinks and are size-bounded
