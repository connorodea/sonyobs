"""FastAPI control server.

Run with `recording-auto api` or `uvicorn recording_automation.api:app`.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .config import AppConfig, ConfigError, load_config
from .health import health_payload
from .obs_client import (
    OBSAuthError,
    OBSClient,
    OBSConnectionError,
    OBSError,
    OBSNotFoundError,
)
from .recording import (
    pause_recording,
    resume_recording,
    start_recording,
    stop_recording,
)
from .sony_camera import connect_rx100_to_obs, scan_cameras

app = FastAPI(
    title="Recording Automation API",
    version=__version__,
    description="Local HTTP control surface for OBS recording.",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config() -> AppConfig:
    try:
        return load_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=f"config error: {exc}")


def _client(cfg: AppConfig) -> OBSClient:
    client = OBSClient(cfg.obs)
    try:
        client.connect()
    except OBSConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OBSAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except OBSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return client


def _status_dict(status) -> dict[str, Any]:
    return {
        "active": status.active,
        "paused": status.paused,
        "timecode": status.timecode,
        "bytes": status.bytes,
    }


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class StartRequest(BaseModel):
    profile: str


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return health_payload()


@app.get("/status")
def status_route() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        status = client.get_record_status()
        scene = client.current_scene()
    finally:
        client.close()
    return {"status": _status_dict(status), "current_scene": scene}


@app.post("/recording/start")
def recording_start(body: StartRequest) -> dict[str, Any]:
    cfg = _config()
    if body.profile not in cfg.profiles:
        raise HTTPException(
            status_code=400,
            detail=f"unknown profile '{body.profile}'. "
            f"available: {sorted(cfg.profiles)}",
        )
    client = _client(cfg)
    try:
        try:
            result = start_recording(client, cfg, body.profile)
        except OBSNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    finally:
        client.close()
    return {
        "profile": result.profile,
        "scene": result.scene_name,
        "missing_sources": result.missing_sources,
        "output_root": result.output_root,
        "status": _status_dict(result.status),
    }


@app.post("/recording/stop")
def recording_stop() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        status, output_path = stop_recording(client)
    finally:
        client.close()
    return {"status": _status_dict(status), "output_path": output_path}


@app.post("/recording/pause")
def recording_pause() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        try:
            status = pause_recording(client)
        except OBSError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    finally:
        client.close()
    return {"status": _status_dict(status)}


@app.post("/recording/resume")
def recording_resume() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        try:
            status = resume_recording(client)
        except OBSError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    finally:
        client.close()
    return {"status": _status_dict(status)}


@app.get("/sources")
def sources_route() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        inputs = client.list_inputs()
    finally:
        client.close()
    return {"sources": inputs}


@app.get("/scenes")
def scenes_route() -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        scenes = client.list_scenes()
        current = client.current_scene()
    finally:
        client.close()
    return {"scenes": scenes, "current": current}


@app.get("/sony/scan")
def sony_scan_route() -> dict[str, Any]:
    cams = scan_cameras()
    return {
        "cameras": [
            {
                "name": c.name,
                "source": c.source,
                "vendor_id": c.vendor_id,
                "product_id": c.product_id,
                "is_sony": c.is_sony,
                "is_rx100": c.is_rx100,
                "is_capture_card": c.is_capture_card,
            }
            for c in cams
        ]
    }


@app.post("/sony/connect")
def sony_connect_route(obs_source: str | None = None) -> dict[str, Any]:
    cfg = _config()
    client = _client(cfg)
    try:
        result = connect_rx100_to_obs(client, cfg, preferred_name=obs_source)
    finally:
        client.close()
    payload = {
        "ok": result.ok,
        "message": result.message,
        "matched_obs_source": result.matched_obs_source,
        "obs_source_kind": result.obs_source_kind,
        "detected": (
            {
                "name": result.detected.name,
                "vendor_id": result.detected.vendor_id,
                "product_id": result.detected.product_id,
                "is_rx100": result.detected.is_rx100,
                "is_sony": result.detected.is_sony,
            }
            if result.detected
            else None
        ),
    }
    if not result.ok:
        raise HTTPException(status_code=409, detail=payload)
    return payload
