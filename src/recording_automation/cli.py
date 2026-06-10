"""Typer CLI entrypoint: `sonyobs <command>` (also `sob`, `recording-auto`)."""
from __future__ import annotations

import json as json_lib
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, state
from .autosetup import AutosetupResult, run_autosetup
from .config import AppConfig, ConfigError, load_config
from .dashboard import DashboardResult, run_dashboard
from .health import run_doctor
from .obs_client import (
    OBSAuthError,
    OBSClient,
    OBSConnectionError,
    OBSError,
    OBSNotFoundError,
)
from .profiles import list_profiles
from .recording import (
    pause_recording,
    resume_recording,
    start_recording,
    status as recording_status,
    stop_recording,
)
from .recordings import find_recent, humanize_age
from .scenes import bootstrap_scenes
from .sony_camera import connect_rx100_to_obs, find_sony_rx100, scan_cameras
from .sources import list_inputs
from .ui import (
    Icons,
    banner_panel,
    fmt_bytes,
    fmt_duration,
    notify,
    parse_duration,
    spinner,
    state_label,
)

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    help="Mac Sony OBS Recording Automation.",
)
obs_app = typer.Typer(no_args_is_help=True, help="OBS WebSocket commands.")
scenes_app = typer.Typer(no_args_is_help=True, help="Scene commands.")
sources_app = typer.Typer(no_args_is_help=True, help="Source commands.")
profiles_app = typer.Typer(no_args_is_help=True, help="Recording profile commands.")
sony_app = typer.Typer(no_args_is_help=True, help="Sony camera (RX100) helpers.")

app.add_typer(obs_app, name="obs")
app.add_typer(scenes_app, name="scenes")
app.add_typer(sources_app, name="sources")
app.add_typer(profiles_app, name="profiles")
app.add_typer(sony_app, name="sony")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


CONFIG_OPT = typer.Option(
    None,
    "--config",
    "-c",
    help="Path to config.yaml. Default: ./config.yaml then config.example.yaml.",
)


def _load(config_path: Optional[Path]) -> AppConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        err_console.print(Panel(str(exc), title="config error", border_style="red"))
        raise typer.Exit(code=2)


def _obs(cfg: AppConfig, *, quiet: bool = False) -> OBSClient:
    client = OBSClient(cfg.obs)
    try:
        if quiet:
            client.connect()
        else:
            with spinner(console, f"Connecting to OBS at {cfg.obs.host}:{cfg.obs.port}"):
                client.connect()
    except OBSConnectionError as exc:
        err_console.print(Panel(str(exc), title="OBS not reachable", border_style="red"))
        raise typer.Exit(code=3)
    except OBSAuthError as exc:
        err_console.print(Panel(str(exc), title="OBS auth failed", border_style="red"))
        raise typer.Exit(code=4)
    except OBSError as exc:
        err_console.print(Panel(str(exc), title="OBS error", border_style="red"))
        raise typer.Exit(code=5)
    return client


def _print_status(status, *, scene_name: str | None = None) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right", min_width=10)
    table.add_column(style="bold")
    table.add_row("state", state_label(status.active, status.paused))
    table.add_row("timecode", Text(status.timecode or "—"))
    table.add_row("size", Text(fmt_bytes(status.bytes)))
    if scene_name:
        table.add_row("scene", Text(scene_name))
    border = (
        "red" if status.active and not status.paused
        else "yellow" if status.paused
        else "grey50"
    )
    console.print(Panel(table, title="recording status", border_style=border))


# ---------------------------------------------------------------------------
# top-level commands
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"sonyobs {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        console.print(banner_panel())
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def menubar() -> None:
    """Launch the macOS menu bar app (statusbar item)."""
    try:
        from .menubar import run as run_menubar
    except RuntimeError as exc:
        err_console.print(
            Panel(str(exc), title="menubar dependency missing", border_style="red")
        )
        raise typer.Exit(code=2)
    run_menubar()


