"""Scene bootstrap + helpers.

The app does not author full scene compositions over the WebSocket; it ensures
the named scenes exist so the user can lay them out in OBS, and switches
between them when starting a profile-based recording.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .obs_client import OBSClient


@dataclass(frozen=True)
class SceneBootstrapResult:
    created: list[str]
    already_present: list[str]


def bootstrap_scenes(client: OBSClient, cfg: AppConfig) -> SceneBootstrapResult:
    """Create any scenes named in profiles that don't already exist in OBS."""
    existing = set(client.list_scenes())
    desired = [p.scene_name for p in cfg.profiles.values()]

    created: list[str] = []
    already: list[str] = []
    for name in desired:
        if name in existing:
            already.append(name)
            continue
        client.create_scene(name)
        created.append(name)
        existing.add(name)

    return SceneBootstrapResult(created=created, already_present=already)


def switch_to_profile_scene(client: OBSClient, cfg: AppConfig, profile_name: str) -> str:
    """Switch OBS to the scene for the given profile. Returns scene name."""
    profile = cfg.get_profile(profile_name)
    client.set_current_scene(profile.scene_name)
    return profile.scene_name
