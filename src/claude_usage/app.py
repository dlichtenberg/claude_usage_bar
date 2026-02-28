"""Standalone macOS menu bar app for Claude usage display."""

import logging
import os
import sys
import threading
import traceback

import rumps
from PyObjCTools import AppHelper

from claude_usage.api import fetch_usage
from claude_usage.auth import get_access_token, trigger_token_refresh, find_claude
from claude_usage.config import (
    load_config,
    save_config,
    MODE_SESSION,
    MODE_WEEK,
    MODE_HIGHEST,
    MODE_COLOR_SPLIT,
    MODE_MARKER,
)
from claude_usage.display import (
    time_until,
    color_hex_for_pct,
    progress_bar,
    progress_bar_segments,
    color_split_bar_segments,
    marker_progress_bar,
    merged_menu_bar_text,
    SESSION_COLOR,
    WEEK_COLOR,
)
from claude_usage.launch_agent import (
    install_launch_agent,
    uninstall_launch_agent,
    is_launch_agent_installed,
)

from claude_usage.attributed import styled_string, styled_segments, set_inert_title

logger = logging.getLogger(__name__)

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
        self._mode_session = rumps.MenuItem(
            "Session (5h)", callback=self._on_mode_session,
        )
        self._mode_week = rumps.MenuItem(
            "Week (all)", callback=self._on_mode_week,
        )
        self._mode_highest = rumps.MenuItem(
            "Highest", callback=self._on_mode_highest,
        )
        self._mode_color_split = rumps.MenuItem(
            "Color Split", callback=self._on_mode_color_split,
        )
        self._mode_color_split_legend = rumps.MenuItem("color_split_legend")
        self._mode_marker = rumps.MenuItem(
            "Marker", callback=self._on_mode_marker,
        )
        self._mode_marker_legend = rumps.MenuItem("marker_legend")

        self._mode_submenu = rumps.MenuItem("Bar Style")
        self._mode_submenu.update([
            self._mode_session,
            self._mode_week,
            self._mode_highest,
            self._mode_color_split,
            self._mode_color_split_legend,
            self._mode_marker,
            self._mode_marker_legend,
        ])

        self._refresh_btn = rumps.MenuItem("Refresh", callback=self._on_refresh)
        self._launch_at_login = rumps.MenuItem(
            "Launch at Login", callback=self._on_toggle_launch_at_login,
        )

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
            self._mode_submenu,
            self._launch_at_login,
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
        self._display_mode = self._config.get("display_mode", MODE_MARKER)
        self._update_mode_checkmarks()

        # Initialize "Launch at Login" checkmark
        self._launch_at_login.state = is_launch_agent_installed()

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
        self._style_mode_previews()
        self._refresh()

    def _style_mode_previews(self):
        """Render preview bars and legends in the Bar Style submenu."""
        # Sample data for previews: 40% session, 60% week
        s, w = 40, 60

        # Color Split: per-character colored bar preview
        cs_segments = color_split_bar_segments(s, w, width=8)
        segments = [("  ", None)]
        segments.extend(cs_segments)
        self._mode_color_split._menuitem.setAttributedTitle_(
            styled_segments(
                [("Color Split  ", None, "Poppins")] + cs_segments,
            )
        )
        # Legend: orange = session, green = week
        set_inert_title(
            self._mode_color_split_legend._menuitem,
            styled_segments([
                ("  ", None),
                ("\u2588 session  ", SESSION_COLOR, "Poppins"),
                ("\u2588 week", WEEK_COLOR, "Poppins"),
            ], font_size=11.0),
        )

        # Marker: session fill + week marker preview
        marker_bar = marker_progress_bar(s, w, width=8)
        self._mode_marker._menuitem.setAttributedTitle_(
            styled_segments([
                ("Marker  ", None, "Poppins"),
                (marker_bar, color_hex_for_pct(s)),
            ])
        )
        set_inert_title(
            self._mode_marker_legend._menuitem,
            styled_string("  bar = session  \u2503\u2502 = week",
                          color="#444444", font_size=11.0),
        )

    def _on_timer(self, _sender):
        self._refresh()

    def _on_refresh(self, _sender):
        self._refresh()

    def _on_mode_session(self, _sender):
        self._set_display_mode(MODE_SESSION)

    def _on_mode_week(self, _sender):
        self._set_display_mode(MODE_WEEK)

    def _on_mode_highest(self, _sender):
        self._set_display_mode(MODE_HIGHEST)

    def _on_mode_color_split(self, _sender):
        self._set_display_mode(MODE_COLOR_SPLIT)

    def _on_mode_marker(self, _sender):
        self._set_display_mode(MODE_MARKER)

    def _on_toggle_launch_at_login(self, sender):
        if sender.state:
            ok = uninstall_launch_agent()
        else:
            ok = install_launch_agent()
        if ok:
            sender.state = not sender.state
        else:
            action = "remove" if sender.state else "install"
            rumps.notification(
                "Claude Usage Bar",
                f"Failed to {action} LaunchAgent",
                "Check Console.app for details.",
            )

    def _set_display_mode(self, mode):
        self._display_mode = mode
        self._config["display_mode"] = mode
        save_config(self._config)
        self._update_mode_checkmarks()
        if self._last_data:
            self._render(self._last_data)

    def _update_mode_checkmarks(self):
        self._mode_session.state = self._display_mode == MODE_SESSION
        self._mode_week.state = self._display_mode == MODE_WEEK
        self._mode_highest.state = self._display_mode == MODE_HIGHEST
        self._mode_color_split.state = self._display_mode == MODE_COLOR_SPLIT
        self._mode_marker.state = self._display_mode == MODE_MARKER
        self._mode_marker_legend._menuitem.setHidden_(
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
        data, err, hint = None, None, None
        try:
            logger.debug("Starting usage fetch")
            token = get_access_token()
            if not token:
                err = "No keychain credentials"
                hint = "Run 'claude' in Terminal to authenticate"
                logger.warning("No access token found in keychain")
            else:
                logger.debug("Token retrieved, calling usage API")
                data, err = fetch_usage(token)

                # If token expired, try refreshing and retry once
                if err == "auth_expired":
                    logger.info("Token expired, attempting refresh")
                    if trigger_token_refresh():
                        logger.info("Refresh succeeded, retrying usage fetch")
                        token = get_access_token()
                        if token:
                            data, err = fetch_usage(token)
                    else:
                        logger.warning("Token refresh failed")
                        err = "Token expired"
                        hint = "Open Claude Code to refresh, or click Refresh"

            # Check CLI availability for hint (done off main thread)
            if err and not hint and find_claude() is None:
                hint = "Install Claude Code CLI"
        except Exception as e:
            data, err = None, f"{type(e).__name__}: {e}"
            logger.error("Unexpected error in fetch: %s", e)

        # Dispatch UI update to the main run-loop thread
        AppHelper.callAfter(self._apply_result, data, err, hint)

    def _apply_result(self, data, err, hint=None):
        """Apply fetched data to the UI (runs on main thread via callAfter)."""
        self._fetching = False

        try:
            if err:
                logger.warning("Entering error state: %s", err)
                self._show_error(err, hint)
                return

            logger.debug("Usage data received, updating UI")
            self._render(data)
        except Exception:
            traceback.print_exc()
            self._show_error("Unexpected error")

    def _show_error(self, msg, hint=None):
        """Display error state in menu bar and dropdown."""
        self._set_title("C: !!", "#FF4444")
        set_inert_title(
            self._session._menuitem,
            styled_string(f"Error: {msg}", color="#FF4444", font_name="Poppins"),
        )
        hint_attr = (
            styled_string(f"  {hint}", color="#444444", font_name="Poppins",
                          font_size=11.0)
            if hint else styled_string("")
        )
        set_inert_title(self._session_reset._menuitem, hint_attr)
        set_inert_title(self._week_all._menuitem, styled_string(""))
        set_inert_title(self._week_all_reset._menuitem, styled_string(""))
        set_inert_title(self._week_sonnet._menuitem, styled_string(""))
        set_inert_title(self._week_sonnet_reset._menuitem, styled_string(""))
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

        # Menu bar title — depends on display mode
        self._set_merged_title(session_pct, week_pct)

        # Only use fixed session/week colors in color_split mode
        use_split_colors = self._display_mode == MODE_COLOR_SPLIT

        # Session (5h)
        self._style_limit(
            self._session, self._session_reset,
            "Session (5h)    ", five_hour,
            color_override=SESSION_COLOR if use_split_colors else None,
        )

        # Week (all)
        self._style_limit(
            self._week_all, self._week_all_reset,
            "Week (all)      ", seven_day,
            color_override=WEEK_COLOR if use_split_colors else None,
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

            set_inert_title(
                self._extra_header._menuitem,
                styled_string(f"Extra Usage      ${used_dollars:.2f} / ${limit_dollars:.2f}"),
            )
            set_inert_title(
                self._extra_bar._menuitem,
                styled_string(f"                 {bar} {pct:.0f}%", color=c),
            )
        else:
            self._extra_header._menuitem.setHidden_(True)
            self._extra_bar._menuitem.setHidden_(True)

    def _style_limit(self, main_item, reset_item, label, bucket,
                     color_override=None):
        """Style a limit row (main line + reset line)."""
        pct = bucket.get("utilization", 0)
        c = color_override or color_hex_for_pct(pct)
        resets = time_until(bucket.get("resets_at"))

        segments = [(label, c, "Poppins")]
        segments.extend(progress_bar_segments(pct, c))
        segments.append((f" {pct:.0f}%", c))

        set_inert_title(main_item._menuitem, styled_segments(segments))
        set_inert_title(
            reset_item._menuitem,
            styled_string(f"  Resets in {resets}", color="#444444", font_size=11.0),
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
        text = merged_menu_bar_text(session_pct, week_pct, self._display_mode)

        # Pick the color based on what the mode is displaying
        if self._display_mode in (MODE_SESSION, MODE_MARKER):
            bar_color = color_hex_for_pct(session_pct)
        elif self._display_mode == MODE_WEEK:
            bar_color = color_hex_for_pct(week_pct)
        else:
            # highest, color_split use max
            bar_color = color_hex_for_pct(max(session_pct, week_pct))

        # Set plain title for rumps internal state
        self.title = text

        if self._display_mode == MODE_COLOR_SPLIT:
            headline_pct = max(session_pct, week_pct)
            bar_segments = color_split_bar_segments(
                session_pct, week_pct, width=8,
            )
            segments = [("C: ", bar_color)]
            segments.extend(bar_segments)
            segments.append((f" {headline_pct:.0f}%", bar_color))
            attr = styled_segments(segments, font_size=12.0)
        else:
            attr = styled_string(text, color=bar_color, font_size=12.0)

        self._nsapp.nsstatusitem.button().setAttributedTitle_(attr)


def main():
    """Entry point for console_scripts."""
    log_level = os.environ.get("CLAUDE_USAGE_LOG", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if "--install" in sys.argv:
        sys.exit(0 if install_launch_agent() else 1)
    if "--uninstall" in sys.argv:
        sys.exit(0 if uninstall_launch_agent() else 1)

    ClaudeUsageApp().run()
