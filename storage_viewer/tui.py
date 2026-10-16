"""Curses TUI: donut charts, size-vs-age graphs, and the ranked removal list.

Standard library only, so it runs on any distro with Python 3 and a terminal.

Colors come from the terminal's own ANSI palette (indexes 0-15 on the default
background), never from fixed RGB values, so the whole UI follows whatever theme
the terminal is using. On Omarchy that palette changes with the system theme.

Everything drawn originates from untrusted filenames, so all text goes through
`safe_text` first and is written with addnstr (never interpreted as markup).
"""

from __future__ import annotations

import curses
import locale
import math
import threading
import time
from collections import Counter

from . import rules
from .config import Settings
from .disks import Disk, list_disks
from .rules import RuleSet
from .scanner import ScanResult, Scanner
from .util import human_size, percent, safe_text

MIN_ROWS, MIN_COLS = 18, 64
DAY = 86400.0

TIER_TAG = {rules.SAFE: " SAFE ", rules.REVIEW: "REVIEW", rules.KEEP: " KEEP "}

# color pair ids
P_OK, P_WARN, P_BAD, P_DIM, P_HEAD = 1, 2, 3, 4, 5
P_SEG = (6, 7, 8, 9, 10, 11, 12, 13)
P_TIER = {rules.SAFE: 14, rules.REVIEW: 15, rules.KEEP: 16}
P_AGE = (17, 18, 19, 20, 21, 22, 23, 24, 25)  # recent (cool) to old (hot)

