"""Tests for auth credential reading and OAuth token refresh logic."""

import json
import subprocess
from unittest import mock

import pytest

from claude_usage.core import (
    KEYCHAIN_SERVICE,
    OAUTH_CLIENT_ID,
    OAUTH_TOKEN_URL,
    _extract_field,
    get_access_token,
    get_credentials,
    get_refresh_token,
    refresh_oauth_token,
    trigger_token_refresh,
    write_credentials,
)


# ── Credential fixtures ──────────────────────────────────────────────────────

FLAT_CREDS = {
    "accessToken": "access-flat",
    "refreshToken": "refresh-flat",
}

NESTED_CREDS = {
    "claudeAiOauth": {
        "accessToken": "access-nested",
        "refreshToken": "refresh-nested",
    }
}

SNAKE_CASE_CREDS = {
    "access_token": "access-snake",
    "refresh_token": "refresh-snake",
}


def _mock_keychain(creds_dict):
    """Return a mock for subprocess.run that simulates a keychain lookup."""
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = json.dumps(creds_dict)
    return result


def _mock_keychain_fail():
    result = mock.MagicMock()
    result.returncode = 44  # security returns non-zero
    result.stdout = ""
    return result


# ── get_credentials ──────────────────────────────────────────────────────────

class TestGetCredentials:
    @mock.patch("claude_usage.core.subprocess.run")
    def test_returns_parsed_dict(self, mock_run):
        mock_run.return_value = _mock_keychain(FLAT_CREDS)
        creds = get_credentials()
        assert creds == FLAT_CREDS

    @mock.patch("claude_usage.core.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = _mock_keychain_fail()
        assert get_credentials() is None

    @mock.patch("claude_usage.core.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run):
        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = ""
        mock_run.return_value = result
        assert get_credentials() is None

    @mock.patch("claude_usage.core.subprocess.run")
    def test_returns_none_on_invalid_json(self, mock_run):
        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = "not-json"
        mock_run.return_value = result
        assert get_credentials() is None

    @mock.patch("claude_usage.core.subprocess.run")
    def test_returns_none_on_non_dict_json(self, mock_run):
        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = '["a", "b"]'
        mock_run.return_value = result
        assert get_credentials() is None


# ── _extract_field ───────────────────────────────────────────────────────────

class TestExtractField:
    def test_none_creds(self):
        assert _extract_field(None, "accessToken") is None

    def test_top_level(self):
        assert _extract_field(FLAT_CREDS, "accessToken") == "access-flat"

    def test_nested(self):
        assert _extract_field(NESTED_CREDS, "accessToken") == "access-nested"

    def test_snake_case_fallback(self):
        assert _extract_field(SNAKE_CASE_CREDS, "accessToken", "access_token") == "access-snake"

    def test_missing_field(self):
        assert _extract_field(FLAT_CREDS, "nonexistent") is None


# ── get_access_token / get_refresh_token ─────────────────────────────────────

class TestGetAccessToken:
    @mock.patch("claude_usage.core.subprocess.run")
    def test_flat_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(FLAT_CREDS)
        assert get_access_token() == "access-flat"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_nested_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(NESTED_CREDS)
        assert get_access_token() == "access-nested"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_snake_case_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(SNAKE_CASE_CREDS)
        assert get_access_token() == "access-snake"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_missing_returns_none(self, mock_run):
        mock_run.return_value = _mock_keychain({"other": "data"})
        assert get_access_token() is None


class TestGetRefreshToken:
    @mock.patch("claude_usage.core.subprocess.run")
    def test_flat_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(FLAT_CREDS)
        assert get_refresh_token() == "refresh-flat"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_nested_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(NESTED_CREDS)
        assert get_refresh_token() == "refresh-nested"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_snake_case_creds(self, mock_run):
        mock_run.return_value = _mock_keychain(SNAKE_CASE_CREDS)
        assert get_refresh_token() == "refresh-snake"

    @mock.patch("claude_usage.core.subprocess.run")
    def test_no_keychain_returns_none(self, mock_run):
        mock_run.return_value = _mock_keychain_fail()
        assert get_refresh_token() is None


# ── refresh_oauth_token ──────────────────────────────────────────────────────

class TestRefreshOAuthToken:
    @mock.patch("claude_usage.core.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        response_data = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 28800,
        }
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        data, err = refresh_oauth_token("old-refresh")
        assert err is None
        assert data["access_token"] == "new-access"
        assert data["refresh_token"] == "new-refresh"

        # Verify the request was made correctly
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == OAUTH_TOKEN_URL
        body = json.loads(req.data.decode())
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "old-refresh"
        assert body["client_id"] == OAUTH_CLIENT_ID

    @mock.patch("claude_usage.core.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        error = urllib.error.HTTPError(
            OAUTH_TOKEN_URL, 400, "Bad Request", {}, None
        )
        mock_urlopen.side_effect = error
        data, err = refresh_oauth_token("bad-refresh")
        assert data is None
        assert "400" in err

    @mock.patch("claude_usage.core.urllib.request.urlopen")
    def test_url_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        data, err = refresh_oauth_token("any-refresh")
        assert data is None
        assert "URL error" in err

    @mock.patch("claude_usage.core.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("timed out")
        data, err = refresh_oauth_token("any-refresh")
        assert data is None
        assert "TimeoutError" in err


# ── write_credentials ────────────────────────────────────────────────────────

class TestWriteCredentials:
    @mock.patch("claude_usage.core.subprocess.run")
    def test_success(self, mock_run):
        # Both delete and add succeed
        mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
        result = write_credentials({"accessToken": "tok"})
        assert result is True
        assert mock_run.call_count == 2

        # First call: delete
        delete_call = mock_run.call_args_list[0]
        assert "delete-generic-password" in delete_call[0][0]

        # Second call: add
        add_call = mock_run.call_args_list[1]
        assert "add-generic-password" in add_call[0][0]

    @mock.patch("claude_usage.core.subprocess.run")
    def test_add_failure(self, mock_run):
        # Delete succeeds, add fails
        def side_effect(cmd, **kwargs):
            r = mock.MagicMock()
            if "add-generic-password" in cmd:
                r.returncode = 1
                r.stderr = "error"
            else:
                r.returncode = 0
                r.stderr = ""
            return r
        mock_run.side_effect = side_effect
        result = write_credentials({"accessToken": "tok"})
        assert result is False

    @mock.patch("claude_usage.core.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = OSError("keychain locked")
        result = write_credentials({"accessToken": "tok"})
        assert result is False


# ── trigger_token_refresh ────────────────────────────────────────────────────

class TestTriggerTokenRefresh:
    @mock.patch("claude_usage.core.write_credentials")
    @mock.patch("claude_usage.core.refresh_oauth_token")
    @mock.patch("claude_usage.core.get_credentials")
    def test_direct_refresh_success(self, mock_get_creds, mock_refresh, mock_write):
        mock_get_creds.return_value = {
            "accessToken": "old-access",
            "refreshToken": "old-refresh",
        }
        mock_refresh.return_value = (
            {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 28800},
            None,
        )
        mock_write.return_value = True

        result = trigger_token_refresh()
        assert result is True
        mock_refresh.assert_called_once_with("old-refresh")

        # Check that credentials were updated
        written = mock_write.call_args[0][0]
        assert written["accessToken"] == "new-access"
        assert written["refreshToken"] == "new-refresh"

    @mock.patch("claude_usage.core._cli_refresh_fallback")
    @mock.patch("claude_usage.core.refresh_oauth_token")
    @mock.patch("claude_usage.core.get_credentials")
    def test_fallback_on_refresh_failure(self, mock_get_creds, mock_refresh, mock_fallback):
        mock_get_creds.return_value = {"refreshToken": "old-refresh"}
        mock_refresh.return_value = (None, "HTTP 401")
        mock_fallback.return_value = True

        result = trigger_token_refresh()
        assert result is True
        mock_fallback.assert_called_once()

    @mock.patch("claude_usage.core._cli_refresh_fallback")
    @mock.patch("claude_usage.core.get_credentials")
    def test_fallback_when_no_refresh_token(self, mock_get_creds, mock_fallback):
        mock_get_creds.return_value = {"accessToken": "tok"}
        mock_fallback.return_value = False

        result = trigger_token_refresh()
        assert result is False
        mock_fallback.assert_called_once()

    @mock.patch("claude_usage.core._cli_refresh_fallback")
    @mock.patch("claude_usage.core.write_credentials")
    @mock.patch("claude_usage.core.refresh_oauth_token")
    @mock.patch("claude_usage.core.get_credentials")
    def test_fallback_on_write_failure(self, mock_get_creds, mock_refresh, mock_write, mock_fallback):
        mock_get_creds.return_value = {"refreshToken": "old-refresh"}
        mock_refresh.return_value = (
            {"access_token": "new", "refresh_token": "new"},
            None,
        )
        mock_write.return_value = False
        mock_fallback.return_value = True

        result = trigger_token_refresh()
        assert result is True
        mock_fallback.assert_called_once()

    @mock.patch("claude_usage.core.write_credentials")
    @mock.patch("claude_usage.core.refresh_oauth_token")
    @mock.patch("claude_usage.core.get_credentials")
    def test_nested_creds_updated_correctly(self, mock_get_creds, mock_refresh, mock_write):
        mock_get_creds.return_value = {
            "claudeAiOauth": {
                "accessToken": "old-access",
                "refreshToken": "old-refresh",
            }
        }
        mock_refresh.return_value = (
            {"access_token": "new-access", "refresh_token": "new-refresh"},
            None,
        )
        mock_write.return_value = True

        result = trigger_token_refresh()
        assert result is True

        written = mock_write.call_args[0][0]
        nested = written["claudeAiOauth"]
        assert nested["accessToken"] == "new-access"
        assert nested["refreshToken"] == "new-refresh"