@app.command()
def doctor(config: Optional[Path] = CONFIG_OPT) -> None:
    """Run the full health check."""
    report = run_doctor(config)
    table = Table(title="doctor", expand=True)
    table.add_column("check", style="bold")
    table.add_column("result")
    table.add_column("detail", overflow="fold")
    table.add_column("hint", overflow="fold")
    for check in report.checks:
        if check.skipped:
            result = Text("skipped", style="yellow")
        elif check.passed:
            result = Text("pass", style="green")
        else:
            result = Text("fail", style="red")
        table.add_row(check.name, result, check.detail or "—", check.hint or "")
    console.print(table)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def start(
    profile: str = typer.Option(..., "--profile", "-p", help="Profile name from config.yaml."),
    config: Optional[Path] = CONFIG_OPT,
) -> None:
    """Switch to the profile's scene and start OBS recording."""
    cfg = _load(config)
    if profile not in cfg.profiles:
        available = ", ".join(sorted(cfg.profiles.keys()))
        err_console.print(
            Panel(
                f"Profile '{profile}' is not defined. Available: {available}",
                title="bad profile",
                border_style="red",
            )
        )
        raise typer.Exit(code=2)
    client = _obs(cfg)
    try:
        try:
            result = start_recording(client, cfg, profile)
        except OBSNotFoundError as exc:
            err_console.print(Panel(str(exc), title="scene missing", border_style="red"))
            raise typer.Exit(code=6)
        if result.missing_sources:
            console.print(
                Panel(
                    "Recording started, but these sources are missing in OBS:\n  - "
                    + "\n  - ".join(result.missing_sources)
                    + "\nAdd them in OBS so the scene composes correctly.",
                    title="warning: missing sources",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel(
                    f"Recording started.\nProfile: [bold]{result.profile}[/]\n"
                    f"Scene:   [bold]{result.scene_name}[/]\n"
                    f"Day folder: {result.output_root}",
                    title="OBS recording started",
                    border_style="green",
                )
            )
        _print_status(result.status, scene_name=result.scene_name)
    finally:
        client.close()


@app.command()
def go(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to record. Defaults to config.default_profile.",
    ),
    duration: Optional[str] = typer.Option(
        None,
        "--for",
        "-d",
        help="Auto-stop after this duration (e.g. 5m, 1h30m, 90, 0:30).",
    ),
    detached: bool = typer.Option(
        False,
        "--detached",
        help="Don't attach the live dashboard — start and return immediately.",
    ),
    quiet_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Suppress macOS start/stop notifications.",
    ),
    config: Optional[Path] = CONFIG_OPT,
) -> None:
    """One-keystroke start. Attaches a live dashboard until Ctrl+C (or --detached)."""
    cfg = _load(config)
    chosen = profile or cfg.default_profile
    if chosen not in cfg.profiles:
        available = ", ".join(sorted(cfg.profiles.keys()))
        err_console.print(
            Panel(
                f"Profile '{chosen}' is not defined. Available: {available}",
                title="bad profile",
                border_style="red",
            )
        )
        raise typer.Exit(code=2)

    deadline_seconds: int | None = None
    if duration:
        try:
            deadline_seconds = parse_duration(duration)
        except ValueError as exc:
            err_console.print(
                Panel(str(exc), title="bad --for value", border_style="red")
            )
            raise typer.Exit(code=2)

    client = _obs(cfg)
    try:
        try:
            result = start_recording(client, cfg, chosen)
        except OBSNotFoundError as exc:
            err_console.print(Panel(str(exc), title="scene missing", border_style="red"))
            raise typer.Exit(code=6)

        state.record_started(result.profile, result.scene_name)
        if not quiet_notify:
            notify(
                "sonyobs · recording",
                f"{result.profile} → {result.scene_name}",
                sound="Tink",
            )

        if result.missing_sources:
            console.print(
                Panel(
                    f"{Icons.WARN} Started, but these sources are missing in OBS:\n  - "
                    + "\n  - ".join(result.missing_sources),
                    title="warning",
                    border_style="yellow",
                )
            )

        if detached:
            console.print(
                Panel(
                    f"{Icons.REC} REC  profile=[bold]{result.profile}[/]  "
                    f"scene=[bold]{result.scene_name}[/]",
                    border_style="red",
                )
            )
            if deadline_seconds is not None:
                console.print(
                    f"[dim]Note: --for is ignored in --detached mode. "
                    f"Use `sonyobs watch` to attach later.[/]"
                )
            _print_status(result.status, scene_name=result.scene_name)
            return

        dash = run_dashboard(
            console,
            client,
            profile=result.profile,
            scene=result.scene_name,
            deadline_seconds=deadline_seconds,
        )
        _summarize_dashboard(dash, profile=result.profile, scene=result.scene_name,
                              notify_enabled=not quiet_notify)
    finally:
        client.close()


