# Homebrew Tap Plan for claude-usage-bar

## Overview

Distribute `claude-usage-bar` via a personal Homebrew tap so users can install with:

```bash
brew tap dlichtenberg/claude-usage-bar
brew install claude-usage-bar
```

No `.app` bundle, code signing, or PyPI publishing required.

---

## Prerequisites

- Tag a release on `dlichtenberg/claude_usage_bar` (e.g. `v0.1.0`)
- Xcode Command Line Tools (users need this — `pyobjc` compiles from source)

---

## Step 1: Create the tap repository

Create `dlichtenberg/homebrew-claude-usage-bar` on GitHub with this structure:

```
homebrew-claude-usage-bar/
  Formula/
    claude-usage-bar.rb
  README.md
```

Homebrew convention: repo must be named `homebrew-<name>`. The `homebrew-` prefix is what `brew tap dlichtenberg/claude-usage-bar` looks for.

## Step 2: Tag a release

```bash
git tag v0.1.0
git push origin v0.1.0
```

Get the archive sha256:

```bash
curl -sL https://github.com/dlichtenberg/claude_usage_bar/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
```

## Step 3: Generate resource stanzas

Every Python dependency (and its transitive deps) needs an explicit `resource` stanza with a PyPI sdist URL and sha256. Use `homebrew-pypi-poet` to generate them:

```bash
python -m venv /tmp/poet-env
source /tmp/poet-env/bin/activate
pip install rumps "pyobjc-framework-Cocoa>=10.0" homebrew-pypi-poet
poet rumps
poet pyobjc-framework-Cocoa
# Combine output, deduplicate (pyobjc-core appears in both)
```

## Step 4: Write the formula

`Formula/claude-usage-bar.rb`:

```ruby
class ClaudeUsageBar < Formula
  include Language::Python::Virtualenv

  desc "macOS menu bar app showing Claude API usage limits"
  homepage "https://github.com/dlichtenberg/claude_usage_bar"
  url "https://github.com/dlichtenberg/claude_usage_bar/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "FILL_IN"
  license "MIT"

  depends_on "python@3.12"
  depends_on :macos

  # --- Paste generated resource stanzas here ---
  # resource "rumps" do ...
  # resource "pyobjc-core" do ...
  # resource "pyobjc-framework-Cocoa" do ...

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s,
      shell_output("#{bin}/claude-usage-bar --version 2>&1", 0)
  end
end
```

Key points:
- `virtualenv_install_with_resources` creates a virtualenv in `libexec/`, installs all resources, installs the main package, and symlinks `claude-usage-bar` into Homebrew's `bin/`.
- Main URL points to GitHub archive (no PyPI needed).
- Dependency resources must point to PyPI sdist tarballs.
- No `service do` block — the app's built-in "Launch at Login" toggle already manages its own LaunchAgent.

## Step 5: Test locally

```bash
brew tap dlichtenberg/claude-usage-bar
brew install --build-from-source claude-usage-bar
claude-usage-bar  # should launch the menu bar app
brew test claude-usage-bar
```

## Step 6: Add a --version flag

The formula's `test do` block needs something to assert against. Add a `--version` flag to the app:

```python
# in __main__.py or app.py
if "--version" in sys.argv:
    print(__version__)
    sys.exit(0)
```

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Tap name | `homebrew-claude-usage-bar` | Single-purpose; can rename to `homebrew-tools` later if more formulae are added |
| Main URL | GitHub archive | Avoids needing to publish to PyPI first |
| Python version | `python@3.12` | Stable, well-tested with pyobjc |
| Service block | Omit | App has its own LaunchAgent toggle in the menu bar |
| PyPI publishing | Deferred | Not required for the tap; can add later for `pip install` users |

---

## Optional: Automate formula updates

Add a GitHub Actions workflow to the tap repo that bumps the formula when a new tag is pushed to the main repo. See [Simon Willison's guide](https://til.simonwillison.net/homebrew/auto-formulas-github-actions) for the pattern — it uses `repository_dispatch` to trigger the tap repo's workflow.

---

## Gotchas

- **pyobjc compile time**: `pyobjc-core` and `pyobjc-framework-Cocoa` compile C extensions from source. `brew install` may appear to hang for a few minutes. This is normal — note it in the README.
- **Executable path**: When installed via Homebrew, `claude-usage-bar` lives at `/opt/homebrew/bin/claude-usage-bar` (Apple Silicon) or `/usr/local/bin/claude-usage-bar` (Intel). The app's `_get_executable_path()` already handles this via `shutil.which()`.
- **No `--help`**: rumps apps launch a GUI event loop, so there's no natural `--help` output. Use `--version` for the test block instead.
- **macOS only**: The formula's `depends_on :macos` ensures Homebrew won't try to install it on Linux.
