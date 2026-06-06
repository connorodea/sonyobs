"""High-level recording orchestration: switch scene + start/stop OBS."""
from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .obs_client import OBSClient, RecordStatus
from .scenes import switch_to_profile_scene
from .sources import verify_profile_sources
from .utils import dated_subfolder


@dataclass(frozen=True)
class StartResult:
    scene_name: str
    profile: str
    status: RecordStatus
    missing_sources: list[str]
    output_root: str


def start_recording(client: OBSClient, cfg: AppConfig, profile_name: str) -> StartResult:
    """Switch to the profile's scene, then start OBS recording.

    Missing sources are reported in the result rather than blocking the start
    so that the user can iterate. The CLI surfaces them as warnings.
    """
    scene_name = switch_to_profile_scene(client, cfg, profile_name)

    checks = verify_profile_sources(client, cfg, profile_name)
    missing = [c.name for c in checks if not c.exists]

    # Make sure today's folder exists; OBS still controls the actual save path.
    folder = dated_subfolder(cfg.recording_root_path)

    status = client.start_recording()

    return StartResult(
        scene_name=scene_name,
        profile=profile_name,
        status=status,
        missing_sources=missing,
        output_root=str(folder),
    )


def stop_recording(client: OBSClient) -> tuple[RecordStatus, str | None]:
    output_path = client.stop_recording()
    return client.get_record_status(), output_path


def pause_recording(client: OBSClient) -> RecordStatus:
    client.pause_recording()
    return client.get_record_status()


def resume_recording(client: OBSClient) -> RecordStatus:
    client.resume_recording()
    return client.get_record_status()


def status(client: OBSClient) -> RecordStatus:
    return client.get_record_status()
