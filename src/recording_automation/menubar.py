"""macOS menu bar app (statusbar item) for sonyobs.

Apple/OpenAI-flavoured minimalism:

* Status item icon is a real SF Symbol (`record.circle`, `record.circle.fill`,
  `pause.circle.fill`, `exclamationmark.triangle`) rendered as a template
  image, so it adapts to dark/light mode and Reduce Transparency.
* Timecode beside the icon uses the system monospaced-digit font so digits
  don't jitter as they tick.
* Menu uses sentence-case labels, single-character keyboard shortcuts on the
  hot paths (⌘R start, ⌘. stop, ⌘P pause, ⌘D diagnostics, ⌘, settings,
  ⌘Q quit), and only the dividers it actually needs.

Run:
    sonyobs menubar

Or, after `./scripts/build_app.sh`, launch the bundled `SonyOBS.app`.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import rumps
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "rumps is not installed. Run `uv sync --extra menubar` "
        "(or `pip install rumps`)."
    ) from exc

# PyObjC is pulled in as a rumps dep on macOS. We use it directly to render
# SF Symbols + a monospaced-digit timecode in the status bar.
try:
    from AppKit import (  # type: ignore
        NSAttributedString,
        NSFont,
        NSFontWeightRegular,
        NSImage,
    )
    from Foundation import NSDictionary  # type: ignore

    HAS_APPKIT = True
except Exception:  # pragma: no cover - non-mac or import failure
    HAS_APPKIT = False

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
POLL_SECONDS = 1.5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class _PollSnapshot:
    ok: bool
    status: RecordStatus | None
    error_message: str | None


def _sf_image(name: str) -> Any | None:
    """Return an SF Symbol as a template NSImage, or None on macOS < 11."""
    if not HAS_APPKIT:
        return None
    try:
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "SonyOBS")
    except Exception:
        return None
    if img is None:
        return None
    img.setTemplate_(True)
    return img


def _mono_timecode_attr(text: str) -> Any | None:
    """Render the timecode in the system monospaced-digit font."""
    if not HAS_APPKIT or not text:
        return None
    try:
        font = NSFont.monospacedDigitSystemFontOfSize_weight_(
            NSFont.systemFontSize(), NSFontWeightRegular
        )
    except Exception:
        return None
    attrs = NSDictionary.dictionaryWithDictionary_({"NSFont": font})
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def _open_path(path: Path) -> None:
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
        # Start with no title; the status item shows an SF Symbol once the run
        # loop is up. On older macOS where SF Symbols are unavailable we fall
        # back to a single restrained glyph.
        super().__init__(APP_NAME, title="", quit_button=None)
        self._lock = threading.Lock()
        self._cfg: AppConfig | None = None
        self._last_snapshot: _PollSnapshot | None = None
        self._config_error: str | None = None
        self._icon_applied = False

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
                rumps.alert("Configuration error", str(exc))

    # -- menu construction --------------------------------------------------

    def _build_menu(self) -> None:
        # State line is disabled (no callback) — it's a readout, not an action.
        self._state_item = rumps.MenuItem("Idle", callback=None)

        self._start_item = rumps.MenuItem(
            "Start recording", callback=self._on_start, key="r"
        )
        self._stop_item = rumps.MenuItem(
            "Stop", callback=self._on_stop, key="."
        )
        self._pause_item = rumps.MenuItem(
            "Pause", callback=self._on_pause_or_resume, key="p"
        )

        self._profiles_menu = rumps.MenuItem("Start with profile")
        self._recent_menu = rumps.MenuItem("Recent")

        settings_menu = rumps.MenuItem("Settings")
        settings_menu.add(
            rumps.MenuItem("Edit configuration…", callback=self._open_config, key=",")
        )
        settings_menu.add(rumps.MenuItem("Edit environment…", callback=self._open_env))
        settings_menu.add(
            rumps.MenuItem("Reload configuration", callback=self._on_reload_config)
        )

        self.menu = [
            self._state_item,
            None,
            self._start_item,
            self._profiles_menu,
            self._pause_item,
            self._stop_item,
            None,
            self._recent_menu,
            rumps.MenuItem("Open in OBS Studio", callback=self._open_obs),
            rumps.MenuItem(
                "Show recordings folder", callback=self._open_recordings_folder
            ),
            None,
            rumps.MenuItem("Run diagnostics", callback=self._on_doctor, key="d"),
            settings_menu,
            None,
            rumps.MenuItem(f"About {APP_NAME}", callback=self._on_about),
            rumps.MenuItem(f"Quit {APP_NAME}", callback=self._on_quit, key="q"),
        ]

        self._refresh_profiles_menu()
        self._refresh_recent_menu()

    def _refresh_profiles_menu(self) -> None:
        self._profiles_menu.clear()
        if self._cfg is None:
            self._profiles_menu.add(
                rumps.MenuItem("Configuration unavailable", callback=None)
            )
            return
        default = self._cfg.default_profile
        for summary in list_profiles(self._cfg):
            # Mark the default profile with a checkmark (rumps `state=1`)
            # rather than mangling the title with a bullet.
            is_default = summary.name == default
            item = rumps.MenuItem(
                summary.name, callback=self._make_profile_callback(summary.name)
            )
            if is_default:
                item.state = 1
            self._profiles_menu.add(item)

    def _make_profile_callback(self, profile_name: str) -> Callable[[rumps.MenuItem], None]:
        def _cb(_sender: rumps.MenuItem) -> None:
            self._start_recording(profile_name)

        return _cb

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        if self._cfg is None:
            self._recent_menu.add(
                rumps.MenuItem("Configuration unavailable", callback=None)
            )
            return
        recent = find_recent(self._cfg.recording_root_path, limit=8)
        if not recent:
            self._recent_menu.add(rumps.MenuItem("No recordings yet", callback=None))
            return
        for r in recent:
            # Just the filename — keep the menu narrow and Apple-clean.
            # Size + age go in the disabled subtitle row inside the dialog.
            label = r.name
            item = rumps.MenuItem(
                label, callback=self._make_reveal_callback(r.path)
            )
            self._recent_menu.add(item)
        self._recent_menu.add(rumps.separator)
        self._recent_menu.add(
            rumps.MenuItem(
                "Show all in Finder", callback=self._open_recordings_folder
            )
        )

    def _make_reveal_callback(self, path: Path) -> Callable[[rumps.MenuItem], None]:
        def _cb(_sender: rumps.MenuItem) -> None:
            _reveal_in_finder(path)

        return _cb

    # -- status-item icon + title ------------------------------------------

    def _statusitem_button(self) -> Any | None:
        """Reach into rumps for the underlying NSStatusBarButton (if up)."""
        try:
            return self._nsapp.nsstatusitem.button()  # type: ignore[attr-defined]
        except Exception:
            return None

    def _apply_status(self, snap: _PollSnapshot) -> None:
        """Set the SF Symbol + monospaced timecode on the status item.

        Falls back to a single unicode glyph if PyObjC / SF Symbols are
        unavailable.
        """
        # Pick the symbol + accompanying text.
        if not snap.ok or snap.status is None:
            symbol = "exclamationmark.triangle"
            text = ""
        else:
            s = snap.status
            if s.active and s.paused:
                symbol = "pause.circle.fill"
                text = f" {s.timecode}"
            elif s.active:
                symbol = "record.circle.fill"
                text = f" {s.timecode}"
            else:
                symbol = "record.circle"
                text = ""

        button = self._statusitem_button()
        img = _sf_image(symbol) if button is not None else None

        if button is not None and img is not None:
            button.setImage_(img)
            # Stick the image to the left edge of the title; the title sits
            # to the right.
            try:
                button.setImagePosition_(2)  # NSImageLeft
            except Exception:
                pass
            attr = _mono_timecode_attr(text)
            if attr is not None:
                button.setAttributedTitle_(attr)
            else:
                button.setTitle_(text)
            self._icon_applied = True
            return

        # Fallback: no PyObjC. Use a single restrained glyph + timecode.
        if not snap.ok or snap.status is None:
            self.title = "⚠"
        else:
            s = snap.status
            if s.active and s.paused:
                self.title = f"⏸ {s.timecode}"
            elif s.active:
                self.title = f"● {s.timecode}"
            else:
                self.title = "◯"

    # -- poll timer ---------------------------------------------------------

    def _tick(self, _sender: rumps.Timer) -> None:
        snap = self._poll_obs()
        with self._lock:
            self._last_snapshot = snap

        self._apply_status(snap)
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
            self._state_item.title = "OBS not reachable"
            return
        s = snap.status
        if s.active and s.paused:
            self._state_item.title = (
                f"Paused — {s.timecode} · {fmt_bytes(s.bytes)}"
            )
        elif s.active:
            self._state_item.title = (
                f"Recording — {s.timecode} · {fmt_bytes(s.bytes)}"
            )
        else:
            self._state_item.title = "Idle"

    def _update_action_enablement(self, snap: _PollSnapshot) -> None:
        s = snap.status
        recording = bool(s and s.active)
        paused = bool(s and s.paused)

        self._start_item.set_callback(None if recording else self._on_start)
        self._stop_item.set_callback(self._on_stop if recording else None)
        if recording:
            self._pause_item.title = "Resume" if paused else "Pause"
            self._pause_item.set_callback(self._on_pause_or_resume)
        else:
            self._pause_item.title = "Pause"
            self._pause_item.set_callback(None)

    # -- actions ------------------------------------------------------------

    def _on_start(self, _sender: rumps.MenuItem) -> None:
        if self._cfg is None:
            rumps.alert("Configuration error", self._config_error or "Not loaded.")
            return
        self._start_recording(self._cfg.default_profile)

    def _start_recording(self, profile_name: str) -> None:
        if self._cfg is None:
            rumps.alert("Configuration error", self._config_error or "Not loaded.")
            return
        try:
            with OBSClient(self._cfg.obs) as client:
                result = start_recording(client, self._cfg, profile_name)
        except (OBSConnectionError, OBSAuthError, OBSNotFoundError, OBSError) as exc:
            rumps.alert("OBS error", str(exc))
            return

        msg = f"Profile {profile_name} · Scene {result.scene_name}"
        if result.missing_sources:
            msg += f"\nMissing sources: {', '.join(result.missing_sources)}"
        notify("Recording started", msg)
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
        notify("Recording stopped", output_path or "Saved")
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
            rumps.alert("Diagnostics failed", str(exc))
            return

        lines = []
        for c in report.checks:
            if c.skipped:
                mark = "•"
            elif c.passed:
                mark = "✓"
            else:
                mark = "✗"
            line = f"{mark}  {c.name}"
            if c.detail:
                line += f"\n    {c.detail}"
            if not c.passed and not c.skipped and c.hint:
                line += f"\n    → {c.hint}"
            lines.append(line)
        headline = "Everything checks out." if report.ok else "Some checks failed."
        rumps.alert("Diagnostics", headline + "\n\n" + "\n\n".join(lines))

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
        notify(APP_NAME, "Configuration reloaded.")

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
            f"Version {__version__}\n\n"
            "Local-first recording automation for OBS Studio.\n"
            "No cloud. No accounts. All controls go through obs-websocket.",
        )

    def _on_quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()


def run() -> None:
    """Entry point for `sonyobs menubar` and for the py2app `.app`."""
    SonyOBSMenuBar().run()


if __name__ == "__main__":  # pragma: no cover
    run()
    sys.exit(0)
