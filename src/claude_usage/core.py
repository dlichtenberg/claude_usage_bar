"""Shared business logic for Claude usage display.

Pure stdlib — no rumps or PyObjC imports.
"""

import json
import os
import shutil
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"

SESSION_COLOR = "#44BB44"  # green
WEEK_COLOR = "#4488FF"     # blue

CONFIG_DIR = os.path.expanduser("~/.config/claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_COLOR_SPLIT = "color_split"
MODE_MARKER = "marker"
DEFAULT_MODE = MODE_COLOR_SPLIT


def get_access_token():
    """Read the OAuth access token from the macOS Keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    try:
        creds = json.loads(raw)
    except json.JSONDecodeError:
        return raw if raw else None

    if not isinstance(creds, dict):
        return None

    # Top-level token
    for key in ("accessToken", "access_token"):
        if key in creds:
            return creds[key]

    # Nested under claudeAiOauth or similar
    for obj in creds.values():
        if isinstance(obj, dict):
            for key in ("accessToken", "access_token"):
                if key in obj:
                    return obj[key]

    return None


def fetch_usage(token):
    """Call the usage API. Returns (data, error_string)."""
    url = f"{BASE_API_URL}/api/oauth/usage"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "Claude-Usage-Bar/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            data = json.loads(body)
            return data, None
    except urllib.error.HTTPError as e:
        code = f"HTTP {e.code} {e.reason}"
        return None, ("auth_expired" if e.code == 401 else code)
    except urllib.error.URLError as e:
        return None, f"URL error: {e.reason}"
    except json.JSONDecodeError:
        return None, "Invalid JSON response"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _find_claude():
    """Resolve the claude binary path, checking common locations."""
    found = shutil.which("claude")
    if found:
        return found
    for path in [
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
    ]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def trigger_claude_refresh():
    """Ask Claude Code to refresh its own tokens via `claude auth status`."""
    claude_bin = _find_claude()
    if not claude_bin:
        return False
    result = subprocess.run(
        [claude_bin, "auth", "status"],
        capture_output=True, timeout=15,
    )
    return result.returncode == 0


def time_until(iso_timestamp):
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
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes and not days:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "<1m"
    except (ValueError, TypeError):
        return "?"


def color_hex_for_pct(pct):
    """Return a color hex string for the given utilization percentage."""
    if pct >= 80:
        return "#FF4444"  # red
    if pct >= 50:
        return "#FFAA00"  # amber
    return "#44BB44"      # green


def progress_bar(pct, width=10):
    """Build a Unicode progress bar string."""
    filled = max(0, min(width, round(pct / 100 * width)))
    empty = width - filled
    return "\u2588" * filled + "\u2591" * empty


def menu_bar_text(pct):
    """Compact menu bar representation: C: ████░░░░ 42%"""
    bar = progress_bar(pct, width=8)
    return f"C: {bar} {pct:.0f}%"


def marker_progress_bar(session_pct, week_pct, width=8):
    """Build a progress bar with session fill and a │ marker for week usage.

    Bar fills based on session, │ is placed at the week position.
    """
    session_filled = max(0, min(width, round(session_pct / 100 * width)))
    week_pos = max(0, min(width - 1, round(week_pct / 100 * (width - 1))))

    chars = []
    for i in range(width):
        if i == week_pos and week_pct > 0:
            chars.append("\u2502")  # │
        elif i < session_filled:
            chars.append("\u2588")  # █
        else:
            chars.append("\u2591")  # ░
    return "".join(chars)


def color_split_bar_segments(session_pct, week_pct, width=8):
    """Return a list of (text, color_hex) segments for the color-split bar.

    The lower usage fills from the left in its color, the higher continues
    filling in its color, and the remainder is empty.
    """
    session_filled = max(0, min(width, round(session_pct / 100 * width)))
    week_filled = max(0, min(width, round(week_pct / 100 * width)))

    if session_filled <= week_filled:
        lower_n, lower_color = session_filled, SESSION_COLOR
        upper_n, upper_color = week_filled, WEEK_COLOR
    else:
        lower_n, lower_color = week_filled, WEEK_COLOR
        upper_n, upper_color = session_filled, SESSION_COLOR

    segments = []
    if lower_n > 0:
        segments.append(("\u2588" * lower_n, lower_color))
    if upper_n - lower_n > 0:
        segments.append(("\u2588" * (upper_n - lower_n), upper_color))
    empty = width - upper_n
    if empty > 0:
        segments.append(("\u2591" * empty, None))
    return segments


def merged_menu_bar_text(session_pct, week_pct, mode):
    """Return menu bar text for merged display modes.

    For marker mode, returns a plain string.
    For color_split mode, returns a plain string (caller handles coloring).
    """
    headline_pct = max(session_pct, week_pct)
    if mode == MODE_MARKER:
        bar = marker_progress_bar(session_pct, week_pct, width=8)
    else:
        bar = progress_bar(headline_pct, width=8)
    return f"C: {bar} {headline_pct:.0f}%"


# ── Config persistence ───────────────────────────────────────────────────────

def load_config():
    """Load config from ~/.config/claude_usage/config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"display_mode": DEFAULT_MODE}


def save_config(config):
    """Save config to ~/.config/claude_usage/config.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
