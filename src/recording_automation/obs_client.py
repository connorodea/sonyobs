"""Thin wrapper around obsws-python that adds friendly error handling.

All OBS WebSocket calls in the app go through this class so that connection
errors, auth errors, and missing scenes/sources surface with actionable
messages.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

try:
    import obsws_python as obsws
except ImportError as exc:  # pragma: no cover - import guard
    raise RuntimeError(
        "obsws-python is not installed. Run `uv sync` (or `pip install obsws-python`)."
    ) from exc

# obsws-python logs tracebacks for connection errors via logger.exception before
# raising. We surface our own friendly messages instead, so silence its logger.
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

from .config import OBSConfig


class OBSError(RuntimeError):
    """Base error for anything raised by `OBSClient`."""


class OBSConnectionError(OBSError):
    """Raised when OBS is unreachable (closed, wrong port, websocket disabled)."""


class OBSAuthError(OBSError):
    """Raised when the OBS WebSocket password is wrong or missing."""


class OBSNotFoundError(OBSError):
    """Raised when a requested scene or source does not exist."""


@dataclass(frozen=True)
class RecordStatus:
    active: bool
    paused: bool
    timecode: str
    bytes: int
    output_path: str | None = None


class OBSClient:
    """Wrapper around `obsws_python.ReqClient`.

    Use as a context manager:

        with OBSClient(cfg.obs) as client:
            client.start_recording()
    """

    def __init__(self, cfg: OBSConfig) -> None:
        self._cfg = cfg
        self._client: obsws.ReqClient | None = None

    # ---- connection lifecycle -------------------------------------------------

    def connect(self) -> None:
        if self._client is not None:
            return
        try:
            self._client = obsws.ReqClient(
                host=self._cfg.host,
                port=self._cfg.port,
                password=self._cfg.password,
                timeout=5,
            )
        except (ConnectionRefusedError, OSError) as exc:
            raise OBSConnectionError(
                f"Could not reach OBS WebSocket at {self._cfg.host}:{self._cfg.port}.\n"
                "Fix:\n"
                "  1. Open OBS Studio.\n"
                "  2. Tools > WebSocket Server Settings.\n"
                "  3. Enable WebSocket server.\n"
                f"  4. Confirm port is {self._cfg.port}."
            ) from exc
        except Exception as exc:  # obsws raises its own auth/handshake errors
            message = str(exc).lower()
            if "auth" in message or "password" in message or "denied" in message:
                raise OBSAuthError(
                    "OBS WebSocket rejected the password.\n"
                    "Fix:\n"
                    "  1. Open Tools > WebSocket Server Settings in OBS.\n"
                    "  2. Copy the password.\n"
                    f"  3. Put it in your .env as {self._cfg.password_env}=<password>."
                ) from exc
            raise OBSConnectionError(
                f"Failed to connect to OBS at {self._cfg.host}:{self._cfg.port}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def __enter__(self) -> "OBSClient":
        self.connect()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ---- low level ------------------------------------------------------------

    @property
    def raw(self) -> obsws.ReqClient:
        if self._client is None:
            raise OBSError("OBS client is not connected. Call .connect() first.")
        return self._client

    def get_version(self) -> dict[str, Any]:
        resp = self.raw.get_version()
        return {
            "obs_version": getattr(resp, "obs_version", None),
            "obs_web_socket_version": getattr(resp, "obs_web_socket_version", None),
            "platform": getattr(resp, "platform", None),
            "platform_description": getattr(resp, "platform_description", None),
            "rpc_version": getattr(resp, "rpc_version", None),
        }

    # ---- scenes ---------------------------------------------------------------

    def list_scenes(self) -> list[str]:
        resp = self.raw.get_scene_list()
        scenes = getattr(resp, "scenes", []) or []
        # OBS returns newest-first; reverse to match the OBS UI order
        names: list[str] = []
        for s in reversed(scenes):
            name = s.get("sceneName") if isinstance(s, dict) else getattr(s, "sceneName", None)
            if name:
                names.append(name)
        return names

    def current_scene(self) -> str | None:
        resp = self.raw.get_scene_list()
        return getattr(resp, "current_program_scene_name", None)

    def create_scene(self, name: str) -> None:
        self.raw.create_scene(name)

    def ensure_scene(self, name: str) -> bool:
        """Create a scene if it does not exist. Returns True if it was created."""
        existing = self.list_scenes()
        if name in existing:
            return False
        self.create_scene(name)
        return True

    def set_current_scene(self, name: str) -> None:
        if name not in self.list_scenes():
            raise OBSNotFoundError(
                f"Scene '{name}' does not exist in OBS. "
                f"Run `recording-auto scenes bootstrap` first."
            )
        self.raw.set_current_program_scene(name)

    # ---- inputs / sources -----------------------------------------------------

    def list_inputs(self) -> list[dict[str, Any]]:
        resp = self.raw.get_input_list()
        items = getattr(resp, "inputs", []) or []
        result: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                result.append(
                    {
                        "name": item.get("inputName"),
                        "kind": item.get("inputKind"),
                        "unversioned_kind": item.get("unversionedInputKind"),
                    }
                )
            else:
                result.append(
                    {
                        "name": getattr(item, "inputName", None),
                        "kind": getattr(item, "inputKind", None),
                        "unversioned_kind": getattr(item, "unversionedInputKind", None),
                    }
                )
        return [r for r in result if r["name"]]

    def input_exists(self, name: str) -> bool:
        return any(item["name"] == name for item in self.list_inputs())

    # ---- recording ------------------------------------------------------------

    def get_record_status(self) -> RecordStatus:
        resp = self.raw.get_record_status()
        return RecordStatus(
            active=bool(getattr(resp, "output_active", False)),
            paused=bool(getattr(resp, "output_paused", False)),
            timecode=str(getattr(resp, "output_timecode", "") or ""),
            bytes=int(getattr(resp, "output_bytes", 0) or 0),
        )

    def start_recording(self) -> RecordStatus:
        status = self.get_record_status()
        if status.active:
            return status
        self.raw.start_record()
        return self.get_record_status()

    def stop_recording(self) -> str | None:
        """Stop recording. Returns the saved file path if OBS reports one."""
        status = self.get_record_status()
        if not status.active:
            return None
        resp = self.raw.stop_record()
        return getattr(resp, "output_path", None)

    def pause_recording(self) -> None:
        status = self.get_record_status()
        if not status.active:
            raise OBSError("Cannot pause: OBS is not recording.")
        if status.paused:
            return
        self.raw.pause_record()

    def resume_recording(self) -> None:
        status = self.get_record_status()
        if not status.active:
            raise OBSError("Cannot resume: OBS is not recording.")
        if not status.paused:
            return
        self.raw.resume_record()


@contextmanager
def connect_obs(cfg: OBSConfig) -> Iterator[OBSClient]:
    """Convenience context manager: `with connect_obs(cfg.obs) as client: ...`"""
    client = OBSClient(cfg)
    client.connect()
    try:
        yield client
    finally:
        client.close()
