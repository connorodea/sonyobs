"""Auto-create OBS inputs and attach them to scenes via WebSocket.

Idempotent: re-running won't duplicate inputs or scene items.

What it does (in order):
  1. Calls `get_input_kind_list` so we know what kinds OBS exposes on this
     machine (kinds vary by OBS version + plugins).
  2. For each logical source (sony_camera, macbook_camera, microphone,
     screen_capture), picks the best matching `input_kind` and creates the
     input if one with that name doesn't exist.
  3. For each profile, makes sure the scene exists and that every resolved
     source name is present as a scene item inside it.

This module deliberately does NOT pick a specific physical device for video
captures — OBS opens the source with default settings and the user can swap
the actual device in the Properties panel. The point is to scaffold the
graph; final device selection is one click in OBS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .obs_client import OBSClient


# Mapping: logical source key -> ordered list of input_kind candidates.
# We try kinds in order; the first one OBS reports as available is used.
KIND_CANDIDATES: dict[str, tuple[str, ...]] = {
    "sony_camera": ("av_capture_input_v2", "av_capture_input"),
    "macbook_camera": ("av_capture_input_v2", "av_capture_input"),
    "microphone": ("coreaudio_input_capture",),
    "screen_capture": (
        "screen_capture",                   # macOS ScreenCaptureKit (OBS 30+)
        "macos-display-capture",            # older fallback
        "display_capture",
    ),
}


@dataclass(frozen=True)
class CreatedInput:
    name: str
    kind: str
    already_existed: bool


@dataclass(frozen=True)
class ScenePopulation:
    scene_name: str
    created_scene: bool
    added_items: list[str]
    already_present: list[str]


@dataclass(frozen=True)
class AutosetupResult:
    inputs: list[CreatedInput]
    skipped_inputs: list[tuple[str, str]]   # (logical, reason)
    scenes: list[ScenePopulation]
    record_directory: str | None = None


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _list_input_kinds(client: OBSClient) -> set[str]:
    """Return the set of input_kind strings this OBS supports."""
    raw = client.raw
    try:
        # obsws-python ReqClient.get_input_kind_list requires `unversioned`.
        resp = raw.get_input_kind_list(False)
    except Exception:
        return set()
    kinds = getattr(resp, "input_kinds", None) or []
    return {k for k in kinds if isinstance(k, str)}


def _pick_kind(logical: str, available: set[str]) -> str | None:
    for candidate in KIND_CANDIDATES.get(logical, ()):
        if candidate in available:
            return candidate
    return None


def _default_settings(kind: str) -> dict[str, Any]:
    """Conservative defaults — OBS will fill in the rest from its UI panel."""
    if kind == "screen_capture":
        # ScreenCaptureKit on macOS — type 0 = display.
        return {"type": 0, "show_cursor": True}
    return {}


def _list_scene_item_names(client: OBSClient, scene_name: str) -> list[str]:
    raw = client.raw
    try:
        resp = raw.get_scene_item_list(scene_name)
    except Exception:
        return []
    items = getattr(resp, "scene_items", []) or []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("sourceName")
        else:
            name = getattr(item, "sourceName", None)
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def run_autosetup(client: OBSClient, cfg: AppConfig) -> AutosetupResult:
    """Bootstrap inputs + scenes for every profile in config."""
    available_kinds = _list_input_kinds(client)
    existing_inputs = {item["name"]: item for item in client.list_inputs()}

    created_inputs: list[CreatedInput] = []
    skipped: list[tuple[str, str]] = []

    for logical, real_name in cfg.sources.as_dict().items():
        if real_name in existing_inputs:
            created_inputs.append(
                CreatedInput(
                    name=real_name,
                    kind=str(existing_inputs[real_name].get("kind") or "?"),
                    already_existed=True,
                )
            )
            continue

        kind = _pick_kind(logical, available_kinds)
        if kind is None:
            skipped.append(
                (logical, f"no compatible input_kind on this OBS (have: {sorted(available_kinds)})")
            )
            continue

        # CreateInput needs a scene to host the new input. We use the first
        # scene that exists; if no scenes exist, we create a temp one and use
        # it as the host. We later add the same input to every profile scene
        # via CreateSceneItem (which doesn't duplicate the underlying input).
        host_scene = _ensure_host_scene(client, cfg)
        try:
            client.raw.create_input(
                host_scene,
                real_name,
                kind,
                _default_settings(kind),
                True,
            )
            created_inputs.append(
                CreatedInput(name=real_name, kind=kind, already_existed=False)
            )
        except Exception as exc:
            skipped.append((logical, f"create_input failed: {exc}"))

    # Populate every profile scene
    scenes_existing = set(client.list_scenes())
    scene_results: list[ScenePopulation] = []
    for profile_name, profile in cfg.profiles.items():
        created_scene = False
        if profile.scene_name not in scenes_existing:
            client.create_scene(profile.scene_name)
            scenes_existing.add(profile.scene_name)
            created_scene = True

        existing_items = set(_list_scene_item_names(client, profile.scene_name))
        added: list[str] = []
        already: list[str] = []

        for logical in profile.sources:
            real_name = cfg.sources.resolve(logical)
            if real_name in existing_items:
                already.append(real_name)
                continue
            # Skip if the input creation failed earlier
            if not _input_exists(client, real_name):
                continue
            try:
                client.raw.create_scene_item(
                    profile.scene_name,
                    real_name,
                    True,
                )
                added.append(real_name)
                existing_items.add(real_name)
            except Exception:
                # Best-effort; scene_items errors are non-fatal
                pass

        scene_results.append(
            ScenePopulation(
                scene_name=profile.scene_name,
                created_scene=created_scene,
                added_items=added,
                already_present=already,
            )
        )

    # Point OBS's recording output at the configured root.
    # SetRecordDirectory is unreliable on some OBS builds (returns 500), so we
    # also write the underlying profile parameters that drive both the simple
    # and advanced output modes.
    record_directory: str | None = None
    target_dir = cfg.recording_root_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target_str = str(target_dir)

    try:
        client.raw.set_record_directory(target_str)
        record_directory = target_str
    except Exception:
        pass
    for category, name in (
        ("SimpleOutput", "FilePath"),
        ("AdvOut", "RecFilePath"),
        ("AdvOut", "FFFilePath"),
    ):
        try:
            client.raw.set_profile_parameter(category, name, target_str)
            record_directory = target_str
        except Exception:
            pass

    return AutosetupResult(
        inputs=created_inputs,
        skipped_inputs=skipped,
        scenes=scene_results,
        record_directory=record_directory,
    )


def _ensure_host_scene(client: OBSClient, cfg: AppConfig) -> str:
    """Return a scene name we can host newly-created inputs in."""
    scenes = client.list_scenes()
    if scenes:
        return scenes[0]
    # No scenes exist at all — make the default profile's scene first.
    name = cfg.get_profile(cfg.default_profile).scene_name
    client.create_scene(name)
    return name


def _input_exists(client: OBSClient, name: str) -> bool:
    return any(item["name"] == name for item in client.list_inputs())
