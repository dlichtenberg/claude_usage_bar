# Claude Usage Bar

- Use `conda activate claude_usage` for the project virtualenv.
- After editing source files, run `pip install -e .` if imports reflect stale code (the package may have been installed non-editable).
- Don't add "Generated with Claude Code" lines to PRs.
- When using `gh` CLI, always pass `--repo dlichtenberg/claude_usage_bar` since the local git remote is a proxy and not recognized as a GitHub host.
- Do not implement direct OAuth token refresh in this app. Token refresh should be handled by the Claude CLI, not by this app.

## Debugging Auth Errors

The app logs the auth/refresh flow via Python `logging` (INFO by default). Set `CLAUDE_USAGE_LOG=DEBUG` for verbose output. When running from Terminal, logs go to stderr. Key things to look for:

- **"Claude CLI binary not found"** — `find_claude()` checked PATH and fallback paths (`~/.local/bin/claude`, `~/.claude/local/claude`, `/usr/local/bin/claude`, `/opt/homebrew/bin/claude`). None existed or were executable.
- **"No access token found in keychain"** — the macOS Keychain has no entry for `Claude Code-credentials`. Run `claude` in Terminal to authenticate.
- **"Token expired, attempting refresh"** — the API returned 401. The app will try `claude auth status` to trigger a token refresh.
- **"Token refresh failed"** — `claude auth status` returned non-zero. Check the logged stderr output for details.
- **"Cannot refresh: Claude CLI not found"** — refresh was needed but the binary couldn't be located (same as the first bullet).
