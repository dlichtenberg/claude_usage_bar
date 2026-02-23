#!/usr/bin/env python3
"""SwiftBar plugin to display Claude Pro/Max usage limits.

Reads OAuth credentials from the macOS Keychain (same ones Claude Code uses)
and calls the usage API to show rate limit utilization in the menu bar.

Filename encodes 5-minute refresh interval for SwiftBar.
"""

import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"

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
        return None, f"HTTP {e.code} {e.reason}"
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
    filled = round(pct / 100 * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def menu_bar_mini(pct):
    """Compact menu bar representation."""
    bar = progress_bar(pct, width=8)
    return f"C: {bar} {pct:.0f}%"


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

    headline_pct = max(
        five_hour.get("utilization", 0),
        seven_day.get("utilization", 0),
    )

    # ── Menu bar line ──
    color = color_for_pct(headline_pct)
    print(f"{menu_bar_mini(headline_pct)} | color={color} font=Menlo size=12")

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

    print("---")
    print("Refresh | refresh=true")


def main():
    token = get_access_token()
    if not token:
        print_error("No keychain credentials")
        sys.exit(0)

    data, api_err = fetch_usage(token)
    if api_err:
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
