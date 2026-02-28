"""HTTP client for Anthropic API and OAuth token exchange.

Pure stdlib — no rumps or PyObjC imports.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

BASE_API_URL = "https://api.anthropic.com"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
# Public OAuth client ID used by Claude Code (not a secret — public clients
# cannot maintain confidentiality per RFC 6749 §2.1).
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Cloudflare blocks Python's default User-Agent (error 1010).
USER_AGENT = "Claude-Usage-Bar/1.0"
DEFAULT_TIMEOUT = 10


def _api_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    method: str = "GET",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any] | None, str | None]:
    """Make an HTTP request and return ``(parsed_json, error_string)``.

    On success the error string is ``None``; on failure the data dict is
    ``None`` and the error string describes what went wrong.
    """
    all_headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if headers:
        all_headers.update(headers)

    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        all_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:200]
        except OSError:
            pass
        msg = f"HTTP {e.code}: {err_body}" if err_body else f"HTTP {e.code} {e.reason}"
        return None, msg
    except urllib.error.URLError as e:
        return None, f"URL error: {e.reason}"
    except json.JSONDecodeError:
        return None, "Invalid JSON response"
    except OSError as e:
        return None, f"{type(e).__name__}: {e}"


def refresh_oauth_token(
    refresh_token: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Exchange a refresh token for new access + refresh tokens.

    Returns ``(new_tokens_dict, error_string)``.  On success the dict
    contains at least ``access_token`` and ``refresh_token``.
    """
    data, err = _api_request(
        OAUTH_TOKEN_URL,
        method="POST",
        json_body={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        },
    )
    if data:
        logger.debug("OAuth token refresh succeeded")
    elif err:
        logger.warning("OAuth token refresh failed: %s", err)
    return data, err


def fetch_usage(token: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call the usage API.  Returns ``(data, error_string)``."""
    data, err = _api_request(
        f"{BASE_API_URL}/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    if err:
        if "HTTP 401" in err:
            logger.warning("Usage API HTTP error: %s", err)
            return None, "auth_expired"
        logger.warning("Usage API error: %s", err)
    else:
        logger.debug("Usage API call succeeded")
    return data, err
