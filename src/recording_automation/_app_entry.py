"""py2app entry point.

This module exists as the .app's main script because py2app prefers a
top-level script. It just delegates to the menubar module.

Outside py2app it has no purpose; the CLI uses `sonyobs menubar` instead.
"""
from recording_automation.menubar import run

if __name__ == "__main__":
    run()
