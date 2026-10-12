"""End-to-end: a full workflow executed through the HTTP API against the
virtual capture source, including a branch, variables and dry-run input."""

from __future__ import annotations

import time

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


def _node(node_id, type_, params=None):
    return {"id": node_id, "type": type_, "name": node_id,
            "position": {"x": 0, "y": 0}, "params": params or {}, "disabled": False}


def _edge(source, target, handle="default"):
    return {"id": f"e_{source}_{target}_{handle}", "source": source,
            "target": target, "sourceHandle": handle}


def test_full_workflow_e2e(client, template_asset, monkeypatch):
    typed: list[str] = []
    monkeypatch.setattr(
        "vxdesk.input.type_text",
        lambda text, **kw: typed.append(text) or {},
    )

    workflow = {
        "name": "e2e",
        "description": "",
        "nodes": [
            _node("n1", "trigger.manual"),
            _node("n2", "vision.find_image",
                  {"template": template_asset, "threshold": 0.9}),
            _node("n3", "control.condition",
                  {"expression": "{{ n2.output.found }} and {{ n2.output.score }} > 0.8"}),
            _node("n4", "control.set_variable",
                  {"name": "hit_at", "value": "{{ n2.output.center.x }},{{ n2.output.center.y }}"}),
            _node("n5", "control.log",
                  {"message": "marker at {{ vars.hit_at }} (score {{ n2.output.score }})"}),
            _node("n6", "action.type_text", {"text": "found {{ vars.hit_at }}"}),
            _node("n7", "control.log", {"message": "marker missing"}),
        ],
        "edges": [
            _edge("n1", "n2"),
            _edge("n2", "n3"),
            _edge("n3", "n4", "true"),
            _edge("n4", "n5"),
            _edge("n5", "n6"),
            _edge("n3", "n7", "false"),
        ],
        "variables": {},
    }

    created = client.post("/api/workflows", json={"name": "e2e"}).json()
    wf_id = created["id"]
    try:
        workflow["id"] = wf_id
        client.put(f"/api/workflows/{wf_id}", json=workflow)

        validation = client.post(f"/api/workflows/{wf_id}/validate").json()
        assert validation["valid"], validation["errors"]

        run_id = client.post(f"/api/workflows/{wf_id}/run",
                             json={"dry_run": True}).json()["run_id"]

        deadline = time.time() + 10
        run = {}
        while time.time() < deadline:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] != "running":
                break
            time.sleep(0.05)

        assert run["status"] == "success"
        states = run["node_states"]
        # vision matched the marker at (120, 80) with size 64x48
        assert states["n2"]["output"]["found"] is True
        assert states["n2"]["output"]["center"] == {"x": 152, "y": 104}
        # condition took the true branch
        assert states["n3"]["output"]["result"] is True
        assert states["n4"]["output"] == {"name": "hit_at", "value": "152,104"}
        assert states["n5"]["status"] == "success"
        assert states["n6"]["status"] == "success"
        # false branch never ran
        assert "n7" not in states
        # dry-run: the real input layer was never invoked
        assert typed == []
    finally:
        client.delete(f"/api/workflows/{wf_id}")
