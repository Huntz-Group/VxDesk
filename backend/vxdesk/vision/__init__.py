"""Vision: OpenCV template matching and RapidOCR text finding (DirectML when available)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("vxdesk.vision")

Region = dict  # {"x": int, "y": int, "w": int, "h": int}


def _crop_with_offset(
    screen_bgr: np.ndarray, region: Optional[Region]
) -> tuple[np.ndarray, int, int]:
    """Crop ``screen_bgr`` to ``region``; returns (crop, offset_x, offset_y)."""
    if not region:
        return screen_bgr, 0, 0
    x, y = int(region.get("x", 0)), int(region.get("y", 0))
    w, h = int(region["w"]), int(region["h"])
    return screen_bgr[y : y + h, x : x + w], x, y


def find_image(
    screen_bgr: np.ndarray,
    template_bgr: np.ndarray,
    threshold: float = 0.8,
    region: Optional[Region] = None,
    scales: Optional[list[float]] = None,
) -> dict:
    """Locate ``template_bgr`` inside ``screen_bgr`` using normalized correlation.

    Returns a dict with ``found`` plus absolute virtual-screen coordinates of the
    best match (region offsets applied). ``scales`` enables multi-scale matching
    (each entry scales the template).
    """
    haystack, off_x, off_y = _crop_with_offset(screen_bgr, region)
    if haystack.size == 0 or template_bgr.size == 0:
        return _no_match()

    scale_list = list(scales) if scales else [1.0]
    best = {"score": -1.0, "x": 0, "y": 0, "w": 0, "h": 0}
    for scale in scale_list:
        if scale <= 0:
            continue
        if scale == 1.0:
            tpl = template_bgr
        else:
            new_w = max(1, int(round(template_bgr.shape[1] * scale)))
            new_h = max(1, int(round(template_bgr.shape[0] * scale)))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            tpl = cv2.resize(template_bgr, (new_w, new_h), interpolation=interp)
        th, tw = tpl.shape[:2]
        if th > haystack.shape[0] or tw > haystack.shape[1]:
            continue
        result = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best["score"]:
            best = {"score": float(max_val), "x": max_loc[0], "y": max_loc[1], "w": tw, "h": th}

    if best["score"] < 0:  # template never fit inside the haystack
        return _no_match()

    found = best["score"] >= threshold
    x, y = best["x"] + off_x, best["y"] + off_y
    return {
        "found": bool(found),
        "x": int(x),
        "y": int(y),
        "w": int(best["w"]),
        "h": int(best["h"]),
        "score": round(best["score"], 5),
        "center": {"x": int(x + best["w"] / 2), "y": int(y + best["h"] / 2)},
    }


def _no_match() -> dict:
    return {
        "found": False,
        "x": 0,
        "y": 0,
        "w": 0,
        "h": 0,
        "score": 0.0,
        "center": {"x": 0, "y": 0},
    }


def test_match(
    screen_bgr: np.ndarray,
    template_bgr: np.ndarray,
    threshold: float = 0.8,
    region: Optional[Region] = None,
    scales: Optional[list[float]] = None,
) -> dict:
    """``find_image`` plus elapsed-time instrumentation (editor debugging)."""
    start = time.perf_counter()
    out = find_image(screen_bgr, template_bgr, threshold, region, scales)
    out["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return out


class OCREngine:
    """Lazy singleton wrapper around RapidOCR with DirectML probing.

    Never raises on construction problems: ``available`` flips to ``False`` and
    every call degrades gracefully (models auto-download on first use, so a
    blocked network simply disables OCR).
    """

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        self._available: Optional[bool] = None
        self._provider = "CPUExecutionProvider"
        self._init_error: Optional[str] = None

    def _probe_provider(self) -> str:
        try:
            import onnxruntime  # noqa: PLC0415

            providers = onnxruntime.get_available_providers()
            if "DmlExecutionProvider" in providers:
                return "DmlExecutionProvider"
        except Exception as exc:
            logger.warning("onnxruntime probe failed: %s", exc)
        return "CPUExecutionProvider"

    def _ensure(self) -> bool:
        if self._available is not None:
            return self._available
        with self._lock:
            if self._available is not None:
                return self._available
            try:
                from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415

                self._provider = self._probe_provider()
                use_dml = self._provider == "DmlExecutionProvider"
                kwargs = {}
                if use_dml:
                    kwargs = {"det_use_dml": True, "cls_use_dml": True, "rec_use_dml": True}
                self._engine = RapidOCR(**kwargs)
                self._available = True
                logger.info("OCR ready provider=%s", self._provider)
            except Exception as exc:
                self._init_error = str(exc)
                self._available = False
                logger.warning("OCR unavailable: %s", exc)
        return bool(self._available)

    @property
    def available(self) -> bool:
        return self._ensure()

    @property
    def provider(self) -> str:
        self._ensure()
        return self._provider

    def recognize(self, image_bgr: np.ndarray) -> list[dict]:
        """Run OCR on a BGR image; returns boxes [{text, confidence, x, y, w, h}]."""
        if not self._ensure():
            return []
        assert self._engine is not None
        result, _ = self._engine(image_bgr)
        boxes: list[dict] = []
        for item in result or []:
            points, text, confidence = item[0], str(item[1]), float(item[2])
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            boxes.append(
                {
                    "text": text,
                    "confidence": round(confidence, 4),
                    "x": int(x0),
                    "y": int(y0),
                    "w": int(x1 - x0),
                    "h": int(y1 - y0),
                }
            )
        return boxes

    def info(self) -> dict:
        return {
            "available": bool(self._ensure()),
            "backend": "rapidocr-onnxruntime",
            "gpu": self.provider == "DmlExecutionProvider",
            "provider": self.provider,
            **({"error": self._init_error} if self._init_error else {}),
        }


_DEFAULT_ENGINE: Optional[OCREngine] = None
_DEFAULT_ENGINE_LOCK = threading.Lock()


def get_ocr_engine() -> OCREngine:
    """Process-wide shared OCR engine (model load happens at most once)."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        with _DEFAULT_ENGINE_LOCK:
            if _DEFAULT_ENGINE is None:
                _DEFAULT_ENGINE = OCREngine()
    return _DEFAULT_ENGINE


