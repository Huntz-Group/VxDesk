"""Remote services tests: hub units, WS/TCP/edge transports, legacy client, E2E."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

from vxdesk import workflows_store
from vxdesk.remote import Hub
from vxdesk.remote.hub import ActivityLog, AgentOfflineError

BACKEND = __import__("pathlib").Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


# ------------------------------------------------------------------ fixtures


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def hub(tmp_path):
    return Hub(data_dir=tmp_path)


@pytest.fixture()
def client(virtual_capture, hub):
    from vxdesk.engine.executor import RunManager, WorkflowEngine
    from vxdesk.server import create_app

    run_manager = RunManager(WorkflowEngine(capture=virtual_capture))
    app = create_app(capture=virtual_capture, run_manager=run_manager, hub=hub)
    with TestClient(app) as c:
        yield c


class LiveHub:
    """In-proc uvicorn serving the app, for real socket-level tests."""

    def __init__(self, app, port: int):
        import uvicorn

        self.port = port
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                     log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def start(self, timeout: float = 20.0) -> None:
        import httpx

        self.thread.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.url}/api/edge/ping", timeout=1).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.2)
        raise TimeoutError("live hub did not come up")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture()
def live(virtual_capture, tmp_path):
    hub = Hub(data_dir=tmp_path)
    from vxdesk.engine.executor import RunManager, WorkflowEngine
    from vxdesk.server import create_app

    port = _free_port()
    run_manager = RunManager(WorkflowEngine(capture=virtual_capture))
    app = create_app(capture=virtual_capture, run_manager=run_manager,
                     hub=hub, main_port=port)
    server = LiveHub(app, port)
    server.start()
    yield types.SimpleNamespace(server=server, hub=hub, port=port,
                                url=server.url, ws_url=server.ws_url)
    server.stop()


def _enable_remote(client_or_url, tcp_port: int) -> dict:
    import httpx

    body = {"enabled": True, "tcp_port": tcp_port}
    if isinstance(client_or_url, str):
        return httpx.put(f"{client_or_url}/api/remote/settings", json=body).json()
    return client_or_url.put("/api/remote/settings", json=body).json()


def _mint(client_or_url, name: str = "test agent") -> dict:
    import httpx

    if isinstance(client_or_url, str):
        return httpx.post(f"{client_or_url}/api/remote/agents",
                          json={"name": name}).json()
    return client_or_url.post("/api/remote/agents", json={"name": name}).json()


# ------------------------------------------------------------------ hub units


def test_settings_defaults_and_persistence(hub, tmp_path):
    settings = hub.settings()
    assert settings["enabled"] is False
    assert settings["bind"] == "127.0.0.1"
    assert settings["transports"] == {"ws": True, "tcp": True, "edge": True}
    assert settings["tcp_port"] == 8766
    assert settings["tls"] == {"cert": "", "key": ""}

    hub.update_settings({"enabled": True, "tcp_port": 9999,
                         "transports": {"tcp": False}})
    reloaded = Hub(data_dir=tmp_path).settings()
    assert reloaded["enabled"] is True
    assert reloaded["tcp_port"] == 9999
    assert reloaded["transports"]["tcp"] is False
    assert reloaded["transports"]["ws"] is True  # untouched key preserved


def test_token_mint_verify_revoke(hub):
    agent_id, token = hub.registry.mint("shop pc")
    assert hub.registry.verify(token)["agent_id"] == agent_id
    assert hub.registry.verify("wrong-token") is None
    # hash at rest: plaintext token must not appear in the file
    raw = hub.registry.path.read_text()
    assert token not in raw
    assert hub.registry.revoke(agent_id) is True
    assert hub.registry.verify(token) is None
    assert hub.registry.revoke(agent_id) is False


def test_queue_and_offline_dispatch(hub):
    agent_id, _ = hub.registry.mint("never connects")
    with pytest.raises(AgentOfflineError):
        hub.dispatch(agent_id, {"command": "shell", "shell": "echo hi"})


def test_activity_cap(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    for i in range(1250):
        log.add({"agent_id": "a1", "kind": "log", "message": f"m{i}"})
    entries = log.read(2000)
    assert len(entries) == 1000
    assert entries[0]["message"] == "m1249"  # newest first
    assert entries[-1]["message"] == "m250"


def test_edge_hello_rebind_and_online_window(hub):
    agent_id, token = hub.registry.mint("legacy box")
    record = hub.registry.upsert_from_hello(
        token, "xp-pos-01", "XP register", {"engine": False})
    assert record["agent_id"] == "xp-pos-01"  # rebind to the client's stable id
    # the edge route marks the transport; poll-side recency counts as online
    hub.registry.set_fields("xp-pos-01", transport="edge")
    assert hub.is_online("xp-pos-01") is True
    assert hub.registry.upsert_from_hello("bad-token", "x", "x", {}) is None


# ------------------------------------------------------------------ management REST


def test_remote_disabled_by_default(client):
    status = client.get("/api/remote/status").json()
    assert status["enabled"] is False
    assert status["agents_total"] == 0
    resp = client.post("/api/edge/hello", json={
        "agent_id": "a", "name": "a", "token": "t", "caps": {}})
    assert resp.status_code == 403


def test_settings_and_agent_crud(client):
    status = _enable_remote(client, _free_port())
    assert status["enabled"] is True
    assert status["restart_required"] is False  # bind unchanged

    minted = _mint(client, "floor pc")
    assert minted["agent_id"] and minted["token"]

    agents = client.get("/api/remote/agents").json()
    assert agents[0]["agent_id"] == minted["agent_id"]
    assert agents[0]["online"] is False
    assert "token" not in agents[0] and "token_hash" not in agents[0]

    # offline agent -> 409
    resp = client.post(f"/api/remote/agents/{minted['agent_id']}/run",
                       json={"workflow_id": "wf_x"})
    assert resp.status_code == 409

    assert client.delete(f"/api/remote/agents/{minted['agent_id']}").json() == {"ok": True}
    assert client.get("/api/remote/agents").json() == []
    assert client.delete(f"/api/remote/agents/{minted['agent_id']}").status_code == 404


def test_restart_required_when_bind_differs(client):
    _enable_remote(client, _free_port())
    status = client.put("/api/remote/settings",
                        json={"bind": "0.0.0.0"}).json()
    assert status["restart_required"] is True
    client.put("/api/remote/settings", json={"bind": "127.0.0.1"})


# ------------------------------------------------------------------ edge endpoints


def test_edge_hello_poll_report(client, hub):
    _enable_remote(client, _free_port())
    minted = _mint(client)

    hello = client.post("/api/edge/hello", json={
        "agent_id": minted["agent_id"], "name": "edge box",
        "token": minted["token"], "caps": {"engine": False}})
    assert hello.status_code == 200
    assert hello.json()["ok"] is True
    assert "token_hash" not in hello.json()["agent"]

    # bad token rejected
    bad = client.get("/api/edge/poll",
                     params={"agent_id": minted["agent_id"], "token": "no"})
    assert bad.status_code == 401

    # empty instant poll
    empty = client.get("/api/edge/poll", params={
        "agent_id": minted["agent_id"], "token": minted["token"], "wait": 0})
    assert empty.json() == {"commands": []}

    # queue a shell command and poll it out
    hub.dispatch(minted["agent_id"],
                 {"command": "shell", "shell": "echo hello-edge"})
    polled = client.get("/api/edge/poll", params={
        "agent_id": minted["agent_id"], "token": minted["token"], "wait": 0})
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "shell"
    assert commands[0]["shell"] == "echo hello-edge"

    # report a result
    report = client.post("/api/edge/report", json={
        "agent_id": minted["agent_id"], "token": minted["token"],
        "events": [{"kind": "status", "message": "executing"}],
        "results": [{"command_id": commands[0]["command_id"], "ok": True,
                     "output": {"stdout": "hello-edge", "exit_code": 0},
                     "error": None}],
    })
    assert report.json() == {"ok": True}
    activity = client.get("/api/remote/activity").json()
    assert any(e.get("command_id") == commands[0]["command_id"]
               and e.get("ok") is True for e in activity)


def test_edge_long_poll(client, hub):
    _enable_remote(client, _free_port())
    minted = _mint(client)
    client.post("/api/edge/hello", json={
        "agent_id": minted["agent_id"], "name": "e", "token": minted["token"],
        "caps": {}})

    def delayed_dispatch():
        time.sleep(0.4)
        hub.dispatch(minted["agent_id"], {"command": "shell", "shell": "echo x"})

    threading.Thread(target=delayed_dispatch, daemon=True).start()
    started = time.perf_counter()
    resp = client.get("/api/edge/poll", params={
        "agent_id": minted["agent_id"], "token": minted["token"], "wait": 5})
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200
    assert len(resp.json()["commands"]) == 1
    assert elapsed < 4  # returned early, not after the full wait


def test_edge_ping(client):
    ping = client.get("/api/edge/ping").json()
    assert ping["ok"] is True and ping["server"] == "vxdesk"
    assert "content-length" in client.get("/api/edge/ping").headers


# ------------------------------------------------------------------ websocket


def _ws_client(url: str, first_message: dict, rounds: int = 1):
    """Connect, send first_message, collect `rounds` messages."""
    import websockets

    async def go():
        out = []
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps(first_message))
            for _ in range(rounds):
                out.append(json.loads(await ws.recv()))
        return out

    return asyncio.run(go())


def test_ws_auth_fail_bad_token(live):
    _enable_remote(live.url, _free_port())
    with pytest.raises(Exception):
        _ws_client(f"{live.ws_url}/ws/remote",
                   {"type": "hello", "agent_id": "x", "name": "x",
                    "token": "bad", "caps": {}}, rounds=2)
    # server must have sent welcome ok:false before closing; verify via a
    # tolerant client that reads until close
    import websockets

    async def go():
        async with websockets.connect(f"{live.ws_url}/ws/remote") as ws:
            await ws.send(json.dumps({"type": "hello", "token": "bad"}))
            return json.loads(await ws.recv())

    welcome = asyncio.run(go())
    assert welcome["ok"] is False
    assert "token" in welcome["error"]


def test_ws_first_message_must_be_hello(live):
    _enable_remote(live.url, _free_port())
    import websockets

    async def go():
        async with websockets.connect(f"{live.ws_url}/ws/remote") as ws:
            await ws.send(json.dumps({"type": "pong", "ts": 1}))
            return json.loads(await ws.recv())

    welcome = asyncio.run(go())
    assert welcome["ok"] is False


def test_ws_command_round_trip(live):
    _enable_remote(live.url, _free_port())
    minted = _mint(live.url, "ws agent")

    import websockets

    async def go():
        async with websockets.connect(f"{live.ws_url}/ws/remote") as ws:
            await ws.send(json.dumps({
                "type": "hello", "agent_id": minted["agent_id"],
                "name": "ws agent", "token": minted["token"],
                "caps": {"engine": True}}))
            welcome = json.loads(await ws.recv())
            assert welcome["ok"] is True

            # dispatch a shell command from the hub side
            import httpx
            # (no REST for shell dispatch; use the hub directly)
            command_id = live.hub.dispatch(
                minted["agent_id"], {"command": "shell", "shell": "echo hi"})
            command = json.loads(await ws.recv())
            assert command["type"] == "command"
            assert command["command_id"] == command_id
            assert command["command"] == "shell"

            await ws.send(json.dumps({
                "type": "event", "kind": "status", "message": "working",
                "ts": time.time()}))
            await ws.send(json.dumps({
                "type": "result", "command_id": command_id, "ok": True,
                "output": {"stdout": "hi", "exit_code": 0}, "error": None}))
            await asyncio.sleep(0.3)
        return command_id

    command_id = asyncio.run(go())
    activity = live.hub.activity.read(50)
    assert any(e.get("command_id") == command_id and e.get("ok") for e in activity)
    assert any(e["kind"] == "status" and "working" in e["message"]
               for e in activity)
    # after close the agent is offline
    deadline = time.time() + 3
    while live.hub.is_online(minted["agent_id"]) and time.time() < deadline:
        time.sleep(0.1)
    assert live.hub.is_online(minted["agent_id"]) is False


def test_ws_keepalive_ping(live, monkeypatch):
    monkeypatch.setattr("vxdesk.remote.routes.WS_PING_INTERVAL_S", 0.3)
    _enable_remote(live.url, _free_port())
    minted = _mint(live.url, "pinger")

    import websockets

    async def go():
        async with websockets.connect(f"{live.ws_url}/ws/remote") as ws:
            await ws.send(json.dumps({
                "type": "hello", "agent_id": minted["agent_id"], "name": "p",
                "token": minted["token"], "caps": {}}))
            await ws.recv()  # welcome
            ping = json.loads(await ws.recv())
            assert ping["type"] == "ping"
            await ws.send(json.dumps({"type": "pong", "ts": ping["ts"]}))
            await asyncio.sleep(0.2)
        return True

    assert asyncio.run(go()) is True


# ------------------------------------------------------------------ TCP


def test_tcp_round_trip(live):
    tcp_port = _free_port()
    _enable_remote(live.url, tcp_port)
    minted = _mint(live.url, "tcp agent")

    time.sleep(0.5)  # let the listener come up
    sock = socket.create_connection(("127.0.0.1", tcp_port), timeout=5)
    reader = sock.makefile("r", encoding="utf-8", newline="\n")
    try:
        sock.sendall((json.dumps({
            "type": "hello", "agent_id": minted["agent_id"], "name": "tcp",
            "token": minted["token"], "caps": {}}) + "\n").encode())
        welcome = json.loads(reader.readline())
        assert welcome["ok"] is True

        command_id = live.hub.dispatch(
            minted["agent_id"], {"command": "shell", "shell": "echo tcp"})
        command = json.loads(reader.readline())
        assert command["command_id"] == command_id

        sock.sendall((json.dumps({
            "type": "result", "command_id": command_id, "ok": True,
            "output": {"stdout": "tcp"}, "error": None}) + "\n").encode())
        deadline = time.time() + 3
        while time.time() < deadline:
            if any(e.get("command_id") == command_id
                   for e in live.hub.activity.read(20)):
                break
            time.sleep(0.1)
        assert any(e.get("command_id") == command_id
                   for e in live.hub.activity.read(20))
    finally:
        sock.close()


def test_tcp_bad_token(live):
    tcp_port = _free_port()
    _enable_remote(live.url, tcp_port)
    time.sleep(0.5)
    sock = socket.create_connection(("127.0.0.1", tcp_port), timeout=5)
    reader = sock.makefile("r", encoding="utf-8", newline="\n")
    try:
        sock.sendall((json.dumps({
            "type": "hello", "agent_id": "x", "name": "x", "token": "bad",
            "caps": {}}) + "\n").encode())
        welcome = json.loads(reader.readline())
        assert welcome["ok"] is False
    finally:
        sock.close()


# ------------------------------------------------------------------ legacy edge client


def test_legacy_edge_client_once(live):
    """Run edge/vxdesk_edge.py --once in a subprocess against the live hub."""
    _enable_remote(live.url, _free_port())
    minted = _mint(live.url, "legacy xp box")

    ini = REPO / "build" / "edge-test.ini"
    ini.parent.mkdir(exist_ok=True)
    ini.write_text(
        "[edge]\n"
        f"server = {live.url}\n"
        f"agent_id = xp-test-01\n"
        f"token = {minted['token']}\n"
        "interval = 1\n",
        encoding="utf-8",
    )

    marker = "vxdesk-edge-marker-42"
    # pre-queue the shell command; the client picks it up on its first poll
    live.hub.queue_command("xp-test-01", {"command": "shell",
                                          "shell": f"echo {marker}"})

    proc = subprocess.run(
        [str(BACKEND / ".venv" / "Scripts" / "python.exe"),
         str(REPO / "edge" / "vxdesk_edge.py"), "--once", "--config", str(ini)],
        capture_output=True, text=True, timeout=60)
    try:
        assert proc.returncode == 0, proc.stderr
        deadline = time.time() + 5
        results = []
        while time.time() < deadline:
            results = [r for r in live.hub.results.values()
                       if r.get("output") and marker in
                       json.dumps(r.get("output") or {})]
            if results:
                break
            time.sleep(0.2)
        assert results and results[0]["ok"] is True
        assert results[0]["output"]["exit_code"] == 0
        assert marker in results[0]["output"]["stdout"]
    finally:
        ini.unlink(missing_ok=True)


# ------------------------------------------------------------------ E2E: full agent over WS


def test_e2e_full_agent_runs_workflow(live, workflow_factory, virtual_capture):
    _enable_remote(live.url, _free_port())
    minted = _mint(live.url, "e2e agent")

    sample = json.loads(
        (REPO / "scripts" / "samples" / "welcome-tour.json").read_text("utf-8"))
    nodes = sample["nodes"]
    edges = sample["edges"]
    workflow = workflow_factory(nodes, edges, variables=sample.get("variables"),
                                name="remote e2e tour")

    import os

    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    agent = subprocess.Popen(
        [str(BACKEND / ".venv" / "Scripts" / "python.exe"), "-m", "vxdesk.agent",
         "--server", f"ws://127.0.0.1:{live.port}",
         "--token", minted["token"], "--agent-id", minted["agent_id"],
         "--name", "e2e agent", "--dry-run-default"],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # wait for online
        deadline = time.time() + 30
        online = False
        while time.time() < deadline:
            import httpx
            agents = httpx.get(f"{live.url}/api/remote/agents").json()
            if agents and agents[0]["online"] and agents[0]["transport"] == "ws":
                online = True
                break
            time.sleep(0.3)
        assert online, "agent never came online"

        import httpx
        resp = httpx.post(
            f"{live.url}/api/remote/agents/{minted['agent_id']}/run",
            json={"workflow_id": workflow["id"], "dry_run": True})
        assert resp.status_code == 200
        command_id = resp.json()["command_id"]

        deadline = time.time() + 60
        result = None
        while time.time() < deadline:
            result = live.hub.results.get(command_id)
            if result:
                break
            time.sleep(0.3)
        assert result is not None, "agent never reported a result"
        assert result["ok"] is True
        assert result["output"]["status"] == "success"
        assert result["output"]["dry_run"] is True  # --dry-run-default honored

        activity = live.hub.activity.read(200)
        kinds = [e["kind"] for e in activity]
        assert "run_started" in kinds and "run_finished" in kinds
        run_id = result["output"]["run_id"]
        assert any(e.get("run_id") == run_id and e["kind"] == "log"
                   for e in activity)

        # REST view reflects it too
        rest_activity = httpx.get(f"{live.url}/api/remote/activity").json()
        assert any(e.get("command_id") == command_id for e in rest_activity)
    finally:
        agent.terminate()
        try:
            agent.wait(10)
        except subprocess.TimeoutExpired:
            agent.kill()
