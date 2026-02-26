# PR Review: #21 — Add auto-start on login via LaunchAgent

Clean PR overall — well-structured, good test coverage, idempotent uninstall, and the plist generation via `plistlib` is the right call. Findings below, ordered by severity.

---

## Bug

### 1. `_get_executable_path()` can produce a relative or unusable path for the plist
`src/claude_usage/core.py:493`

The `sys.argv[0]` fallback can return a relative path (e.g. `./claude-usage-bar`), a module flag (`-m`), or even an interpreter path. `launchd` requires an absolute path in `ProgramArguments` — a relative one silently fails at login with no user-visible error.

```python
# current
return sys.argv[0]

# suggested: resolve to absolute, and validate it exists
fallback = os.path.abspath(sys.argv[0])
if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
    return fallback
return None  # caller should handle
```

`install_launch_agent()` should then check for `None` and return `False` with a log warning so the user gets the failure notification rather than a silently broken plist.

---

## Issues

### 2. Uninstall doesn't `launchctl bootout` — agent stays running until next reboot
`src/claude_usage/core.py:537–544`

Removing the plist file prevents the agent from loading on the *next* login, but if it's currently loaded, `launchd` keeps it running for the rest of the session. Users toggling "Launch at Login" off would expect it to take effect immediately.

```python
def uninstall_launch_agent():
    # Unload from launchd first (harmless if not loaded)
    try:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass  # best-effort; file removal is what matters
    ...
```

Symmetrically, `install_launch_agent()` could `launchctl bootstrap` (or the older `launchctl load`) after writing the plist so the agent starts immediately without requiring a logout/login cycle. Not critical since the user is already running the app at install time, but worth considering for the CLI `--install` path.

### 3. CLI flag tests don't simulate `sys.exit` termination — execution leaks past the exit call
`tests/test_launch_agent.py:143–177`

Because `sys.exit` is mocked to a no-op, `main()` continues past the `sys.exit(0)` line, falls through to the `--uninstall` check, and then calls `ClaudeUsageApp().run()`. The assertions still pass (exit *was* called with 0), but the test exercises an impossible code path. If someone later adds logic between the flag checks and `ClaudeUsageApp().run()`, these tests would mask the bug.

Fix: give the mock a side effect so it actually terminates:
```python
with mock.patch("claude_usage.app.sys.exit", side_effect=SystemExit) as mock_exit:
    with pytest.raises(SystemExit):
        main()
    mock_exit.assert_called_once_with(0)
```

### 4. `.app` bundle heuristic can false-positive on directory names containing `.app/Contents/`
`src/claude_usage/core.py:487–491`

The substring check `".app/Contents/" in __file__` would trigger on a non-bundle path like `/Users/joe/my-cool.app/Contents/venv/lib/python3.12/site-packages/claude_usage/core.py`. This is unlikely but the heuristic would produce a broken executable path. A more defensive check would verify the constructed MacOS binary actually exists before returning it:

```python
candidate = os.path.join(app_root, "MacOS", app_name)
if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
    return candidate
```

---

## Nits

### 5. Module-level `os.path.expanduser` for `LAUNCH_AGENT_DIR`/`LAUNCH_AGENT_PATH`
`src/claude_usage/core.py:472–474`

These are evaluated at import time. If `HOME` changes after import (e.g. in tests that manipulate the environment), the paths won't reflect it. The existing tests work around this by mocking `os.path.isfile` / `os.remove`, but it means integration-style tests would need to be careful. Not a problem today, just something to be aware of.

### 6. `--install` and `--uninstall` use raw `in sys.argv` instead of `argparse`
`src/claude_usage/app.py:448–451`

This is consistent with the existing codebase (no argparse anywhere), so it's fine for now. But it means `--install` would also match a hypothetical future `--install-plugin` flag. If more flags are added later, consider switching to `argparse`.

---

## Suggestions

### 7. Log the resolved executable path at install time
`src/claude_usage/core.py:517`

The install function logs the plist path but not which executable it resolved. Adding `logger.info("Resolved executable: %s", exe)` right after `exe = _get_executable_path()` would make debugging much easier when a user reports that the agent doesn't start after login.

### 8. Consider `ProcessType` key in the plist
`src/claude_usage/core.py:499–508`

Adding `"ProcessType": "Interactive"` tells macOS the agent is a user-facing app, which gives it slightly better scheduling priority and is the standard practice for menu bar agents.

---

## Summary

The main actionable item is **#1** (relative path bug) — it would cause silent login-launch failures for anyone not on a pip-installed entry point. **#2** and **#3** are worth addressing for correctness. The rest are polish.
