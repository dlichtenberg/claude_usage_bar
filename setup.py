"""py2app build configuration.

Build a standalone .app bundle:
    python setup.py py2app
"""

import re
from setuptools import setup

# Read version from source to avoid import side effects at build time
_version_re = re.compile(r'__version__\s*=\s*"([^"]+)"')
with open("src/claude_usage/__init__.py") as f:
    _match = _version_re.search(f.read())
    VERSION = _match.group(1) if _match else "0.0.0"

APP = ["src/claude_usage/__main__.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,  # no dock icon
        "CFBundleIdentifier": "com.github.dlichtenberg.claude-usage-bar",
        "CFBundleName": "Claude Usage Bar",
        "CFBundleShortVersionString": VERSION,
    },
    "packages": ["rumps", "claude_usage"],
}

setup(
    app=APP,
    name="Claude Usage Bar",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