def _summarize_dashboard(
    dash: DashboardResult,
    *,
    profile: str,
    scene: str,
    notify_enabled: bool,
) -> None:
    reason_label = {
        "user": "stopped (Ctrl+C)",
        "deadline": "stopped (auto-stop deadline)",
        "obs_stopped": "OBS stopped recording",
        "error": "stopped on error",
    }.get(dash.reason, dash.reason)

    if dash.reason == "error":
        err_console.print(
            Panel(dash.error or "unknown error",
                  title="dashboard error", border_style="red")
        )

    state.record_finished(dash.output_path)

    body = Table.grid(padding=(0, 2))
    body.add_column(style="dim", justify="right", min_width=10)
    body.add_column(style="bold")
    body.add_row("reason", reason_label)
    body.add_row("profile", profile)
    body.add_row("scene", scene)
    body.add_row("duration", fmt_duration(dash.elapsed_seconds))
    if dash.output_path:
        body.add_row("file", str(dash.output_path))
    console.print(Panel(body, title=f"{Icons.OK} recording finished", border_style="green"))

    if notify_enabled:
        notify(
            "sonyobs · stopped",
            f"{fmt_duration(dash.elapsed_seconds)} · {profile}",
            sound="Glass",
        )


@app.command()
def watch(config: Optional[Path] = CONFIG_OPT) -> None:
    """Attach the live dashboard to whatever OBS is currently recording."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        status = client.get_record_status()
        if not status.active:
            console.print(
                Panel(
                    "OBS is not recording. Start one with `sonyobs go`.",
                    title="nothing to watch",
                    border_style="yellow",
                )
            )
            return
        scene = client.current_scene() or "?"
        last = state.last_recording() or {}
        profile = last.get("profile", "?")
        dash = run_dashboard(
            console, client, profile=profile, scene=scene, deadline_seconds=None
        )
        _summarize_dashboard(dash, profile=profile, scene=scene, notify_enabled=True)
    finally:
        client.close()


@app.command()
def stop(config: Optional[Path] = CONFIG_OPT) -> None:
    """Stop OBS recording."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        status, output_path = stop_recording(client)
        if output_path:
            console.print(
                Panel(
                    f"Saved to: [bold]{output_path}[/]",
                    title="OBS recording stopped",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    "Recording stopped (no file path reported).",
                    title="OBS recording stopped",
                    border_style="green",
                )
            )
        _print_status(status)
    finally:
        client.close()


@app.command()
def pause(config: Optional[Path] = CONFIG_OPT) -> None:
    """Pause OBS recording."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        try:
            status = pause_recording(client)
        except OBSError as exc:
            err_console.print(Panel(str(exc), title="cannot pause", border_style="red"))
            raise typer.Exit(code=7)
        _print_status(status)
    finally:
        client.close()


@app.command()
def resume(config: Optional[Path] = CONFIG_OPT) -> None:
    """Resume a paused OBS recording."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        try:
            status = resume_recording(client)
        except OBSError as exc:
            err_console.print(Panel(str(exc), title="cannot resume", border_style="red"))
            raise typer.Exit(code=7)
        _print_status(status)
    finally:
        client.close()


