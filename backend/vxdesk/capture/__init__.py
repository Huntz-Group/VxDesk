"""Screen capture: DXcam (DXGI, GPU) primary, mss fallback, virtual file source for tests.

All frames are returned as BGR ``numpy.ndarray`` (OpenCV convention) and all
coordinates are absolute virtual-screen pixels.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("vxdesk.capture")

Region = dict  # {"x": int, "y": int, "w": int, "h": int}


def _crop(frame: np.ndarray, region: Optional[Region]) -> np.ndarray:
    if not region:
        return frame
    x, y = int(region.get("x", 0)), int(region.get("y", 0))
    w, h = int(region["w"]), int(region["h"])
    h_f, w_f = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_f, x + w), min(h_f, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"region {region} is outside the captured frame {w_f}x{h_f}")
    return frame[y0:y1, x0:x1]


class _FileBackend:
    """Virtual capture source: serves a static image instead of the real screen."""

    name = "file"

    def __init__(self, path: Path) -> None:
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)  # BGR
        if frame is None:
            raise ValueError(f"cannot read virtual capture source image: {path}")
        self._frame = frame
        logger.info("capture backend=file path=%s (%dx%d)", path, frame.shape[1], frame.shape[0])

    def grab(self, region: Optional[Region]) -> np.ndarray:
        return _crop(self._frame, region).copy()

    def screens(self) -> list[dict]:
        h, w = self._frame.shape[:2]
        return [{"index": 0, "x": 0, "y": 0, "width": w, "height": h}]

    @property
    def capabilities(self) -> dict:
        return {"backend": "file", "gpu": False, "fps_hint": 0, "virtual": True}


class _DxcamBackend:
    name = "dxcam"

    def __init__(self) -> None:
        import dxcam  # noqa: PLC0415

        self._camera = dxcam.create(output_color="BGR")
        if self._camera is None:
            raise RuntimeError("dxcam.create() returned None (no DXGI output?)")
        self._lock = threading.Lock()
        self._last: Optional[np.ndarray] = None
        logger.info("capture backend=dxcam device=%s", getattr(self._camera, "device_name", "?"))

    def grab(self, region: Optional[Region]) -> np.ndarray:
        dx_region = None
        if region:
            x, y = int(region.get("x", 0)), int(region.get("y", 0))
            dx_region = (x, y, x + int(region["w"]), y + int(region["h"]))
        frame: Optional[np.ndarray] = None
        with self._lock:
            for _ in range(5):
                frame = self._camera.grab(region=dx_region)
                if frame is not None:
                    break
                time.sleep(0.005)
            if frame is None and dx_region is None and self._last is not None:
                frame = self._last
        if frame is None:
            raise RuntimeError("dxcam returned no frame")
        self._last = frame
        return frame

    def screens(self) -> list[dict]:
        return _mss_screens()

    @property
    def capabilities(self) -> dict:
        return {"backend": "dxcam", "gpu": True, "fps_hint": 120, "virtual": False}


class _MssBackend:
    name = "mss"

    def __init__(self) -> None:
        import mss  # noqa: PLC0415

        self._sct = mss.mss()
        self._lock = threading.Lock()
        logger.info("capture backend=mss")

    def grab(self, region: Optional[Region]) -> np.ndarray:
        with self._lock:
            if region:
                mon = {
                    "left": int(region.get("x", 0)),
                    "top": int(region.get("y", 0)),
                    "width": int(region["w"]),
                    "height": int(region["h"]),
                }
            else:
                mon = self._sct.monitors[0]  # whole virtual screen
            shot = self._sct.grab(mon)
        frame = np.asarray(shot)[:, :, :3]  # BGRA -> BGR (mss channels are B,G,R,A)
        return frame

    def screens(self) -> list[dict]:
        return _mss_screens()

    @property
    def capabilities(self) -> dict:
        return {"backend": "mss", "gpu": False, "fps_hint": 30, "virtual": False}


def _mss_screens() -> list[dict]:
    try:
        import mss  # noqa: PLC0415

        with mss.mss() as sct:
            out = []
            for i, mon in enumerate(sct.monitors[1:]):  # skip the "all monitors" entry
                out.append(
                    {
                        "index": i,
                        "x": mon["left"],
                        "y": mon["top"],
                        "width": mon["width"],
                        "height": mon["height"],
                    }
                )
            return out
    except Exception as exc:  # pragma: no cover - extremely unusual
        logger.warning("screen enumeration failed: %s", exc)
        return []


class Capture:
    """Facade over the active capture backend with capability probing.

    The backend is chosen at construction time:

    1. ``source`` argument or ``VXDESK_CAPTURE_SOURCE`` env var (``file:<path>``)
       -> virtual file source (tests / headless).
    2. DXcam (DXGI Desktop Duplication, GPU-side).
    3. mss (CPU) fallback.
    """

    def __init__(self, source: Optional[str] = None) -> None:
        self._backend = self._probe(source)
        self.capabilities: dict = self._backend.capabilities

    @staticmethod
    def _probe(source: Optional[str]):
        source = source or os.environ.get("VXDESK_CAPTURE_SOURCE", "").strip()
        if source:
            if source.startswith("file:"):
                return _FileBackend(Path(source[len("file:"):]))
            logger.warning("unknown VXDESK_CAPTURE_SOURCE %r — falling back to real screen", source)
        try:
            return _DxcamBackend()
        except Exception as exc:
            logger.warning("dxcam unavailable (%s); falling back to mss", exc)
        try:
            return _MssBackend()
        except Exception as exc:  # pragma: no cover - no display at all
            logger.error("mss unavailable (%s); capture disabled", exc)
            return _NullBackend(str(exc))

    def grab(self, region: Optional[Region] = None) -> np.ndarray:
        """Grab the screen (or a region of it) as a BGR ndarray."""
        return self._backend.grab(region)

    def screens(self) -> list[dict]:
        return self._backend.screens()

    @property
    def backend_name(self) -> str:
        return str(self.capabilities.get("backend", "none"))


class _NullBackend:
    name = "none"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def grab(self, region: Optional[Region]) -> np.ndarray:
        raise RuntimeError(f"no capture backend available: {self._reason}")

    def screens(self) -> list[dict]:
        return []

    @property
    def capabilities(self) -> dict:
        return {"backend": "none", "gpu": False, "fps_hint": 0, "virtual": False}
