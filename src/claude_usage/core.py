"""Shared business logic for Claude usage display.

Pure stdlib — no rumps or PyObjC imports.
"""

import json
import shutil
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CLAUDE_BIN = shutil.which("claude")


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
        return None, type(e).__name__


def trigger_claude_refresh():
    """Ask Claude Code to refresh its own tokens via `claude auth status`."""
    if not CLAUDE_BIN:
        return False
    result = subprocess.run(
        [CLAUDE_BIN, "auth", "status"],
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
    filled = round(pct / 100 * width)
    empty = width - filled
    return "\u2588" * filled + "\u2591" * empty


def menu_bar_text(pct):
    """Compact menu bar representation: C: ████░░░░ 42%"""
    bar = progress_bar(pct, width=8)
    return f"C: {bar} {pct:.0f}%"
