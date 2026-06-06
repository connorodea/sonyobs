"""Live recording dashboard.

Renders a Rich `Live` panel that polls OBS for record status and refreshes
~2× per second. Ctrl+C cleanly stops the recording and exits.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .obs_client import OBSClient, OBSError, RecordStatus
from .ui import (
    Icons,
    fmt_bytes,
    fmt_duration,
    small_banner,
    state_label,
)


REFRESH_HZ = 2.0


@dataclass
class DashboardResult:
    reason: str  # "user", "deadline", "obs_stopped", "error"
    final_status: RecordStatus | None
    output_path: str | None
    elapsed_seconds: int
    error: str | None = None


def run_dashboard(
    console: Console,
    client: OBSClient,
    *,
    profile: str,
    scene: str,
    deadline_seconds: int | None = None,
    on_stop: Callable[[], str | None] | None = None,
) -> DashboardResult:
    """Run the live dashboard until Ctrl+C, deadline, or OBS stops.

    Parameters
    ----------
    on_stop:
        Optional callback invoked when the dashboard decides to stop the
        recording (returns the output file path if any). If None, the caller
        is responsible for calling `client.stop_recording()` afterwards.
    """
    started_at = time.monotonic()
    first_bytes: int | None = None
    first_bytes_at: float | None = None

    def _render(status: RecordStatus) -> Panel:
        nonlocal first_bytes, first_bytes_at
        now = time.monotonic()
        elapsed = int(now - started_at)

        if first_bytes is None and status.active and status.bytes > 0:
            first_bytes = status.bytes
            first_bytes_at = now

        rate_str = "—"
        if first_bytes is not None and first_bytes_at is not None:
            dt = max(now - first_bytes_at, 1e-6)
            rate = (status.bytes - first_bytes) / dt
            if rate > 0:
                rate_str = f"{fmt_bytes(int(rate))}/s"

        remaining_str = ""
        if deadline_seconds is not None:
            remaining = max(deadline_seconds - elapsed, 0)
            remaining_str = f"  (auto-stop in {fmt_duration(remaining)})"

        # ─── header ────────────────────────────────────────────────────────
        header = Table.grid(expand=True)
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row(
            small_banner(),
            Text(datetime.now().strftime("%H:%M:%S"), style="dim"),
        )

        # ─── big REC line ─────────────────────────────────────────────────
        big = Text()
        big.append("  ")
        big.append_text(state_label(status.active, status.paused))
        big.append("   ")
        big.append(
            status.timecode or fmt_duration(elapsed),
            style="bold white on grey11",
        )
        big.append(remaining_str, style="dim cyan")

        # ─── metrics grid ─────────────────────────────────────────────────
        metrics = Table.grid(padding=(0, 2))
        metrics.add_column(style="dim", justify="right", min_width=10)
        metrics.add_column(style="bold")
        metrics.add_row("profile", profile)
        metrics.add_row("scene", scene)
        metrics.add_row("size", fmt_bytes(status.bytes))
        metrics.add_row("rate", rate_str)

        # ─── footer ───────────────────────────────────────────────────────
        footer = Text(
            f"{Icons.DOT} Press Ctrl+C to stop  "
            f"{Icons.DOT} 'sonyobs pause' to pause from another shell",
            style="dim",
        )

        body = Group(
            header,
            Text(""),
            Align.left(big),
            Text(""),
            metrics,
            Text(""),
            footer,
        )
        border = "red" if status.active and not status.paused else (
            "yellow" if status.paused else "grey50"
        )
        return Panel(
            body,
            title=f"[bold]sonyobs[/]  ·  recording",
            border_style=border,
            padding=(1, 2),
        )

    # Initial status fetch so we render something immediately.
    try:
        initial = client.get_record_status()
    except OBSError as exc:
        return DashboardResult(
            reason="error",
            final_status=None,
            output_path=None,
            elapsed_seconds=0,
            error=str(exc),
        )

    reason: str = "obs_stopped"
    output_path: str | None = None
    last_status: RecordStatus = initial
    error: str | None = None

    refresh_interval = 1.0 / REFRESH_HZ

    with Live(
        _render(initial),
        console=console,
        refresh_per_second=REFRESH_HZ,
        screen=False,
        transient=False,
    ) as live:
        try:
            while True:
                try:
                    status = client.get_record_status()
                except OBSError as exc:
                    error = str(exc)
                    reason = "error"
                    break

                last_status = status
                live.update(_render(status))

                if not status.active:
                    reason = "obs_stopped"
                    break

                elapsed = int(time.monotonic() - started_at)
                if deadline_seconds is not None and elapsed >= deadline_seconds:
                    reason = "deadline"
                    break

                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            reason = "user"

    if reason in ("user", "deadline") and last_status.active:
        try:
            if on_stop is not None:
                output_path = on_stop()
            else:
                output_path = client.stop_recording()
        except OBSError as exc:
            error = str(exc)

    return DashboardResult(
        reason=reason,
        final_status=last_status,
        output_path=output_path,
        elapsed_seconds=int(time.monotonic() - started_at),
        error=error,
    )
