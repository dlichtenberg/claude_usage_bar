"""Configuration persistence and display mode constants.

Pure stdlib — no rumps or PyObjC imports.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.config/claude_usage")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_SESSION = "session"
MODE_WEEK = "week"
MODE_HIGHEST = "highest"
MODE_COLOR_SPLIT = "color_split"
MODE_MARKER = "marker"
DEFAULT_MODE = MODE_MARKER


def load_config() -> dict[str, Any]:
    """Load config from ~/.config/claude_usage/config.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"display_mode": DEFAULT_MODE}


def save_config(config: dict[str, Any]) -> None:
    """Save config to ~/.config/claude_usage/config.json."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        logger.warning("Failed to save config: %s", e)