@app.command()
def status(
    config: Optional[Path] = CONFIG_OPT,
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Print OBS recording status."""
    cfg = _load(config)
    client = _obs(cfg, quiet=json)
    try:
        st = recording_status(client)
        scene = client.current_scene()
    finally:
        client.close()
    if json:
        typer.echo(
            json_lib.dumps(
                {
                    "active": st.active,
                    "paused": st.paused,
                    "timecode": st.timecode,
                    "bytes": st.bytes,
                    "scene": scene,
                },
                indent=2,
            )
        )
        return
    _print_status(st, scene_name=scene)


@app.command()
def recent(
    config: Optional[Path] = CONFIG_OPT,
    limit: int = typer.Option(10, "--limit", "-n", help="Max files to show."),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List the most recent recordings under config.recording_root."""
    cfg = _load(config)
    root = cfg.recording_root_path
    rows = find_recent(root, limit=limit)

    if json:
        typer.echo(
            json_lib.dumps(
                [
                    {
                        "name": r.name,
                        "path": str(r.path),
                        "size_bytes": r.size_bytes,
                        "modified_at": r.modified_at.isoformat(timespec="seconds"),
                        "age_seconds": r.age_seconds,
                    }
                    for r in rows
                ],
                indent=2,
            )
        )
        return

    if not rows:
        console.print(
            Panel(
                f"No video files found under {root}.\n"
                "Either you haven't recorded yet, or OBS is saving somewhere else "
                "(check OBS → Settings → Output → Recording → Recording Path).",
                title="no recordings",
                border_style="yellow",
            )
        )
        return

    table = Table(title=f"recent recordings · {root}", expand=True)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("file", overflow="fold")
    table.add_column("size", justify="right")
    table.add_column("when", justify="right", style="cyan")
    for i, rec in enumerate(rows, start=1):
        try:
            rel = rec.path.relative_to(root)
        except ValueError:
            rel = rec.path
        table.add_row(str(i), str(rel), fmt_bytes(rec.size_bytes),
                      humanize_age(rec.age_seconds))
    console.print(table)


@app.command()
def clip(
    label: str = typer.Argument(..., help="Label to append to the latest recording filename."),
    config: Optional[Path] = CONFIG_OPT,
) -> None:
    """Stop OBS (if recording) and rename the latest file with a label.

    The new filename is `<original-stem>__<label>.<ext>`. Whitespace in the
    label is replaced with hyphens.
    """
    cfg = _load(config)
    client = _obs(cfg)
    try:
        st = recording_status(client)
        stop_path: str | None = None
        if st.active:
            stop_path = client.stop_recording()
            state.record_finished(stop_path)
    finally:
        client.close()

    candidate: Path | None = None
    if stop_path:
        candidate = Path(stop_path).expanduser()
    elif (last := state.last_recording()) and last.get("output_path"):
        candidate = Path(last["output_path"]).expanduser()
    else:
        rows = find_recent(cfg.recording_root_path, limit=1)
        if rows:
            candidate = rows[0].path

    if candidate is None or not candidate.exists():
        err_console.print(
            Panel(
                "Could not find a recent recording to rename.\n"
                "OBS may not have flushed the file yet — wait a couple of seconds "
                "and try `sonyobs recent` to confirm.",
                title="no file to clip",
                border_style="red",
            )
        )
        raise typer.Exit(code=10)

    clean = "-".join(label.split())
    new_name = f"{candidate.stem}__{clean}{candidate.suffix}"
    new_path = candidate.with_name(new_name)
    try:
        candidate.rename(new_path)
    except OSError as exc:
        err_console.print(
            Panel(f"Rename failed: {exc}", title="clip failed", border_style="red")
        )
        raise typer.Exit(code=11)

    console.print(
        Panel(
            f"{Icons.OK} {candidate.name}\n   {Icons.ARROW} {new_path.name}\n"
            f"[dim]{new_path.parent}[/]",
            title="clipped",
            border_style="green",
        )
    )
    state.record_finished(str(new_path))


@app.command(name="api")
def api_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="API bind host."),
    port: int = typer.Option(8765, "--port", help="API bind port."),
    config: Optional[Path] = CONFIG_OPT,
) -> None:
    """Start the local FastAPI control server."""
    import uvicorn

    from . import api as api_module

    if config is not None:
        # Pre-validate that the config file is loadable before starting the server.
        _load(config)
        import os

        os.environ["RECORDING_AUTO_CONFIG"] = str(config.resolve())

    console.print(
        Panel(
            f"Local API at http://{host}:{port}\nDocs: http://{host}:{port}/docs",
            title="recording-auto api",
            border_style="cyan",
        )
    )
    uvicorn.run(api_module.app, host=host, port=port, log_level="info")


# ---------------------------------------------------------------------------
# obs sub-commands
# ---------------------------------------------------------------------------


