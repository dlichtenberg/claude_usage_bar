# Claude Usage Bar

See your Claude Pro/Max usage at a glance — right in your macOS menu bar.

<img width="253" height="319" alt="Claude Usage Bar screenshot" src="https://github.com/user-attachments/assets/cddb035e-5672-493c-8027-3500ef2ff6c3" />

## Getting started

Install and run:

```sh
pip install claude-usage-bar
claude-usage-bar &
```

To keep it running across restarts, click the menu bar icon and enable **Launch at Login**.

## Requirements

- macOS
- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and logged in

## How it works

Claude Usage Bar periodically checks your current usage against the Anthropic API and displays a progress bar, so you always know where you stand against your plan's limits. Authentication is handled through your existing Claude Code login.

## Debugging

Set `CLAUDE_USAGE_LOG` for verbose output when running from Terminal:

```sh
CLAUDE_USAGE_LOG=DEBUG claude-usage-bar
```

## Contributing

Contributions are welcome — feedback and bug reports are greatly appreciated. [open an issue](https://github.com/dlichtenberg/claude_usage_bar/issues) to discuss bugs or ideas.

### Local development

```sh
uv venv --python 3.12   # or: python3 -m venv .venv (if you don't have uv)
source .venv/bin/activate

# Install the package and its dependencies in editable mode,
# so local source changes take effect without reinstalling
uv pip install -e .        # or: pip install -e .

# Run the app
python -m claude_usage

# Run tests
uv pip install pytest      # or: pip install pytest
python -m pytest tests/
```

## License

[MIT](LICENSE)
