"""Shared pytest fixtures: a synthetic virtual screen + template, headless-safe.

All engine/server tests run against ``VXDESK_CAPTURE_SOURCE=file:<png>`` so no
real display interaction is required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from vxdesk import workflows_store  # noqa: E402
from vxdesk.paths import ROOT, TEMPLATES_DIR, ensure_dirs  # noqa: E402

# geometry of the synthetic screen, shared with the vision tests
MARKER_POS = (120, 80)  # x, y of the red marker rectangle
MARKER_SIZE = (64, 48)  # w, h
SCREEN_SIZE = (800, 600)


def _build_screen() -> np.ndarray:
    """800x600 screen with a distinctive marker + rendered text."""
    img = Image.new("RGB", SCREEN_SIZE, (245, 245, 240))
    draw = ImageDraw.Draw(img)
    x, y = MARKER_POS
    w, h = MARKER_SIZE
    # distinctive marker: red body, white cross, blue corner square
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(200, 30, 30))
    draw.line([x, y, x + w - 1, y + h - 1], fill=(255, 255, 255), width=4)
    draw.line([x + w - 1, y, x, y + h - 1], fill=(255, 255, 255), width=4)
    draw.rectangle([x + 4, y + 4, x + 16, y + 16], fill=(30, 30, 200))
    # text for OCR tests
    draw.text((300, 300), "Hello VxDesk", fill=(0, 0, 0))
    draw.text((80, 420), "Submit", fill=(10, 10, 10))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


@pytest.fixture(scope="session")
def screen_bgr() -> np.ndarray:
    return _build_screen()


@pytest.fixture(scope="session")
def template_bgr(screen_bgr) -> np.ndarray:
    x, y = MARKER_POS
    w, h = MARKER_SIZE
    return screen_bgr[y : y + h, x : x + w].copy()


@pytest.fixture(scope="session")
def virtual_screen_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("capture") / "screen.png"
    cv2.imwrite(str(path), _build_screen())
    return path


@pytest.fixture()
def virtual_capture(virtual_screen_path, monkeypatch):
    """Point the capture layer at the synthetic screen for this test."""
    monkeypatch.setenv("VXDESK_CAPTURE_SOURCE", f"file:{virtual_screen_path}")
    from vxdesk.capture import Capture

    return Capture()


@pytest.fixture()
def template_asset(template_bgr):
    """Write the marker template into assets/templates and clean up after."""
    ensure_dirs()
    path = TEMPLATES_DIR / "marker.png"
    cv2.imwrite(str(path), template_bgr)
    yield "marker.png"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture()
def workflow_factory():
    """Create a workflow on disk; delete all created workflows after the test."""
    created: list[str] = []

    def make(nodes, edges, variables=None, name="test-wf") -> dict:
        workflow = {
            "id": workflows_store.new_workflow_id(),
            "name": name,
            "description": "",
            "nodes": nodes,
            "edges": edges,
            "variables": variables or {},
        }
        workflows_store.save_workflow(workflow["id"], workflow)
        created.append(workflow["id"])
        return workflow

    yield make
    for workflow_id in created:
        try:
            workflows_store.delete_workflow(workflow_id)
        except FileNotFoundError:
            pass


def make_node(node_id: str, type: str, params: dict | None = None, name: str | None = None,
              disabled: bool = False) -> dict:
    return {
        "id": node_id,
        "type": type,
        "name": name or node_id,
        "position": {"x": 0, "y": 0},
        "params": params or {},
        "disabled": disabled,
    }


def make_edge(source: str, target: str, handle: str = "default") -> dict:
    return {
        "id": f"e_{source}_{target}_{handle}",
        "source": source,
        "target": target,
        "sourceHandle": handle,
    }
