"""Detect and connect a Sony RX100 (and other Sony cameras) on macOS.

This module is intentionally OS-specific and uses macOS-native tools (no
proprietary SDKs in v1):

  * `system_profiler SPCameraDataType -json`  → UVC / FaceTime / capture devices
  * `system_profiler SPUSBDataType -json`     → USB-connected Sony bodies
  * AVFoundation (if PyObjC is available)     → optional camera enumeration

A "Sony RX100" can appear on the Mac in three ways:

  1. Capture card path: HDMI out → Elgato/AVerMedia/Magewell capture device.
     The Mac sees the capture card as the camera, not the Sony body.
  2. USB webcam path: cameras with USB Streaming output (RX100 VI/VII when
     in `MENU > Network > USB Streaming`) appear as a UVC device named
     "ILCE-…" or "DSC-RX100…".
  3. Imaging Edge Webcam: Sony's helper app re-exposes the camera as
     "Sony Camera (Imaging Edge)". We detect that string too.

Public API:
    scan_cameras()           -> list[DetectedCamera]
    find_sony_rx100()        -> DetectedCamera | None
    connect_rx100_to_obs(...) -> ConnectResult
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Iterable

from .config import AppConfig
from .obs_client import OBSClient


SONY_VENDOR_IDS = {"0x054c"}  # Sony Corporation
RX100_PATTERNS = [
    re.compile(r"\bDSC[-_ ]?RX100\b", re.IGNORECASE),
    re.compile(r"\bRX100\b", re.IGNORECASE),
    re.compile(r"\bILCE-\d+\b", re.IGNORECASE),  # Alpha bodies w/ similar pipeline
]
SONY_HINT_PATTERNS = [
    re.compile(r"\bSony\b", re.IGNORECASE),
    re.compile(r"\bImaging Edge\b", re.IGNORECASE),
]
KNOWN_CAPTURE_CARD_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (r"Elgato", r"Cam Link", r"AVerMedia", r"Magewell", r"HDMI", r"Capture")
]


@dataclass(frozen=True)
class DetectedCamera:
    name: str
    source: str  # "AVFoundation" | "system_profiler:camera" | "system_profiler:usb"
    vendor_id: str | None = None
    product_id: str | None = None
    is_sony: bool = False
    is_rx100: bool = False
    is_capture_card: bool = False
    raw: dict | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ConnectResult:
    matched_obs_source: str | None
    obs_source_kind: str | None
    detected: DetectedCamera | None
    message: str
    ok: bool


# ---------------------------------------------------------------------------
# scanners
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: float = 8.0) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _scan_system_profiler_cameras() -> list[DetectedCamera]:
    out = _run(["system_profiler", "SPCameraDataType", "-json"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    entries = data.get("SPCameraDataType", []) or []
    cameras: list[DetectedCamera] = []
    for entry in entries:
        name = entry.get("_name") or entry.get("spcamera_model-id") or ""
        if not name:
            continue
        is_sony = any(p.search(name) for p in SONY_HINT_PATTERNS)
        is_rx100 = any(p.search(name) for p in RX100_PATTERNS)
        is_capture = any(p.search(name) for p in KNOWN_CAPTURE_CARD_PATTERNS)
        cameras.append(
            DetectedCamera(
                name=name,
                source="system_profiler:camera",
                is_sony=is_sony,
                is_rx100=is_rx100,
                is_capture_card=is_capture,
                raw=entry,
            )
        )
    return cameras


def _walk_usb(items: Iterable[dict]) -> Iterable[dict]:
    for item in items:
        yield item
        children = item.get("_items") or []
        if children:
            yield from _walk_usb(children)


def _scan_system_profiler_usb() -> list[DetectedCamera]:
    out = _run(["system_profiler", "SPUSBDataType", "-json"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    cameras: list[DetectedCamera] = []
    for item in _walk_usb(data.get("SPUSBDataType", []) or []):
        vendor = (item.get("vendor_id") or "").lower()
        name = item.get("_name") or ""
        manufacturer = item.get("manufacturer") or ""
        if not name:
            continue
        looks_sony = vendor in SONY_VENDOR_IDS or any(
            p.search(name) for p in SONY_HINT_PATTERNS
        ) or any(p.search(manufacturer) for p in SONY_HINT_PATTERNS)
        if not looks_sony:
            continue
        is_rx100 = any(p.search(name) for p in RX100_PATTERNS)
        cameras.append(
            DetectedCamera(
                name=name,
                source="system_profiler:usb",
                vendor_id=item.get("vendor_id"),
                product_id=item.get("product_id"),
                is_sony=True,
                is_rx100=is_rx100,
                is_capture_card=False,
                raw=item,
            )
        )
    return cameras


def _scan_avfoundation() -> list[DetectedCamera]:
    """Optional: enumerate via AVFoundation if PyObjC is installed."""
    try:
        import AVFoundation  # type: ignore[import-not-found]
    except ImportError:
        return []

    cameras: list[DetectedCamera] = []
    try:
        media = AVFoundation.AVMediaTypeVideo
        devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(media) or []
        for device in devices:
            name = str(device.localizedName())
            is_sony = any(p.search(name) for p in SONY_HINT_PATTERNS)
            is_rx100 = any(p.search(name) for p in RX100_PATTERNS)
            is_capture = any(p.search(name) for p in KNOWN_CAPTURE_CARD_PATTERNS)
            cameras.append(
                DetectedCamera(
                    name=name,
                    source="AVFoundation",
                    is_sony=is_sony,
                    is_rx100=is_rx100,
                    is_capture_card=is_capture,
                )
            )
    except Exception:
        return []
    return cameras


def scan_cameras() -> list[DetectedCamera]:
    """Return every camera-like device we can see on this Mac (deduped by name)."""
    found: dict[str, DetectedCamera] = {}
    for scanner in (_scan_avfoundation, _scan_system_profiler_cameras, _scan_system_profiler_usb):
        for cam in scanner():
            existing = found.get(cam.name)
            if existing is None:
                found[cam.name] = cam
                continue
            # Merge "is_sony"/"is_rx100"/"is_capture_card" flags
            found[cam.name] = DetectedCamera(
                name=cam.name,
                source=existing.source + "+" + cam.source,
                vendor_id=existing.vendor_id or cam.vendor_id,
                product_id=existing.product_id or cam.product_id,
                is_sony=existing.is_sony or cam.is_sony,
                is_rx100=existing.is_rx100 or cam.is_rx100,
                is_capture_card=existing.is_capture_card or cam.is_capture_card,
                raw=existing.raw or cam.raw,
            )
    return list(found.values())


def find_sony_rx100() -> DetectedCamera | None:
    """Pick the best Sony RX100 (or Sony) candidate from a scan."""
    cams = scan_cameras()
    rx100s = [c for c in cams if c.is_rx100]
    if rx100s:
        return rx100s[0]
    sony = [c for c in cams if c.is_sony and not c.is_capture_card]
    if sony:
        return sony[0]
    # Capture cards are RX100-via-HDMI in practice — surface them as a fallback hint.
    cards = [c for c in cams if c.is_capture_card]
    if cards:
        return cards[0]
    return None


# ---------------------------------------------------------------------------
# OBS integration
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _find_matching_obs_input(client: OBSClient, candidate_name: str) -> dict | None:
    target = _normalize(candidate_name)
    inputs = client.list_inputs()
    # Exact (case-insensitive) match wins
    for item in inputs:
        if (item["name"] or "").lower() == candidate_name.lower():
            return item
    # Normalized substring match
    for item in inputs:
        if target and target in _normalize(item["name"] or ""):
            return item
    return None


def connect_rx100_to_obs(
    client: OBSClient,
    cfg: AppConfig,
    *,
    preferred_name: str | None = None,
) -> ConnectResult:
    """Locate the RX100 on this Mac, then try to match it to an OBS input.

    The match-by-name strategy:
      1. If `preferred_name` is given, look for that input exactly.
      2. Otherwise, scan the system for a Sony/RX100 device and search OBS
         inputs for one whose name matches that device.
      3. Fall back to `cfg.sources.sony_camera`.
    """
    detected = find_sony_rx100()

    candidates: list[str] = []
    if preferred_name:
        candidates.append(preferred_name)
    if detected:
        candidates.append(detected.name)
    candidates.append(cfg.sources.sony_camera)

    matched: dict | None = None
    for name in candidates:
        if not name:
            continue
        matched = _find_matching_obs_input(client, name)
        if matched:
            break

    if matched is None:
        if detected is None:
            return ConnectResult(
                matched_obs_source=None,
                obs_source_kind=None,
                detected=None,
                ok=False,
                message=(
                    "No Sony / RX100 camera was detected on this Mac and no matching "
                    "OBS input was found.\n"
                    "Fix one of:\n"
                    "  * RX100 VI/VII: MENU > Network > USB Streaming > On, then plug USB-C in.\n"
                    "  * Or run Sony 'Imaging Edge Webcam' so the camera shows up as a UVC source.\n"
                    "  * Or HDMI out into a capture card (Elgato Cam Link / Magewell)."
                ),
            )
        return ConnectResult(
            matched_obs_source=None,
            obs_source_kind=None,
            detected=detected,
            ok=False,
            message=(
                f"Detected camera '{detected.name}' on this Mac, but OBS has no input "
                "with a matching name. Add it in OBS: + > Video Capture Device > "
                f"choose '{detected.name}' and name the source '{cfg.sources.sony_camera}' "
                "(or update sources.sony_camera in config.yaml)."
            ),
        )

    return ConnectResult(
        matched_obs_source=matched["name"],
        obs_source_kind=matched.get("kind"),
        detected=detected,
        ok=True,
        message=(
            f"Connected: OBS input '{matched['name']}' "
            f"(kind={matched.get('kind')}) "
            + (f"matches detected device '{detected.name}'." if detected else "found.")
        ),
    )
