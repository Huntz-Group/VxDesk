"""OCR tests — skipped entirely when the OCR engine/models are unavailable."""

from __future__ import annotations

import pytest

from vxdesk.vision import OCREngine, find_text, ocr


@pytest.fixture(scope="module")
def engine() -> OCREngine:
    eng = OCREngine()
    if not eng.available:
        pytest.skip(f"OCR engine unavailable (models not downloaded?): {eng.info()}")
    return eng


def test_find_text_locates_rendered_text(engine, screen_bgr):
    result = find_text(screen_bgr, "Hello", engine=engine)
    assert result["found"] is True
    assert result["first"] is not None
    # "Hello VxDesk" was rendered at (300, 300)
    assert abs(result["first"]["x"] - 300) < 40
    assert abs(result["first"]["y"] - 300) < 40


def test_find_text_missing_text(engine, screen_bgr):
    result = find_text(screen_bgr, "zzz-not-on-screen-zzz", engine=engine)
    assert result["found"] is False
    assert result["boxes"] == []
    assert result["first"] is None


def test_ocr_boxes_shape_and_elapsed(engine, screen_bgr):
    result = ocr(screen_bgr, engine=engine)
    assert result["elapsed_ms"] >= 0
    assert isinstance(result["boxes"], list)
    if result["boxes"]:
        box = result["boxes"][0]
        assert {"text", "confidence", "x", "y", "w", "h"} <= set(box)


def test_ocr_text_filter(engine, screen_bgr):
    all_boxes = ocr(screen_bgr, engine=engine)["boxes"]
    filtered = ocr(screen_bgr, text="Submit", engine=engine)["boxes"]
    assert len(filtered) <= len(all_boxes)
    for box in filtered:
        assert "submit" in box["text"].lower()
