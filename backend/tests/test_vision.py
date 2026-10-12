"""Template-matching tests against synthetic images."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vxdesk.vision import find_image
from vxdesk.vision import test_match as vision_test_match

from conftest import MARKER_POS, MARKER_SIZE


def test_find_image_exact(screen_bgr, template_bgr):
    result = find_image(screen_bgr, template_bgr, threshold=0.95)
    assert result["found"] is True
    assert abs(result["x"] - MARKER_POS[0]) <= 2
    assert abs(result["y"] - MARKER_POS[1]) <= 2
    assert result["w"] == MARKER_SIZE[0]
    assert result["h"] == MARKER_SIZE[1]
    assert result["score"] > 0.99
    assert abs(result["center"]["x"] - (MARKER_POS[0] + MARKER_SIZE[0] // 2)) <= 2


@pytest.mark.parametrize("scale", [0.5, 0.75, 1.0, 1.5, 2.0])
def test_find_image_multiscale(screen_bgr, template_bgr, scale):
    """A screen rendered at another scale must be matched via ``scales``."""
    scaled_screen = cv2.resize(screen_bgr, None, fx=scale, fy=scale)
    result = find_image(scaled_screen, template_bgr, threshold=0.95, scales=[scale])
    assert result["found"] is True, f"scale={scale} score={result['score']}"
    assert abs(result["x"] - MARKER_POS[0] * scale) <= 2
    assert abs(result["y"] - MARKER_POS[1] * scale) <= 2


def test_find_image_scales_param_searches_multiple(screen_bgr, template_bgr):
    result = find_image(screen_bgr, template_bgr, threshold=0.95,
                        scales=[0.5, 1.0, 1.5])
    assert result["found"] is True
    assert abs(result["x"] - MARKER_POS[0]) <= 2


def test_find_image_below_threshold_not_found(screen_bgr):
    # template that does not exist on the screen
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 255, size=(40, 40, 3), dtype=np.uint8)
    result = find_image(screen_bgr, noise, threshold=0.99)
    assert result["found"] is False
    assert result["score"] < 0.99


def test_find_image_region_offsets(screen_bgr, template_bgr):
    region = {"x": 100, "y": 60, "w": 300, "h": 200}
    result = find_image(screen_bgr, template_bgr, threshold=0.95, region=region)
    assert result["found"] is True
    # coordinates must be absolute (region offset applied)
    assert abs(result["x"] - MARKER_POS[0]) <= 2
    assert abs(result["y"] - MARKER_POS[1]) <= 2


def test_find_image_region_excluding_marker(screen_bgr, template_bgr):
    region = {"x": 400, "y": 0, "w": 300, "h": 300}
    result = find_image(screen_bgr, template_bgr, threshold=0.95, region=region)
    assert result["found"] is False


def test_test_match_reports_elapsed(screen_bgr, template_bgr):
    result = vision_test_match(screen_bgr, template_bgr, threshold=0.9)
    assert result["found"] is True
    assert result["elapsed_ms"] >= 0


def test_virtual_capture_backend(virtual_capture):
    frame = virtual_capture.grab()
    assert frame.shape[:2] == (600, 800)
    assert frame.shape[2] == 3
    assert virtual_capture.capabilities["backend"] == "file"
    screens = virtual_capture.screens()
    assert screens == [{"index": 0, "x": 0, "y": 0, "width": 800, "height": 600}]
    region = virtual_capture.grab({"x": 10, "y": 20, "w": 100, "h": 50})
    assert region.shape[:2] == (50, 100)
