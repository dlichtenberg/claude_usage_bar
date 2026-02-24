# Claude Usage Bar

A [SwiftBar](https://github.com/swiftbar/SwiftBar) plugin that displays your Claude Pro/Max usage limits in the macOS menu bar.

![menu bar screenshot](https://img.shields.io/badge/macOS-menu%20bar-blue)

## Features

- Shows session (5-hour) and weekly usage as progress bars
- Color-coded indicators: green, amber, and red based on utilization
- Displays time until each limit resets
- Shows extra usage spend if enabled on your account
- Auto-refreshes every 5 minutes

## Requirements

- macOS
- [SwiftBar](https://github.com/swiftbar/SwiftBar)
- Python 3
- An active Claude Pro or Max subscription with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) credentials in the macOS Keychain

## Installation

1. Install SwiftBar (e.g. `brew install --cask swiftbar`)
2. Clone this repo:
   ```sh
   git clone https://github.com/dlichtenberg/claude_usage_bar.git
   ```
3. Symlink or copy the plugin into your SwiftBar plugins directory:
   ```sh
   ln -s "$(pwd)/claude_usage_bar/claude-usage.5m.py" ~/swiftbar/
   ```
4. Make sure the script is executable:
   ```sh
   chmod +x claude-usage.5m.py
   ```

The plugin reads OAuth credentials from the macOS Keychain (the same ones Claude Code stores), so no manual API key configuration is needed.

## How It Works

The filename `claude-usage.5m.py` tells SwiftBar to run the script every 5 minutes. It calls the Anthropic usage API and renders a compact progress bar in the menu bar, with a dropdown showing detailed breakdowns per limit window.
