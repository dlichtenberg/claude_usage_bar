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

SESSION_COLOR = "#44BB44"  # green
WEEK_COLOR = "#4488FF"     # blue

CONFIG_DIR = os.path.expanduser("~/.config/claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_SESSION = "session"
MODE_WEEK = "week"
MODE_HIGHEST = "highest"
MODE_COLOR_SPLIT = "color_split"
MODE_MARKER = "marker"
DEFAULT_MODE = MODE_MARKER


def get_credentials():
    """Read and parse the full credential dict from macOS Keychain.

    Returns the parsed dict, or None if credentials are missing / invalid.
    """
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
        logger.debug("Keychain value is not JSON")
        return None

    if not isinstance(creds, dict):
        logger.debug("Keychain JSON is not a dict")
        return None

    logger.debug("Keychain JSON keys: %s", list(creds.keys()))
    for k, v in creds.items():
        if isinstance(v, dict):
            logger.debug("  nested '%s' keys: %s", k, list(v.keys()))

    return creds


def _extract_field(creds, *key_names):
    """Search for a field in credentials, checking top-level then nested dicts."""
    if creds is None:
        return None

    # Top-level
    for key in key_names:
        if key in creds:
            logger.debug("Found field under top-level key '%s'", key)
            return creds[key]

    # Nested under claudeAiOauth or similar
    for obj in creds.values():
        if isinstance(obj, dict):
            for key in key_names:
                if key in obj:
                    logger.debug("Found field under nested key '%s'", key)
                    return obj[key]

    return None


def get_access_token():
    """Read the OAuth access token from credentials."""
    creds = get_credentials()
    token = _extract_field(creds, "accessToken", "access_token")
    if creds is not None and token is None:
        logger.warning("Keychain credentials present but no access token found")
    return token


def get_refresh_token():
    """Read the OAuth refresh token from credentials."""
    creds = get_credentials()
    return _extract_field(creds, "refreshToken", "refresh_token")


OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def refresh_oauth_token(refresh_token):
    """Exchange a refresh token for new access + refresh tokens.

    Returns (new_tokens_dict, error_string). On success the dict contains
    at least ``access_token`` and ``refresh_token``.
    """
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()

    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Claude-Usage-Bar/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            data = json.loads(body)
            logger.debug("OAuth token refresh succeeded")
            return data, None
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:200]
        except Exception:
            pass
        msg = f"HTTP {e.code}: {err_body}" if err_body else f"HTTP {e.code}"
        logger.warning("OAuth token refresh HTTP error: %s", msg)
        return None, msg
    except urllib.error.URLError as e:
        logger.warning("OAuth token refresh URL error: %s", e.reason)
        return None, f"URL error: {e.reason}"
    except Exception as e:
        logger.warning("OAuth token refresh error: %s", e)
        return None, f"{type(e).__name__}: {e}"


def write_credentials(creds_dict):
    """Write credentials back to the macOS Keychain.

    Deletes the old entry and adds a new one so Claude CLI stays in sync.
    Returns True on success, False on failure.
    """
    creds_json = json.dumps(creds_dict)
    try:
        # Delete old entry (ignore errors if it doesn't exist)
        subprocess.run(
            ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE],
            capture_output=True, timeout=10,
        )
        # Add new entry
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYCHAIN_SERVICE,
             "-a", "",
             "-w", creds_json,
             "-U"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Keychain write failed (exit %d): %s",
                           result.returncode, result.stderr.strip())
            return False
        logger.debug("Credentials written to keychain")
        return True
    except Exception as e:
        logger.warning("Keychain write error: %s", e)
        return False


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


def _cli_refresh_fallback():
    """Fallback: trigger a token refresh via a lightweight Claude CLI prompt."""
    claude_bin = find_claude()
    if not claude_bin:
        logger.warning("Cannot refresh via CLI: Claude CLI not found")
        return False
    cmd = [claude_bin, "-p", "one char response."]
    logger.debug("Running CLI fallback refresh: %s", cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning("CLI fallback refresh timed out after 15s")
        return False
    if result.returncode != 0:
        logger.warning("CLI fallback refresh failed (exit %d)", result.returncode)
        return False
    logger.debug("CLI fallback refresh succeeded")
    return True


def trigger_token_refresh():
    """Refresh the OAuth token directly via the Anthropic token endpoint.

    Falls back to Claude CLI prompt if direct refresh fails.
    """
    # 1. Get current credentials and refresh token
    creds = get_credentials()
    refresh_token = _extract_field(creds, "refreshToken", "refresh_token")

    if not refresh_token:
        logger.info("No refresh token found, falling back to CLI refresh")
        return _cli_refresh_fallback()

    # 2. Exchange refresh token for new tokens
    logger.info("Attempting direct OAuth token refresh")
    new_tokens, err = refresh_oauth_token(refresh_token)
    if err or not new_tokens:
        logger.warning("Direct token refresh failed: %s — falling back to CLI", err)
        return _cli_refresh_fallback()

    # 3. Merge new tokens into existing credential dict
    if creds is None:
        creds = {}

    # Update top-level or nested depending on where the token was found
    target = creds
    for obj in creds.values():
        if isinstance(obj, dict) and (
            "accessToken" in obj or "access_token" in obj
            or "refreshToken" in obj or "refresh_token" in obj
        ):
            target = obj
            break

    # Map OAuth response fields to credential keys
    if "access_token" in new_tokens:
        if "accessToken" in target:
            target["accessToken"] = new_tokens["access_token"]
        else:
            target["access_token"] = new_tokens["access_token"]
    if "refresh_token" in new_tokens:
        if "refreshToken" in target:
            target["refreshToken"] = new_tokens["refresh_token"]
        else:
            target["refresh_token"] = new_tokens["refresh_token"]
    if "expires_in" in new_tokens:
        target["expiresIn"] = new_tokens["expires_in"]
    if "expires_at" in new_tokens:
        target["expiresAt"] = new_tokens["expires_at"]

    # 4. Write back to keychain
    if not write_credentials(creds):
        logger.warning("Failed to write refreshed credentials, falling back to CLI")
        return _cli_refresh_fallback()

    logger.info("Direct token refresh succeeded")
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


def progress_bar_segments(pct, color, width=10):
    """Return (text, color_hex) segments for a progress bar.

    Filled blocks use the given color; empty blocks use a neutral gray
    so they stay visible on light backgrounds.
    """
    filled = max(0, min(width, round(pct / 100 * width)))
    empty = width - filled
    segments = []
    if filled:
        segments.append(("\u2588" * filled, color))
    if empty:
        segments.append(("\u2591" * empty, "#AAAAAA"))
    return segments


def menu_bar_text(pct):
    """Compact menu bar representation: C: ████░░░░ 42%"""
    bar = progress_bar(pct, width=8)
    return f"C: {bar} {pct:.0f}%"


def marker_progress_bar(session_pct, week_pct, width=8):
    """Build a progress bar with session fill and a │ marker for week usage.

    Bar fills based on session, │ is placed at the week position.
    Uses ┃ (thick vertical) when the marker falls inside the filled zone
    so no session block is visually lost.
    """
    session_filled = max(0, min(width, round(session_pct / 100 * width)))
    week_pos = max(0, min(width - 1, round(week_pct / 100 * (width - 1))))

    chars = []
    for i in range(width):
        if i == week_pos and week_pct > 0:
            chars.append("\u2503" if i < session_filled else "\u2502")  # ┃ or │
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
    # MODE_COLOR_SPLIT
    headline_pct = max(session_pct, week_pct)
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
