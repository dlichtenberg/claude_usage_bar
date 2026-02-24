"""py2app build configuration.

Build a standalone .app bundle:
    python setup.py py2app
"""

from setuptools import setup

APP = ["src/claude_usage/__main__.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,  # no dock icon
        "CFBundleIdentifier": "com.github.dlichtenberg.claude-usage-bar",
        "CFBundleName": "Claude Usage Bar",
        "CFBundleShortVersionString": "0.1.0",
    },
    "packages": ["rumps", "claude_usage"],
}

setup(
    app=APP,
    name="Claude Usage Bar",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
