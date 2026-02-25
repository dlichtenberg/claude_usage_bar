"""Standalone macOS menu bar app for Claude usage display."""

import threading
import traceback

import rumps
from PyObjCTools import AppHelper

from claude_usage.core import (
    get_access_token,
    fetch_usage,
    trigger_claude_refresh,
    time_until,
    color_hex_for_pct,
    progress_bar,
    color_split_bar_segments,
    merged_menu_bar_text,
    load_config,
    save_config,
    SESSION_COLOR,
    WEEK_COLOR,
    MODE_COLOR_SPLIT,
    MODE_MARKER,
)
from claude_usage.attributed import styled_string, styled_segments

REFRESH_INTERVAL = 300  # 5 minutes


class ClaudeUsageApp(rumps.App):
    def __init__(self):
        super().__init__("Claude Usage", title="C: ...")

        # Build menu items with stable key names
        self._session = rumps.MenuItem("Session (5h)")
        self._session_reset = rumps.MenuItem("  Resets in ...")
        self._week_all = rumps.MenuItem("Week (all)")
        self._week_all_reset = rumps.MenuItem("  Resets in ...")
        self._week_sonnet = rumps.MenuItem("Week (Sonnet)")
        self._week_sonnet_reset = rumps.MenuItem("  Resets in ...")

        self._extra_header = rumps.MenuItem("Extra Usage")
        self._extra_bar = rumps.MenuItem("  ...")

        # Display mode items
        self._mode_color_split = rumps.MenuItem(
            "Color Split", callback=self._on_mode_color_split,
        )
        self._mode_marker = rumps.MenuItem(
            "Marker", callback=self._on_mode_marker,
        )
        self._marker_legend = rumps.MenuItem("  bar = session  ┃│ = week")

        self._refresh_btn = rumps.MenuItem("Refresh", callback=self._on_refresh)

        self.menu = [
            self._session,
            self._session_reset,
            None,  # separator
            self._week_all,
            self._week_all_reset,
            None,
            self._week_sonnet,
            self._week_sonnet_reset,
            None,
            self._extra_header,
            self._extra_bar,
            None,
            self._mode_color_split,
            self._mode_marker,
            self._marker_legend,
            None,
            self._refresh_btn,
        ]

        # Hide extra usage by default.
        # _menuitem is a private rumps API (no public alternative for
        # setHidden_ / setAttributedTitle_); pinned to rumps <0.5.
        self._extra_header._menuitem.setHidden_(True)
        self._extra_bar._menuitem.setHidden_(True)

        # Load display mode config
        self._config = load_config()
        self._display_mode = self._config.get("display_mode", MODE_COLOR_SPLIT)
        self._update_mode_checkmarks()

        # Cache last API data for re-render on mode change
        self._last_data = None

        self._fetching = False

        # Periodic refresh timer
        self._timer = rumps.Timer(self._on_timer, REFRESH_INTERVAL)
        self._timer.start()

        # One-shot timer to do initial fetch once the run loop is up
        # (can't access nsstatusitem during __init__)
        self._init_timer = rumps.Timer(self._on_init, 1)
        self._init_timer.start()

    def _on_init(self, _sender):
        """Initial fetch after the run loop starts."""
        self._init_timer.stop()
        self._refresh()

    def _on_timer(self, _sender):
        self._refresh()

    def _on_refresh(self, _sender):
        self._refresh()

    def _on_mode_color_split(self, _sender):
        self._set_display_mode(MODE_COLOR_SPLIT)

    def _on_mode_marker(self, _sender):
        self._set_display_mode(MODE_MARKER)

    def _set_display_mode(self, mode):
        self._display_mode = mode
        self._config["display_mode"] = mode
        save_config(self._config)
        self._update_mode_checkmarks()
        if self._last_data:
            self._render(self._last_data)

    def _update_mode_checkmarks(self):
        self._mode_color_split.state = self._display_mode == MODE_COLOR_SPLIT
        self._mode_marker.state = self._display_mode == MODE_MARKER
        self._marker_legend._menuitem.setHidden_(
            self._display_mode != MODE_MARKER
        )

    def _refresh(self):
        """Kick off a background fetch. No-op if one is already in flight."""
        if self._fetching:
            return
        self._fetching = True
        threading.Thread(target=self._fetch_bg, daemon=True).start()

    def _fetch_bg(self):
        """Run all blocking work (keychain, HTTP, subprocess) off the main thread."""
        data, err = None, None
        try:
            token = get_access_token()
            if not token:
                err = "No keychain credentials"
            else:
                data, err = fetch_usage(token)

                # If token expired, try refreshing and retry once
                if err == "auth_expired":
                    if trigger_claude_refresh():
                        token = get_access_token()
                        if token:
                            data, err = fetch_usage(token)
        except Exception as e:
            data, err = None, f"{type(e).__name__}: {e}"

        # Dispatch UI update to the main run-loop thread
        AppHelper.callAfter(self._apply_result, data, err)

    def _apply_result(self, data, err):
        """Apply fetched data to the UI (runs on main thread via callAfter)."""
        self._fetching = False

        try:
            if err:
                if err == "auth_expired":
                    self._show_error("Token expired \u2014 open Claude Code to re-auth")
                else:
                    self._show_error(err)
                return

            self._render(data)
        except Exception:
            traceback.print_exc()
            self._show_error("Unexpected error")

    def _show_error(self, msg):
        """Display error state in menu bar and dropdown."""
        self._set_title("C: !!", "#FF4444")
        self._session._menuitem.setAttributedTitle_(
            styled_string(f"Error: {msg}", color="#FF4444")
        )
        self._session_reset._menuitem.setAttributedTitle_(styled_string(""))
        self._week_all._menuitem.setAttributedTitle_(styled_string(""))
        self._week_all_reset._menuitem.setAttributedTitle_(styled_string(""))
        self._week_sonnet._menuitem.setAttributedTitle_(styled_string(""))
        self._week_sonnet_reset._menuitem.setAttributedTitle_(styled_string(""))
        self._extra_header._menuitem.setHidden_(True)
        self._extra_bar._menuitem.setHidden_(True)

    def _render(self, data):
        """Update all menu items from API response data."""
        self._last_data = data

        five_hour = data.get("five_hour", {})
        seven_day = data.get("seven_day", {})
        seven_day_sonnet = data.get("seven_day_sonnet", {})
        extra = data.get("extra_usage", {})

        session_pct = five_hour.get("utilization", 0)
        week_pct = seven_day.get("utilization", 0)
        headline_pct = max(session_pct, week_pct)

        # Menu bar title — depends on display mode
        self._set_merged_title(session_pct, week_pct)

        # Session (5h)
        self._style_limit(
            self._session, self._session_reset,
            "Session (5h)    ", five_hour,
        )

        # Week (all)
        self._style_limit(
            self._week_all, self._week_all_reset,
            "Week (all)      ", seven_day,
        )

        # Week (Sonnet)
        self._style_limit(
            self._week_sonnet, self._week_sonnet_reset,
            "Week (Sonnet)   ", seven_day_sonnet,
        )

        # Extra Usage
        if extra.get("is_enabled"):
            self._extra_header._menuitem.setHidden_(False)
            self._extra_bar._menuitem.setHidden_(False)

            used_cents = extra.get("used_credits", 0)
            limit_cents = extra.get("monthly_limit", 0)
            used_dollars = used_cents / 100
            limit_dollars = limit_cents / 100
            pct = extra.get("utilization", 0)
            c = color_hex_for_pct(pct)
            bar = progress_bar(pct)

            self._extra_header._menuitem.setAttributedTitle_(
                styled_string(f"Extra Usage      ${used_dollars:.2f} / ${limit_dollars:.2f}")
            )
            self._extra_bar._menuitem.setAttributedTitle_(
                styled_string(f"                 {bar} {pct:.0f}%", color=c)
            )
        else:
            self._extra_header._menuitem.setHidden_(True)
            self._extra_bar._menuitem.setHidden_(True)

    def _style_limit(self, main_item, reset_item, label, bucket):
        """Style a limit row (main line + reset line)."""
        pct = bucket.get("utilization", 0)
        c = color_hex_for_pct(pct)
        bar = progress_bar(pct)
        resets = time_until(bucket.get("resets_at"))

        main_item._menuitem.setAttributedTitle_(
            styled_string(f"{label}{bar} {pct:.0f}%", color=c)
        )
        reset_item._menuitem.setAttributedTitle_(
            styled_string(f"  Resets in {resets}", color="#999999", font_size=11.0)
        )

    def _set_title(self, text, color=None):
        """Set the menu bar title with optional color.

        Sets plain title first (for rumps internal state), then overlays
        with an attributed string for color.
        """
        self.title = text
        if color:
            attr = styled_string(text, color=color, font_size=12.0)
            # _nsapp.nsstatusitem is a private rumps API; pinned to rumps <0.5
            self._nsapp.nsstatusitem.button().setAttributedTitle_(attr)

    def _set_merged_title(self, session_pct, week_pct):
        """Set the menu bar title using the active display mode."""
        headline_pct = max(session_pct, week_pct)
        headline_color = color_hex_for_pct(headline_pct)
        text = merged_menu_bar_text(session_pct, week_pct, self._display_mode)

        # Set plain title for rumps internal state
        self.title = text

        if self._display_mode == MODE_COLOR_SPLIT:
            # Build per-character colored bar
            bar_segments = color_split_bar_segments(
                session_pct, week_pct, width=8,
            )
            segments = [("C: ", headline_color)]
            segments.extend(bar_segments)
            segments.append((f" {headline_pct:.0f}%", headline_color))
            attr = styled_segments(segments, font_size=12.0)
        else:
            # Marker mode — single color
            attr = styled_string(text, color=headline_color, font_size=12.0)

        self._nsapp.nsstatusitem.button().setAttributedTitle_(attr)


def main():
    """Entry point for console_scripts."""
    ClaudeUsageApp().run()
