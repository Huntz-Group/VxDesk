"""Recorder tests: pure converter rules, pynput capture session, API e2e."""

from __future__ import annotations

import time
import types

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vxdesk import workflows_store
from vxdesk.engine.validate import validate_workflow
from vxdesk.recorder import convert
from vxdesk.recorder.capture import RecorderManager, AlreadyRecording

from conftest import MARKER_POS, MARKER_SIZE

MARKER_CENTER = (MARKER_POS[0] + MARKER_SIZE[0] // 2, MARKER_POS[1] + MARKER_SIZE[1] // 2)


def _crop() -> np.ndarray:
    return np.full((80, 80, 3), 127, dtype=np.uint8)


# ================================================================== converter


class TestCharCoalescing:
    def test_simple_run(self):
        events = [
            {"t": 0.10, "kind": "char", "text": "h"},
            {"t": 0.20, "kind": "char", "text": "i"},
            {"t": 0.30, "kind": "char", "text": "!"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert [s["type"] for s in steps] == ["action.type_text"]
        assert steps[0]["params"] == {"text": "hi!", "interval_ms": 30}
        assert steps[0]["name"] == "Type “hi!”"

    def test_gap_over_800ms_splits_run(self):
        events = [
            {"t": 0.10, "kind": "char", "text": "a"},
            {"t": 0.95, "kind": "char", "text": "b"},  # 850 ms later
        ]
        steps = convert.build_steps(events, mode="coordinates")
        types = [s["type"] for s in steps]
        assert types == ["action.type_text", "control.wait", "action.type_text"]
        assert steps[0]["params"]["text"] == "a"
        assert steps[2]["params"]["text"] == "b"
        assert steps[1]["params"]["ms"] == 850

    def test_gap_790ms_still_coalesces(self):
        events = [
            {"t": 0.10, "kind": "char", "text": "a"},
            {"t": 0.89, "kind": "char", "text": "b"},  # 790 ms later
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert [s["type"] for s in steps] == ["action.type_text"]
        assert steps[0]["params"]["text"] == "ab"

    def test_window_change_splits_run(self):
        events = [
            {"t": 0.10, "kind": "char", "text": "a", "window": "Editor"},
            {"t": 0.20, "kind": "char", "text": "b", "window": "Browser"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        types = [s["type"] for s in steps]
        assert types == ["action.focus_window", "action.type_text",
                         "action.focus_window", "action.type_text"]
        assert steps[0]["params"]["title"] == "Editor"
        assert steps[1]["params"]["text"] == "a"
        assert steps[2]["params"]["title"] == "Browser"
        assert steps[3]["params"]["text"] == "b"


class TestWaitRules:
    def test_gap_inserts_wait(self):
        events = [
            {"t": 0.10, "kind": "key", "key": "enter"},
            {"t": 2.00, "kind": "key", "key": "tab"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert [s["type"] for s in steps] == [
            "action.press_key", "control.wait", "action.press_key"]
        assert steps[1]["params"]["ms"] == 1900
        assert steps[1]["name"] == "Wait 1.9s"

    def test_wait_capped_at_5000(self):
        events = [
            {"t": 0.10, "kind": "key", "key": "enter"},
            {"t": 20.0, "kind": "key", "key": "tab"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert steps[1]["params"]["ms"] == 5000
        assert steps[1]["name"] == "Wait 5s"

    def test_leading_wait_kept(self):
        events = [{"t": 2.00, "kind": "key", "key": "enter"}]
        steps = convert.build_steps(events, mode="coordinates")
        assert steps[0]["type"] == "control.wait"
        assert steps[0]["params"]["ms"] == 2000

    def test_trailing_wait_dropped(self):
        events = [
            {"t": 0.10, "kind": "key", "key": "enter"},
            {"t": 0.50, "kind": "window", "title": "A"},
            {"t": 3.00, "kind": "window", "title": "A"},  # same title -> no focus
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert steps[-1]["type"] != "control.wait"
        # focus A appears exactly once (dedup)
        assert [s["type"] for s in steps].count("action.focus_window") == 1


class TestFocusDedup:
    def test_one_focus_per_title_in_a_row(self):
        events = [
            {"t": 0.10, "kind": "window", "title": "Notepad"},
            {"t": 0.20, "kind": "window", "title": "Notepad"},
            {"t": 0.30, "kind": "window", "title": "Chrome"},
            {"t": 0.40, "kind": "window", "title": "Notepad"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        titles = [s["params"]["title"] for s in steps
                  if s["type"] == "action.focus_window"]
        assert titles == ["Notepad", "Chrome", "Notepad"]
        assert steps[0]["name"] == "Focus “Notepad”"

    def test_click_window_attribute_triggers_focus(self):
        events = [
            {"t": 0.10, "kind": "click", "x": 10, "y": 10, "button": "left",
             "window": "Notepad"},
            {"t": 0.20, "kind": "click", "x": 20, "y": 20, "button": "left",
             "window": "Notepad"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert [s["type"] for s in steps].count("action.focus_window") == 1


class TestKeysAndClicks:
    def test_special_key_vs_char(self):
        events = [
            {"t": 0.10, "kind": "char", "text": "x"},
            {"t": 0.20, "kind": "key", "key": "enter"},
        ]
        steps = convert.build_steps(events, mode="coordinates")
        assert steps[0]["type"] == "action.type_text"
        assert steps[1] == steps[-1]
        assert steps[1]["type"] == "action.press_key"
        assert steps[1]["params"] == {"keys": "enter"}
        assert steps[1]["name"] == "Press Enter"

    def test_chord_normalization(self):
        events = [{"t": 0.10, "kind": "key", "key": "ctrl+s"}]
        steps = convert.build_steps(events, mode="coordinates")
        assert steps[0]["params"] == {"keys": ["ctrl", "s"]}
        assert steps[0]["name"] == "Press Ctrl+S"

    def test_coordinates_click(self):
        events = [{"t": 0.10, "kind": "click", "x": 450, "y": 320, "button": "right"}]
        steps = convert.build_steps(events, mode="coordinates")
        assert [s["type"] for s in steps] == ["action.click"]
        assert steps[0]["params"] == {"target": "point", "x": 450, "y": 320,
                                      "button": "right"}
        assert steps[0]["name"] == "Click at (450, 320)"

    def test_smart_click_emits_find_image_and_last_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(convert, "TEMPLATES_DIR", tmp_path)
        events = [{"t": 0.10, "kind": "click", "x": 450, "y": 320, "button": "left",
                   "_crop": _crop()}]
        steps = convert.build_steps(events, mode="smart", session_id="abc123")
        assert [s["type"] for s in steps] == ["vision.find_image", "action.click"]
        find, click = steps
        assert find["params"]["threshold"] == 0.85
        assert find["params"]["template"] == "rec_abc123_1.png"
        assert (tmp_path / "rec_abc123_1.png").exists()
        assert click["params"]["target"] == "last_found"
        assert click["params"]["x"] == 450 and click["params"]["y"] == 320

    def test_smart_click_without_crop_falls_back_to_point(self, tmp_path, monkeypatch):
        monkeypatch.setattr(convert, "TEMPLATES_DIR", tmp_path)
        events = [{"t": 0.10, "kind": "click", "x": 1, "y": 2, "button": "left"}]
        steps = convert.build_steps(events, mode="smart", session_id="abc123")
        assert [s["type"] for s in steps] == ["action.click"]
        assert steps[0]["params"]["target"] == "point"
        assert list(tmp_path.iterdir()) == []


class TestWorkflowAssembly:
    def test_layout_edges_trigger_and_validation(self):
        events = [
            {"t": 0.10, "kind": "click", "x": 1, "y": 2, "button": "left",
             "window": "Notepad"},
            {"t": 1.00, "kind": "char", "text": "h"},
            {"t": 1.10, "kind": "char", "text": "i"},
            {"t": 1.50, "kind": "key", "key": "ctrl+s"},
        ]
        workflow = convert.build_workflow(events, "My recording", mode="coordinates",
                                          session_id="s1")
        nodes = workflow["nodes"]
        assert nodes[0]["type"] == "trigger.manual"
        assert nodes[0]["position"] == {"x": 0, "y": 120}
        for i, node in enumerate(nodes):
            assert node["position"] == {"x": i * 220, "y": 120}
        # sequential default edges
        assert len(workflow["edges"]) == len(nodes) - 1
        for edge, a, b in zip(workflow["edges"], nodes, nodes[1:]):
            assert edge["source"] == a["id"] and edge["target"] == b["id"]
            assert edge["sourceHandle"] == "default"
        validation = validate_workflow(workflow)
        assert validation["valid"], validation["errors"]

    def test_preview_matches_node_names(self):
        events = [
            {"t": 0.10, "kind": "click", "x": 1, "y": 2, "button": "left",
             "_crop": _crop()},
            {"t": 0.50, "kind": "key", "key": "enter"},
        ]
        preview = convert.step_preview(events, session_id="s1")
        steps = convert.build_steps(events, mode="smart", session_id="s1",
                                    template_writer=None)
        assert preview == [{"type": s["type"], "name": s["name"]} for s in steps]

    def test_name_truncation(self):
        events = [{"t": 0.10, "kind": "char", "text": c}
                  for c in "this is a very long sentence"]
        steps = convert.build_steps(events, mode="coordinates")
        type_node = next(s for s in steps if s["type"] == "action.type_text")
        assert type_node["name"] == "Type “this is a…”"
        assert type_node["params"]["text"] == "this is a very long sentence"


# ================================================================== capture session


class _FakeListener:
    instances: list = []

    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.started = False
        _FakeListener.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


@pytest.fixture()
def fake_pynput(monkeypatch):
    _FakeListener.instances = []
    monkeypatch.setattr("vxdesk.recorder.capture._MOUSE",
                        types.SimpleNamespace(Listener=_FakeListener))
    monkeypatch.setattr("vxdesk.recorder.capture._KEYBOARD",
                        types.SimpleNamespace(Listener=_FakeListener))
    monkeypatch.setattr("vxdesk.recorder.capture._foreground_title",
                        lambda: "TestWin")
    return _FakeListener.instances


@pytest.fixture()
def manager(virtual_capture):
    return RecorderManager(virtual_capture)


def _keys():
    from pynput.keyboard import Key, KeyCode
    from pynput.mouse import Button
    return Key, KeyCode, Button


def test_capture_records_events(monkeypatch, fake_pynput, manager):
    Key, KeyCode, Button = _keys()
    session_id = manager.start()
    session = manager.active
    assert session_id == session.id
    assert len(fake_pynput) == 2 and all(l.started for l in fake_pynput)

    session.on_click(100, 200, Button.left, True)
    session.on_press(KeyCode.from_char("h"))
    session.on_press(KeyCode.from_char("i"))
    session.on_release(KeyCode.from_char("i"))
    session.on_press(Key.enter)

    events = session.events
    kinds = [e["kind"] for e in events]
    # window event first (foreground changed to TestWin)
    assert kinds[0] == "window" and events[0]["title"] == "TestWin"
    click = events[1]
    assert click["kind"] == "click" and click["x"] == 100 and click["y"] == 200
    assert click["window"] == "TestWin"
    assert "_crop" in click  # click-time screenshot stashed
    assert [e["kind"] for e in events[2:]] == ["char", "char", "key"]
    assert events[4]["key"] == "enter"
    # monotonic timestamps
    ts = [e["t"] for e in events]
    assert ts == sorted(ts) and all(t >= 0 for t in ts)

    stopped = manager.stop()
    assert stopped.id == session_id
    assert all(not l.started for l in fake_pynput)
    assert manager.active is None


def test_capture_chords_and_modifier_tracking(fake_pynput, manager):
    Key, KeyCode, Button = _keys()
    manager.start()
    session = manager.active

    session.on_press(Key.ctrl_l)
    session.on_press(KeyCode.from_char("s"))
    session.on_release(KeyCode.from_char("s"))
    session.on_release(Key.ctrl_l)
    session.on_press(Key.shift_l)
    session.on_press(Key.enter)
    session.on_release(Key.enter)
    session.on_release(Key.shift_l)
    session.on_press(Key.alt_l)
    session.on_press(Key.tab)

    keys = [e["key"] for e in session.events if e["kind"] == "key"]
    assert keys == ["ctrl+s", "shift+enter", "alt+tab"]
    manager.stop()


def test_capture_space_is_a_char(fake_pynput, manager):
    Key, KeyCode, Button = _keys()
    manager.start()
    session = manager.active
    session.on_press(KeyCode.from_char("a"))
    session.on_release(KeyCode.from_char("a"))
    session.on_press(Key.space)
    session.on_release(Key.space)
    chars = [e["text"] for e in session.events if e["kind"] == "char"]
    assert chars == ["a", " "]
    manager.stop()


def test_esc_stops_recording_and_is_not_recorded(fake_pynput, manager):
    Key, KeyCode, Button = _keys()
    manager.start()
    session = manager.active
    session.on_press(KeyCode.from_char("x"))
    session.on_release(KeyCode.from_char("x"))
    session.on_press(Key.esc)  # bare Esc -> stop
    deadline = time.time() + 3
    while manager.active is not None and time.time() < deadline:
        time.sleep(0.02)
    assert manager.active is None
    stored = manager.get(session.id)
    assert all(not (e["kind"] == "key" and e.get("key") == "esc")
               for e in stored.events)


def test_modified_esc_is_recorded(fake_pynput, manager):
    Key, KeyCode, Button = _keys()
    manager.start()
    session = manager.active
    session.on_press(Key.shift_l)
    session.on_press(Key.esc)
    assert manager.active is session  # still recording
    keys = [e["key"] for e in session.events if e["kind"] == "key"]
    assert keys == ["shift+esc"]
    manager.stop()


def test_double_start_raises(fake_pynput, manager):
    manager.start()
    with pytest.raises(AlreadyRecording):
        manager.start()
    manager.stop()


def test_discard(fake_pynput, manager):
    manager.start()
    session = manager.stop()
    manager.discard(session.id)
    with pytest.raises(KeyError):
        manager.get(session.id)


# ================================================================== API e2e


@pytest.fixture()
def client(virtual_capture, fake_pynput):
    from vxdesk.engine.executor import RunManager, WorkflowEngine
    from vxdesk.server import create_app

    run_manager = RunManager(WorkflowEngine(capture=virtual_capture))
    app = create_app(capture=virtual_capture, run_manager=run_manager)
    with TestClient(app) as c:
        yield c


def _record_sample_session(client) -> str:
    """Start via API, drive fake listener callbacks, stop via API."""
    session_id = client.post("/api/recorder/start").json()["session_id"]
    manager = client.app.state.recorder_manager
    session = manager.active
    Key, KeyCode, Button = _keys()
    session.on_click(*MARKER_CENTER, Button.left, True)
    session.on_press(KeyCode.from_char("h"))
    session.on_press(KeyCode.from_char("i"))
    session.on_press(Key.enter)
    resp = client.post("/api/recorder/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == session_id
    assert body["duration_s"] >= 0
    assert body["step_preview"]
    kinds = [e["kind"] for e in body["events"]]
    assert "click" in kinds and "char" in kinds and "key" in kinds
    assert all("_crop" not in e for e in body["events"])  # internals stripped
    return session_id


def test_api_double_start_409_and_status(client):
    first = client.post("/api/recorder/start")
    assert first.status_code == 200
    status = client.get("/api/recorder/status").json()
    assert status["recording"] is True
    assert status["session_id"] == first.json()["session_id"]
    second = client.post("/api/recorder/start")
    assert second.status_code == 409
    client.post("/api/recorder/stop")
    status = client.get("/api/recorder/status").json()
    assert status["recording"] is False


def test_api_unknown_session_404s(client):
    assert client.post("/api/recorder/discard",
                       json={"session_id": "nope"}).status_code == 404
    assert client.post("/api/recorder/convert",
                       json={"session_id": "nope", "name": "x",
                             "mode": "smart"}).status_code == 404


def test_api_discard(client):
    session_id = client.post("/api/recorder/start").json()["session_id"]
    client.post("/api/recorder/stop")
    assert client.post("/api/recorder/discard",
                       json={"session_id": session_id}).json() == {"ok": True}
    assert client.post("/api/recorder/convert",
                       json={"session_id": session_id, "name": "x",
                             "mode": "smart"}).status_code == 404


def _run_workflow_dry(client, workflow_id: str) -> dict:
    run_id = client.post(f"/api/workflows/{workflow_id}/run",
                         json={"dry_run": True}).json()["run_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise TimeoutError("run did not finish")


def test_api_convert_coordinates_and_run(client):
    from conftest import make_edge  # noqa: F401 (documents fixture reuse)

    session_id = _record_sample_session(client)
    resp = client.post("/api/recorder/convert",
                       json={"session_id": session_id,
                             "name": "Recorded coords", "mode": "coordinates"})
    assert resp.status_code == 200
    workflow = resp.json()
    created = workflow["id"]
    try:
        assert workflow["name"] == "Recorded coords"
        types_ = [n["type"] for n in workflow["nodes"]]
        assert "action.click" in types_ and "action.type_text" in types_
        click = next(n for n in workflow["nodes"] if n["type"] == "action.click")
        assert click["params"]["target"] == "point"
        validation = client.post(f"/api/workflows/{created}/validate").json()
        assert validation["valid"], validation["errors"]
        run = _run_workflow_dry(client, created)
        assert run["status"] == "success"
    finally:
        client.delete(f"/api/workflows/{created}")


def test_api_convert_smart_and_run(client):
    session_id = _record_sample_session(client)
    resp = client.post("/api/recorder/convert",
                       json={"session_id": session_id,
                             "name": "Recorded smart", "mode": "smart"})
    assert resp.status_code == 200
    workflow = resp.json()
    created = workflow["id"]
    templates = [n["params"]["template"] for n in workflow["nodes"]
                 if n["type"] == "vision.find_image"]
    try:
        assert templates == [f"rec_{session_id}_1.png"]
        listing = client.get("/api/assets/templates").json()
        assert any(t["name"] == templates[0] for t in listing)
        click = next(n for n in workflow["nodes"] if n["type"] == "action.click")
        assert click["params"]["target"] == "last_found"
        assert click["params"]["x"] == MARKER_CENTER[0]
        run = _run_workflow_dry(client, created)
        assert run["status"] == "success"
        # find_image located the click-time crop on the same virtual screen
        find_state = next(s for nid, s in run["node_states"].items()
                          if s.get("output") and "score" in (s["output"] or {}))
        assert find_state["output"]["found"] is True
    finally:
        client.delete(f"/api/workflows/{created}")
        client.delete(f"/api/assets/templates/{templates[0]}")


def test_api_convert_consumes_session(client):
    session_id = _record_sample_session(client)
    body = {"session_id": session_id, "name": "once", "mode": "coordinates"}
    assert client.post("/api/recorder/convert", json=body).status_code == 200
    created = client.post("/api/recorder/convert", json=body)
    assert created.status_code == 404
    # cleanup the workflow from the first convert
    workflows = client.get("/api/workflows").json()
    for w in workflows:
        if w["name"] == "once":
            client.delete(f"/api/workflows/{w['id']}")
