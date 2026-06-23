"""py2app bundler for SonyOBS.app — the menu bar app.

Usage:
    ./scripts/build_app.sh
    # equivalent to:
    #   uv pip install py2app rumps
    #   uv run python setup.py py2app

The output is `dist/SonyOBS.app`. Drag it to /Applications.

This setup.py is intentionally separate from pyproject.toml because py2app's
`py2app` command only registers itself with classic setuptools, not with
hatchling (the build backend declared in pyproject.toml). We still ship the
library + CLI via pyproject.toml; setup.py exists only to produce the .app.
"""
from __future__ import annotations

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).parent
ENTRY = str(HERE / "src" / "recording_automation" / "_app_entry.py")

OPTIONS = {
    # LSUIElement = 1 → no Dock icon, menu bar only.
    "plist": {
        "CFBundleName": "SonyOBS",
        "CFBundleDisplayName": "SonyOBS",
        "CFBundleIdentifier": "com.upscaledinc.sonyobs",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # We do not record audio or capture screens ourselves — OBS does that —
        # but declaring the keys here keeps macOS from killing the app if a
        # future feature wants them.
        "NSCameraUsageDescription": "SonyOBS lists Sony cameras to wire them into OBS.",
        "NSMicrophoneUsageDescription": "SonyOBS does not record audio; OBS does.",
    },
    "packages": [
        "recording_automation",
        "rumps",
        "obsws_python",
        "pydantic",
        "yaml",
        "dotenv",
        "rich",
        "typer",
    ],
    "includes": [
        "recording_automation.menubar",
    ],
    # rumps depends on these AppKit bridge modules; py2app usually picks them up
    # but we list them to be safe.
    "frameworks": [],
    "argv_emulation": False,
    "strip": True,
}

setup(
    name="SonyOBS",
    app=[ENTRY],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
