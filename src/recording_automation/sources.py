"""Source listing + profile→source mapping checks."""
from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .obs_client import OBSClient


@dataclass(frozen=True)
class SourceCheck:
    name: str
    exists: bool
    kind: str | None = None


def list_inputs(client: OBSClient) -> list[dict[str, str | None]]:
    return client.list_inputs()


def verify_profile_sources(
    client: OBSClient, cfg: AppConfig, profile_name: str
) -> list[SourceCheck]:
    """Check that every source a profile needs exists in OBS."""
    resolved_names = cfg.resolved_sources_for(profile_name)
    inputs = {item["name"]: item for item in client.list_inputs()}
    return [
        SourceCheck(name=name, exists=name in inputs, kind=(inputs.get(name) or {}).get("kind"))
        for name in resolved_names
    ]


def verify_all_mapped_sources(client: OBSClient, cfg: AppConfig) -> list[SourceCheck]:
    """Check every source in `cfg.sources` regardless of profile."""
    inputs = {item["name"]: item for item in client.list_inputs()}
    checks: list[SourceCheck] = []
    for _logical, real_name in cfg.sources.as_dict().items():
        checks.append(
            SourceCheck(
                name=real_name,
                exists=real_name in inputs,
                kind=(inputs.get(real_name) or {}).get("kind"),
            )
        )
    return checks
