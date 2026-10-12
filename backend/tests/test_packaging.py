"""Packaging-related tests: frozen data dirs, SPA fallback, desktop entry."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from vxdesk import paths


def test_frozen_data_paths(tmp_path, monkeypatch):
    """When sys.frozen, user data must live under %LOCALAPPDATA%/VxDesk."""
    with monkeypatch.context() as m:
        m.setattr(sys, "frozen", True, raising=False)
        m.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
        m.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
        importlib.reload(paths)
        try:
            assert paths.is_frozen()
            assert paths.ROOT == tmp_path / "lad" / "VxDesk"
            assert paths.WORKFLOWS_DIR == paths.ROOT / "workflows"
            assert paths.RUNS_DIR == paths.ROOT / "workflows" / ".runs"
            assert paths.TEMPLATES_DIR == paths.ROOT / "assets" / "templates"
            assert paths.SCREENSHOTS_DIR == paths.ROOT / "runs"
            assert paths.SETTINGS_FILE_PATH == paths.ROOT / "ai-settings.json"
            assert paths.bundle_dir() == tmp_path / "bundle"
        finally:
            pass
    importlib.reload(paths)  # restore dev paths for the rest of the suite
    assert not paths.is_frozen()


def test_dev_data_paths_unchanged():
    repo = Path(__file__).resolve().parents[2]
    assert paths.ROOT == repo
    assert paths.WORKFLOWS_DIR == repo / "workflows"


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html").is_file(),
    reason="frontend build not present",
)
def test_spa_serving_and_fallback(virtual_capture):
    from fastapi.testclient import TestClient

    from vxdesk.server import create_app

    app = create_app(capture=virtual_capture)
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "text/html" in root.headers["content-type"]
        # client-side route falls back to index.html
        deep = client.get("/workflow/wf_doesnotmatter")
        assert deep.status_code == 200
        assert deep.text == root.text
        # API is unaffected
        assert client.get("/api/system/info").status_code == 200


def test_desktop_pick_port():
    from vxdesk.desktop import pick_port

    port = pick_port()
    assert port == 8765 or port > 1024
