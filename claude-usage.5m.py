#!/usr/bin/env python3
"""SwiftBar plugin to display Claude Pro/Max usage limits.

Reads OAuth credentials from the macOS Keychain (same ones Claude Code uses)
and calls the usage API to show rate limit utilization in the menu bar.

Filename encodes 5-minute refresh interval for SwiftBar.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

log_level = os.environ.get("CLAUDE_USAGE_LOG", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

BASE_API_URL = "https://api.anthropic.com"
KEYCHAIN_SERVICE = "Claude Code-credentials"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
# Public OAuth client ID used by Claude Code (not a secret — public clients
# cannot maintain confidentiality per RFC 6749 §2.1).
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

CONFIG_DIR = os.path.expanduser("~/.config/claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_SESSION = "session"
MODE_WEEK = "week"
MODE_HIGHEST = "highest"
MODE_COLOR_SPLIT = "color_split"
MODE_MARKER = "marker"
DEFAULT_MODE = MODE_MARKER

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_credentials():
    """Read and parse the full credential dict from macOS Keychain."""
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
        return None

    if not isinstance(creds, dict):
        return None

    logger.debug("Keychain JSON keys: %s", list(creds.keys()))
    for k, v in creds.items():
        if isinstance(v, dict):
            logger.debug("  nested '%s' keys: %s", k, list(v.keys()))

    return creds


def get_keychain_account():
    """Discover the account name used by the existing keychain entry."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return ""
        m = re.search(r'"acct"<blob>="(.*?)"', result.stdout)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _extract_field(creds, *key_names):
    """Search for a field in credentials, checking top-level then nested dicts."""
    if creds is None:
        return None
    for key in key_names:
        if key in creds:
            return creds[key]
    for obj in creds.values():
        if isinstance(obj, dict):
            for key in key_names:
                if key in obj:
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


def refresh_oauth_token(refresh_token):
    """Exchange a refresh token for new access + refresh tokens."""
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
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"HTTP {e.code}: {err_body}" if err_body else f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"URL error: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def write_credentials(creds_dict, account=None):
    """Write credentials back to the macOS Keychain."""
    if account is None:
        account = get_keychain_account()
    creds_json = json.dumps(creds_dict)
    try:
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", KEYCHAIN_SERVICE,
             "-a", account,
             "-w", creds_json,
             "-U"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def find_claude():
    """Resolve the claude binary path."""
    found = shutil.which("claude")
    if found:
        return found
    for path in [
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _cli_refresh_fallback():
    """Fallback: trigger a token refresh via a lightweight Claude CLI prompt."""
    claude_bin = find_claude()
    if not claude_bin:
        logger.warning("Cannot refresh via CLI: Claude CLI not found")
        return False
    logger.debug("Running CLI fallback refresh: %s", claude_bin)
    try:
        result = subprocess.run(
            [claude_bin, "-p", "one char response."],
            capture_output=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        logger.warning("CLI fallback refresh timed out after 15s")
        return False
    if result.returncode != 0:
        logger.warning("CLI fallback refresh failed (exit %d)", result.returncode)
        return False
    logger.debug("CLI fallback refresh succeeded")
    return True


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
    return "#d97757"      # brand orange



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
    if mode in (MODE_SESSION, MODE_MARKER):
        color = color_for_pct(session_pct)
    elif mode == MODE_WEEK:
        color = color_for_pct(week_pct)
    else:
        color = color_for_pct(headline_pct)
    print(f"{merged_menu_bar_mini(session_pct, week_pct, mode)} | color={color} font=Menlo size=12")

    print("---")

    # ── Session (5h) ──
    pct = five_hour.get("utilization", 0)
    c = "#d97757" if mode == MODE_COLOR_SPLIT else color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(five_hour.get("resets_at"))
    print(f"Session (5h)     {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=#444444")

    print("---")

    # ── Week (all models) ──
    pct = seven_day.get("utilization", 0)
    c = "#788c5d" if mode == MODE_COLOR_SPLIT else color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(seven_day.get("resets_at"))
    print(f"Week (all)       {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=#444444")

    print("---")

    # ── Week (Sonnet) ──
    pct = seven_day_sonnet.get("utilization", 0)
    c = color_for_pct(pct)
    bar = progress_bar(pct)
    resets = time_until(seven_day_sonnet.get("resets_at"))
    print(f"Week (Sonnet)    {bar} {pct:.0f}% | font=Menlo size=13 color={c}")
    print(f"  Resets in {resets} | font=Menlo size=11 color=#444444")

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
    mode_labels = {
        MODE_SESSION: "Session",
        MODE_WEEK: "Week",
        MODE_HIGHEST: "Highest",
        MODE_COLOR_SPLIT: "Color Split",
        MODE_MARKER: "Marker",
    }
    mode_label = mode_labels.get(mode, mode)
    print(f"Mode: {mode_label} | font=Menlo size=11 color=#444444")
    if mode == MODE_MARKER:
        print("  bar = session  ┃│ = week | font=Menlo size=11 color=#444444")

    print("---")
    print("Refresh | refresh=true")


WRITE_RETRIES = 3


def trigger_token_refresh():
    """Refresh the OAuth token directly, falling back to CLI if needed.

    After a successful OAuth exchange the old refresh token is consumed,
    so CLI fallback cannot help — we retry the keychain write instead.
    """
    creds = get_credentials()
    refresh_token = _extract_field(creds, "refreshToken", "refresh_token")

    if not refresh_token:
        logger.info("No refresh token found, falling back to CLI refresh")
        return _cli_refresh_fallback()

    # Discover account before consuming the refresh token
    account = get_keychain_account()

    logger.info("Attempting direct OAuth token refresh")
    new_tokens, err = refresh_oauth_token(refresh_token)
    if err or not new_tokens or "access_token" not in new_tokens:
        logger.warning("Direct token refresh failed: %s — falling back to CLI", err)
        return _cli_refresh_fallback()

    # ── Point of no return: old refresh token is now consumed ──

    target = creds
    for obj in creds.values():
        if isinstance(obj, dict) and (
            "accessToken" in obj or "access_token" in obj
            or "refreshToken" in obj or "refresh_token" in obj
        ):
            target = obj
            break

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

    # Compute expiresAt from expires_in (OAuth returns seconds, not a timestamp)
    expires_in = new_tokens.get("expires_in")
    if expires_in is not None:
        target["expiresIn"] = expires_in
        target["expiresAt"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
    if "expires_at" in new_tokens:
        target["expiresAt"] = new_tokens["expires_at"]

    # Retry keychain write since old token is already gone
    for attempt in range(1, WRITE_RETRIES + 1):
        if write_credentials(creds, account=account):
            logger.info("Direct token refresh succeeded")
            return True
        logger.warning("Keychain write attempt %d/%d failed", attempt, WRITE_RETRIES)
        if attempt < WRITE_RETRIES:
            time.sleep(0.5)

    logger.error(
        "All %d keychain write attempts failed after successful OAuth refresh; "
        "user must re-authenticate via Claude Code", WRITE_RETRIES,
    )
    return False


def main():
    token = get_access_token()
    if not token:
        print_error("No keychain credentials")
        sys.exit(0)

    data, api_err = fetch_usage(token)

    # If the token is expired, ask Claude Code to refresh and retry once
    if api_err == "auth_expired":
        if trigger_token_refresh():
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
