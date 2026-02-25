"""Tests for display mode logic in core.py and claude-usage.5m.py (SwiftBar plugin).

Covers the five display modes (session, week, highest, color_split, marker),
default mode, panel colors, bar color selection, and contrast settings.
"""

import importlib.util
import re
import sys
import textwrap
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest

# ── Import core module normally ──────────────────────────────────────────────

from claude_usage.core import (
    DEFAULT_MODE,
    MODE_COLOR_SPLIT,
    MODE_HIGHEST,
    MODE_MARKER,
    MODE_SESSION,
    MODE_WEEK,
    SESSION_COLOR,
    WEEK_COLOR,
    color_hex_for_pct,
    color_split_bar_segments,
    marker_progress_bar,
    merged_menu_bar_text,
    progress_bar,
)

# ── Import SwiftBar module as a standalone module ────────────────────────────

SWIFTBAR_PATH = Path(__file__).resolve().parent.parent / "claude-usage.5m.py"


@pytest.fixture()
def swiftbar():
    """Import the SwiftBar plugin as a module (skipping main execution)."""
    spec = importlib.util.spec_from_file_location("swiftbar_plugin", SWIFTBAR_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Prevent it from running main() on import
    with mock.patch.object(mod, "__name__", "swiftbar_plugin"):
        spec.loader.exec_module(mod)
    return mod


# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_pct(text):
    """Extract the trailing percentage number from menu bar text like 'C: ████░░░░ 30%'."""
    m = re.search(r"(\d+)%", text)
    assert m, f"No percentage found in: {text!r}"
    return int(m.group(1))


# ── Mode constants ───────────────────────────────────────────────────────────

class TestModeConstants:
    def test_all_modes_are_distinct(self):
        modes = [MODE_SESSION, MODE_WEEK, MODE_HIGHEST, MODE_COLOR_SPLIT, MODE_MARKER]
        assert len(set(modes)) == 5

    def test_default_mode_is_marker(self):
        assert DEFAULT_MODE == MODE_MARKER

    def test_swiftbar_default_mode_is_marker(self, swiftbar):
        assert swiftbar.DEFAULT_MODE == "marker"

    def test_swiftbar_has_all_mode_constants(self, swiftbar):
        assert swiftbar.MODE_SESSION == "session"
        assert swiftbar.MODE_WEEK == "week"
        assert swiftbar.MODE_HIGHEST == "highest"
        assert swiftbar.MODE_COLOR_SPLIT == "color_split"
        assert swiftbar.MODE_MARKER == "marker"


# ── merged_menu_bar_text (core.py) ───────────────────────────────────────────

class TestMergedMenuBarText:
    """Test that each mode shows the correct percentage and bar."""

    S, W = 30, 60  # session < week

    def test_session_mode_shows_session_pct(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_SESSION)
        assert extract_pct(text) == self.S

    def test_week_mode_shows_week_pct(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_WEEK)
        assert extract_pct(text) == self.W

    def test_highest_mode_shows_max_pct(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_HIGHEST)
        assert extract_pct(text) == max(self.S, self.W)

    def test_color_split_mode_shows_max_pct(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_COLOR_SPLIT)
        assert extract_pct(text) == max(self.S, self.W)

    def test_marker_mode_shows_session_pct(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_MARKER)
        assert extract_pct(text) == self.S

    def test_marker_mode_shows_session_pct_when_session_higher(self):
        text = merged_menu_bar_text(70, 20, MODE_MARKER)
        assert extract_pct(text) == 70

    def test_all_modes_start_with_prefix(self):
        for mode in [MODE_SESSION, MODE_WEEK, MODE_HIGHEST, MODE_COLOR_SPLIT, MODE_MARKER]:
            text = merged_menu_bar_text(self.S, self.W, mode)
            assert text.startswith("C: ")

    def test_session_mode_bar_length(self):
        text = merged_menu_bar_text(self.S, self.W, MODE_SESSION)
        bar = text[3:].split()[0]  # strip "C: " prefix, take bar before space
        assert len(bar) == 8

    def test_zero_values(self):
        for mode in [MODE_SESSION, MODE_WEEK, MODE_HIGHEST, MODE_COLOR_SPLIT, MODE_MARKER]:
            text = merged_menu_bar_text(0, 0, mode)
            assert extract_pct(text) == 0

    def test_full_values(self):
        text = merged_menu_bar_text(100, 100, MODE_HIGHEST)
        assert extract_pct(text) == 100


# ── merged_menu_bar_mini (SwiftBar) ──────────────────────────────────────────

class TestSwiftBarMergedMenuBarMini:
    """Mirror tests for the SwiftBar standalone version."""

    S, W = 30, 60

    def test_session_mode_shows_session_pct(self, swiftbar):
        text = swiftbar.merged_menu_bar_mini(self.S, self.W, "session")
        assert extract_pct(text) == self.S

    def test_week_mode_shows_week_pct(self, swiftbar):
        text = swiftbar.merged_menu_bar_mini(self.S, self.W, "week")
        assert extract_pct(text) == self.W

    def test_highest_mode_shows_max_pct(self, swiftbar):
        text = swiftbar.merged_menu_bar_mini(self.S, self.W, "highest")
        assert extract_pct(text) == max(self.S, self.W)

    def test_color_split_mode_shows_max_pct(self, swiftbar):
        text = swiftbar.merged_menu_bar_mini(self.S, self.W, "color_split")
        assert extract_pct(text) == max(self.S, self.W)

    def test_marker_mode_shows_session_pct(self, swiftbar):
        text = swiftbar.merged_menu_bar_mini(self.S, self.W, "marker")
        assert extract_pct(text) == self.S

    def test_parity_with_core(self, swiftbar):
        """SwiftBar merged_menu_bar_mini should match core merged_menu_bar_text."""
        for mode in ["session", "week", "highest", "color_split", "marker"]:
            core_text = merged_menu_bar_text(self.S, self.W, mode)
            sb_text = swiftbar.merged_menu_bar_mini(self.S, self.W, mode)
            assert extract_pct(core_text) == extract_pct(sb_text), (
                f"Parity mismatch for mode {mode!r}: core={core_text!r}, swiftbar={sb_text!r}"
            )


# ── Bar color selection per mode ─────────────────────────────────────────────

class TestBarColorSelection:
    """Verify the correct severity color is picked for each mode."""

    def test_session_mode_uses_session_color(self):
        # session=85 (red), week=10 (green) — session mode should be red
        assert color_hex_for_pct(85) == "#FF4444"
        assert color_hex_for_pct(10) == "#44BB44"

    def test_week_mode_uses_week_color(self):
        # session=10 (green), week=85 (red) — week mode should be red
        assert color_hex_for_pct(10) == "#44BB44"
        assert color_hex_for_pct(85) == "#FF4444"

    def test_highest_uses_max_color(self):
        # max(10, 85) = 85 → red
        assert color_hex_for_pct(max(10, 85)) == "#FF4444"

    def test_color_thresholds(self):
        assert color_hex_for_pct(0) == "#44BB44"
        assert color_hex_for_pct(49) == "#44BB44"
        assert color_hex_for_pct(50) == "#FFAA00"
        assert color_hex_for_pct(79) == "#FFAA00"
        assert color_hex_for_pct(80) == "#FF4444"
        assert color_hex_for_pct(100) == "#FF4444"


# ── Panel colors ─────────────────────────────────────────────────────────────

class TestPanelColors:
    """Verify session/week rows use fixed colors only in color_split mode."""

    def test_session_color_constant(self):
        assert SESSION_COLOR == "#44BB44"

    def test_week_color_constant(self):
        assert WEEK_COLOR == "#4488FF"

    def test_swiftbar_session_row_green_in_color_split(self, swiftbar):
        """Session line uses #44BB44 in color_split mode."""
        data = self._make_data(session_pct=90, week_pct=10)
        output = self._capture_render(swiftbar, data, mode="color_split")
        session_line = [l for l in output.splitlines() if l.startswith("Session (5h)")][0]
        assert "color=#44BB44" in session_line

    def test_swiftbar_week_row_blue_in_color_split(self, swiftbar):
        """Week (all) line uses #4488FF in color_split mode."""
        data = self._make_data(session_pct=10, week_pct=90)
        output = self._capture_render(swiftbar, data, mode="color_split")
        week_line = [l for l in output.splitlines() if l.startswith("Week (all)")][0]
        assert "color=#4488FF" in week_line

    def test_swiftbar_session_row_severity_in_marker(self, swiftbar):
        """Session line uses severity color (red for 90%) in non-color_split modes."""
        data = self._make_data(session_pct=90, week_pct=10)
        output = self._capture_render(swiftbar, data, mode="marker")
        session_line = [l for l in output.splitlines() if l.startswith("Session (5h)")][0]
        assert "color=#FF4444" in session_line

    def test_swiftbar_week_row_severity_in_marker(self, swiftbar):
        """Week (all) line uses severity color (red for 90%) in non-color_split modes."""
        data = self._make_data(session_pct=10, week_pct=90)
        output = self._capture_render(swiftbar, data, mode="marker")
        week_line = [l for l in output.splitlines() if l.startswith("Week (all)")][0]
        assert "color=#FF4444" in week_line

    def test_swiftbar_sonnet_row_uses_severity_color(self, swiftbar):
        """Week (Sonnet) should always use severity-based coloring."""
        data = self._make_data(session_pct=10, week_pct=10, sonnet_pct=90)
        output = self._capture_render(swiftbar, data, mode="color_split")
        sonnet_line = [l for l in output.splitlines() if l.startswith("Week (Sonnet)")][0]
        # 90% → red
        assert "color=#FF4444" in sonnet_line

    @staticmethod
    def _make_data(session_pct=0, week_pct=0, sonnet_pct=0):
        return {
            "five_hour": {"utilization": session_pct, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": week_pct, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": sonnet_pct, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }

    @staticmethod
    def _capture_render(swiftbar, data, mode="marker"):
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": mode}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        return buf.getvalue()


# ── Contrast: #999999 → #444444 ─────────────────────────────────────────────

class TestContrast:
    """Verify reset labels and hint text use #444444 (not #999999)."""

    def test_swiftbar_no_gray_keyword(self):
        """The SwiftBar source should not contain 'color=gray'."""
        source = SWIFTBAR_PATH.read_text()
        # Only check inside the render function area, not comments
        assert "color=gray" not in source

    def test_swiftbar_no_999999(self):
        """The SwiftBar source should not contain '#999999'."""
        source = SWIFTBAR_PATH.read_text()
        assert "#999999" not in source

    def test_swiftbar_reset_lines_use_444444(self, swiftbar):
        data = {
            "five_hour": {"utilization": 30, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 40, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 20, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": "marker"}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        output = buf.getvalue()
        reset_lines = [l for l in output.splitlines() if "Resets in" in l]
        assert len(reset_lines) == 3
        for line in reset_lines:
            assert "color=#444444" in line

    def test_swiftbar_mode_label_uses_444444(self, swiftbar):
        data = {
            "five_hour": {"utilization": 30, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 40, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 20, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": "marker"}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        output = buf.getvalue()
        mode_line = [l for l in output.splitlines() if l.startswith("Mode:")][0]
        assert "color=#444444" in mode_line

    def test_swiftbar_marker_legend_uses_444444(self, swiftbar):
        data = {
            "five_hour": {"utilization": 30, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 40, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 20, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": "marker"}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        output = buf.getvalue()
        legend_lines = [l for l in output.splitlines() if "bar = session" in l]
        assert len(legend_lines) == 1
        assert "color=#444444" in legend_lines[0]

    def test_app_source_no_999999(self):
        """app.py should not contain '#999999'."""
        app_path = Path(__file__).resolve().parent.parent / "src" / "claude_usage" / "app.py"
        source = app_path.read_text()
        assert "#999999" not in source


# ── SwiftBar mode label rendering ────────────────────────────────────────────

class TestSwiftBarModeLabels:
    """Verify the mode label in SwiftBar output matches each mode."""

    @pytest.fixture()
    def data(self):
        return {
            "five_hour": {"utilization": 30, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 40, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 20, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }

    @pytest.mark.parametrize("mode,expected_label", [
        ("session", "Mode: Session"),
        ("week", "Mode: Week"),
        ("highest", "Mode: Highest"),
        ("color_split", "Mode: Color Split"),
        ("marker", "Mode: Marker"),
    ])
    def test_mode_label(self, swiftbar, data, mode, expected_label):
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": mode}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        output = buf.getvalue()
        mode_line = [l for l in output.splitlines() if l.startswith("Mode:")][0]
        assert mode_line.startswith(expected_label)

    def test_marker_legend_only_in_marker_mode(self, swiftbar, data):
        for mode in ["session", "week", "highest", "color_split"]:
            buf = StringIO()
            with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": mode}):
                with mock.patch("sys.stdout", buf):
                    swiftbar.render(data)
            output = buf.getvalue()
            legend_lines = [l for l in output.splitlines() if "bar = session" in l]
            assert len(legend_lines) == 0, f"Legend should not appear in mode {mode!r}"


# ── SwiftBar bar color per mode ──────────────────────────────────────────────

class TestSwiftBarBarColor:
    """Verify the menu bar line color in SwiftBar output matches mode semantics."""

    @staticmethod
    def _get_menu_bar_color(swiftbar, data, mode):
        buf = StringIO()
        with mock.patch.object(swiftbar, "load_config", return_value={"display_mode": mode}):
            with mock.patch("sys.stdout", buf):
                swiftbar.render(data)
        first_line = buf.getvalue().splitlines()[0]
        m = re.search(r"color=([#\w]+)", first_line)
        assert m, f"No color found in menu bar line: {first_line!r}"
        return m.group(1)

    def test_session_mode_color_follows_session(self, swiftbar):
        # session=85 (red), week=10 (green)
        data = {
            "five_hour": {"utilization": 85, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 0, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        color = self._get_menu_bar_color(swiftbar, data, "session")
        assert color == "#FF4444"  # red for 85%

    def test_week_mode_color_follows_week(self, swiftbar):
        # session=10 (green), week=85 (red)
        data = {
            "five_hour": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 85, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 0, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        color = self._get_menu_bar_color(swiftbar, data, "week")
        assert color == "#FF4444"  # red for 85%

    def test_highest_mode_color_follows_max(self, swiftbar):
        # session=10, week=85 → max=85 → red
        data = {
            "five_hour": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 85, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 0, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        color = self._get_menu_bar_color(swiftbar, data, "highest")
        assert color == "#FF4444"

    def test_session_mode_green_when_session_low(self, swiftbar):
        # session=10 (green), week=85 (red) — session mode should be green
        data = {
            "five_hour": {"utilization": 10, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day": {"utilization": 85, "resets_at": "2099-01-01T00:00:00Z"},
            "seven_day_sonnet": {"utilization": 0, "resets_at": "2099-01-01T00:00:00Z"},
            "extra_usage": {},
        }
        color = self._get_menu_bar_color(swiftbar, data, "session")
        assert color == "#44BB44"  # green for 10%


# ── Progress bar helpers ─────────────────────────────────────────────────────

class TestProgressBar:
    def test_empty(self):
        bar = progress_bar(0, width=8)
        assert bar == "\u2591" * 8

    def test_full(self):
        bar = progress_bar(100, width=8)
        assert bar == "\u2588" * 8

    def test_half(self):
        bar = progress_bar(50, width=8)
        assert len(bar) == 8
        assert "\u2588" in bar
        assert "\u2591" in bar

    def test_width_preserved(self):
        for pct in [0, 25, 50, 75, 100]:
            bar = progress_bar(pct, width=10)
            assert len(bar) == 10


class TestMarkerProgressBar:
    def test_width_preserved(self):
        bar = marker_progress_bar(30, 60, width=8)
        assert len(bar) == 8

    def test_contains_marker_when_week_nonzero(self):
        bar = marker_progress_bar(30, 60, width=8)
        assert "\u2502" in bar or "\u2503" in bar

    def test_no_marker_when_week_zero(self):
        bar = marker_progress_bar(30, 0, width=8)
        assert "\u2502" not in bar
        assert "\u2503" not in bar


class TestColorSplitBarSegments:
    def test_returns_list_of_tuples(self):
        segs = color_split_bar_segments(30, 60, width=8)
        assert isinstance(segs, list)
        for text, color in segs:
            assert isinstance(text, str)

    def test_total_width(self):
        segs = color_split_bar_segments(30, 60, width=8)
        total = sum(len(text) for text, _ in segs)
        assert total == 8

    def test_uses_session_and_week_colors(self):
        segs = color_split_bar_segments(30, 60, width=8)
        colors = {c for _, c in segs if c is not None}
        assert SESSION_COLOR in colors or WEEK_COLOR in colors

    def test_zero_values(self):
        segs = color_split_bar_segments(0, 0, width=8)
        total = sum(len(text) for text, _ in segs)
        assert total == 8
