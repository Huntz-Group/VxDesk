"""FastAPI application implementing every endpoint of ``docs/api-contract.md``."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import platform
import sys
import threading
from typing import Optional

import cv2
from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .. import __version__, assets, input as inp, vision, workflows_store
from ..ai import agent as ai_agent
from ..ai import settings as ai_settings
from ..ai.tools import ToolContext
from ..capture import Capture
from ..engine.catalog import get_catalog
from ..engine.executor import RunManager
from ..engine.validate import validate_workflow
from ..paths import ROOT, bundle_dir, ensure_dirs, is_frozen
from ..recorder import AlreadyRecording, NoActiveRecording, RecorderManager
from ..recorder import convert as recorder_convert
from ..recorder.capture import public_events
from ..remote import Hub, RemoteServices, register_remote_routes

logger = logging.getLogger("vxdesk.server")


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""


class RunRequest(BaseModel):
    inputs: Optional[dict] = None
    dry_run: bool = False


class ScreenshotRequest(BaseModel):
    region: Optional[dict] = None
    format: str = "png"


class TestMatchRequest(BaseModel):
    template: str
    threshold: float = 0.8
    region: Optional[dict] = None


class TestOcrRequest(BaseModel):
    region: Optional[dict] = None
    text: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    workflow_id: Optional[str] = None


class RecorderSessionRequest(BaseModel):
    session_id: str


class RecorderConvertRequest(BaseModel):
    session_id: str
    name: str = "Recorded workflow"
    mode: str = "smart"


class WSManager:
    """Fans run events out to WebSocket clients.

    A client connecting mid-run first gets a ``snapshot`` event (same shape as
    ``GET /api/runs/{run_id}``), then every buffered event it missed, then live
    events — with no gap, because the manager lock serializes all three steps.
    """

    def __init__(self, run_manager: RunManager) -> None:
        self._run_manager = run_manager
        self._sockets: dict[str, set[WebSocket]] = {}
        self._lock = threading.Lock()

    async def handle(self, websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        run = self._run_manager.get(run_id)
        if run is None:
            await websocket.send_json({"event": "error", "message": f"unknown run {run_id}"})
            await websocket.close(code=4404)
            return

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def listener(event: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        # Under run.lock: copy snapshot + already-emitted events AND subscribe,
        # so no event can slip between the snapshot and the live stream.
        with run.lock:
            snapshot = {"event": "snapshot", **run.to_dict()}
            missed = list(run.events)
            self._run_manager.add_listener(run_id, listener)
        await websocket.send_json(snapshot)
        for event in missed:
            await websocket.send_json(event)
        with self._lock:
            self._sockets.setdefault(run_id, set()).add(websocket)
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if event.get("event") == "run_finished":
                    # keep the socket open briefly so the client sees the end,
                    # then let it close cleanly
                    await websocket.close()
                    return
        except WebSocketDisconnect:
            pass
        finally:
            self._run_manager.remove_listener(run_id, listener)
            with self._lock:
                self._sockets.get(run_id, set()).discard(websocket)


def create_app(
    capture: Optional[Capture] = None,
    run_manager: Optional[RunManager] = None,
    hub: Optional[Hub] = None,
    main_port: int = 8765,
) -> FastAPI:
    ensure_dirs()
    capture = capture or Capture()
    run_manager = run_manager or RunManager()
    if run_manager.engine.capture is not capture:
        run_manager.engine.capture = capture
    ws_manager = WSManager(run_manager)
    recorder_manager = RecorderManager(capture)
    hub = hub or Hub()
    remote_services = RemoteServices(hub, main_port=main_port)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        remote_services.apply()
        yield
        remote_services.shutdown()

    app = FastAPI(title="VxDesk", version=__version__, lifespan=lifespan)
    app.state.capture = capture
    app.state.run_manager = run_manager
    app.state.recorder_manager = recorder_manager
    app.state.hub = hub
    app.state.remote_services = remote_services

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------- system

    @app.get("/api/system/info")
    def system_info() -> dict:
        ocr_info = run_manager.engine.ocr.info()
        return {
            "version": __version__,
            "os": platform.system().lower(),
            "python": platform.python_version(),
            "capture": dict(capture.capabilities),
            "ocr": ocr_info,
            "gpu": {"name": _gpu_name(), "directml": ocr_info.get("gpu", False)},
            "screens": capture.screens(),
        }

    # ---------------------------------------------------------------- workflows

    @app.get("/api/workflows")
    def list_workflows() -> list[dict]:
        return workflows_store.list_workflows()

    @app.post("/api/workflows", status_code=201)
    def create_workflow(body: WorkflowCreate) -> dict:
        return workflows_store.create_workflow(body.name, body.description)

    @app.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict:
        try:
            return workflows_store.load_workflow(workflow_id)
        except FileNotFoundError:
            raise HTTPException(404, f"workflow not found: {workflow_id}")

    @app.put("/api/workflows/{workflow_id}")
    def put_workflow(workflow_id: str, workflow: dict) -> dict:
        try:
            return workflows_store.save_workflow(workflow_id, workflow)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/workflows/{workflow_id}")
    def delete_workflow(workflow_id: str) -> dict:
        try:
            workflows_store.delete_workflow(workflow_id)
        except FileNotFoundError:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        return {"ok": True}

    @app.post("/api/workflows/{workflow_id}/validate")
    def validate(workflow_id: str) -> dict:
        try:
            workflow = workflows_store.load_workflow(workflow_id)
        except FileNotFoundError:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        return validate_workflow(workflow)

    @app.post("/api/workflows/{workflow_id}/run")
    def run_workflow(workflow_id: str, body: Optional[RunRequest] = None) -> dict:
        try:
            workflow = workflows_store.load_workflow(workflow_id)
        except FileNotFoundError:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        body = body or RunRequest()
        run = run_manager.start(workflow, inputs=body.inputs, dry_run=body.dry_run)
        return {"run_id": run.run_id}

    @app.get("/api/workflows/{workflow_id}/runs")
    def workflow_runs(workflow_id: str) -> list[dict]:
        return run_manager.runs_for(workflow_id)

    # ---------------------------------------------------------------- runs

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = run_manager.get(run_id)
        if run is None:
            raise HTTPException(404, f"run not found: {run_id}")
        return run.to_dict()

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict:
        if not run_manager.stop(run_id):
            raise HTTPException(404, f"run not found: {run_id}")
        return {"ok": True}

    @app.websocket("/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str) -> None:
        await ws_manager.handle(websocket, run_id)

    # ---------------------------------------------------------------- capture / vision utilities

    @app.post("/api/capture/screenshot")
    def screenshot(body: Optional[ScreenshotRequest] = None) -> Response:
        body = body or ScreenshotRequest()
        try:
            frame = capture.grab(body.region)
        except Exception as exc:
            raise HTTPException(503, f"capture failed: {exc}")
        fmt = (body.format or "png").lower()
        if fmt not in ("png", "jpeg"):
            raise HTTPException(400, "format must be 'png' or 'jpeg'")
        ok, buf = cv2.imencode(f".{fmt}", frame)
        if not ok:
            raise HTTPException(500, "image encoding failed")
        media = "image/png" if fmt == "png" else "image/jpeg"
        return Response(content=buf.tobytes(), media_type=media)

    @app.get("/api/windows")
    def windows() -> list[dict]:
        try:
            return inp.list_windows()
        except Exception as exc:
            logger.warning("list_windows failed: %s", exc)
            return []

    @app.post("/api/vision/test-match")
    def test_match(body: TestMatchRequest) -> dict:
        try:
            template = assets.load_template(body.template)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, str(exc))
        screen = capture.grab()
        return vision.test_match(screen, template, body.threshold, body.region)

    @app.post("/api/vision/test-ocr")
    def test_ocr(body: TestOcrRequest) -> dict:
        screen = capture.grab()
        return vision.ocr(
            screen, region=body.region, text=body.text, engine=run_manager.engine.ocr
        )

    # ---------------------------------------------------------------- template assets

    @app.get("/api/assets/templates")
    def list_templates() -> list[dict]:
        return assets.list_templates()

    @app.post("/api/assets/templates", status_code=201)
    async def upload_template(file: UploadFile, name: str = Form(...)) -> dict:
        data = await file.read()
        if not data:
            raise HTTPException(400, "empty upload")
        try:
            return assets.save_template(name or (file.filename or "template.png"), data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/assets/templates/{name}")
    def get_template(name: str) -> Response:
        try:
            return Response(content=assets.read_template_bytes(name), media_type="image/png")
        except FileNotFoundError:
            raise HTTPException(404, f"template not found: {name}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/assets/templates/{name}")
    def delete_template(name: str) -> dict:
        try:
            assets.delete_template(name)
        except FileNotFoundError:
            raise HTTPException(404, f"template not found: {name}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    # ---------------------------------------------------------------- node catalog

    @app.get("/api/nodes/catalog")
    def node_catalog() -> dict:
        return get_catalog()

    # ---------------------------------------------------------------- AI assistant

    @app.get("/api/ai/settings")
    def ai_get_settings() -> dict:
        return ai_settings.get_settings()

    @app.put("/api/ai/settings")
    def ai_put_settings(body: dict) -> dict:
        try:
            updates = {k: body[k] for k in ("provider", "base_url", "model", "api_key")
                       if k in body}
            return ai_settings.update_settings(**updates)
        except Exception as exc:
            raise HTTPException(400, f"could not save settings: {exc}")

    @app.get("/api/ai/status")
    def ai_status() -> dict:
        return ai_settings.probe_status(timeout=4.0)

    @app.post("/api/ai/chat")
    def ai_chat(body: ChatRequest) -> StreamingResponse:
        tool_ctx = ToolContext(capture=capture, run_manager=run_manager)

        async def stream():
            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def emit(event: dict) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, event)

            def worker() -> None:
                try:
                    ai_agent.run_agent(
                        [m.model_dump() for m in body.messages],
                        body.workflow_id,
                        tool_ctx,
                        emit,
                    )
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            threading.Thread(target=worker, name="vxdesk-ai-agent", daemon=True).start()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # heartbeat so proxies don't stall
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---------------------------------------------------------------- recorder

    @app.post("/api/recorder/start")
    def recorder_start() -> dict:
        try:
            session_id = recorder_manager.start()
        except AlreadyRecording as exc:
            raise HTTPException(409, str(exc))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        return {"session_id": session_id}

    @app.post("/api/recorder/stop")
    def recorder_stop() -> dict:
        try:
            session = recorder_manager.stop()
        except NoActiveRecording as exc:
            raise HTTPException(409, str(exc))
        return {
            "session_id": session.id,
            "events": public_events(session.events),
            "duration_s": session.duration_s,
            # preview from internal events (with crops) so smart-mode names
            # match what /convert will produce
            "step_preview": recorder_convert.step_preview(session.events,
                                                          session_id=session.id),
        }

    @app.post("/api/recorder/discard")
    def recorder_discard(body: RecorderSessionRequest) -> dict:
        try:
            recorder_manager.discard(body.session_id)
        except KeyError:
            raise HTTPException(404, f"unknown recording session: {body.session_id}")
        return {"ok": True}

    @app.get("/api/recorder/status")
    def recorder_status() -> dict:
        return recorder_manager.status()

    @app.post("/api/recorder/convert")
    def recorder_convert_endpoint(body: RecorderConvertRequest) -> dict:
        if body.mode not in ("smart", "coordinates"):
            raise HTTPException(400, "mode must be 'smart' or 'coordinates'")
        try:
            session = recorder_manager.consume(body.session_id)
        except KeyError:
            raise HTTPException(404, f"unknown recording session: {body.session_id}")
        try:
            workflow = recorder_convert.build_workflow(
                session.events, body.name, mode=body.mode, session_id=session.id
            )
            validation = validate_workflow(workflow)
            if not validation["valid"]:
                raise HTTPException(
                    400, "converted workflow failed validation: "
                    + "; ".join(validation["errors"])
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"conversion failed: {exc}")
        return workflows_store.save_workflow(workflow["id"], workflow)

    # ---------------------------------------------------------------- remote services

    register_remote_routes(
        app, hub,
        running_bind="127.0.0.1",
        on_settings_changed=remote_services.apply,
    )

    # ---------------------------------------------------------------- static frontend (optional)

    spa_dir = _find_frontend()
    if spa_dir is not None:
        from fastapi.staticfiles import StaticFiles
        from starlette.exceptions import HTTPException as StarletteHTTPException

        class SPAStaticFiles(StaticFiles):
            """Static files with SPA fallback to index.html for client routes."""

            async def get_response(self, path: str, scope):
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code == 404:
                        return await super().get_response("index.html", scope)
                    raise

        app.mount("/", SPAStaticFiles(directory=str(spa_dir), html=True), name="frontend")

    if is_frozen():
        _seed_sample_workflows()

    return app


def _find_frontend() -> Optional["Path"]:
    """Built SPA: frontend/dist in dev, bundled frontend_dist when frozen."""
    from pathlib import Path

    for candidate in (bundle_dir() / "frontend_dist", bundle_dir() / "frontend" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _seed_sample_workflows() -> None:
    """On first frozen run, copy the bundled sample workflows into the data dir."""
    from ..paths import WORKFLOWS_DIR

    samples = bundle_dir() / "samples"
    if not samples.is_dir() or any(WORKFLOWS_DIR.glob("wf_*.json")):
        return
    import shutil

    for sample in samples.glob("*.json"):
        try:
            import json as _json

            data = _json.loads(sample.read_text(encoding="utf-8"))
            data["id"] = workflows_store.new_workflow_id()
            workflows_store.save_workflow(data["id"], data)
        except Exception as exc:
            logger.warning("could not seed sample workflow %s: %s", sample, exc)


def _gpu_name() -> str:
    try:
        import re

        import dxcam  # noqa: PLC0415

        info = str(dxcam.device_info() or "")
        match = re.search(r"Device Name:\s*([^<>\n]+?)(?:\s+Dedicated|\s*$)", info)
        if match:
            return match.group(1).strip()
        return info.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()
