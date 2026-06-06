from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from recording_automation.config import (
    AppConfig,
    ConfigError,
    SourceMap,
    load_config,
)


VALID_YAML = textwrap.dedent(
    """
    recording_root: "~/Movies/TestRecordings"
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
        sources:
          - sony_camera
          - microphone
      screen_tutorial:
        scene_name: "Screen Tutorial"
        sources:
          - screen_capture
          - microphone
    """
).strip()


def _write(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_loads_valid_config(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, VALID_YAML)
    cfg = load_config(cfg_path)
    assert isinstance(cfg, AppConfig)
    assert cfg.default_profile == "talking_head"
    assert cfg.obs.port == 4455
    assert "talking_head" in cfg.profiles
    assert cfg.recording_root_path.is_absolute()


def test_resolves_profile_sources(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, VALID_YAML))
    resolved = cfg.resolved_sources_for("talking_head")
    assert resolved == ["Sony Camera", "Microphone"]


def test_missing_profiles_block_fails(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        recording_root: "~/x"
        default_profile: "talking_head"
        obs: {host: "localhost", port: 4455, password_env: "P"}
        sources: {sony_camera: "S", macbook_camera: "M", microphone: "Mic", screen_capture: "Scr"}
        profiles: {}
        """
    ).strip()
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, body))


def test_profile_with_no_sources_fails(tmp_path: Path) -> None:
    body = textwrap.dedent(
        """
        recording_root: "~/x"
        default_profile: "talking_head"
        obs: {host: "localhost", port: 4455, password_env: "P"}
        sources: {sony_camera: "S", macbook_camera: "M", microphone: "Mic", screen_capture: "Scr"}
        profiles:
          talking_head:
            scene_name: "Talking Head"
            sources: []
        """
    ).strip()
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, body))


def test_top_level_not_mapping_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "- not\n- a\n- mapping\n"))


def test_invalid_yaml_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, ":\n  this: [is: not yaml"))


def test_unknown_source_key_raises() -> None:
    sm = SourceMap()
    with pytest.raises(ConfigError):
        sm.resolve("not_a_source")


def test_missing_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RECORDING_AUTO_CONFIG", raising=False)
    with pytest.raises(ConfigError):
        load_config()


def test_obs_password_reads_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config(_write(tmp_path, VALID_YAML))
    monkeypatch.setenv("TEST_OBS_PASSWORD", "hunter2")
    assert cfg.obs.password == "hunter2"