def ocr(
    screen_bgr: np.ndarray,
    region: Optional[Region] = None,
    text: Optional[str] = None,
    case_sensitive: bool = False,
    engine: Optional[OCREngine] = None,
) -> dict:
    """OCR helper with elapsed timing; optionally filter boxes by ``text``."""
    engine = engine or get_ocr_engine()
    start = time.perf_counter()
    crop, off_x, off_y = _crop_with_offset(screen_bgr, region)
    boxes = engine.recognize(crop) if crop.size else []
    for b in boxes:  # back to absolute coordinates
        b["x"] += off_x
        b["y"] += off_y
    if text:
        needle = text if case_sensitive else text.lower()
        boxes = [
            b for b in boxes if (needle in (b["text"] if case_sensitive else b["text"].lower()))
        ]
    return {"boxes": boxes, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)}


def find_text(
    screen_bgr: np.ndarray,
    text: str,
    case_sensitive: bool = False,
    region: Optional[Region] = None,
    engine: Optional[OCREngine] = None,
) -> dict:
    """Find ``text`` on screen via OCR. Returns found flag, matching boxes, first hit."""
    result = ocr(
        screen_bgr,
        region=region,
        text=text,
        case_sensitive=case_sensitive,
        engine=engine or get_ocr_engine(),
    )
    boxes = result["boxes"]
    out: dict = {"found": bool(boxes), "boxes": boxes, "first": None}
    if boxes:
        b = boxes[0]
        out["first"] = {
            "x": b["x"],
            "y": b["y"],
            "w": b["w"],
            "h": b["h"],
            "center": {"x": b["x"] + b["w"] // 2, "y": b["y"] + b["h"] // 2},
        }
    return out
