"""Tests for LaunchAgent install/uninstall logic."""

import plistlib
import sys
from unittest import mock

import pytest

from claude_usage.core import (
    LAUNCH_AGENT_LABEL,
    LAUNCH_AGENT_PATH,
    _get_executable_path,
    generate_launch_agent_plist,
    install_launch_agent,
    is_launch_agent_installed,
    uninstall_launch_agent,
)


# ── generate_launch_agent_plist ──────────────────────────────────────────────

class TestGenerateLaunchAgentPlist:
    def test_valid_xml(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        # Should be parseable by plistlib
        parsed = plistlib.loads(xml.encode())
        assert isinstance(parsed, dict)

    def test_label(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        parsed = plistlib.loads(xml.encode())
        assert parsed["Label"] == LAUNCH_AGENT_LABEL

    def test_program_arguments(self):
        exe = "/usr/local/bin/claude-usage-bar"
        xml = generate_launch_agent_plist(exe)
        parsed = plistlib.loads(xml.encode())
        assert parsed["ProgramArguments"] == [exe]

    def test_run_at_load(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        parsed = plistlib.loads(xml.encode())
        assert parsed["RunAtLoad"] is True

    def test_keep_alive_false(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        parsed = plistlib.loads(xml.encode())
        assert parsed["KeepAlive"] is False

    def test_log_paths(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        parsed = plistlib.loads(xml.encode())
        assert "StandardOutPath" in parsed
        assert "StandardErrorPath" in parsed
        assert "claude-usage-bar" in parsed["StandardOutPath"]

    def test_process_type_interactive(self):
        xml = generate_launch_agent_plist("/usr/local/bin/claude-usage-bar")
        parsed = plistlib.loads(xml.encode())
        assert parsed["ProcessType"] == "Interactive"


# ── _get_executable_path ─────────────────────────────────────────────────────

class TestGetExecutablePath:
    @mock.patch("claude_usage.core.shutil.which")
    def test_pip_install_via_which(self, mock_which):
        mock_which.return_value = "/usr/local/bin/claude-usage-bar"
        result = _get_executable_path()
        assert result == "/usr/local/bin/claude-usage-bar"
        mock_which.assert_called_once_with("claude-usage-bar")

    @mock.patch("claude_usage.core._is_valid_executable", return_value=True)
    @mock.patch("claude_usage.core.shutil.which", return_value=None)
    def test_app_bundle_detection(self, _mock_which, _mock_valid):
        fake_path = "/Applications/ClaudeUsage.app/Contents/MacOS/lib/core.py"
        with mock.patch("claude_usage.core.__file__", fake_path):
            result = _get_executable_path()
        assert result.endswith("ClaudeUsage.app/Contents/MacOS/ClaudeUsage")

    @mock.patch("claude_usage.core._is_valid_executable", return_value=True)
    @mock.patch("claude_usage.core.shutil.which", return_value=None)
    def test_fallback_to_sys_argv(self, _mock_which, _mock_valid):
        with mock.patch("claude_usage.core.__file__", "/some/venv/lib/core.py"):
            with mock.patch.object(sys, "argv", ["/home/user/.local/bin/claude-usage-bar"]):
                result = _get_executable_path()
        assert result == "/home/user/.local/bin/claude-usage-bar"

    @mock.patch("claude_usage.core._is_valid_executable", return_value=False)
    @mock.patch("claude_usage.core.shutil.which", return_value=None)
    def test_returns_none_when_no_valid_exe(self, _mock_which, _mock_valid):
        with mock.patch("claude_usage.core.__file__", "/some/venv/lib/core.py"):
            with mock.patch.object(sys, "argv", ["./relative-script"]):
                result = _get_executable_path()
        assert result is None


# ── install_launch_agent ─────────────────────────────────────────────────────

class TestInstallLaunchAgent:
    @mock.patch("claude_usage.core._get_executable_path", return_value="/usr/local/bin/claude-usage-bar")
    @mock.patch("claude_usage.core.os.makedirs")
    @mock.patch("builtins.open", mock.mock_open())
    def test_success_writes_file(self, mock_makedirs, _mock_exe):
        result = install_launch_agent()
        assert result is True
        mock_makedirs.assert_called_once()

    @mock.patch("claude_usage.core._get_executable_path", return_value="/usr/local/bin/claude-usage-bar")
    @mock.patch("claude_usage.core.os.makedirs", side_effect=OSError("permission denied"))
    def test_makedirs_failure(self, _mock_makedirs, _mock_exe):
        result = install_launch_agent()
        assert result is False

    @mock.patch("claude_usage.core._get_executable_path", return_value="/usr/local/bin/claude-usage-bar")
    @mock.patch("claude_usage.core.os.makedirs")
    @mock.patch("builtins.open", side_effect=OSError("permission denied"))
    def test_write_failure(self, _mock_open, _mock_makedirs, _mock_exe):
        result = install_launch_agent()
        assert result is False

    @mock.patch("claude_usage.core._get_executable_path", return_value=None)
    @mock.patch("claude_usage.core.os.makedirs")
    def test_no_valid_executable(self, _mock_makedirs, _mock_exe):
        result = install_launch_agent()
        assert result is False


# ── uninstall_launch_agent ───────────────────────────────────────────────────

class TestUninstallLaunchAgent:
    @mock.patch("claude_usage.core.os.path.isfile", return_value=True)
    @mock.patch("claude_usage.core.os.remove")
    def test_removes_existing_file(self, mock_remove, _mock_isfile):
        result = uninstall_launch_agent()
        assert result is True
        mock_remove.assert_called_once_with(LAUNCH_AGENT_PATH)

    @mock.patch("claude_usage.core.os.path.isfile", return_value=False)
    def test_noop_when_absent(self, _mock_isfile):
        result = uninstall_launch_agent()
        assert result is True  # idempotent

    @mock.patch("claude_usage.core.os.path.isfile", return_value=True)
    @mock.patch("claude_usage.core.os.remove", side_effect=OSError("permission denied"))
    def test_remove_failure(self, _mock_remove, _mock_isfile):
        result = uninstall_launch_agent()
        assert result is False


# ── is_launch_agent_installed ────────────────────────────────────────────────

class TestIsLaunchAgentInstalled:
    @mock.patch("claude_usage.core.os.path.isfile", return_value=True)
    def test_true_when_file_exists(self, _mock_isfile):
        assert is_launch_agent_installed() is True

    @mock.patch("claude_usage.core.os.path.isfile", return_value=False)
    def test_false_when_absent(self, _mock_isfile):
        assert is_launch_agent_installed() is False


# ── CLI flags ────────────────────────────────────────────────────────────────

class TestCLIFlags:
    @mock.patch("claude_usage.app.install_launch_agent", return_value=True)
    def test_install_flag_success(self, _mock_install):
        with mock.patch.object(sys, "argv", ["claude-usage-bar", "--install"]):
            with mock.patch("claude_usage.app.ClaudeUsageApp"):
                from claude_usage.app import main
                with mock.patch("claude_usage.app.sys.exit", side_effect=SystemExit) as mock_exit:
                    with pytest.raises(SystemExit):
                        main()
                    mock_exit.assert_called_once_with(0)

    @mock.patch("claude_usage.app.install_launch_agent", return_value=False)
    def test_install_flag_failure(self, _mock_install):
        with mock.patch.object(sys, "argv", ["claude-usage-bar", "--install"]):
            with mock.patch("claude_usage.app.ClaudeUsageApp"):
                from claude_usage.app import main
                with mock.patch("claude_usage.app.sys.exit", side_effect=SystemExit) as mock_exit:
                    with pytest.raises(SystemExit):
                        main()
                    mock_exit.assert_called_once_with(1)

    @mock.patch("claude_usage.app.uninstall_launch_agent", return_value=True)
    def test_uninstall_flag_success(self, _mock_uninstall):
        with mock.patch.object(sys, "argv", ["claude-usage-bar", "--uninstall"]):
            with mock.patch("claude_usage.app.ClaudeUsageApp"):
                from claude_usage.app import main
                with mock.patch("claude_usage.app.sys.exit", side_effect=SystemExit) as mock_exit:
                    with pytest.raises(SystemExit):
                        main()
                    mock_exit.assert_called_once_with(0)

    @mock.patch("claude_usage.app.uninstall_launch_agent", return_value=False)
    def test_uninstall_flag_failure(self, _mock_uninstall):
        with mock.patch.object(sys, "argv", ["claude-usage-bar", "--uninstall"]):
            with mock.patch("claude_usage.app.ClaudeUsageApp"):
                from claude_usage.app import main
                with mock.patch("claude_usage.app.sys.exit", side_effect=SystemExit) as mock_exit:
                    with pytest.raises(SystemExit):
                        main()
                    mock_exit.assert_called_once_with(1)
