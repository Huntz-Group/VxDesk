"""API tests via FastAPI TestClient against the virtual capture source."""

from __future__ import annotations

import io
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(virtual_capture, template_asset):
    from vxdesk.engine.executor import RunManager, WorkflowEngine
    from vxdesk.server import create_app

    run_manager = RunManager(WorkflowEngine(capture=virtual_capture))
    app = create_app(capture=virtual_capture, run_manager=run_manager)
    with TestClient(app) as c:
        yield c


def wait_run(client: TestClient, run_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise TimeoutError(f"run {run_id} still running")


# ---------------------------------------------------------------- system


def test_system_info(client):
    info = client.get("/api/system/info").json()
    assert info["version"] == "0.1.0"
    assert info["os"] == "windows"
    assert info["capture"]["backend"] == "file"
    assert info["ocr"]["backend"] == "rapidocr-onnxruntime"
    assert isinstance(info["ocr"]["available"], bool)
    assert info["screens"][0]["width"] == 800
    assert "gpu" in info and "directml" in info["gpu"]


# ---------------------------------------------------------------- workflow CRUD


def test_workflow_crud(client):
    created = client.post("/api/workflows", json={"name": "crud-test"}).json()
    wf_id = created["id"]
    try:
        assert created["nodes"][0]["type"] == "trigger.manual"

        listing = client.get("/api/workflows").json()
        assert any(w["id"] == wf_id and w["node_count"] == 1 for w in listing)

        created["description"] = "updated"
        created["nodes"].append(
            {"id": "n2", "type": "control.log", "name": "Log",
             "position": {"x": 100, "y": 0}, "params": {"message": "hi"},
             "disabled": False}
        )
        created["edges"].append(
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"}
        )
        saved = client.put(f"/api/workflows/{wf_id}", json=created).json()
        assert saved["description"] == "updated"

        loaded = client.get(f"/api/workflows/{wf_id}").json()
        assert len(loaded["nodes"]) == 2

        validation = client.post(f"/api/workflows/{wf_id}/validate").json()
        assert validation["valid"] is True
        assert validation["errors"] == []
    finally:
        assert client.delete(f"/api/workflows/{wf_id}").json() == {"ok": True}
    assert client.get(f"/api/workflows/{wf_id}").status_code == 404


def test_validate_rejects_unknown_type(client):
    created = client.post("/api/workflows", json={"name": "bad"}).json()
    wf_id = created["id"]
    try:
        created["nodes"].append(
            {"id": "n2", "type": "bogus.type", "name": "X",
             "position": {"x": 0, "y": 0}, "params": {}, "disabled": False}
        )
        client.put(f"/api/workflows/{wf_id}", json=created)
        validation = client.post(f"/api/workflows/{wf_id}/validate").json()
        assert validation["valid"] is False
        assert any("unknown type" in e for e in validation["errors"])
    finally:
        client.delete(f"/api/workflows/{wf_id}")


def test_run_endpoint_and_run_history(client):
    created = client.post("/api/workflows", json={"name": "run-test"}).json()
    wf_id = created["id"]
    try:
        created["nodes"].append(
            {"id": "n2", "type": "control.set_variable", "name": "Set",
             "position": {"x": 0, "y": 0}, "params": {"name": "x", "value": "42"},
             "disabled": False}
        )
        created["edges"].append(
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"}
        )
        client.put(f"/api/workflows/{wf_id}", json=created)

        run_id = client.post(f"/api/workflows/{wf_id}/run",
                             json={"dry_run": True}).json()["run_id"]
        run = wait_run(client, run_id)
        assert run["status"] == "success"
        assert run["node_states"]["n2"]["output"] == {"name": "x", "value": "42"}

        runs = client.get(f"/api/workflows/{wf_id}/runs").json()
        assert any(r["run_id"] == run_id for r in runs)

        # persisted run file is loadable
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "success"
    finally:
        client.delete(f"/api/workflows/{wf_id}")


def test_stop_unknown_run_404(client):
    assert client.post("/api/runs/run_nope/stop").status_code == 404


# ---------------------------------------------------------------- catalog


def test_node_catalog_complete(client):
    catalog = client.get("/api/nodes/catalog").json()["nodes"]
    types = {n["type"] for n in catalog}
    expected = {
        "trigger.manual", "input.data_table", "control.loop", "control.condition",
        "control.wait", "control.wait_for", "control.set_variable", "control.log",
        "capture.screenshot", "vision.find_image", "vision.find_text",
        "action.click", "action.move", "action.drag", "action.type_text",
        "action.press_key", "action.focus_window", "action.launch",
        "script.python", "output.save_screenshot",
    }
    assert types == expected
    by_type = {n["type"]: n for n in catalog}
    find_image = by_type["vision.find_image"]
    assert find_image["branch_handles"] == ["found", "not_found"]
    param_kinds = {p["name"]: p["kind"] for p in find_image["params"]}
    assert param_kinds["template"] == "template"
    assert param_kinds["threshold"] == "number"
    assert param_kinds["region"] == "region"
    loop = by_type["control.loop"]
    assert loop["branch_handles"] == ["body", "done"]
    mode = next(p for p in loop["params"] if p["name"] == "mode")
    assert mode["kind"] == "select" and len(mode["options"]) == 2
    for entry in catalog:
        assert "default" not in entry["branch_handles"]


# ---------------------------------------------------------------- capture / vision / windows


def test_screenshot_endpoint_png_and_jpeg(client):
    resp = client.post("/api/capture/screenshot", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (600, 800)

    resp = client.post("/api/capture/screenshot",
                       json={"region": {"x": 0, "y": 0, "w": 100, "h": 50},
                             "format": "jpeg"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (50, 100)


def test_windows_endpoint(client):
    resp = client.get("/api/windows")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_test_match_endpoint(client, template_asset):
    resp = client.post("/api/vision/test-match",
                       json={"template": template_asset, "threshold": 0.9})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert abs(body["x"] - 120) <= 2 and abs(body["y"] - 80) <= 2
    assert body["elapsed_ms"] >= 0


def test_test_match_unknown_template_404(client):
    resp = client.post("/api/vision/test-match", json={"template": "nope.png"})
    assert resp.status_code == 404


def test_test_ocr_endpoint(client):
    resp = client.post("/api/vision/test-ocr", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["boxes"], list)
    assert body["elapsed_ms"] >= 0


# ---------------------------------------------------------------- template assets


def test_template_upload_list_get_delete(client):
    buf = io.BytesIO()
    img = np.zeros((20, 30, 3), dtype=np.uint8)
    img[:] = (0, 255, 0)
    ok, png = cv2.imencode(".png", img)
    assert ok
    resp = client.post(
        "/api/assets/templates",
        files={"file": ("green.png", png.tobytes(), "image/png")},
        data={"name": "green.png"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"name": "green.png", "width": 30, "height": 20}

    listing = client.get("/api/assets/templates").json()
    assert any(t["name"] == "green.png" and t["width"] == 30 for t in listing)

    fetched = client.get("/api/assets/templates/green.png")
    assert fetched.status_code == 200
    assert fetched.content == png.tobytes()

    assert client.delete("/api/assets/templates/green.png").json() == {"ok": True}
    assert client.get("/api/assets/templates/green.png").status_code == 404


def test_template_upload_rejects_non_image(client):
    resp = client.post(
        "/api/assets/templates",
        files={"file": ("x.png", b"not an image", "image/png")},
        data={"name": "x.png"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------- websocket


def test_ws_snapshot_and_events(client):
    created = client.post("/api/workflows", json={"name": "ws-test"}).json()
    wf_id = created["id"]
    try:
        created["nodes"].append(
            {"id": "n2", "type": "control.log", "name": "Log",
             "position": {"x": 0, "y": 0}, "params": {"message": "ws hello"},
             "disabled": False}
        )
        created["edges"].append(
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"}
        )
        client.put(f"/api/workflows/{wf_id}", json=created)
        run_id = client.post(f"/api/workflows/{wf_id}/run",
                             json={"dry_run": True}).json()["run_id"]

        with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
            first = ws.receive_json()
            assert first["event"] == "snapshot"
            assert first["run_id"] == run_id
            events = [first]
            for _ in range(50):
                event = ws.receive_json()
                events.append(event)
                if event["event"] == "run_finished":
                    break
        names = [e["event"] for e in events]
        assert "run_started" in names
        assert "node_finished" in names
        assert "run_finished" in names
        assert events[-1]["event"] == "run_finished"
        assert events[-1]["status"] == "success"
        assert any(e.get("message") == "ws hello" for e in events
                   if e["event"] == "log")
    finally:
        client.delete(f"/api/workflows/{wf_id}")
