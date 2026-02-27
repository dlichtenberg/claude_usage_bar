# Claude Usage Bar

- Use the local `.venv`: `source .venv/bin/activate` (or just use `.venv/bin/python` directly).
- Recreate with `uv venv --python 3.12 && uv pip install -e . pytest`.
- **Worktrees**: WorktreeCreate hooks are broken in Claude Code (anthropics/claude-code#27989 — silent hang). Until fixed, manually run `uv venv --python 3.12 && uv pip install -e . pytest` after creating a worktree.
- After editing source files, run `uv pip install -e .` if imports reflect stale code (the package may have been installed non-editable).
- Run the tool: `uv pip install -e .` first, then `.venv/bin/python -m claude_usage`.
- Run tests: `.venv/bin/python -m pytest tests/`.
- Don't add "Generated with Claude Code" lines to PRs.
- When using `gh` CLI, always pass `--repo dlichtenberg/claude_usage_bar` since the local git remote is a proxy and not recognized as a GitHub host.
- Do not attempt to read the developer's token. Do not use `security find-generic-password` in development or testing.

## Debugging Auth Errors

The app logs the auth/refresh flow via Python `logging` (INFO by default). Set `CLAUDE_USAGE_LOG=DEBUG` for verbose output. When running from Terminal, logs go to stderr. Key things to look for:

- **"Keychain JSON keys: [...]"** — DEBUG-level log showing the structure of keychain credentials. Useful for confirming field names.
- **"Claude CLI binary not found"** — `find_claude()` checked PATH and fallback paths (`~/.local/bin/claude`, `~/.claude/local/claude`, `/usr/local/bin/claude`, `/opt/homebrew/bin/claude`). None existed or were executable.
- **"No access token found in keychain"** — the macOS Keychain has no entry for `Claude Code-credentials`. Run `claude` in Terminal to authenticate.
- **"Token expired, attempting refresh"** — the API returned 401. The app will attempt a direct OAuth token refresh via `console.anthropic.com`.
- **"Direct token refresh succeeded"** — the OAuth refresh token exchange worked and new credentials were written to the keychain.
- **"Direct token refresh failed ... falling back to CLI"** — the OAuth refresh failed (e.g., refresh token expired, network error). The app will fall back to `claude -p` as a last resort.
- **"No refresh token found, falling back to CLI refresh"** — credentials exist but contain no refresh token. Falls back to CLI.
- **"Cannot refresh via CLI: Claude CLI not found"** — both direct refresh and CLI fallback failed because the binary couldn't be located.

## Architecture Notes

- `claude-usage.5m.py` (SwiftBar plugin) is a standalone script that **duplicates** business logic from `src/claude_usage/core.py` because SwiftBar requires a single self-contained file. When changing shared logic (progress bars, color thresholds, config loading, etc.), always update both files or they will diverge.
- User preferences are stored in `~/.config/claude_usage/config.json`.
- Do not write scratch/planning files into the repo — use the conversation instead.
- Keychain credentials are nested: `{"claudeAiOauth": {"accessToken", "refreshToken", "expiresAt", "scopes", "subscriptionType", "rateLimitTier"}}`. The code handles flat and snake_case variants too.
- HTTP requests to Anthropic endpoints (console.anthropic.com, api.anthropic.com) must set a `User-Agent` header — Cloudflare blocks Python's default `Python-urllib/x.y` with error 1010.
- The OAuth client ID is Claude Code's public client ID. We must use it (not our own) because we're refreshing tokens originally issued to that client.
- For keychain writes, use `security add-generic-password -U` (atomic upsert) — never delete-then-add, which creates a window where credentials are absent.
 