@obs_app.command("test")
def obs_test(config: Optional[Path] = CONFIG_OPT) -> None:
    """Test the OBS WebSocket connection and print version info."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        info = client.get_version()
    finally:
        client.close()
    table = Table.grid(padding=(0, 2))
    for key, value in info.items():
        table.add_row(Text(key, style="bold"), str(value))
    console.print(Panel(table, title="OBS WebSocket OK", border_style="green"))


# ---------------------------------------------------------------------------
# scenes sub-commands
# ---------------------------------------------------------------------------


@scenes_app.command("list")
def scenes_list(config: Optional[Path] = CONFIG_OPT) -> None:
    """List OBS scenes."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        scenes = client.list_scenes()
        current = client.current_scene()
    finally:
        client.close()
    table = Table(title="OBS scenes")
    table.add_column("name")
    table.add_column("current", justify="center")
    for name in scenes:
        table.add_row(name, "★" if name == current else "")
    console.print(table)


@app.command()
def autosetup(config: Optional[Path] = CONFIG_OPT) -> None:
    """Auto-create missing OBS inputs + scenes and wire them together.

    Idempotent. Picks compatible input kinds for this OBS version, creates each
    missing input with default settings, then makes sure every scene contains
    the sources its profile lists. Open OBS afterwards and pick the actual
    device for each video input in the Properties panel.
    """
    cfg = _load(config)
    client = _obs(cfg)
    try:
        with spinner(console, "Configuring OBS scenes + inputs"):
            result = run_autosetup(client, cfg)
    finally:
        client.close()

    # ─── inputs ─────────────────────────────────────────────────────────────
    inputs_table = Table(title="inputs", expand=True)
    inputs_table.add_column("name")
    inputs_table.add_column("kind")
    inputs_table.add_column("status")
    for ci in result.inputs:
        status = "already existed" if ci.already_existed else "[green]created[/]"
        inputs_table.add_row(ci.name, ci.kind, status)
    console.print(inputs_table)

    if result.skipped_inputs:
        body = "\n".join(f"  - [bold]{n}[/]: {why}" for n, why in result.skipped_inputs)
        console.print(
            Panel(
                f"{Icons.WARN} Skipped inputs:\n{body}",
                title="skipped",
                border_style="yellow",
            )
        )

    # ─── scenes ─────────────────────────────────────────────────────────────
    scenes_table = Table(title="scenes", expand=True)
    scenes_table.add_column("scene")
    scenes_table.add_column("created")
    scenes_table.add_column("added items", overflow="fold")
    scenes_table.add_column("already present", overflow="fold")
    for sc in result.scenes:
        scenes_table.add_row(
            sc.scene_name,
            "[green]yes[/]" if sc.created_scene else "no",
            ", ".join(sc.added_items) or "—",
            ", ".join(sc.already_present) or "—",
        )
    console.print(scenes_table)

    dir_line = (
        f"recording directory: [bold]{result.record_directory}[/]\n\n"
        if result.record_directory
        else ""
    )
    console.print(
        Panel(
            f"{Icons.OK} OBS is wired up.\n\n"
            f"{dir_line}"
            "Next:\n"
            "  1. Open OBS and click each Video Capture input → Properties → pick the actual device.\n"
            "  2. `sonyobs doctor` to confirm all checks pass.\n"
            "  3. `sonyobs go` to start recording.",
            title="autosetup complete",
            border_style="green",
        )
    )


@scenes_app.command("bootstrap")
def scenes_bootstrap(config: Optional[Path] = CONFIG_OPT) -> None:
    """Create any missing scenes named in config.yaml profiles."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        result = bootstrap_scenes(client, cfg)
    finally:
        client.close()
    if result.created:
        console.print(
            Panel(
                "Created scenes:\n  - " + "\n  - ".join(result.created),
                title="scenes created",
                border_style="green",
            )
        )
    if result.already_present:
        console.print(
            Panel(
                "Already present:\n  - " + "\n  - ".join(result.already_present),
                title="no changes",
                border_style="cyan",
            )
        )
    console.print(
        "Next: open OBS, select each scene, and add your sources "
        "(see docs/OBS_SETUP.md).",
        style="dim",
    )


# ---------------------------------------------------------------------------
# sources sub-commands
# ---------------------------------------------------------------------------


@sources_app.command("list")
def sources_list(config: Optional[Path] = CONFIG_OPT) -> None:
    """List OBS input sources."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        inputs = list_inputs(client)
    finally:
        client.close()
    if not inputs:
        console.print("[yellow]No inputs found in OBS.[/]")
        return
    table = Table(title="OBS inputs")
    table.add_column("name")
    table.add_column("kind")
    for item in inputs:
        table.add_row(str(item.get("name") or ""), str(item.get("kind") or ""))
    console.print(table)


