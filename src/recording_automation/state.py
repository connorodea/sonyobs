"""Tiny on-disk state — only used to remember the last recording's path."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .utils import expand_path

STATE_DIR = expand_path("~/.sonyobs")
STATE_FILE = STATE_DIR / "state.json"


def _load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_started(profile: str, scene: str) -> None:
    data = _load()
    data["last_start"] = {
        "profile": profile,
        "scene": scene,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)


def record_finished(output_path: str | None) -> None:
    data = _load()
    last_start = data.get("last_start", {})
    data["last_recording"] = {
        **last_start,
        "output_path": output_path,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)


def last_recording() -> dict[str, Any] | None:
    return _load().get("last_recording")
