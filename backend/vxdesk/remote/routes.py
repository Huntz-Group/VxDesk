"""Remote routes: /ws/remote, /api/edge/*, /api/remote/* — registerable on any app.

Registered on the main app and (when TLS is configured) on a second app served
by a dedicated HTTPS listener, so the local UI stays plain HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import __version__, workflows_store
from .hub import AgentOfflineError, Hub, LiveConnection

logger = logging.getLogger("vxdesk.remote.routes")

WS_PING_INTERVAL_S = 30.0


class AgentCreateRequest(BaseModel):
    name: str


class AgentRunRequest(BaseModel):
    workflow_id: str
    dry_run: bool = False


def _public_agent(record: dict) -> dict:
    """Agent record without the token hash."""
    return {k: v for k, v in record.items() if k != "token_hash"}


def register_remote_routes(
    app: FastAPI,
    hub: Hub,
    running_bind: str = "127.0.0.1",
    on_settings_changed: Optional[Callable[[], None]] = None,
) -> None:
    """Attach all remote-services routes to ``app``."""

    def _require_enabled(transport: str) -> dict:
        settings = hub.settings()
        if not settings["enabled"] or not settings["transports"].get(transport, False):
            raise HTTPException(403, "remote services are disabled "
                                     f"(transport: {transport})")
        return settings

    def _auth(agent_id: str, token: str) -> dict:
        record = hub.registry.verify(token or "")
        if record is None:
            raise HTTPException(401, "invalid token")
        if agent_id and agent_id != record["agent_id"]:
            known = hub.registry.get(agent_id)
            if known is not None:
                raise HTTPException(401, "agent_id/token mismatch")
        return record

    # ------------------------------------------------------------ websocket

    @app.websocket("/ws/remote")
    async def remote_ws(websocket: WebSocket) -> None:
        settings = hub.settings()
        await websocket.accept()
        if not settings["enabled"] or not settings["transports"].get("ws", False):
            await websocket.send_json({"type": "welcome", "ok": False,
                                       "error": "remote services disabled"})
            await websocket.close()
            return

        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        except Exception:
            await websocket.close()
            return
        if first.get("type") != "hello":
            await websocket.send_json({"type": "welcome", "ok": False,
                                       "error": "first message must be hello"})
            await websocket.close()
            return

        record = hub.registry.upsert_from_hello(
            str(first.get("token", "")),
            str(first.get("agent_id", "") or ""),
            str(first.get("name", "") or ""),
            first.get("caps") if isinstance(first.get("caps"), dict) else {},
        )
        if record is None:
            await websocket.send_json({"type": "welcome", "ok": False,
                                       "error": "invalid token"})
            await websocket.close()
            return
        agent_id = record["agent_id"]

        loop = asyncio.get_running_loop()
        client = websocket.client
        address = f"{client.host}:{client.port}" if client else "?"

        def send_threadsafe(obj: dict) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(websocket.send_json(obj)))

        def close_threadsafe() -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(websocket.close()))

        conn = LiveConnection("ws", address, send_threadsafe, close_threadsafe)
        hub.connect(agent_id, conn)
        await websocket.send_json({"type": "welcome", "ok": True, "error": None,
                                   "agent_id": agent_id})
        logger.info("agent %s connected via ws from %s", agent_id, address)

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(WS_PING_INTERVAL_S)
                try:
                    await websocket.send_json({"type": "ping", "ts": time.time()})
                except Exception:
                    return

        ping_task = asyncio.ensure_future(keepalive())
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")
                if msg_type == "event":
                    hub.handle_event(agent_id, msg)
                elif msg_type == "result":
                    hub.handle_result(agent_id, msg)
                elif msg_type == "pong":
                    hub.registry.touch(agent_id)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception as exc:
            logger.debug("ws agent %s error: %s", agent_id, exc)
        finally:
            ping_task.cancel()
            hub.disconnect(agent_id, conn)
            logger.info("agent %s disconnected", agent_id)

    # ------------------------------------------------------------ edge polling

    @app.post("/api/edge/hello")
    def edge_hello(body: dict) -> dict:
        _require_enabled("edge")
        record = hub.registry.upsert_from_hello(
            str(body.get("token", "")),
            str(body.get("agent_id", "") or ""),
            str(body.get("name", "") or ""),
            body.get("caps") if isinstance(body.get("caps"), dict) else {},
        )
        if record is None:
            raise HTTPException(401, "invalid token")
        hub.registry.set_fields(record["agent_id"], transport="edge")
        hub.log_activity(record["agent_id"], "status", "edge hello")
        return {"ok": True, "agent": _public_agent(record)}

    @app.get("/api/edge/poll")
    def edge_poll(agent_id: str = Query(""), token: str = Query(""),
                  wait: float = Query(0.0)) -> dict:
        _require_enabled("edge")
        record = _auth(agent_id, token)
        canonical_id = record["agent_id"]
        hub.registry.touch(canonical_id)
        commands = hub.poll_commands(canonical_id, wait_s=min(25.0, max(0.0, wait)))
        return {"commands": commands}

    @app.post("/api/edge/report")
    def edge_report(body: dict) -> dict:
        _require_enabled("edge")
        record = _auth(str(body.get("agent_id", "")), str(body.get("token", "")))
        agent_id = record["agent_id"]
        for event in body.get("events") or []:
            if isinstance(event, dict):
                hub.handle_event(agent_id, {"type": "event", **event})
        for result in body.get("results") or []:
            if isinstance(result, dict):
                hub.handle_result(agent_id, {"type": "result", **result})
        return {"ok": True}

    @app.get("/api/edge/ping")
    def edge_ping() -> dict:
        return {"ok": True, "server": "vxdesk", "version": __version__}

    # ------------------------------------------------------------ management REST

    @app.get("/api/remote/status")
    def remote_status() -> dict:
        return hub.status_view(running_bind)

    @app.put("/api/remote/settings")
    def remote_put_settings(body: dict) -> dict:
        hub.update_settings(body)
        if on_settings_changed is not None:
            try:
                on_settings_changed()
            except Exception as exc:
                logger.warning("applying remote settings failed: %s", exc)
        return hub.status_view(running_bind)

    @app.get("/api/remote/agents")
    def remote_agents() -> list[dict]:
        return hub.agents_view()

    @app.post("/api/remote/agents", status_code=201)
    def remote_create_agent(body: AgentCreateRequest) -> dict:
        agent_id, token = hub.registry.mint(body.name)
        hub.log_activity(agent_id, "status", f"agent “{body.name}” registered")
        return {"agent_id": agent_id, "token": token}

    @app.delete("/api/remote/agents/{agent_id}")
    def remote_delete_agent(agent_id: str) -> dict:
        if not hub.registry.revoke(agent_id):
            raise HTTPException(404, f"unknown agent: {agent_id}")
        with hub._lock:
            conn = hub._live.pop(agent_id, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        hub.log_activity(agent_id, "status", "agent revoked")
        return {"ok": True}

    @app.post("/api/remote/agents/{agent_id}/run")
    def remote_run(agent_id: str, body: AgentRunRequest) -> dict:
        if hub.registry.get(agent_id) is None:
            raise HTTPException(404, f"unknown agent: {agent_id}")
        if not hub.is_online(agent_id):
            raise HTTPException(409, f"agent {agent_id} is offline")
        try:
            workflow = workflows_store.load_workflow(body.workflow_id)
        except FileNotFoundError:
            raise HTTPException(404, f"workflow not found: {body.workflow_id}")
        try:
            command_id = hub.dispatch(agent_id, {
                "command": "run_workflow",
                "workflow_id": body.workflow_id,
                "workflow": workflow,
                "dry_run": bool(body.dry_run),
            })
        except AgentOfflineError:
            raise HTTPException(409, f"agent {agent_id} is offline")
        return {"command_id": command_id}

    @app.get("/api/remote/activity")
    def remote_activity(limit: int = Query(200)) -> list[dict]:
        return hub.activity.read(limit)
