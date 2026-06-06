"""Small helpers shared by other modules."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand `~` and environment variables, then resolve to an absolute path."""
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def ensure_dir(path: Path) -> Path:
    """Create the directory if it doesn't exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def dated_subfolder(root: Path, *, now: datetime | None = None) -> Path:
    """Return `<root>/YYYY-MM-DD`, creating it if missing."""
    now = now or datetime.now()
    folder = root / now.strftime("%Y-%m-%d")
    return ensure_dir(folder)


def is_writable(path: Path) -> bool:
    """Test whether a directory exists and is writable."""
    try:
        if not path.exists():
            return False
        probe = path / ".__write_probe__"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
