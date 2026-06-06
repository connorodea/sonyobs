"""Doctor / health-check pipeline.

Each check returns a `HealthCheck` with pass/fail + a remediation hint. The
checks degrade gracefully: an OBS connection failure won't crash later checks,
they'll just be reported as `skipped`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig, ConfigError, load_config
from .obs_client import (
    OBSAuthError,
    OBSClient,
    OBSConnectionError,
    OBSError,
)
from .utils import expand_path, is_writable


@dataclass
class HealthCheck:
    name: str
    passed: bool
    detail: str = ""
    hint: str = ""
    skipped: bool = False


@dataclass
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed or c.skipped for c in self.checks)

    def add(self, check: HealthCheck) -> None:
        self.checks.append(check)


def _check_config(cfg_path: Path | None) -> tuple[HealthCheck, AppConfig | None]:
    try:
        cfg = load_config(cfg_path)
        return (
            HealthCheck(
                name="config.yaml loads",
                passed=True,
                detail=f"{len(cfg.profiles)} profiles defined",
            ),
            cfg,
        )
    except ConfigError as exc:
        return (
            HealthCheck(
                name="config.yaml loads",
                passed=False,
                detail=str(exc).splitlines()[0],
                hint="Copy config.example.yaml to config.yaml and edit it.",
            ),
            None,
        )


def _check_env_password(cfg: AppConfig) -> HealthCheck:
    var = cfg.obs.password_env
    value = os.environ.get(var, "")
    if not value:
        return HealthCheck(
            name=f"${var} is set",
            passed=False,
            detail="empty",
            hint=f"Add `{var}=<your-obs-password>` to your .env file.",
        )
    if value == "change_me":
        return HealthCheck(
            name=f"${var} is set",
            passed=False,
            detail="placeholder value",
            hint=f"Replace `change_me` in .env with the real OBS WebSocket password.",
        )
    return HealthCheck(name=f"${var} is set", passed=True, detail=f"{len(value)} chars")


def _check_recording_root(cfg: AppConfig) -> HealthCheck:
    root = cfg.recording_root_path
    if not root.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return HealthCheck(
                name="recording_root writable",
                passed=False,
                detail=f"could not create {root}: {exc}",
                hint=f"Pick a writable folder for recording_root in config.yaml.",
            )
    if not is_writable(root):
        return HealthCheck(
            name="recording_root writable",
            passed=False,
            detail=str(root),
            hint=f"Grant write permission on {root} or choose a different folder.",
        )
    return HealthCheck(name="recording_root writable", passed=True, detail=str(root))


def _check_obs_connection(cfg: AppConfig) -> tuple[HealthCheck, OBSClient | None]:
    client = OBSClient(cfg.obs)
    try:
        client.connect()
    except OBSConnectionError as exc:
        return (
            HealthCheck(
                name="OBS WebSocket reachable",
                passed=False,
                detail=str(exc).splitlines()[0],
                hint="Open OBS, then Tools > WebSocket Server Settings > Enable.",
            ),
            None,
        )
    except OBSAuthError as exc:
        return (
            HealthCheck(
                name="OBS WebSocket reachable",
                passed=False,
                detail="auth failed",
                hint=str(exc).splitlines()[-1],
            ),
            None,
        )
    except OBSError as exc:
        return (
            HealthCheck(
                name="OBS WebSocket reachable",
                passed=False,
                detail=str(exc),
                hint="See OBS logs.",
            ),
            None,
        )

    try:
        info = client.get_version()
    except OBSError as exc:
        return (
            HealthCheck(
                name="OBS WebSocket reachable",
                passed=False,
                detail=str(exc),
                hint="Try restarting OBS.",
            ),
            None,
        )

    return (
        HealthCheck(
            name="OBS WebSocket reachable",
            passed=True,
            detail=f"OBS {info.get('obs_version')} / ws {info.get('obs_web_socket_version')}",
        ),
        client,
    )


def _check_sources(client: OBSClient, cfg: AppConfig) -> HealthCheck:
    try:
        inputs = {item["name"] for item in client.list_inputs()}
    except OBSError as exc:
        return HealthCheck(
            name="OBS sources present",
            passed=False,
            detail=str(exc),
            hint="Check OBS logs.",
        )
    expected = list(cfg.sources.as_dict().values())
    missing = [name for name in expected if name not in inputs]
    if missing:
        return HealthCheck(
            name="OBS sources present",
            passed=False,
            detail=f"missing: {', '.join(missing)}",
            hint=(
                "Add these as inputs in OBS (Video/Audio/Display Capture) so the "
                "names match config.yaml. Or update sources: in config.yaml to "
                "match the names you already use."
            ),
        )
    return HealthCheck(
        name="OBS sources present",
        passed=True,
        detail=f"{len(expected)} sources mapped",
    )


def _check_scenes(client: OBSClient, cfg: AppConfig) -> HealthCheck:
    try:
        scenes = set(client.list_scenes())
    except OBSError as exc:
        return HealthCheck(
            name="OBS scenes present",
            passed=False,
            detail=str(exc),
            hint="Check OBS logs.",
        )
    expected = [p.scene_name for p in cfg.profiles.values()]
    missing = [name for name in expected if name not in scenes]
    if missing:
        return HealthCheck(
            name="OBS scenes present",
            passed=False,
            detail=f"missing: {', '.join(missing)}",
            hint="Run `recording-auto scenes bootstrap` to create them.",
        )
    return HealthCheck(
        name="OBS scenes present",
        passed=True,
        detail=f"{len(expected)} scenes mapped",
    )


def run_doctor(cfg_path: Path | None = None) -> HealthReport:
    """Run all health checks. Always returns a report; never raises."""
    report = HealthReport()

    cfg_check, cfg = _check_config(cfg_path)
    report.add(cfg_check)
    if cfg is None:
        return report

    report.add(_check_env_password(cfg))
    report.add(_check_recording_root(cfg))

    obs_check, client = _check_obs_connection(cfg)
    report.add(obs_check)

    if client is None:
        report.add(HealthCheck(name="OBS sources present", passed=False, skipped=True))
        report.add(HealthCheck(name="OBS scenes present", passed=False, skipped=True))
        return report

    try:
        report.add(_check_sources(client, cfg))
        report.add(_check_scenes(client, cfg))
    finally:
        client.close()

    return report


# Convenience for FastAPI
def health_payload() -> dict:
    report = run_doctor()
    return {
        "ok": report.ok,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "skipped": c.skipped,
                "detail": c.detail,
                "hint": c.hint,
            }
            for c in report.checks
        ],
    }


__all__ = [
    "HealthCheck",
    "HealthReport",
    "run_doctor",
    "health_payload",
    "expand_path",
]
