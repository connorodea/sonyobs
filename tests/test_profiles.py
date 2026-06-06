from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from recording_automation.config import ConfigError, load_config
from recording_automation.profiles import get_profile, list_profiles


YAML = textwrap.dedent(
    """
    recording_root: "~/Movies/TestRecordings"
    default_profile: "talking_head"
    obs:
      host: "localhost"
      port: 4455
      password_env: "P"
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
      dual_camera:
        scene_name: "Dual Camera"
        sources: [sony_camera, macbook_camera, microphone]
    """
).strip()


@pytest.fixture()
def cfg(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML, encoding="utf-8")
    return load_config(p)


def test_list_profiles_has_all(cfg) -> None:
    names = {s.name for s in list_profiles(cfg)}
    assert names == {"talking_head", "screen_tutorial", "dual_camera"}


def test_get_profile_returns_scene(cfg) -> None:
    p = get_profile(cfg, "dual_camera")
    assert p.scene_name == "Dual Camera"
    assert p.sources == ["sony_camera", "macbook_camera", "microphone"]


def test_get_profile_unknown_raises(cfg) -> None:
    with pytest.raises(ConfigError):
        get_profile(cfg, "does_not_exist")


def test_resolved_sources_for_profile(cfg) -> None:
    assert cfg.resolved_sources_for("dual_camera") == [
        "Sony Camera",
        "MacBook Camera",
        "Microphone",
    ]


def test_default_profile_is_in_profiles(cfg) -> None:
    assert cfg.default_profile in cfg.profiles
