"""Scan the recording folder for finished video files."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".m4v", ".flv", ".ts"}


@dataclass(frozen=True)
class Recording:
    path: Path
    size_bytes: int
    modified_at: datetime

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def age_seconds(self) -> int:
        return int((datetime.now() - self.modified_at).total_seconds())


def find_recent(root: Path, *, limit: int = 10) -> list[Recording]:
    """Return the most recently modified video files under `root`, newest first."""
    if not root.exists():
        return []
    found: list[Recording] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append(
            Recording(
                path=path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
            )
        )
    found.sort(key=lambda r: r.modified_at, reverse=True)
    return found[:limit]


def humanize_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h}h ago"
    days = seconds // 86400
    return f"{days}d ago"
