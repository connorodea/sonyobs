"""Typer CLI entrypoint: `recording-auto <command>`."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import AppConfig, ConfigError, load_config
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
from .scenes import bootstrap_scenes
from .sony_camera import connect_rx100_to_obs, find_sony_rx100, scan_cameras
from .sources import list_inputs

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


def _obs(cfg: AppConfig) -> OBSClient:
    client = OBSClient(cfg.obs)
    try:
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
    state = "RECORDING" if status.active else "stopped"
    if status.paused:
        state = "PAUSED"
    color = "green" if status.active and not status.paused else (
        "yellow" if status.paused else "white"
    )
    table = Table.grid(padding=(0, 1))
    table.add_row(Text("state", style="bold"), Text(state, style=color))
    table.add_row("timecode", status.timecode or "—")
    table.add_row("bytes", f"{status.bytes:,}")
    if scene_name:
        table.add_row("scene", scene_name)
    console.print(Panel(table, title="recording status", border_style="cyan"))


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
        console.print(ctx.get_help())
        raise typer.Exit()


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
    config: Optional[Path] = CONFIG_OPT,
) -> None:
    """One-keystroke start: switch scene + start recording with the default profile."""
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
    client = _obs(cfg)
    try:
        try:
            result = start_recording(client, cfg, chosen)
        except OBSNotFoundError as exc:
            err_console.print(Panel(str(exc), title="scene missing", border_style="red"))
            raise typer.Exit(code=6)
        if result.missing_sources:
            console.print(
                Panel(
                    "Recording started, but missing in OBS:\n  - "
                    + "\n  - ".join(result.missing_sources),
                    title="warning",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold green]REC[/]  profile=[bold]{result.profile}[/]  "
                    f"scene=[bold]{result.scene_name}[/]",
                    border_style="green",
                )
            )
        _print_status(result.status, scene_name=result.scene_name)
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
def status(config: Optional[Path] = CONFIG_OPT) -> None:
    """Print OBS recording status."""
    cfg = _load(config)
    client = _obs(cfg)
    try:
        _print_status(recording_status(client))
    finally:
        client.close()


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
def sony_scan() -> None:
    """Scan this Mac for Sony cameras and HDMI capture cards."""
    cams = scan_cameras()
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
