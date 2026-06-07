"""Shared UI helpers: banner, icons, spinner, macOS notifications.

Everything in here is presentation-only — pulling these into a separate module
keeps `cli.py` focused on command wiring.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from contextlib import contextmanager
from typing import Iterator

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import __version__


# ---------------------------------------------------------------------------
# state icons
# ---------------------------------------------------------------------------


class Icons:
    REC = "●"
    PAUSED = "⏸"
    STOPPED = "○"
    OK = "✓"
    FAIL = "✗"
    WARN = "▲"
    SKIP = "·"
    DOT = "•"
    ARROW = "→"


def state_label(active: bool, paused: bool) -> Text:
    if paused:
        return Text(f"{Icons.PAUSED} PAUSED", style="bold yellow")
    if active:
        return Text(f"{Icons.REC} REC", style="bold red")
    return Text(f"{Icons.STOPPED} stopped", style="dim")


# ---------------------------------------------------------------------------
# banner
# ---------------------------------------------------------------------------


_LOGO = r"""
 ███████╗ ██████╗ ███╗   ██╗██╗   ██╗ ██████╗ ██████╗ ███████╗
 ██╔════╝██╔═══██╗████╗  ██║╚██╗ ██╔╝██╔═══██╗██╔══██╗██╔════╝
 ███████╗██║   ██║██╔██╗ ██║ ╚████╔╝ ██║   ██║██████╔╝███████╗
 ╚════██║██║   ██║██║╚██╗██║  ╚██╔╝  ██║   ██║██╔══██╗╚════██║
 ███████║╚██████╔╝██║ ╚████║   ██║   ╚██████╔╝██████╔╝███████║
 ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═════╝ ╚══════╝
"""


def banner_text() -> Text:
    """Render the SONYOBS logo with a cyan→magenta horizontal gradient."""
    lines = _LOGO.strip("\n").splitlines()
    width = max(len(line) for line in lines)
    # Simple two-stop gradient cyan -> magenta over column position.
    palette = _gradient(width, (0, 200, 255), (200, 60, 255))
    text = Text()
    for line in lines:
        for col, ch in enumerate(line.ljust(width)):
            text.append(ch, style=f"bold {palette[col]}")
        text.append("\n")
    return text


def banner_panel() -> Panel:
    sub = Text.assemble(
        Text("record. one keystroke.", style="italic dim"),
        Text("    "),
        Text(f"v{__version__}", style="magenta"),
    )
    body = Text.assemble(banner_text(), "\n", Align.center(sub, width=64).renderable)
    return Panel(body, border_style="cyan", expand=False, padding=(0, 2))


def small_banner() -> Text:
    """Compact one-liner for inside other panels."""
    return Text.assemble(
        Text("SONYOBS", style="bold cyan"),
        Text("  ·  ", style="dim"),
        Text(f"v{__version__}", style="magenta"),
    )


def _gradient(width: int, start_rgb: tuple[int, int, int], end_rgb: tuple[int, int, int]) -> list[str]:
    out: list[str] = []
    for i in range(max(width, 1)):
        t = i / max(width - 1, 1)
        r = round(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * t)
        g = round(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * t)
        b = round(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * t)
        out.append(f"rgb({r},{g},{b})")
    return out


# ---------------------------------------------------------------------------
# spinner
# ---------------------------------------------------------------------------


@contextmanager
def spinner(console: Console, message: str) -> Iterator[None]:
    """Show a dots spinner with `message` until the block exits."""
    with console.status(f"[cyan]{message}[/]", spinner="dots", spinner_style="cyan"):
        yield


# ---------------------------------------------------------------------------
# macOS notifications
# ---------------------------------------------------------------------------


def notify(title: str, message: str, *, sound: str | None = None) -> None:
    """Best-effort macOS notification.

    Tries `terminal-notifier` first (richer), then falls back to `osascript`.
    Silently no-ops on non-mac systems.
    """
    if shutil.which("terminal-notifier"):
        args = [
            "terminal-notifier",
            "-title",
            title,
            "-message",
            message,
            "-group",
            "sonyobs",
        ]
        if sound:
            args.extend(["-sound", sound])
        try:
            subprocess.run(args, check=False, timeout=2)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass

    if shutil.which("osascript"):
        # Escape any embedded double-quotes so the AppleScript stays well-formed.
        safe_title = title.replace('"', '\\"')
        safe_message = message.replace('"', '\\"')
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        if sound:
            script += f' sound name "{sound}"'
        try:
            subprocess.run(["osascript", "-e", script], check=False, timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass


# ---------------------------------------------------------------------------
# duration parsing  (e.g. "5m", "1h30m", "90", "0:30")
# ---------------------------------------------------------------------------


_DURATION_RE = re.compile(
    r"""^
    (?:(?P<h>\d+)h)?
    (?:(?P<m>\d+)m)?
    (?:(?P<s>\d+)s?)?
    $""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_duration(value: str) -> int:
    """Parse a human duration into seconds.

    Accepted shapes:
      * `90`        → 90 s
      * `5m`        → 300 s
      * `1h`        → 3600 s
      * `1h30m`     → 5400 s
      * `0:30`      → 30 s
      * `1:23:45`   → 5025 s
    """
    raw = value.strip()
    if not raw:
        raise ValueError("empty duration")

    if ":" in raw:
        parts = raw.split(":")
        if not all(p.isdigit() for p in parts) or len(parts) > 3:
            raise ValueError(f"bad duration: {value!r}")
        nums = [int(p) for p in parts]
        while len(nums) < 3:
            nums.insert(0, 0)
        h, m, s = nums
        return h * 3600 + m * 60 + s

    if raw.isdigit():
        value_int = int(raw)
        if value_int <= 0:
            raise ValueError(f"duration must be > 0: {value!r}")
        return value_int

    match = _DURATION_RE.fullmatch(raw)
    if not match or not any(match.groupdict().values()):
        raise ValueError(f"bad duration: {value!r}")
    h = int(match.group("h") or 0)
    m = int(match.group("m") or 0)
    s = int(match.group("s") or 0)
    total = h * 3600 + m * 60 + s
    if total <= 0:
        raise ValueError(f"duration must be > 0: {value!r}")
    return total


def fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def fmt_bytes(n: int) -> str:
    n = max(0, int(n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{n} B"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"  # unreachable
