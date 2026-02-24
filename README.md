# Claude Usage Bar

A macOS menu bar app that displays your Claude Pro/Max usage limits. Available as a **standalone app** or as a **SwiftBar plugin**.

![menu bar screenshot](https://img.shields.io/badge/macOS-menu%20bar-blue)

<img width="277" height="273" alt="image" src="https://github.com/user-attachments/assets/71d950ee-7bc6-4900-abd6-1fcc15164eda" />

## Installation

with pypi
`pip install claude-usage-bar`

with homebrew
`brew install claude-usage-bar`

download .app bundle
TODO

with [SwiftBar](https://github.com/swiftbar/SwiftBar) plugin:
## Standalone App (Recommended)

### Install and run

```sh
pip install -e .
claude-usage-bar
```

Or run directly:

```sh
python -m claude_usage
```

### Build a .app bundle

```sh
pip install py2app
python setup.py py2app
```

This produces `dist/Claude Usage Bar.app`. Move it to `/Applications` and add it to **System Settings > General > Login Items** to start automatically.

## SwiftBar Plugin

If you prefer [SwiftBar](https://github.com/swiftbar/SwiftBar):

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

## Requirements

- Python 3.10+
- An active Claude Pro or Max subscription with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed.
