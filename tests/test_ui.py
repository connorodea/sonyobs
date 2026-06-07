from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from recording_automation.recordings import find_recent, humanize_age
from recording_automation.ui import (
    fmt_bytes,
    fmt_duration,
    parse_duration,
    state_label,
)


# ---- parse_duration -------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90", 90),
        ("5m", 300),
        ("1h", 3600),
        ("1h30m", 5400),
        ("1H30M", 5400),
        ("1h30m15s", 5415),
        ("0:30", 30),
        ("1:23:45", 5025),
        ("45s", 45),
    ],
)
def test_parse_duration_accepts(value: str, expected: int) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "5x", "-30", "1:2:3:4", "h", "0", "0m"],
)
def test_parse_duration_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)


# ---- fmt_duration ---------------------------------------------------------


@pytest.mark.parametrize(
    "secs,expected",
    [(0, "0:00"), (5, "0:05"), (65, "1:05"), (3661, "1:01:01")],
)
def test_fmt_duration(secs: int, expected: str) -> None:
    assert fmt_duration(secs) == expected


# ---- fmt_bytes ------------------------------------------------------------


def test_fmt_bytes_units() -> None:
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(2048).endswith("KB")
    assert fmt_bytes(2 * 1024 * 1024).endswith("MB")
    assert fmt_bytes(3 * 1024 * 1024 * 1024).endswith("GB")


# ---- state_label ----------------------------------------------------------


def test_state_label_paused_takes_precedence() -> None:
    t = state_label(active=True, paused=True)
    assert "PAUSED" in t.plain


def test_state_label_active() -> None:
    t = state_label(active=True, paused=False)
    assert "REC" in t.plain


def test_state_label_stopped() -> None:
    t = state_label(active=False, paused=False)
    assert "stopped" in t.plain


# ---- recordings -----------------------------------------------------------


def test_find_recent_filters_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x" * 100)
    (tmp_path / "b.mkv").write_bytes(b"x" * 200)
    (tmp_path / "notvideo.log").write_text("nope")
    rows = find_recent(tmp_path)
    names = {r.name for r in rows}
    assert names == {"a.mp4", "b.mkv"}


def test_find_recent_orders_newest_first(tmp_path: Path) -> None:
    a = tmp_path / "older.mp4"
    b = tmp_path / "newer.mp4"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    older_mtime = (datetime.now() - timedelta(hours=1)).timestamp()
    import os
    os.utime(a, (older_mtime, older_mtime))
    rows = find_recent(tmp_path)
    assert [r.name for r in rows][0] == "newer.mp4"


def test_find_recent_recurses(tmp_path: Path) -> None:
    sub = tmp_path / "2026-06-06"
    sub.mkdir()
    (sub / "clip.mp4").write_bytes(b"x")
    rows = find_recent(tmp_path)
    assert len(rows) == 1


def test_find_recent_limit(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.mp4").write_bytes(b"x")
    rows = find_recent(tmp_path, limit=2)
    assert len(rows) == 2


def test_find_recent_missing_dir_is_empty(tmp_path: Path) -> None:
    assert find_recent(tmp_path / "does_not_exist") == []


def test_humanize_age_buckets() -> None:
    assert humanize_age(10).endswith("s ago")
    assert humanize_age(120).endswith("m ago")
    assert humanize_age(7200).endswith("h ago")
    assert humanize_age(86400 * 3).endswith("d ago")
