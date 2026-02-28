"""LaunchAgent plist management for auto-start at login.

Pure stdlib — no rumps or PyObjC imports.
"""

from __future__ import annotations

import logging
import os
import plistlib
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LAUNCH_AGENT_LABEL = "com.github.dlichtenberg.claude-usage-bar"
LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
LAUNCH_AGENT_PATH = os.path.join(LAUNCH_AGENT_DIR, f"{LAUNCH_AGENT_LABEL}.plist")


def _is_valid_executable(path: str) -> bool:
    """Check that a path is an absolute, existing, executable file."""
    return (
        os.path.isabs(path)
        and os.path.isfile(path)
        and os.access(path, os.X_OK)
    )


def _get_executable_path() -> str | None:
    """Resolve the path to the claude-usage-bar executable.

    Checks: shutil.which (pip install), .app bundle, sys.argv[0] fallback.
    Returns ``None`` if no valid executable can be found.
    """
    found = shutil.which("claude-usage-bar")
    if found:
        return os.path.realpath(found)

    # Check alongside the Python interpreter (e.g. .venv/bin/claude-usage-bar).
    sibling = os.path.join(os.path.dirname(sys.executable), "claude-usage-bar")
    if _is_valid_executable(sibling):
        return os.path.realpath(sibling)

    # .app bundle: __file__ will be inside Something.app/Contents/...
    if ".app/Contents/" in __file__:
        file_path = Path(__file__)
        parts = file_path.parts
        try:
            idx = next(i for i, p in enumerate(parts) if p.endswith(".app"))
            app_name = parts[idx].removesuffix(".app")
            candidate = str(Path(*parts[: idx + 1]) / "Contents" / "MacOS" / app_name)
            if _is_valid_executable(candidate):
                return candidate
        except StopIteration:
            pass

    fallback = os.path.abspath(sys.argv[0])
    if _is_valid_executable(fallback):
        return fallback

    return None


def generate_launch_agent_plist(executable_path: str) -> str:
    """Generate a LaunchAgent plist XML string."""
    log_path = os.path.expanduser("~/Library/Logs/claude-usage-bar.log")
    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [executable_path],
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML).decode()


def install_launch_agent() -> bool:
    """Install the LaunchAgent plist. Returns True on success."""
    try:
        os.makedirs(LAUNCH_AGENT_DIR, exist_ok=True)
    except OSError as e:
        logger.warning("Failed to create LaunchAgents dir: %s", e)
        return False

    exe = _get_executable_path()
    if exe is None:
        logger.warning("Cannot install LaunchAgent: no valid executable found")
        return False
    logger.info("Resolved executable: %s", exe)
    plist_xml = generate_launch_agent_plist(exe)

    try:
        with open(LAUNCH_AGENT_PATH, "w") as f:
            f.write(plist_xml)
    except OSError as e:
        logger.warning("Failed to write LaunchAgent plist: %s", e)
        return False

    logger.info("LaunchAgent installed: %s", LAUNCH_AGENT_PATH)
    return True


def uninstall_launch_agent() -> bool:
    """Remove the LaunchAgent plist. Idempotent — returns True if absent."""
    if not os.path.isfile(LAUNCH_AGENT_PATH):
        return True
    try:
        os.remove(LAUNCH_AGENT_PATH)
    except OSError as e:
        logger.warning("Failed to remove LaunchAgent plist: %s", e)
        return False
    logger.info("LaunchAgent uninstalled: %s", LAUNCH_AGENT_PATH)
    return True


def is_launch_agent_installed() -> bool:
    """Check whether the LaunchAgent plist file exists."""
    return os.path.isfile(LAUNCH_AGENT_PATH)
