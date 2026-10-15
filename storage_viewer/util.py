"""Small shared helpers: size formatting and display-safe strings."""

from __future__ import annotations

_UNITS = ("B", "K", "M", "G", "T", "P")

# Longest string we ever hand to a UI. A filename can be up to 255 bytes and a
# path far longer; clipping here keeps one hostile entry from flooding a view.
MAX_DISPLAY = 240


def human_size(n: float) -> str:
    """Format a byte count as a short IEC-style string (1.5G, 980M, 12K)."""
    n = max(0.0, float(n))
    for unit in _UNITS:
        if n < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.1f}{unit}" if n < 10 else f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}P"  # pragma: no cover


def safe_text(value: object, limit: int = MAX_DISPLAY) -> str:
    """Make an untrusted string safe to print on a terminal or render in QML.

    Control characters (including ESC, which starts terminal escape sequences)
    and anything else unprintable are replaced, and the result is clipped.
    """
    text = str(value)
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in text)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned


def percent(part: float, whole: float) -> float:
    return 0.0 if whole <= 0 else max(0.0, min(100.0, part * 100.0 / whole))
