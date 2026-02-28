"""Keychain credential I/O and OAuth token refresh orchestration.

Pure stdlib — no rumps or PyObjC imports.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from claude_usage.api import refresh_oauth_token

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "Claude Code-credentials"
KEYCHAIN_TIMEOUT = 15
WRITE_RETRIES = 3
WRITE_RETRY_DELAY = 0.5
CLI_REFRESH_TIMEOUT = 15


# ── Keychain I/O ─────────────────────────────────────────────────────────────


def get_credentials() -> dict[str, Any] | None:
    """Read and parse the full credential dict from macOS Keychain.

    Returns the parsed dict, or ``None`` if credentials are missing / invalid.
    """
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=KEYCHAIN_TIMEOUT,
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


def get_keychain_account() -> str:
    """Discover the account name used by the existing keychain entry.

    Runs ``security find-generic-password`` without ``-w`` to get metadata,
    then parses the ``"acct"`` attribute.  Returns the account string, or
    ``""`` if the entry doesn't exist or the attribute can't be found.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            capture_output=True, text=True, timeout=KEYCHAIN_TIMEOUT,
        )
        if result.returncode != 0:
            logger.debug("Keychain account lookup failed (exit %d)", result.returncode)
            return ""
        m = re.search(r'"acct"<blob>="(.*?)"', result.stdout)
        if m:
            logger.debug("Discovered keychain account: %r", m.group(1))
            return m.group(1)
        logger.debug("No acct attribute found in keychain metadata")
        return ""
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("Keychain account discovery error: %s", e)
        return ""


def _extract_field(creds: dict[str, Any] | None, *key_names: str) -> Any | None:
    """Search for a field in credentials, checking top-level then nested dicts."""
    if creds is None:
        return None

    for key in key_names:
        if key in creds:
            logger.debug("Found field under top-level key '%s'", key)
            return creds[key]

    for obj in creds.values():
        if isinstance(obj, dict):
            for key in key_names:
                if key in obj:
                    logger.debug("Found field under nested key '%s'", key)
                    return obj[key]

    return None


def get_access_token() -> str | None:
    """Read the OAuth access token from credentials."""
    creds = get_credentials()
    token = _extract_field(creds, "accessToken", "access_token")
    if creds is not None and token is None:
        logger.warning("Keychain credentials present but no access token found")
    return token


def get_refresh_token() -> str | None:
    """Read the OAuth refresh token from credentials."""
    creds = get_credentials()
    return _extract_field(creds, "refreshToken", "refresh_token")


def write_credentials(creds_dict: dict[str, Any], account: str | None = None) -> bool:
    """Write credentials back to the macOS Keychain.

    Uses ``-U`` (update-or-add) for an atomic upsert so Claude CLI stays
    in sync and there is no window where credentials are absent.

    *account* is the ``-a`` value.  When ``None`` (default), the account is
    auto-discovered from the existing keychain entry so we update in place
    rather than creating a duplicate.
    Returns True on success, False on failure.
    """
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
            capture_output=True, text=True, timeout=KEYCHAIN_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning("Keychain write failed (exit %d): %s",
                           result.returncode, result.stderr.strip())
            return False
        logger.debug("Credentials written to keychain (account=%r)", account)
        return True
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("Keychain write error: %s", e)
        return False


# ── CLI discovery ─────────────────────────────────────────────────────────────


def find_claude() -> str | None:
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


# ── Token refresh orchestration ──────────────────────────────────────────────


def _cli_refresh_fallback() -> bool:
    """Fallback: trigger a token refresh via a lightweight Claude CLI prompt."""
    claude_bin = find_claude()
    if not claude_bin:
        logger.warning("Cannot refresh via CLI: Claude CLI not found")
        return False
    cmd = [claude_bin, "-p", "one char response."]
    logger.debug("Running CLI fallback refresh: %s", cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=CLI_REFRESH_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("CLI fallback refresh timed out after %ds", CLI_REFRESH_TIMEOUT)
        return False
    if result.returncode != 0:
        logger.warning("CLI fallback refresh failed (exit %d)", result.returncode)
        return False
    logger.debug("CLI fallback refresh succeeded")
    return True


def _find_token_target(creds: dict[str, Any]) -> dict[str, Any]:
    """Find the nested dict containing token fields, or return *creds* itself."""
    for obj in creds.values():
        if isinstance(obj, dict) and (
            "accessToken" in obj or "access_token" in obj
            or "refreshToken" in obj or "refresh_token" in obj
        ):
            return obj
    return creds


def _merge_token_field(
    target: dict[str, Any],
    new_tokens: dict[str, Any],
    oauth_key: str,
    camel_key: str,
) -> None:
    """Merge a single OAuth response field into the credential dict.

    Uses whichever key style (camelCase or snake_case) is already present
    in *target*.
    """
    if oauth_key in new_tokens:
        dest_key = camel_key if camel_key in target else oauth_key
        target[dest_key] = new_tokens[oauth_key]


def trigger_token_refresh() -> bool:
    """Refresh the OAuth token directly via the Anthropic token endpoint.

    Falls back to Claude CLI prompt only when the OAuth exchange itself
    fails or no refresh token is available.  After a successful exchange
    the old refresh token is consumed (invalidated server-side), so CLI
    fallback cannot help — we retry the keychain write instead.
    """
    creds = get_credentials()
    refresh_token = _extract_field(creds, "refreshToken", "refresh_token")

    if not refresh_token:
        logger.info("No refresh token found, falling back to CLI refresh")
        return _cli_refresh_fallback()

    # Discover the keychain account *before* consuming the refresh token
    account = get_keychain_account()

    logger.info("Attempting direct OAuth token refresh")
    new_tokens, err = refresh_oauth_token(refresh_token)
    if err or not new_tokens or "access_token" not in new_tokens:
        logger.warning("Direct token refresh failed: %s — falling back to CLI", err)
        return _cli_refresh_fallback()

    # ── Point of no return: old refresh token is now consumed ──

    target = _find_token_target(creds)
    _merge_token_field(target, new_tokens, "access_token", "accessToken")
    _merge_token_field(target, new_tokens, "refresh_token", "refreshToken")

    expires_in = new_tokens.get("expires_in")
    if expires_in is not None:
        target["expiresIn"] = expires_in
        target["expiresAt"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
    if "expires_at" in new_tokens:
        target["expiresAt"] = new_tokens["expires_at"]

    # Write back to keychain — retry since the old token is already gone
    for attempt in range(1, WRITE_RETRIES + 1):
        if write_credentials(creds, account=account):
            logger.info("Direct token refresh succeeded")
            return True
        logger.warning("Keychain write attempt %d/%d failed", attempt, WRITE_RETRIES)
        if attempt < WRITE_RETRIES:
            time.sleep(WRITE_RETRY_DELAY)

    logger.error(
        "All %d keychain write attempts failed after successful OAuth refresh; "
        "user must re-authenticate via Claude Code", WRITE_RETRIES,
    )
    return False