# braille dot bit for (column, row) inside one 2x4 cell
_BRAILLE = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
            (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


class State:
    def __init__(self, root: str, settings: Settings, ruleset: RuleSet) -> None:
        self.root = root
        self.settings = settings
        self.ruleset = ruleset
        self.disks: list[Disk] = []
        self.notes: list[str] = []
        self.result: ScanResult | None = None
        self.error = ""
        self.scanning = False
        self.progress = (0, 0.0)
        self.selected = 0
        self.cancel = threading.Event()
        self._lock = threading.Lock()

    def refresh_disks(self) -> None:
        self.disks, self.notes = list_disks()

    def start_scan(self) -> None:
        with self._lock:
            if self.scanning:
                return
            self.scanning = True
            self.error = ""
            self.cancel = threading.Event()
        self.refresh_disks()
        threading.Thread(target=self._scan, args=(self.cancel,), daemon=True).start()

    def _scan(self, cancel: threading.Event) -> None:
        def progress(n: int, elapsed: float) -> None:
            self.progress = (n, elapsed)

        try:
            scanner = Scanner(self.root, settings=self.settings, ruleset=self.ruleset,
                              progress=progress, cancel=cancel)
            res = scanner.run()
            if not cancel.is_set():
                self.result = res
                self.selected = 0
        except Exception as exc:  # the UI must survive any scan failure
            self.error = safe_text(f"scan failed: {exc}")
        finally:
            self.scanning = False


# ------------------------------------------------------------------ glyphs

class Glyphs:
    def __init__(self) -> None:
        try:
            codeset = locale.nl_langinfo(locale.CODESET).lower()
        except (AttributeError, ValueError):
            codeset = ""
        self.utf = "utf" in codeset
        self.full = "█" if self.utf else "#"
        self.empty = "░" if self.utf else "-"
        # Thin line glyphs for stacked rows: full blocks fill the whole cell
        # height, so bars on neighbouring rows would fuse into one slab.
        self.thin_full = "━" if self.utf else "="
        self.thin_empty = "─" if self.utf else "-"
        self.spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if self.utf else "|/-\\"
        self.dot = "●" if self.utf else "*"
        self.vline = "│" if self.utf else "|"
        self.corner = "└" if self.utf else "+"
        self.hline = "─" if self.utf else "-"


# ----------------------------------------------------------------- helpers

def _put(win, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    room = w - x - (1 if y == h - 1 else 0)
    if width is not None:
        room = min(room, width)
    if room <= 0:
        return
    try:
        win.addnstr(y, x, text, room, attr)
    except curses.error:
        pass


def _clip_middle(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    keep = width - 1
    head = keep // 2
    return text[:head] + "…" + text[len(text) - (keep - head):]


def _clip_end(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _cp(pid: int) -> int:
    return curses.color_pair(pid)


def _usage_attr(pct: float, settings: Settings) -> int:
    if pct >= settings.critical_percent:
        return _cp(P_BAD) | curses.A_BOLD
    if pct >= settings.warn_percent:
        return _cp(P_WARN)
    return _cp(P_OK)


def _disk_for(disks: list[Disk], path: str) -> Disk | None:
    best = None
    for d in disks:
        mount = d.mount.rstrip("/") + "/"
        if (path.rstrip("/") + "/").startswith(mount) and (best is None or len(d.mount) > len(best.mount)):
            best = d
    return best


def fmt_days(days: float) -> str:
    """Short age label: 3d, 5w, 14mo, 2y."""
    if days < 14:
        return f"{max(0, int(days))}d"
    if days < 60:
        return f"{int(days // 7)}w"
    if days < 730:
        return f"{int(round(days / 30.4))}mo"
    return f"{int(days // 365)}y"


def bucket_labels(bounds: list[int]) -> list[str]:
    labels = [f"< {fmt_days(bounds[0])}"]
    for lo, hi in zip(bounds, bounds[1:]):
        labels.append(f"{fmt_days(lo)} - {fmt_days(hi)}")
    labels.append(f"> {fmt_days(bounds[-1])}")
    return labels


# ------------------------------------------------------------------- donut

def donut_cells(rows: int, cols: int, fractions: list[float]) -> list[list[tuple[str, int]]]:
    """Rasterize a ring into braille cells. Returns rows x cols of (char, segment).

    A terminal cell is about twice as tall as wide and a braille cell holds 2x4
    dots, so a dot is roughly square and the ring comes out circular.
    """
    width, height = cols * 2, rows * 4
    cx, cy = width / 2.0, height / 2.0
    outer = min(width, height) / 2.0 - 0.5
    inner = outer * 0.58
    cuts, acc = [], 0.0
    for f in fractions:
        acc += max(0.0, f)
        cuts.append(acc)
    total = cuts[-1] if cuts else 0.0
    out: list[list[tuple[str, int]]] = []
    for r in range(rows):
        line = []
        for c in range(cols):
            mask, votes = 0, Counter()
            for dc in range(2):
                for dr in range(4):
                    dx = c * 2 + dc + 0.5 - cx
                    dy = r * 4 + dr + 0.5 - cy
                    dist = math.hypot(dx, dy)
                    if not (inner <= dist <= outer):
                        continue
                    frac = (math.atan2(dx, -dy) % (2 * math.pi)) / (2 * math.pi)
                    seg = len(cuts) - 1
                    for i, cut in enumerate(cuts):
                        if frac * total < cut or i == len(cuts) - 1:
                            seg = i
                            break
                    mask |= _BRAILLE[(dc, dr)]
                    votes[seg] += 1
            if mask:
                line.append((chr(0x2800 + mask), votes.most_common(1)[0][0]))
            else:
                line.append((" ", -1))
        out.append(line)
    return out


def draw_donut(win, y: int, x: int, rows: int, cols: int, fractions: list[float],
               attrs: list[int], g: Glyphs, center: tuple[str, str]) -> None:
    cells = donut_cells(rows, cols, fractions)
    for r, line in enumerate(cells):
        for c, (ch, seg) in enumerate(line):
            if seg < 0:
                continue
            if not g.utf:
                ch = g.full if bin(ord(ch) - 0x2800).count("1") >= 3 else "."
            _put(win, y + r, x + c, ch, attrs[seg % len(attrs)])
    big, small = center
    mid = y + rows // 2
    _put(win, mid - 1, x + max(0, (cols - len(big)) // 2), big, curses.A_BOLD)
    _put(win, mid, x + max(0, (cols - len(small)) // 2), small, _cp(P_DIM))


def legend_row(win, y: int, x: int, width: int, attr: int, name: str, size: int, pct: float, g: Glyphs) -> None:
    _put(win, y, x, g.dot, attr)
    name_w = max(4, width - 2 - 7 - 5 - 2)
    _put(win, y, x + 2, f"{_clip_end(safe_text(name), name_w):<{name_w}}", 0, name_w)
    _put(win, y, x + 2 + name_w + 1, f"{human_size(size):>6}", curses.A_BOLD)
    _put(win, y, x + 2 + name_w + 8, f"{pct:3.0f}%", _cp(P_DIM))


# ------------------------------------------------------------------ bars

def _draw_bar(win, y: int, x: int, width: int, frac: float, attr: int, g: Glyphs) -> None:
    filled = int(round(max(0.0, min(1.0, frac)) * width))
    _put(win, y, x, g.thin_full * filled, attr)
    _put(win, y, x + filled, g.thin_empty * (width - filled), _cp(P_DIM))


def _draw_stacked(win, y: int, x: int, width: int, parts: list[tuple[float, int]], g: Glyphs) -> None:
    cursor, acc = 0, 0.0
    for frac, attr in parts:
        acc += max(0.0, frac)
        end = min(width, int(round(acc * width)))
        if end > cursor:
            _put(win, y, x + cursor, g.full * (end - cursor), attr)
            cursor = end
    if cursor < width:
        _put(win, y, x + cursor, g.empty * (width - cursor), _cp(P_DIM))


# ------------------------------------------------------------- age graphs

def _age_attr(idx: int, count: int) -> int:
    pos = idx * (len(P_AGE) - 1) // max(1, count - 1)
    return _cp(P_AGE[pos])


def draw_age_histogram(win, y: int, x: int, width: int, res: ScanResult, g: Glyphs) -> int:
    """Bytes by last-modified bucket. Returns rows used."""
    labels = bucket_labels(res.age_bounds_days)
    total = sum(res.age_bytes) or 1
    peak = max(res.age_bytes) or 1
    label_w = max(len(s) for s in labels)
    stats_w = 6 + 2 + 4
    bar_w = max(6, width - label_w - stats_w - 4)
    for i, (label, size) in enumerate(zip(labels, res.age_bytes)):
        row = y + i * 1
        attr = _age_attr(i, len(labels))
        _put(win, row, x, f"{label:>{label_w}}", _cp(P_DIM))
        _draw_bar(win, row, x + label_w + 2, bar_w, size / peak, attr, g)
        _put(win, row, x + label_w + 3 + bar_w, f"{human_size(size):>6}", curses.A_BOLD)
        _put(win, row, x + label_w + 10 + bar_w, f"{percent(size, total):3.0f}%", _cp(P_DIM))
    return len(labels)


_SIZE_TICKS = [2 ** 20 * 4 ** i for i in range(0, 10)]  # 1M, 4M, 16M, ... 64G, 256G
_AGE_TICKS = [1, 7, 30, 90, 365, 1825]


def draw_scatter(win, y: int, x: int, width: int, height: int, items, selected: int,
                 now: float, g: Glyphs) -> None:
    """Items placed by last-modified age (x, log) and size (y, log).

    Dotted gridlines mark the tick values, each item is a colored point followed
    by its rank in the list, and both axes are labelled.
    """
    pts = [(i, it) for i, it in enumerate(items) if it.mtime > 0 and it.size > 0]
    label_w = 6
    pw, ph = width - label_w - 3, height - 3
    dim = _cp(P_DIM)
    if pw < 20 or ph < 3 or not pts:
        _put(win, y, x, "not enough data for the plot", dim)
        return
    ages = [max(1.0, (now - it.mtime) / DAY) for _, it in pts]
    sizes = [math.log10(it.size) for _, it in pts]
    x_hi = math.log10(max(max(ages), 365.0) * 1.2)
    y_lo, y_hi = min(sizes) - 0.25, max(sizes) + 0.25
    ox = x + label_w + 1                         # first plot column

    def col(days: float) -> int:
        return ox + 1 + int(min(1.0, math.log10(max(1.0, days)) / x_hi) * (pw - 3))

    def row(log_size: float) -> int:
        frac = (log_size - y_lo) / (y_hi - y_lo)
        return y + (ph - 1) - int(max(0.0, min(1.0, frac)) * (ph - 1))

    dot = "·" if g.utf else "."
    # horizontal gridlines + size labels
    for tick in _SIZE_TICKS:
        lg = math.log10(tick)
        if not (y_lo <= lg <= y_hi):
            continue
        ry = row(lg)
        _put(win, ry, x, f"{human_size(tick):>{label_w - 1}}", dim)
        _put(win, ry, ox + 1, dot * (pw - 1), dim)
    # vertical gridlines + age labels
    for days in _AGE_TICKS:
        if math.log10(days) > x_hi:
            continue
        cx = col(days)
        for r in range(ph):
            _put(win, y + r, cx, g.vline if g.utf else "|", dim)
        _put(win, y + ph + 1, max(ox, cx - 1), fmt_days(days), dim)
    # axes
    for r in range(ph):
        _put(win, y + r, ox, g.vline, dim)
    _put(win, y + ph, ox, g.corner + g.hline * (pw - 1), dim)
    _put(win, y - 1, x, "y: size", dim | curses.A_BOLD)
    _put(win, y - 1, x + width - 19, "x: last modified", dim | curses.A_BOLD)

    # points last, so they sit on top of the grid; the selected one on top of all
    order = sorted(zip(pts, ages, sizes), key=lambda t: t[0][0] == selected)
    for (idx, item), age, lg in order:
        cx, cy = col(age), row(lg)
        attr = _cp(P_TIER[item.tier]) | curses.A_BOLD
        sel = idx == selected
        if sel:
            attr |= curses.A_REVERSE
        _put(win, cy, cx, ("●" if g.utf else "o"), attr)
        _put(win, cy, cx + 1, str(idx + 1), (curses.A_BOLD | (curses.A_REVERSE if sel else 0)))


# ------------------------------------------------------------------- draw

def draw(win, st: State, g: Glyphs, tick: int) -> None:
    win.erase()
    h, w = win.getmaxyx()
    if h < MIN_ROWS or w < MIN_COLS:
        _put(win, 0, 0, f"Terminal too small ({w}x{h}); need {MIN_COLS}x{MIN_ROWS}. q quits.")
        win.refresh()
        return

    s = st.settings
    res = st.result
    head = _cp(P_HEAD) | curses.A_BOLD
    dim = _cp(P_DIM)
    margin = 2
    inner_w = w - margin * 2
    wide = w >= 100 and h >= 30
    show_age = res is not None and h >= 40 and w >= 76
    show_scatter = show_age and w >= 112

    y = 0
    _put(win, y, 0, " Storage Viewer ", head | curses.A_REVERSE)
    _put(win, y, 18, safe_text(st.root), dim)
    y += 2

    root_disk = _disk_for(st.disks, st.root)

    # ---- overview: donuts or bars ---------------------------------------
    if wide:
        d_rows, d_cols = 9, 20
        _put(win, y, margin, "DISK", head)
        half = w // 2
        _put(win, y, half, "HOME", head)
        y += 2
        top = y
        disk = root_disk or (st.disks[0] if st.disks else None)
        if disk:
            home_bytes = min(res.total, disk.used) if res else 0
            other = max(0, disk.used - home_bytes)
            fr = [home_bytes, other, disk.free]
            attrs = [_cp(P_SEG[0]), _cp(P_SEG[1]), dim]
            draw_donut(win, top, margin, d_rows, d_cols, fr, attrs, g,
                       (f"{disk.percent_used:.0f}%", "used"))
            lx, lw = margin + d_cols + 3, half - (margin + d_cols + 3) - 3
            _put(win, top, lx, _clip_end(f"{safe_text(disk.mount)}  {safe_text(disk.fstype)}", lw), curses.A_BOLD)
            legend_row(win, top + 2, lx, lw, attrs[0], "Home" if res else "Home (scanning)", home_bytes,
                       percent(home_bytes, disk.total), g)
            legend_row(win, top + 3, lx, lw, attrs[1], "Other used", other, percent(other, disk.total), g)
            legend_row(win, top + 4, lx, lw, attrs[2], "Free", disk.free, percent(disk.free, disk.total), g)
            _put(win, top + 5, lx + 2, f"of {human_size(disk.total)}", dim)
            row = top + 7
            for d in st.disks:
                if d is disk or row >= top + d_rows:
                    continue
                _put(win, row, lx, _clip_end(f"{safe_text(d.mount)}  {d.percent_used:.0f}% of {human_size(d.total)}", lw),
                     _usage_attr(d.percent_used, s))
                row += 1
        if res is None:
            n, secs = st.progress
            msg = st.error or f"{g.spin[tick % len(g.spin)]} scanning... {n:,} entries, {secs:.0f}s"
            _put(win, top + 2, half, msg, _cp(P_BAD) if st.error else dim)
        else:
            fr = [size for _, size in res.breakdown]
            attrs = [_cp(P_SEG[i % len(P_SEG)]) for i in range(len(fr))]
            draw_donut(win, top, half, d_rows, d_cols, fr, attrs, g, (human_size(res.total), "in home"))
            lx = half + d_cols + 3
            lw = w - lx - margin
            for i, (name, size) in enumerate(res.breakdown[:d_rows]):
                legend_row(win, top + i, lx, lw, attrs[i], name, size, percent(size, res.total), g)
        y = top + d_rows + 1
    else:
        _put(win, y, margin, "DISKS", head)
        y += 2
        label_w = min(14, max((len(d.mount) for d in st.disks), default=1) + 1)
        for d in st.disks:
            if y >= h - 12:
                break
            pct = d.percent_used
            stats = f"{pct:4.0f}%  {human_size(d.used)} / {human_size(d.total)}  ({human_size(d.free)} free)"
            bar_w = max(8, w - margin * 2 - label_w - len(stats) - 4)
            _put(win, y, margin, _clip_end(safe_text(d.mount), label_w - 1), curses.A_BOLD)
            _put(win, y, margin + label_w, "[", dim)
            _draw_bar(win, y, margin + label_w + 1, bar_w, pct / 100, _usage_attr(pct, s), g)
            _put(win, y, margin + label_w + 1 + bar_w, "]", dim)
            _put(win, y, margin + label_w + 3 + bar_w, stats, _usage_attr(pct, s))
            y += 1
        y += 1
        title = f"HOME  {safe_text(st.root)}"
        if res:
            title += f"  {human_size(res.total)}"
            if root_disk:
                title += f"  ({percent(res.total, root_disk.total):.0f}% of {safe_text(root_disk.mount)})"
        _put(win, y, margin, _clip_end(title, inner_w), head)
        y += 2
        if res is None:
            n, secs = st.progress
            msg = st.error or f"{g.spin[tick % len(g.spin)]} scanning... {n:,} entries, {secs:.0f}s"
            _put(win, y, margin, msg, _cp(P_BAD) if st.error else dim)
            y += 2
        else:
            segs = [(size / res.total if res.total else 0.0, _cp(P_SEG[i % len(P_SEG)]))
                    for i, (_, size) in enumerate(res.breakdown)]
            _draw_stacked(win, y, margin, inner_w, segs, g)
            y += 2
            cols = 2 if w >= 90 else 1
            col_w = inner_w // cols
            rows_n = (len(res.breakdown) + cols - 1) // cols
            for i, (name, size) in enumerate(res.breakdown):
                r, c = i % rows_n, i // rows_n
                if y + r < h - 10:
                    legend_row(win, y + r, margin + c * col_w, col_w - 2, _cp(P_SEG[i % len(P_SEG)]),
                               name, size, percent(size, res.total), g)
            y += min(rows_n, max(0, h - 10 - y)) + 1

    if res is not None:
        flags = []
        if st.scanning:
            flags.append(f"rescanning... {st.progress[0]:,} entries")
        if res.truncated:
            flags.append(f"partial scan: {res.truncated_reason}")
        if res.blocked:
            flags.append(f"{len(res.blocked)} folders unreadable (permission denied)")
        if flags:
            _put(win, y - 1, margin, _clip_end("! " + "; ".join(flags), inner_w), _cp(P_WARN))
            y += 1

    # ---- size vs last modified ------------------------------------------
    if show_age and res is not None and res.age_bytes:
        _put(win, y, margin, "SIZE BY LAST MODIFIED", head)
        if show_scatter:
            _put(win, y, w // 2, "BIGGEST ITEMS: SIZE vs AGE", head)
            _put(win, y, w // 2 + 28, "(numbers match the list below)", _cp(P_DIM))
        y += 2
        hist_w = (w // 2 - margin - 3) if show_scatter else inner_w
        used = draw_age_histogram(win, y, margin, hist_w, res, g)
        if show_scatter:
            draw_scatter(win, y, w // 2, w - w // 2 - margin, max(used + 3, 8), res.items, st.selected,
                         time.time(), g)
        y += max(used, 8 if show_scatter else 0) + 1

    # ---- ranked list -----------------------------------------------------
    _put(win, y, margin, "TOP ITEMS", head)
    _put(win, y, margin + 11, "most removable first", dim)
    y += 2
    footer = 4
    if res is not None:
        items = res.items
        avail = max(1, h - y - footer)
        # Breathing room between rows whenever the whole list still fits.
        step = 2 if len(items) * 2 - 1 <= avail else 1
        per_page = max(1, (avail + step - 1) // step)
        offset = max(0, st.selected - per_page + 1)
        biggest = max((i.size for i in items), default=1) or 1
        now = time.time()
        path_w = max(14, min(46, (w - 52) // 2))
        for row, item in enumerate(items[offset: offset + per_page]):
            idx = offset + row
            sel = idx == st.selected
            base = curses.A_REVERSE if sel else 0
            tier_attr = _cp(P_TIER[item.tier]) | curses.A_BOLD | base
            _put(win, y, 0, " " * (w - 1), base)
            x = margin
            _put(win, y, x, f"{idx + 1:>2}", dim | base)
            _put(win, y, x + 4, f"[{TIER_TAG[item.tier]}]", tier_attr)
            _put(win, y, x + 14, f"{human_size(item.size):>6}", curses.A_BOLD | base)
            filled = max(1, int(round(item.size / biggest * 8)))
            _put(win, y, x + 22, g.thin_full * filled, tier_attr)
            _put(win, y, x + 22 + filled, g.thin_empty * (8 - filled), dim | base)
            age = fmt_days((now - item.mtime) / DAY) if item.mtime > 0 else "?"
            _put(win, y, x + 32, f"{age:>4}", dim | base)
            px = x + 39
            _put(win, y, px, _clip_middle(("~/" + item.rel) if item.rel else "~", path_w), base)
            rx = px + path_w + 3
            if w - rx > 8:
                _put(win, y, rx, _clip_end(item.reason, w - rx - 1), dim | base)
            y += step
        if not items:
            _put(win, y, margin, "Nothing above the size threshold found.", dim)

    # ---- detail + keys ---------------------------------------------------
    if res is not None and res.items and 0 <= st.selected < len(res.items):
        item = res.items[st.selected]
        detail = f"{item.path}  -  {item.reason}"
        if item.blocked:
            detail += "  (some contents unreadable)"
        _put(win, h - 3, margin, _clip_end(detail, inner_w), curses.A_BOLD)
    _put(win, h - 2, margin, "age = newest file inside   SAFE regenerates   REVIEW only you can judge   KEEP personal data or code", dim)
    _put(win, h - 1, margin, "up/down select   r rescan   q quit      read-only: nothing is ever deleted", dim)
    win.refresh()


# --------------------------------------------------------------- main loop

def _init_colors() -> None:
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    bright = curses.COLORS >= 16
    # ANSI palette indexes: 1 red 2 green 3 yellow 4 blue 5 magenta 6 cyan, +8 bright.
    pairs = {
        P_OK: 2, P_WARN: 3, P_BAD: 1,
        P_DIM: 8 if bright else 7, P_HEAD: 6,
        P_SEG[0]: 4, P_SEG[1]: 5, P_SEG[2]: 6, P_SEG[3]: 2,
        P_SEG[4]: 3, P_SEG[5]: 1, P_SEG[6]: 12 if bright else 4, P_SEG[7]: 13 if bright else 5,
        P_TIER[rules.SAFE]: 2, P_TIER[rules.REVIEW]: 3, P_TIER[rules.KEEP]: 6,
    }
    ramp = [2, 10 if bright else 2, 6, 14 if bright else 6, 3, 11 if bright else 3, 5, 1, 9 if bright else 1]
    for pid, fg in zip(P_AGE, ramp):
        pairs[pid] = fg
    for pid, fg in pairs.items():
        try:
            curses.init_pair(pid, fg, bg)
        except curses.error:
            pass


def _loop(stdscr, st: State) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    if curses.has_colors():
        _init_colors()
    g = Glyphs()
    stdscr.timeout(120)
    st.start_scan()
    tick = 0
    last_disk_refresh = time.monotonic()
    while True:
        if time.monotonic() - last_disk_refresh > 5:
            st.refresh_disks()
            last_disk_refresh = time.monotonic()
        draw(stdscr, st, g, tick)
        tick += 1
        key = stdscr.getch()
        n = len(st.result.items) if st.result else 0
        if key in (ord("q"), ord("Q"), 27):
            st.cancel.set()
            return
        if key in (ord("r"), ord("R")):
            st.start_scan()
        elif key in (curses.KEY_DOWN, ord("j")) and n:
            st.selected = min(n - 1, st.selected + 1)
        elif key in (curses.KEY_UP, ord("k")) and n:
            st.selected = max(0, st.selected - 1)
        elif key in (curses.KEY_HOME, ord("g")):
            st.selected = 0
        elif key in (curses.KEY_END, ord("G")) and n:
            st.selected = n - 1


def run_tui(root: str, settings: Settings, ruleset: RuleSet) -> int:
    locale.setlocale(locale.LC_ALL, "")
    st = State(root, settings, ruleset)
    st.refresh_disks()
    try:
        curses.wrapper(_loop, st)
    except KeyboardInterrupt:
        st.cancel.set()
    return 0
