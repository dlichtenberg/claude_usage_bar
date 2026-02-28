"""Progress bars, colors, and menu bar text rendering.

Pure stdlib — no rumps or PyObjC imports.
"""

from __future__ import annotations

from datetime import datetime, timezone

from claude_usage.config import (
    MODE_COLOR_SPLIT,
    MODE_HIGHEST,
    MODE_MARKER,
    MODE_SESSION,
    MODE_WEEK,
)

SESSION_COLOR = "#d97757"  # brand orange
WEEK_COLOR = "#788c5d"     # brand green

HIGH_USAGE_THRESHOLD = 80
COLOR_RED = "#FF4444"
COLOR_EMPTY = "#AAAAAA"

FILLED_CHAR = "\u2588"   # █
EMPTY_CHAR = "\u2591"    # ░
THIN_MARKER = "\u2502"   # │
THICK_MARKER = "\u2503"  # ┃


def _bar_fill(pct: float, width: int) -> int:
    """Compute the number of filled blocks for a progress bar."""
    return max(0, min(width, round(pct / 100 * width)))


def time_until(iso_timestamp: str | None) -> str:
    """Return a human-readable string like '2h 13m' until the given ISO timestamp."""
    if not iso_timestamp:
        return "?"
    try:
        target = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = target - now
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "now"
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes and not days:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "<1m"
    except (ValueError, TypeError):
        return "?"


def color_hex_for_pct(pct: float) -> str:
    """Return a color hex string for the given utilization percentage."""
    if pct >= HIGH_USAGE_THRESHOLD:
        return COLOR_RED
    return SESSION_COLOR  # brand orange


def progress_bar(pct: float, width: int = 10) -> str:
    """Build a Unicode progress bar string."""
    filled = _bar_fill(pct, width)
    return FILLED_CHAR * filled + EMPTY_CHAR * (width - filled)


def progress_bar_segments(
    pct: float,
    color: str,
    width: int = 10,
) -> list[tuple[str, str]]:
    """Return ``(text, color_hex)`` segments for a progress bar.

    Filled blocks use the given color; empty blocks use a neutral gray
    so they stay visible on light backgrounds.
    """
    filled = _bar_fill(pct, width)
    empty = width - filled
    segments: list[tuple[str, str]] = []
    if filled:
        segments.append((FILLED_CHAR * filled, color))
    if empty:
        segments.append((EMPTY_CHAR * empty, COLOR_EMPTY))
    return segments


def menu_bar_text(pct: float) -> str:
    """Compact menu bar representation: ``C: ████░░░░ 42%``"""
    bar = progress_bar(pct, width=8)
    return f"C: {bar} {pct:.0f}%"


def marker_progress_bar(
    session_pct: float,
    week_pct: float,
    width: int = 8,
) -> str:
    """Build a progress bar with session fill and a marker for week usage.

    Bar fills based on session; ``│`` is placed at the week position.
    Uses ``┃`` (thick vertical) when the marker falls inside the filled zone
    so no session block is visually lost.
    """
    session_filled = _bar_fill(session_pct, width)
    week_pos = max(0, min(width - 1, round(week_pct / 100 * (width - 1))))

    chars: list[str] = []
    for i in range(width):
        if i == week_pos and week_pct > 0:
            chars.append(THICK_MARKER if i < session_filled else THIN_MARKER)
        elif i < session_filled:
            chars.append(FILLED_CHAR)
        else:
            chars.append(EMPTY_CHAR)
    return "".join(chars)


def color_split_bar_segments(
    session_pct: float,
    week_pct: float,
    width: int = 8,
) -> list[tuple[str, str | None]]:
    """Return ``(text, color_hex)`` segments for the color-split bar.

    The lower usage fills from the left in its color, the higher continues
    filling in its color, and the remainder is empty.
    """
    session_filled = _bar_fill(session_pct, width)
    week_filled = _bar_fill(week_pct, width)

    if session_filled <= week_filled:
        lower_n, lower_color = session_filled, SESSION_COLOR
        upper_n, upper_color = week_filled, WEEK_COLOR
    else:
        lower_n, lower_color = week_filled, WEEK_COLOR
        upper_n, upper_color = session_filled, SESSION_COLOR

    segments: list[tuple[str, str | None]] = []
    if lower_n > 0:
        segments.append((FILLED_CHAR * lower_n, lower_color))
    if upper_n - lower_n > 0:
        segments.append((FILLED_CHAR * (upper_n - lower_n), upper_color))
    empty = width - upper_n
    if empty > 0:
        segments.append((EMPTY_CHAR * empty, None))
    return segments


def merged_menu_bar_text(
    session_pct: float,
    week_pct: float,
    mode: str,
) -> str:
    """Return menu bar text for merged display modes.

    For marker mode, returns a plain string (% = session).
    For color_split mode, returns a plain string (caller handles coloring, % = max).
    For session/week/highest, shows single-metric bar and %.
    """
    if mode == MODE_SESSION:
        bar = progress_bar(session_pct, width=8)
        return f"C: {bar} {session_pct:.0f}%"
    if mode == MODE_WEEK:
        bar = progress_bar(week_pct, width=8)
        return f"C: {bar} {week_pct:.0f}%"
    if mode == MODE_HIGHEST:
        highest = max(session_pct, week_pct)
        bar = progress_bar(highest, width=8)
        return f"C: {bar} {highest:.0f}%"
    if mode == MODE_MARKER:
        bar = marker_progress_bar(session_pct, week_pct, width=8)
        return f"C: {bar} {session_pct:.0f}%"
    if mode == MODE_COLOR_SPLIT:
        headline_pct = max(session_pct, week_pct)
        bar = progress_bar(headline_pct, width=8)
        return f"C: {bar} {headline_pct:.0f}%"
    raise ValueError(f"Unknown display mode: {mode!r}")
