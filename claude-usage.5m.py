#!/usr/bin/env python3
"""SwiftBar plugin to display Claude Pro/Max usage limits.

Reads OAuth credentials from the macOS Keychain (same ones Claude Code uses)
and calls the usage API to show rate limit utilization in the menu bar.

Filename encodes 5-minute refresh interval for SwiftBar.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CLAUDE_BIN = shutil.which("claude")

CONFIG_DIR = os.path.expanduser("~/.config/claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_COLOR_SPLIT = "color_split"
MODE_MARKER = "marker"
DEFAULT_MODE = MODE_COLOR_SPLIT

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_access_token():
    """Read the OAuth access token from the macOS Keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True,
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
        "User-Agent": "SwiftBar-Claude-Usage/1.0",
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
        return None, str(type(e).__name__)


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


def color_for_pct(pct):
    """Return a SwiftBar-compatible color hex for the given percentage."""
    if pct >= 80:
        return "#FF4444"  # red
    if pct >= 50:
        return "#FFAA00"  # yellow/amber
    return "#44BB44"      # green



def progress_bar(pct, width=10):
    """Build a Unicode progress bar string."""
    filled = max(0, min(width, round(pct / 100 * width)))
    empty = width - filled
    return "█" * filled + "░" * empty


def marker_progress_bar(session_pct, week_pct, width=8):
    """Build a progress bar with session fill and a │ marker for week usage."""
    session_filled = max(0, min(width, round(session_pct / 100 * width)))
    week_pos = max(0, min(width - 1, round(week_pct / 100 * (width - 1))))

    chars = []
    for i in range(width):
        if i == week_pos and week_pct > 0:
            chars.append("┃" if i < session_filled else "│")
        elif i < session_filled:
            chars.append("█")
        else:
            chars.append("░")
    return "".join(chars)


def merged_menu_bar_mini(session_pct, week_pct, mode):
    """Menu bar text for merged display modes."""
    headline_pct = max(session_pct, week_pct)
    if mode == MODE_MARKER:
        bar = marker_progress_bar(session_pct, week_pct, width=8)
    else:
        bar = progress_bar(headline_pct, width=8)
    return f"C: {bar} {headline_pct:.0f}%"


def load_config():
    """Load config from ~/.config/claude_usage/config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"display_mode": DEFAULT_MODE}


# ── SwiftBar Output ──────────────────────────────────────────────────────────

def print_error(msg):
    """Show an error state in the menu bar."""
    print("C: ⚠️")
    print("---")
    print(f"Error: {msg} | color=red")
    print("---")
    print("Refresh | refresh=true")


def render(data):
    """Render the full SwiftBar output from API response data."""
    # Determine the "headline" percentage — use the highest utilization
    five_hour = data.get("five_hour", {})
    seven_day = data.get("seven_day", {})
    seven_day_sonnet = data.get("seven_day_sonnet", {})
    extra = data.get("extra_usage", {})

    session_pct = five_hour.get("utilization", 0)
    week_pct = seven_day.get("utilization", 0)
    headline_pct = max(session_pct, week_pct)

    config = load_config()
    mode = config.get("display_mode", DEFAULT_MODE)

    # ── Menu bar line ──
    # SwiftBar doesn't support per-character coloring, so color_split
    # falls back to a single-color bar. Marker mode works natively.
    color = color_for_pct(headline_pct)
    print(f"{merged_menu_bar_mini(session_pct, week_pct, mode)} | color={color} font=Menlo size=12")

    print("---")

    # ── Session (5h) ──
    pct = five_hour.get("utilization", 0)
    c = color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(five_hour.get("resets_at"))
    print(f"Session (5h)     {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=gray")

    print("---")

    # ── Week (all models) ──
    pct = seven_day.get("utilization", 0)
    c = color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(seven_day.get("resets_at"))
    print(f"Week (all)       {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=gray")

    print("---")

    # ── Week (Sonnet) ──
    pct = seven_day_sonnet.get("utilization", 0)
    c = color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(seven_day_sonnet.get("resets_at"))
    print(f"Week (Sonnet)    {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=gray")

    # ── Extra Usage (if enabled) ──
    if extra.get("is_enabled"):
        print("---")
        used_cents = extra.get("used_credits", 0)
        limit_cents = extra.get("monthly_limit", 0)
        used_dollars = used_cents / 100
        limit_dollars = limit_cents / 100
        pct = extra.get("utilization", 0) or 0
        c = color_for_pct(pct)
        bar = progress_bar(pct)
        print(f"Extra Usage      ${used_dollars:.2f} / ${limit_dollars:.2f} | font=Menlo size=13")
        print(f"                 {bar} {pct:.0f}% | font=Menlo size=13 color={c}")

    # ── Display Mode (read-only, changed via standalone app) ──
    print("---")
    mode_label = "Color Split" if mode == MODE_COLOR_SPLIT else "Marker"
    print(f"Mode: {mode_label} | font=Menlo size=11 color=gray")
    if mode == MODE_MARKER:
        print("  bar = session  ┃│ = week | font=Menlo size=11 color=gray")

    print("---")
    print("Refresh | refresh=true")


def trigger_claude_refresh():
    """Ask Claude Code to refresh its own tokens via `claude auth status`."""
    if not CLAUDE_BIN:
        return False
    result = subprocess.run(
        [CLAUDE_BIN, "auth", "status"],
        capture_output=True, timeout=15,
    )
    return result.returncode == 0


def main():
    token = get_access_token()
    if not token:
        print_error("No keychain credentials")
        sys.exit(0)

    data, api_err = fetch_usage(token)

    # If the token is expired, ask Claude Code to refresh and retry once
    if api_err == "auth_expired":
        if trigger_claude_refresh():
            token = get_access_token()
            if token:
                data, api_err = fetch_usage(token)

    if api_err:
        if api_err == "auth_expired":
            print_error("Token expired — open Claude Code to re-auth")
        else:
            print_error(api_err)
        sys.exit(0)

    render(data)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Suppress tracebacks to avoid leaking credentials in error output
        print_error("Unexpected error")
        sys.exit(0)
