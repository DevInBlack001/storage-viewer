"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, report
from .config import load_settings
from .rules import RuleSet
from .scanner import Scanner


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="storage-viewer",
        description="Show disk usage and the biggest items in your home directory, "
        "ordered by how safe they are to remove. Read-only: nothing is ever deleted.",
    )
    p.add_argument("--json", action="store_true", help="print a JSON report instead of opening the TUI")
    p.add_argument("--text", action="store_true", help="print a plain-text report instead of opening the TUI")
    p.add_argument("--disks-only", action="store_true", help="with --json/--text: skip the home scan (fast)")
    p.add_argument("--refresh", action="store_true", help="with --json: ignore the cached scan")
    p.add_argument("--max-age", type=float, default=None, metavar="SEC",
                   help="with --json: reuse a cached scan younger than this (config: cache_max_age)")
    p.add_argument("--root", default=os.path.expanduser("~"), metavar="DIR",
                   help="directory to scan (default: your home directory)")
    p.add_argument("--top", type=int, default=None, metavar="N", help="number of items to list (config: top_n)")
    p.add_argument("--max-seconds", type=float, default=None, metavar="SEC",
                   help="stop scanning after this long (config: max_seconds)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    if args.top is not None:
        settings.top_n = max(1, min(args.top, 50))
    if args.max_seconds is not None:
        settings.max_seconds = max(1.0, args.max_seconds)
    max_age = settings.cache_max_age if args.max_age is None else args.max_age
    root = os.path.abspath(args.root)
    ruleset = RuleSet(os.path.expanduser("~"), settings)
    for warning in settings.warnings + ruleset.warnings:
        print(f"storage-viewer: {warning}", file=sys.stderr)

    if not (args.json or args.text) and sys.stdout.isatty() and sys.stdin.isatty():
        from .tui import run_tui

        return run_tui(root, settings, ruleset)

    result_payload = None
    if not args.disks_only:
        result_payload = report.read_cache(root, max_age) if (args.json and not args.refresh) else None
        if result_payload is None:
            try:
                result = Scanner(root, settings=settings, ruleset=ruleset).run()
            except FileNotFoundError as exc:
                print(f"storage-viewer: {exc}", file=sys.stderr)
                return 2
            result_payload = report.scan_payload(result)
            report.write_cache(result_payload, root)

    payload = {"version": __version__}
    payload.update(report.disks_payload())
    payload["home"] = result_payload

    if args.json:
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(report.text_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
