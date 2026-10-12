"""AI assistant tests: settings store, status probe, SSE agent loop.

A tiny threading HTTP server mocks the OpenAI-compatible endpoint (``/models``
plus scripted ``/chat/completions`` responses), so no real LLM is needed.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from vxdesk import workflows_store
from vxdesk.ai import settings as ai_settings


# ------------------------------------------------------------------ mock LLM


def _cc(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return 200, {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _tc(name, args, call_id):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(200, {"object": "list",
                             "data": [{"id": "mock-model", "object": "model"}]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        server = self.server
        server.requests.append(body)
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        behavior = server.script[min(server.call_count, len(server.script) - 1)]
        server.call_count += 1
        status, payload = behavior(body) if callable(behavior) else behavior
        self._json(status, payload)


class MockLLM:
    def __init__(self, script):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        self.server.script = script
        self.server.requests = []
        self.server.call_count = 0
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    @property
    def requests(self) -> list:
        return self.server.requests

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    """Isolate ai-settings.json into a tmp dir for the test."""
    path = tmp_path / "ai-settings.json"
    monkeypatch.setattr(ai_settings, "SETTINGS_FILE", path)
    return path


@pytest.fixture()
def client(virtual_capture, settings_file):
    from vxdesk.engine.executor import RunManager, WorkflowEngine
    from vxdesk.server import create_app

    run_manager = RunManager(WorkflowEngine(capture=virtual_capture))
    app = create_app(capture=virtual_capture, run_manager=run_manager)
    with TestClient(app) as c:
        yield c


def _configure(base_url: str, model: str = "mock-model", api_key=None):
    ai_settings.update_settings(provider="custom", base_url=base_url, model=model,
                                api_key=api_key)


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        assert line.startswith("data: "), f"bad SSE line: {line!r}"
        events.append(json.loads(line[len("data: "):]))
    return events


# ------------------------------------------------------------------ settings


def test_settings_roundtrip_key_write_only(client):
    put = client.put("/api/ai/settings", json={
        "provider": "openai", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "api_key": "sk-super-secret",
    })
    assert put.status_code == 200
    assert "sk-super-secret" not in put.text

    got = client.get("/api/ai/settings")
    body = got.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert body["has_api_key"] is True
    assert "sk-super-secret" not in got.text
    assert "api_key" not in body
    assert any(p["id"] == "ollama" for p in body["presets"])
    assert len(body["presets"]) == 6

    # omitted api_key keeps the existing one
    client.put("/api/ai/settings", json={"model": "other-model"})
    assert client.get("/api/ai/settings").json()["has_api_key"] is True
    # empty string also keeps it
    client.put("/api/ai/settings", json={"api_key": ""})
    assert client.get("/api/ai/settings").json()["has_api_key"] is True
    # null clears it
    client.put("/api/ai/settings", json={"api_key": None})
    assert client.get("/api/ai/settings").json()["has_api_key"] is False


def test_status_reachable_and_unreachable(client):
    mock = MockLLM(script=[_cc(content="hi")])
    try:
        client.put("/api/ai/settings", json={
            "provider": "custom", "base_url": mock.url, "model": "mock-model"})
        status = client.get("/api/ai/status").json()
        assert status["configured"] is True
        assert status["reachable"] is True
        assert status["model"] == "mock-model"
        assert status["detail"] == "connected"
    finally:
        mock.close()

    client.put("/api/ai/settings", json={
        "provider": "custom", "base_url": "http://127.0.0.1:59998/v1",
        "model": "mock-model"})
    status = client.get("/api/ai/status").json()  # must not raise
    assert status["configured"] is True
    assert status["reachable"] is False
    assert "could not reach" in status["detail"]


def test_status_unconfigured(client, settings_file):
    status = client.get("/api/ai/status").json()
    assert status["configured"] is False
    assert status["reachable"] is False


# ------------------------------------------------------------------ chat / agent loop


VALID_GRAPH_NODES = [
    {"id": "n1", "type": "trigger.manual", "name": "Start",
     "position": {"x": 0, "y": 0}, "params": {}, "disabled": False},
    {"id": "n2", "type": "control.log", "name": "Say hello",
     "position": {"x": 200, "y": 0}, "params": {"message": "hello from ai"},
     "disabled": False},
]
VALID_GRAPH_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"},
]


def test_chat_agent_loop_creates_workflow(client):
    mock = MockLLM(script=[
        _cc(content="I'll check your workflows and build that.",
            tool_calls=[_tc("list_workflows", {}, "call_1")]),
        _cc(tool_calls=[_tc("create_workflow", {
            "name": "AI notepad demo",
            "description": "made by the assistant test",
            "nodes": VALID_GRAPH_NODES,
            "edges": VALID_GRAPH_EDGES,
        }, "call_2")]),
        _cc(content="Done! I created “AI notepad demo” — it validates cleanly."),
    ])
    created_ids: list[str] = []
    try:
        _configure(mock.url)
        resp = client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": "Make a tiny hello workflow"}],
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.text)

        kinds = [e["event"] for e in events]
        assert kinds[0] == "assistant_message"
        assert kinds.count("tool_start") == 2
        assert kinds.count("tool_end") == 2
        # exactly one terminal event, and it is last
        assert kinds[-1] == "done"
        assert sum(k in ("done", "error") for k in kinds) == 1

        t1, t2 = (e for e in events if e["event"] == "tool_end")
        assert t1["name"] == "list_workflows" and t1["ok"] is True
        assert t1["summary"]
        assert t2["name"] == "create_workflow" and t2["ok"] is True
        assert t2["workflow_id"]
        assert "valid" in t2["summary"]
        created_ids.append(t2["workflow_id"])

        # the workflow really exists on disk and passes validation
        workflow = workflows_store.load_workflow(t2["workflow_id"])
        assert workflow["name"] == "AI notepad demo"
        assert len(workflow["nodes"]) == 2
        validation = client.post(
            f"/api/workflows/{t2['workflow_id']}/validate").json()
        assert validation["valid"] is True

        assert events[-1]["content"].startswith("Done!")
        assert mock.server.call_count == 3
    finally:
        mock.close()
        for workflow_id in created_ids:
            try:
                workflows_store.delete_workflow(workflow_id)
            except FileNotFoundError:
                pass


def test_chat_tools_unsupported_fallback(client):
    def behavior(body):
        if "tools" in body:
            return 400, {"error": {"message": "Unknown field 'tools' in request"}}
        return _cc(content="I can only chat — no tools here.")

    mock = MockLLM(script=[behavior, behavior])
    try:
        _configure(mock.url)
        resp = client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        events = _parse_sse(resp.text)
        assert len(events) == 1
        assert events[0]["event"] == "done"
        assert "I can only chat" in events[0]["content"]
        assert "does not support tool calling" in events[0]["content"]
        # first attempt carried tools, the retry did not
        assert "tools" in mock.requests[0]
        assert "tools" not in mock.requests[1]
    finally:
        mock.close()


def test_chat_agent_round_cap(client):
    # the mock keeps asking for tool calls forever -> cap after 10 rounds
    mock = MockLLM(script=[
        _cc(tool_calls=[_tc("list_workflows", {}, "call_x")]),
    ])
    try:
        _configure(mock.url)
        resp = client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": "loop forever"}],
        })
        events = _parse_sse(resp.text)
        kinds = [e["event"] for e in events]
        assert kinds.count("tool_start") == 10
        assert kinds[-1] == "done"
        assert "step limit" in events[-1]["content"]
        assert sum(k in ("done", "error") for k in kinds) == 1
    finally:
        mock.close()


def test_chat_unreachable_model_friendly_error(client):
    _configure("http://127.0.0.1:59997/v1")
    resp = client.post("/api/ai/chat", json={
        "messages": [{"role": "user", "content": "hello"}],
    })
    events = _parse_sse(resp.text)
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "Could not reach the model" in events[0]["message"]
    assert "59997" in events[0]["message"]


def test_chat_unconfigured_friendly_error(client, settings_file):
    resp = client.post("/api/ai/chat", json={
        "messages": [{"role": "user", "content": "hello"}],
    })
    events = _parse_sse(resp.text)
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "not configured" in events[0]["message"]


def test_chat_run_workflow_tool_end_to_end(client, workflow_factory):
    workflow = workflow_factory(VALID_GRAPH_NODES, VALID_GRAPH_EDGES,
                                name="ai-run-me")
    mock = MockLLM(script=[
        _cc(tool_calls=[_tc("run_workflow",
                            {"workflow_id": workflow["id"], "dry_run": True},
                            "call_run")]),
        _cc(content="Ran it in practice mode — success."),
    ])
    try:
        _configure(mock.url)
        resp = client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": "run it in practice mode"}],
        })
        events = _parse_sse(resp.text)
        end = next(e for e in events if e["event"] == "tool_end")
        assert end["name"] == "run_workflow"
        assert end["ok"] is True
        assert "success" in end["summary"]
        assert end["workflow_id"] == workflow["id"]
        assert events[-1]["event"] == "done"
    finally:
        mock.close()
