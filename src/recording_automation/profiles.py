"""Profile lookup + listing helpers."""
from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig, Profile


@dataclass(frozen=True)
class ProfileSummary:
    name: str
    scene_name: str
    sources: list[str]


def list_profiles(cfg: AppConfig) -> list[ProfileSummary]:
    summaries: list[ProfileSummary] = []
    for name, profile in cfg.profiles.items():
        summaries.append(
            ProfileSummary(
                name=name,
                scene_name=profile.scene_name,
                sources=list(profile.sources),
            )
        )
    return summaries


def get_profile(cfg: AppConfig, name: str) -> Profile:
    return cfg.get_profile(name)