# ---------------------------------------------------------------------------
# profiles sub-commands
# ---------------------------------------------------------------------------


@profiles_app.command("list")
def profiles_list(config: Optional[Path] = CONFIG_OPT) -> None:
    """List configured recording profiles."""
    cfg = _load(config)
    table = Table(title="recording profiles")
    table.add_column("name")
    table.add_column("scene")
    table.add_column("sources")
    table.add_column("default", justify="center")
    for summary in list_profiles(cfg):
        resolved = [cfg.sources.resolve(s) for s in summary.sources]
        table.add_row(
            summary.name,
            summary.scene_name,
            ", ".join(resolved),
            "★" if summary.name == cfg.default_profile else "",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# sony sub-commands  (Sony RX100 detection / quick-connect)
# ---------------------------------------------------------------------------


@sony_app.command("scan")
def sony_scan(
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Scan this Mac for Sony cameras and HDMI capture cards."""
    cams = scan_cameras()
    if json:
        typer.echo(
            json_lib.dumps(
                [
                    {
                        "name": c.name,
                        "source": c.source,
                        "vendor_id": c.vendor_id,
                        "product_id": c.product_id,
                        "is_sony": c.is_sony,
                        "is_rx100": c.is_rx100,
                        "is_capture_card": c.is_capture_card,
                    }
                    for c in cams
                ],
                indent=2,
            )
        )
        return
    if not cams:
        console.print(
            Panel(
                "No cameras detected on this Mac.\n"
                "Make sure the RX100 is plugged in and powered on, or HDMI'd "
                "into a capture card.",
                title="sony scan",
                border_style="yellow",
            )
        )
        return
    table = Table(title="Detected cameras")
    table.add_column("name")
    table.add_column("source", overflow="fold")
    table.add_column("sony?", justify="center")
    table.add_column("RX100?", justify="center")
    table.add_column("capture card?", justify="center")
    table.add_column("USB ids", overflow="fold")
    for cam in cams:
        usb = (
            f"{cam.vendor_id}:{cam.product_id}"
            if cam.vendor_id or cam.product_id
            else "—"
        )
        table.add_row(
            cam.name,
            cam.source,
            "✓" if cam.is_sony else "",
            "✓" if cam.is_rx100 else "",
            "✓" if cam.is_capture_card else "",
            usb,
        )
    console.print(table)
    best = find_sony_rx100()
    if best is None:
        console.print(
            Panel(
                "No Sony or RX100 device was matched.\n"
                "RX100 VI/VII tip: MENU > Network > USB Streaming > On.\n"
                "Or install Sony 'Imaging Edge Webcam' for older RX100 models.",
                title="hint",
                border_style="yellow",
            )
        )
    else:
        label = "RX100" if best.is_rx100 else "Sony" if best.is_sony else "capture card"
        console.print(
            Panel(
                f"Best match: [bold]{best.name}[/]  ({label})",
                title="best match",
                border_style="green",
            )
        )


@sony_app.command("connect")
def sony_connect(
    config: Optional[Path] = CONFIG_OPT,
    obs_source: Optional[str] = typer.Option(
        None,
        "--obs-source",
        help="Force a specific OBS input name to use (skips name matching).",
    ),
) -> None:
    """Find the RX100 and bind it to the matching OBS Video Capture input."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        result = connect_rx100_to_obs(client, cfg, preferred_name=obs_source)
    finally:
        client.close()
    if result.detected:
        console.print(
            Panel(
                f"Device: [bold]{result.detected.name}[/]\n"
                f"Source: {result.detected.source}\n"
                f"USB:    {result.detected.vendor_id}:{result.detected.product_id}",
                title="detected",
                border_style="cyan",
            )
        )
    border = "green" if result.ok else "yellow"
    console.print(Panel(result.message, title="connect result", border_style=border))
    if not result.ok:
        raise typer.Exit(code=8)


if __name__ == "__main__":  # pragma: no cover
    app()
