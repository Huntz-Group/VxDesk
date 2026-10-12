"""MCP stdio server exposing desktop automation tools to AI agents.

Run with ``python -m vxdesk.mcp_server``. Uses the official ``mcp`` SDK's
FastMCP when importable; otherwise falls back to a minimal hand-rolled
JSON-RPC 2.0 stdio implementation exposing the same tool names.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import time
from typing import Optional

import cv2

from . import input as inp
from . import vision, workflows_store
from .capture import Capture
from .engine.executor import RunManager
from .vision import get_ocr_engine

logger = logging.getLogger("vxdesk.mcp")

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
    from mcp.server.fastmcp import Image as _MCPImage
except (ImportError, ModuleNotFoundError):
    try:  # mcp 2.x renamed FastMCP -> MCPServer
        from mcp.server.mcpserver import MCPServer as _MCPServer
        from mcp.server.mcpserver import Image as _MCPImage
    except (ImportError, ModuleNotFoundError):
        _MCPServer = None  # type: ignore[assignment]
        _MCPImage = None  # type: ignore[assignment]

TOOLS = [
    "screenshot",
    "find_image",
    "find_text",
    "click",
    "type_text",
    "press_key",
    "list_windows",
    "run_workflow",
]


# --------------------------------------------------------------------- core ops


class Desktop:
    """Shared runtime for the MCP tools (lazy capture/OCR)."""

    def __init__(self) -> None:
        self._capture: Optional[Capture] = None
        self._run_manager: Optional[RunManager] = None

    @property
    def capture(self) -> Capture:
        if self._capture is None:
            self._capture = Capture()
        return self._capture

    @property
    def runs(self) -> RunManager:
        if self._run_manager is None:
            from .engine.executor import WorkflowEngine

            self._run_manager = RunManager(
                WorkflowEngine(capture=self.capture, ocr=get_ocr_engine())
            )
        return self._run_manager


_DESKTOP = Desktop()


def op_screenshot(x=None, y=None, w=None, h=None) -> bytes:
    region = None
    if w is not None and h is not None:
        region = {"x": int(x or 0), "y": int(y or 0), "w": int(w), "h": int(h)}
    frame = _DESKTOP.capture.grab(region)
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def op_find_image(template: str, threshold: float = 0.8) -> dict:
    from .assets import load_template

    screen = _DESKTOP.capture.grab()
    return vision.find_image(screen, load_template(template), threshold=threshold)


def op_find_text(text: str, case_sensitive: bool = False) -> dict:
    screen = _DESKTOP.capture.grab()
    return vision.find_text(
        screen, text, case_sensitive=case_sensitive, engine=get_ocr_engine()
    )


def op_run_workflow(workflow: str, dry_run: bool = False, timeout_s: float = 120.0) -> dict:
    workflow_id = workflows_store.find_workflow_id(workflow)
    if workflow_id is None:
        raise ValueError(f"workflow not found by id or name: {workflow!r}")
    wf = workflows_store.load_workflow(workflow_id)
    run = _DESKTOP.runs.start(wf, dry_run=dry_run)
    deadline = time.time() + timeout_s
    while run.status == "running" and time.time() < deadline:
        time.sleep(0.1)
    if run.status == "running":
        _DESKTOP.runs.stop(run.run_id)
        time.sleep(0.3)
    result = run.to_dict()
    result["timed_out"] = run.status == "running"
    return result


# --------------------------------------------------------------------- FastMCP


def _build_fastmcp():
    if _MCPServer is None:
        raise ImportError("official mcp SDK is not importable")
    mcp = _MCPServer("vxdesk")

    @mcp.tool()
    def screenshot(x: int = 0, y: int = 0, w: int = 0, h: int = 0) -> _MCPImage:
        """Capture the screen (or region x/y/w/h in absolute pixels) as PNG."""
        region = None if w <= 0 or h <= 0 else {"x": x, "y": y, "w": w, "h": h}
        frame = _DESKTOP.capture.grab(region)
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("PNG encoding failed")
        return _MCPImage(data=buf.tobytes(), format="png")

    @mcp.tool()
    def find_image(template: str, threshold: float = 0.8) -> dict:
        """Find a template image (name from assets/templates) on screen."""
        return op_find_image(template, threshold)

    @mcp.tool()
    def find_text(text: str, case_sensitive: bool = False) -> dict:
        """Find text on screen via OCR."""
        return op_find_text(text, case_sensitive)

    @mcp.tool()
    def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
        """Click at absolute virtual-screen coordinates."""
        return inp.click(x, y, button=button, clicks=clicks)

    @mcp.tool()
    def type_text(text: str, interval_ms: int = 0) -> dict:
        """Type text with the keyboard."""
        return inp.type_text(text, interval_ms=interval_ms)

    @mcp.tool()
    def press_key(keys: list[str]) -> dict:
        """Press a key (["enter"]) or chord (["ctrl", "s"])."""
        return inp.press_key(keys)

    @mcp.tool()
    def list_windows() -> list[dict]:
        """List top-level windows with title and rect."""
        return inp.list_windows()

    @mcp.tool()
    def run_workflow(workflow: str, dry_run: bool = False, timeout_s: float = 120.0) -> dict:
        """Run a saved workflow by id or name; waits for completion."""
        return op_run_workflow(workflow, dry_run=dry_run, timeout_s=timeout_s)

    return mcp


# ------------------------------------------------- minimal JSON-RPC fallback


def _jsonrpc_fallback_main() -> None:  # pragma: no cover - only used without mcp SDK
    def handle(method: str, params: dict):
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vxdesk", "version": "0.1.0"},
            }
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "tools/list":
            return {"tools": [{"name": t, "description": t, "inputSchema": {"type": "object"}}
                              for t in TOOLS]}
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            result = _dispatch(name, args)
            if isinstance(result, (bytes, bytearray)):
                content = [{"type": "image", "data": base64.b64encode(result).decode(),
                            "mimeType": "image/png"}]
            else:
                content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
            return {"content": content, "isError": False}
        if method == "ping":
            return {}
        raise ValueError(f"unknown method: {method}")

    def _dispatch(name: str, args: dict):
        if name == "screenshot":
            return op_screenshot(args.get("x"), args.get("y"), args.get("w"), args.get("h"))
        if name == "find_image":
            return op_find_image(args["template"], args.get("threshold", 0.8))
        if name == "find_text":
            return op_find_text(args["text"], args.get("case_sensitive", False))
        if name == "click":
            return inp.click(args["x"], args["y"], args.get("button", "left"),
                             args.get("clicks", 1))
        if name == "type_text":
            return inp.type_text(args["text"], args.get("interval_ms", 0))
        if name == "press_key":
            return inp.press_key(args["keys"])
        if name == "list_windows":
            return inp.list_windows()
        if name == "run_workflow":
            return op_run_workflow(args["workflow"], args.get("dry_run", False),
                                   args.get("timeout_s", 120.0))
        raise ValueError(f"unknown tool: {name}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle(request.get("method", ""), request.get("params", {}) or {})
            if response is None or "id" not in request:
                continue
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                         "result": response}) + "\n")
        except Exception as exc:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": json.loads(line).get("id") if line else None,
                "error": {"code": -32000, "message": str(exc)},
            }) + "\n")
        sys.stdout.flush()


def main() -> None:  # pragma: no cover - manual entry point
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        mcp = _build_fastmcp()
    except ImportError:
        logger.warning("official mcp SDK not available; using JSON-RPC fallback")
        _jsonrpc_fallback_main()
        return
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
