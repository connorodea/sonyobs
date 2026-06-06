"""Health-check tests using a mock OBS client.

These tests never reach a real OBS instance — they monkeypatch the OBSClient
class used inside the health module.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from recording_automation import health as health_mod
from recording_automation.config import load_config


VALID_YAML = textwrap.dedent(
    """
    recording_root: "{recording_root}"
    default_profile: "talking_head"
    obs:
      host: "localhost"
      port: 4455
      password_env: "TEST_OBS_PASSWORD"
    sources:
      sony_camera: "Sony Camera"
      macbook_camera: "MacBook Camera"
      microphone: "Microphone"
      screen_capture: "Screen Capture"
    profiles:
      talking_head:
        scene_name: "Talking Head"
        sources: [sony_camera, microphone]
      screen_tutorial:
        scene_name: "Screen Tutorial"
        sources: [screen_capture, microphone]
    """
).strip()


class FakeOBSClient:
    """Minimal stand-in for OBSClient used by run_doctor."""

    def __init__(
        self,
        *,
        connect_error: Exception | None = None,
        scenes: list[str] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        version: dict[str, Any] | None = None,
    ) -> None:
        self._connect_error = connect_error
        self._scenes = scenes or []
        self._inputs = inputs or []
        self._version = version or {
            "obs_version": "30.0.0",
            "obs_web_socket_version": "5.4.0",
        }

    def __init_subclass__(cls, **kwargs: Any) -> None:  # pragma: no cover
        super().__init_subclass__(**kwargs)

    # Mimic OBSClient surface used by health
    def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error

    def close(self) -> None:
        pass

    def get_version(self) -> dict[str, Any]:
        return self._version

    def list_scenes(self) -> list[str]:
        return list(self._scenes)

    def list_inputs(self) -> list[dict[str, Any]]:
        return list(self._inputs)


@pytest.fixture()
def cfg_path(tmp_path: Path) -> Path:
    rec_root = tmp_path / "rec"
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML.format(recording_root=rec_root), encoding="utf-8")
    return p


def _set_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_OBS_PASSWORD", "secret-not-placeholder")


def test_doctor_all_pass(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_password(monkeypatch)
    fake = FakeOBSClient(
        scenes=["Talking Head", "Screen Tutorial"],
        inputs=[
            {"name": "Sony Camera", "kind": "av_capture_input_v2"},
            {"name": "MacBook Camera", "kind": "av_capture_input_v2"},
            {"name": "Microphone", "kind": "coreaudio_input_capture"},
            {"name": "Screen Capture", "kind": "screen_capture"},
        ],
    )
    with patch.object(health_mod, "OBSClient", lambda _cfg: fake):
        report = health_mod.run_doctor(cfg_path)
    assert report.ok, [c.__dict__ for c in report.checks if not c.passed and not c.skipped]


def test_doctor_flags_placeholder_password(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_OBS_PASSWORD", "change_me")
    fake = FakeOBSClient(
        scenes=["Talking Head", "Screen Tutorial"],
        inputs=[],
    )
    with patch.object(health_mod, "OBSClient", lambda _cfg: fake):
        report = health_mod.run_doctor(cfg_path)
    password_check = next(c for c in report.checks if "TEST_OBS_PASSWORD" in c.name)
    assert not password_check.passed
    assert "change_me" in password_check.hint.lower() or "placeholder" in password_check.detail


def test_doctor_obs_unreachable(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_password(monkeypatch)
    from recording_automation.obs_client import OBSConnectionError

    fake = FakeOBSClient(connect_error=OBSConnectionError("boom"))
    with patch.object(health_mod, "OBSClient", lambda _cfg: fake):
        report = health_mod.run_doctor(cfg_path)
    assert not report.ok
    obs_check = next(c for c in report.checks if c.name == "OBS WebSocket reachable")
    assert not obs_check.passed
    # Downstream checks must be skipped, not crash
    skipped = [c for c in report.checks if c.skipped]
    assert any(c.name == "OBS sources present" for c in skipped)


def test_doctor_missing_sources_and_scenes(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_password(monkeypatch)
    fake = FakeOBSClient(
        scenes=["Talking Head"],  # Screen Tutorial missing
        inputs=[
            {"name": "Sony Camera", "kind": "av_capture_input_v2"},
            # Microphone missing
        ],
    )
    with patch.object(health_mod, "OBSClient", lambda _cfg: fake):
        report = health_mod.run_doctor(cfg_path)
    src = next(c for c in report.checks if c.name == "OBS sources present")
    scn = next(c for c in report.checks if c.name == "OBS scenes present")
    assert not src.passed
    assert "Microphone" in src.detail
    assert not scn.passed
    assert "Screen Tutorial" in scn.detail


def test_health_payload_shape(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_password(monkeypatch)
    monkeypatch.setenv("RECORDING_AUTO_CONFIG", str(cfg_path))
    fake = FakeOBSClient(
        scenes=["Talking Head", "Screen Tutorial"],
        inputs=[
            {"name": "Sony Camera", "kind": "x"},
            {"name": "MacBook Camera", "kind": "x"},
            {"name": "Microphone", "kind": "x"},
            {"name": "Screen Capture", "kind": "x"},
        ],
    )
    with patch.object(health_mod, "OBSClient", lambda _cfg: fake):
        payload = health_mod.health_payload()
    assert "ok" in payload
    assert "checks" in payload
    assert isinstance(payload["checks"], list)
    for check in payload["checks"]:
        assert {"name", "passed", "skipped", "detail", "hint"} <= check.keys()


def test_config_loads_via_helper(cfg_path: Path) -> None:
    cfg = load_config(cfg_path)
    assert cfg.default_profile == "talking_head"
