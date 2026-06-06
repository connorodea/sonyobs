"""Typed configuration loading.

Reads `config.yaml` into Pydantic models and resolves the OBS password from the
environment variable named in `obs.password_env`. Raises clear errors when
required fields are missing or malformed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

from .utils import expand_path


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or is invalid."""


class OBSConfig(BaseModel):
    host: str = "localhost"
    port: int = 4455
    password_env: str = "OBS_PASSWORD"

    @property
    def password(self) -> str:
        value = os.environ.get(self.password_env, "")
        return value


class SourceMap(BaseModel):
    sony_camera: str = "Sony Camera"
    macbook_camera: str = "MacBook Camera"
    microphone: str = "Microphone"
    screen_capture: str = "Screen Capture"

    def as_dict(self) -> dict[str, str]:
        return self.model_dump()

    def resolve(self, key: str) -> str:
        if key not in type(self).model_fields:
            valid = ", ".join(type(self).model_fields.keys())
            raise ConfigError(f"Unknown source key '{key}'. Valid keys: {valid}")
        return getattr(self, key)


class Profile(BaseModel):
    scene_name: str
    sources: list[str] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def _no_empty_sources(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("profile must list at least one source")
        return v


class AppConfig(BaseModel):
    recording_root: str = "~/Movies/OBS_Recordings"
    default_profile: str = "talking_head"
    obs: OBSConfig = Field(default_factory=OBSConfig)
    sources: SourceMap = Field(default_factory=SourceMap)
    profiles: dict[str, Profile] = Field(default_factory=dict)

    @field_validator("profiles")
    @classmethod
    def _profiles_present(cls, v: dict[str, Profile]) -> dict[str, Profile]:
        if not v:
            raise ValueError("at least one profile must be defined")
        return v

    @property
    def recording_root_path(self) -> Path:
        return expand_path(self.recording_root)

    def get_profile(self, name: str) -> Profile:
        if name not in self.profiles:
            available = ", ".join(sorted(self.profiles.keys()))
            raise ConfigError(
                f"Profile '{name}' not found. Available profiles: {available}"
            )
        return self.profiles[name]

    def resolved_sources_for(self, profile_name: str) -> list[str]:
        """Return concrete OBS source names for a profile."""
        profile = self.get_profile(profile_name)
        return [self.sources.resolve(key) for key in profile.sources]


def _candidate_config_paths(explicit: Path | None) -> list[Path]:
    if explicit is not None:
        return [expand_path(explicit)]
    env_path = os.environ.get("RECORDING_AUTO_CONFIG")
    if env_path:
        return [expand_path(env_path)]
    return [
        Path.cwd() / "config.yaml",
        Path.cwd() / "config.example.yaml",
        expand_path("~/.config/recording-automation/config.yaml"),
    ]


def load_dotenv_if_present() -> None:
    """Load a .env file from the current working directory if one exists."""
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    else:
        load_dotenv(override=False)


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate `config.yaml`.

    Looks (in order) at the explicit path, then `$RECORDING_AUTO_CONFIG`,
    then `./config.yaml`, then `./config.example.yaml`, then
    `~/.config/recording-automation/config.yaml`.
    """
    load_dotenv_if_present()

    for candidate in _candidate_config_paths(path):
        if candidate.exists():
            return _parse_yaml(candidate)

    searched = "\n  ".join(str(p) for p in _candidate_config_paths(path))
    raise ConfigError(
        "config.yaml not found. Searched:\n  "
        + searched
        + "\n\nCopy config.example.yaml to config.yaml and edit it."
    )


def _parse_yaml(path: Path) -> AppConfig:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Top-level YAML in {path} must be a mapping")

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(
            f"Invalid config at {path}:\n{exc}"
        ) from exc
