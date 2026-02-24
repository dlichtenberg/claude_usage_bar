"""Standalone macOS menu bar app for Claude usage display."""

import threading

import rumps

from claude_usage.core import (
    get_access_token,
    fetch_usage,
    trigger_claude_refresh,
    time_until,
    color_hex_for_pct,
    progress_bar,
    menu_bar_text,
)
from claude_usage.attributed import styled_string

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
            self._refresh_btn,
        ]

        # Hide extra usage by default.
        # _menuitem is a private rumps API (no public alternative for
        # setHidden_ / setAttributedTitle_); pinned to rumps <0.5.
        self._extra_header._menuitem.setHidden_(True)
        self._extra_bar._menuitem.setHidden_(True)

        self._pending = None
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

    def _refresh(self):
        """Kick off a background fetch. No-op if one is already in flight."""
        if self._fetching:
            return
        self._fetching = True
        threading.Thread(target=self._fetch_bg, daemon=True).start()

    def _fetch_bg(self):
        """Run all blocking work (keychain, HTTP, subprocess) off the main thread."""
        data, err = None, None

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

        self._pending = (data, err)
        # Schedule UI update on the main run-loop thread via a 0-delay timer
        self._apply_timer = rumps.Timer(self._apply_result, 0)
        self._apply_timer.start()

    def _apply_result(self, _sender):
        """Apply fetched data to the UI (runs on main thread via timer)."""
        self._apply_timer.stop()
        self._fetching = False

        try:
            data, err = self._pending
            self._pending = None

            if err:
                if err == "auth_expired":
                    self._show_error("Token expired \u2014 open Claude Code to re-auth")
                else:
                    self._show_error(err)
                return

            self._render(data)
        except Exception:
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
        five_hour = data.get("five_hour", {})
        seven_day = data.get("seven_day", {})
        seven_day_sonnet = data.get("seven_day_sonnet", {})
        extra = data.get("extra_usage", {})

        headline_pct = max(
            five_hour.get("utilization", 0),
            seven_day.get("utilization", 0),
        )

        # Menu bar title
        self._set_title(menu_bar_text(headline_pct), color_hex_for_pct(headline_pct))

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
            pct = extra.get("utilization", 0) or 0
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


def main():
    """Entry point for console_scripts."""
    ClaudeUsageApp().run()
