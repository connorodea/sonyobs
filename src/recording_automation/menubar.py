"""macOS menu bar app (statusbar item) for sonyobs.

Launches a `rumps`-powered status item that shows live OBS recording state and
exposes the same actions as the CLI: go, stop, pause/resume, profile picker,
recent recordings, doctor, reveal in Finder.

Run:
    sonyobs menubar

Or, after `./scripts/build_app.sh`, launch the bundled `SonyOBS.app` from
`/Applications`.

The menu bar app is intentionally a thin wrapper over the same orchestration
functions the CLI calls — no duplicate business logic.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import rumps
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "rumps is not installed. Run `uv sync --extra menubar` "
        "(or `pip install rumps`)."
    ) from exc

from .config import AppConfig, ConfigError, load_config
from .health import run_doctor
from .obs_client import (
    OBSAuthError,
    OBSClient,
    OBSConnectionError,
    OBSError,
    OBSNotFoundError,
    RecordStatus,
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
from .ui import fmt_bytes, notify


APP_NAME = "SonyOBS"
DEFAULT_TITLE = "○ SonyOBS"
POLL_SECONDS = 1.5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class _PollSnapshot:
    """What the polling timer reads from OBS."""

    ok: bool
    status: RecordStatus | None
    error_message: str | None


def _format_title(snap: _PollSnapshot) -> str:
    if not snap.ok or snap.status is None:
        return "⚠ SonyOBS"
    s = snap.status
    if s.active and s.paused:
        return f"⏸ {s.timecode}"
    if s.active:
        return f"● REC {s.timecode}"
    return DEFAULT_TITLE


def _open_path(path: Path) -> None:
    """`open` a file or directory in Finder."""
    if not path.exists():
        return
    subprocess.run(["open", str(path)], check=False)


def _reveal_in_finder(path: Path) -> None:
    if not path.exists():
        return
    subprocess.run(["open", "-R", str(path)], check=False)


# ---------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------


class SonyOBSMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title=DEFAULT_TITLE, quit_button=None)
        self._lock = threading.Lock()
        self._cfg: AppConfig | None = None
        self._last_snapshot: _PollSnapshot | None = None
        self._config_error: str | None = None

        # Try to load config up front; surface failures in the menu instead of
        # crashing the menu bar.
        self._reload_config(silent=True)

        self._build_menu()

        self._timer = rumps.Timer(self._tick, POLL_SECONDS)
        self._timer.start()

    # -- config -------------------------------------------------------------

    def _reload_config(self, *, silent: bool = False) -> None:
        try:
            self._cfg = load_config()
            self._config_error = None
        except ConfigError as exc:
            self._cfg = None
            self._config_error = str(exc)
            if not silent:
                rumps.alert("Config error", str(exc))

    # -- menu construction --------------------------------------------------

    def _build_menu(self) -> None:
        self._state_item = rumps.MenuItem("Idle", callback=None)

        self._go_item = rumps.MenuItem("Go (default profile)", callback=self._on_go)
        self._stop_item = rumps.MenuItem("Stop", callback=self._on_stop)
        self._pause_item = rumps.MenuItem(
            "Pause", callback=self._on_pause_or_resume
        )

        self._profiles_menu = rumps.MenuItem("Start with profile")
        self._recent_menu = rumps.MenuItem("Recent recordings")

        prefs_menu = rumps.MenuItem("Preferences")
        prefs_menu.add(rumps.MenuItem("Open config.yaml", callback=self._open_config))
        prefs_menu.add(rumps.MenuItem("Open .env", callback=self._open_env))
        prefs_menu.add(
            rumps.MenuItem("Reload config", callback=self._on_reload_config)
        )

        self.menu = [
            self._state_item,
            None,
            self._go_item,
            self._profiles_menu,
            self._pause_item,
            self._stop_item,
            None,
            self._recent_menu,
            rumps.MenuItem("Open OBS Studio", callback=self._open_obs),
            rumps.MenuItem(
                "Open recordings folder", callback=self._open_recordings_folder
            ),
            None,
            rumps.MenuItem("Run Doctor", callback=self._on_doctor),
            prefs_menu,
            None,
            rumps.MenuItem("About", callback=self._on_about),
            rumps.MenuItem("Quit", callback=self._on_quit),
        ]

        self._refresh_profiles_menu()
        self._refresh_recent_menu()

    def _refresh_profiles_menu(self) -> None:
        self._profiles_menu.clear()
        if self._cfg is None:
            self._profiles_menu.add(
                rumps.MenuItem("(config not loaded)", callback=None)
            )
            return
        for summary in list_profiles(self._cfg):
            label = f"{summary.name}  ({summary.scene_name})"
            item = rumps.MenuItem(
                label, callback=self._make_profile_callback(summary.name)
            )
            self._profiles_menu.add(item)

    def _make_profile_callback(self, profile_name: str) -> Callable[[rumps.MenuItem], None]:
        def _cb(_sender: rumps.MenuItem) -> None:
            self._start_recording(profile_name)

        return _cb

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        if self._cfg is None:
            self._recent_menu.add(rumps.MenuItem("(config not loaded)", callback=None))
            return
        recent = find_recent(self._cfg.recording_root_path, limit=8)
        if not recent:
            self._recent_menu.add(rumps.MenuItem("(none yet)", callback=None))
            return
        for r in recent:
            label = f"{r.name}  ·  {fmt_bytes(r.size_bytes)}  ·  {humanize_age(r.age_seconds)}"
            self._recent_menu.add(
                rumps.MenuItem(label, callback=self._make_reveal_callback(r.path))
            )

    def _make_reveal_callback(self, path: Path) -> Callable[[rumps.MenuItem], None]:
        def _cb(_sender: rumps.MenuItem) -> None:
            _reveal_in_finder(path)

        return _cb

    # -- poll timer ---------------------------------------------------------

    def _tick(self, _sender: rumps.Timer) -> None:
        snap = self._poll_obs()
        with self._lock:
            self._last_snapshot = snap

        self.title = _format_title(snap)
        self._update_state_item(snap)
        self._update_action_enablement(snap)

    def _poll_obs(self) -> _PollSnapshot:
        if self._cfg is None:
            return _PollSnapshot(False, None, self._config_error or "no config")
        try:
            with OBSClient(self._cfg.obs) as client:
                return _PollSnapshot(True, recording_status(client), None)
        except OBSError as exc:
            return _PollSnapshot(False, None, str(exc))
        except Exception as exc:  # defensive — never crash the timer
            return _PollSnapshot(False, None, f"{type(exc).__name__}: {exc}")

    def _update_state_item(self, snap: _PollSnapshot) -> None:
        if not snap.ok or snap.status is None:
            self._state_item.title = "⚠ OBS not reachable"
            return
        s = snap.status
        if s.active and s.paused:
            self._state_item.title = (
                f"⏸ Paused  {s.timecode}  ·  {fmt_bytes(s.bytes)}"
            )
        elif s.active:
            self._state_item.title = (
                f"● Recording  {s.timecode}  ·  {fmt_bytes(s.bytes)}"
            )
        else:
            self._state_item.title = "○ Idle"

    def _update_action_enablement(self, snap: _PollSnapshot) -> None:
        s = snap.status
        recording = bool(s and s.active)
        paused = bool(s and s.paused)

        # While recording you can stop / pause-resume; while idle you can start.
        self._go_item.set_callback(None if recording else self._on_go)
        self._stop_item.set_callback(self._on_stop if recording else None)
        if recording:
            self._pause_item.title = "Resume" if paused else "Pause"
            self._pause_item.set_callback(self._on_pause_or_resume)
        else:
            self._pause_item.title = "Pause"
            self._pause_item.set_callback(None)

    # -- actions ------------------------------------------------------------

    def _on_go(self, _sender: rumps.MenuItem) -> None:
        if self._cfg is None:
            rumps.alert("Config error", self._config_error or "Config not loaded.")
            return
        self._start_recording(self._cfg.default_profile)

    def _start_recording(self, profile_name: str) -> None:
        if self._cfg is None:
            rumps.alert("Config error", self._config_error or "Config not loaded.")
            return
        try:
            with OBSClient(self._cfg.obs) as client:
                result = start_recording(client, self._cfg, profile_name)
        except (OBSConnectionError, OBSAuthError, OBSNotFoundError, OBSError) as exc:
            rumps.alert("OBS error", str(exc))
            return

        msg = f"Profile: {profile_name}  ·  Scene: {result.scene_name}"
        if result.missing_sources:
            msg += f"\nMissing sources: {', '.join(result.missing_sources)}"
        notify("Recording started", msg)
        # Force an immediate refresh so the title flips to ● REC right away.
        self._tick(self._timer)

    def _on_stop(self, _sender: rumps.MenuItem) -> None:
        if self._cfg is None:
            return
        try:
            with OBSClient(self._cfg.obs) as client:
                _status, output_path = stop_recording(client)
        except OBSError as exc:
            rumps.alert("OBS error", str(exc))
            return
        notify("Recording stopped", output_path or "saved")
        self._refresh_recent_menu()
        self._tick(self._timer)

    def _on_pause_or_resume(self, sender: rumps.MenuItem) -> None:
        if self._cfg is None:
            return
        try:
            with OBSClient(self._cfg.obs) as client:
                if sender.title == "Resume":
                    resume_recording(client)
                    notify("Recording resumed", "")
                else:
                    pause_recording(client)
                    notify("Recording paused", "")
        except OBSError as exc:
            rumps.alert("OBS error", str(exc))
            return
        self._tick(self._timer)

    def _on_doctor(self, _sender: rumps.MenuItem) -> None:
        try:
            report = run_doctor()
        except Exception as exc:
            rumps.alert("Doctor failed", str(exc))
            return

        lines = []
        for c in report.checks:
            if c.skipped:
                mark = "—"
            elif c.passed:
                mark = "✓"
            else:
                mark = "✗"
            line = f"{mark} {c.name}"
            if c.detail:
                line += f" — {c.detail}"
            if not c.passed and not c.skipped and c.hint:
                line += f"\n    hint: {c.hint}"
            lines.append(line)
        summary = "All good." if report.ok else "One or more checks failed."
        rumps.alert("Doctor", summary + "\n\n" + "\n".join(lines))

    def _open_config(self, _sender: rumps.MenuItem) -> None:
        for candidate in [Path.cwd() / "config.yaml", Path.cwd() / "config.example.yaml"]:
            if candidate.exists():
                _open_path(candidate)
                return
        rumps.alert("config.yaml not found", "Run `sonyobs autosetup` first.")

    def _open_env(self, _sender: rumps.MenuItem) -> None:
        for candidate in [Path.cwd() / ".env", Path.cwd() / ".env.example"]:
            if candidate.exists():
                _open_path(candidate)
                return
        rumps.alert(".env not found", "Copy .env.example to .env and edit.")

    def _on_reload_config(self, _sender: rumps.MenuItem) -> None:
        self._reload_config(silent=False)
        self._refresh_profiles_menu()
        self._refresh_recent_menu()
        notify("SonyOBS", "Config reloaded.")

    def _open_obs(self, _sender: rumps.MenuItem) -> None:
        subprocess.Popen(["open", "-a", "OBS"])

    def _open_recordings_folder(self, _sender: rumps.MenuItem) -> None:
        if self._cfg is None:
            return
        _open_path(self._cfg.recording_root_path)

    def _on_about(self, _sender: rumps.MenuItem) -> None:
        from . import __version__

        rumps.alert(
            APP_NAME,
            f"sonyobs {__version__}\n"
            "Mac Sony OBS Recording Automation\n\n"
            "Local-first. No cloud. Drives OBS over WebSocket.",
        )

    def _on_quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()


def run() -> None:
    """Entry point for `sonyobs menubar` and for the py2app `.app`."""
    SonyOBSMenuBar().run()


if __name__ == "__main__":  # pragma: no cover
    run()
    sys.exit(0)
