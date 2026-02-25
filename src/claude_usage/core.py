"""Shared business logic for Claude usage display.

Pure stdlib — no rumps or PyObjC imports.
"""

import json
import logging
import os
import shutil
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"


def get_access_token():
    """Read the OAuth access token from the macOS Keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        logger.debug("Keychain lookup failed (exit %d)", result.returncode)
        return None

    raw = result.stdout.strip()
    if not raw:
        logger.debug("Keychain returned empty credentials")
        return None

    try:
        creds = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Keychain value is not JSON, using as raw token")
        return raw  # guaranteed non-empty by check above

    if not isinstance(creds, dict):
        logger.debug("Keychain JSON is not a dict")
        return None

    # Top-level token
    for key in ("accessToken", "access_token"):
        if key in creds:
            logger.debug("Found token under top-level key '%s'", key)
            return creds[key]

    # Nested under claudeAiOauth or similar
    for obj in creds.values():
        if isinstance(obj, dict):
            for key in ("accessToken", "access_token"):
                if key in obj:
                    logger.debug("Found token under nested key '%s'", key)
                    return obj[key]

    logger.warning("Keychain credentials present but no access token found")
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
            logger.debug("Usage API call succeeded")
            return data, None
    except urllib.error.HTTPError as e:
        code = f"HTTP {e.code} {e.reason}"
        err = "auth_expired" if e.code == 401 else code
        logger.warning("Usage API HTTP error: %s", code)
        return None, err
    except urllib.error.URLError as e:
        logger.warning("Usage API URL error: %s", e.reason)
        return None, f"URL error: {e.reason}"
    except json.JSONDecodeError:
        logger.warning("Usage API returned invalid JSON")
        return None, "Invalid JSON response"
    except Exception as e:
        logger.warning("Usage API unexpected error: %s", e)
        return None, f"{type(e).__name__}: {e}"


def find_claude():
    """Resolve the claude binary path, checking common locations."""
    found = shutil.which("claude")
    if found:
        logger.debug("Found claude via PATH: %s", found)
        return found
    for path in [
        os.path.expanduser("~/.local/bin/claude"),    # native installer
        os.path.expanduser("~/.claude/local/claude"),  # legacy
        "/usr/local/bin/claude",                       # Intel Homebrew / manual
        "/opt/homebrew/bin/claude",                    # Apple Silicon Homebrew
    ]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            logger.debug("Found claude at fallback path: %s", path)
            return path
    logger.warning("Claude CLI binary not found in PATH or fallback locations")
    return None


def trigger_claude_refresh():
    """Ask Claude Code to refresh its own tokens via `claude auth status`."""
    claude_bin = find_claude()
    if not claude_bin:
        logger.warning("Cannot refresh: Claude CLI not found")
        return False
    cmd = [claude_bin, "auth", "status"]
    logger.debug("Running token refresh: %s", cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning("Token refresh timed out after 15s")
        return False
    if result.returncode != 0:
        logger.warning("Token refresh failed (exit %d)", result.returncode)
        logger.debug(
            "Token refresh output: stdout=%s stderr=%s",
            result.stdout[:200] if result.stdout else b"",
            result.stderr[:200] if result.stderr else b"",
        )
        return False
    logger.debug("Token refresh succeeded")
    return True


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
