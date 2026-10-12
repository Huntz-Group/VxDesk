"""Agent tool definitions (OpenAI function-calling schemas) and local executors.

Thin wrappers over the existing engine/server internals. ``create_workflow`` /
``update_workflow`` always run static validation and return the errors so the
model can self-correct. ``run_workflow`` waits for completion (max 60 s) and
returns status plus the last few log lines. ``screenshot`` saves a PNG under
``runs/`` and returns dimensions + path — never image bytes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

import cv2

from .. import assets, input as inp, vision, workflows_store
from ..capture import Capture
from ..engine.catalog import get_catalog
from ..engine.executor import RunManager
from ..engine.validate import validate_workflow
from ..paths import ROOT

logger = logging.getLogger("vxdesk.ai.tools")

RUN_TIMEOUT_S = 60.0
MAX_LOG_LINES = 8

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "List all saved workflows (id, name, description, node count).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow",
            "description": "Get the full JSON of one workflow by id.",
            "parameters": {
                "type": "object",
                "properties": {"workflow_id": {"type": "string"}},
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": "Create a new workflow. Nodes need id/type/name/params; edges need "
            "id/source/target/sourceHandle ('default' or a branch handle like 'true', "
            "'found', 'body'). The result includes validation errors to fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "nodes": {"type": "array", "items": {"type": "object"}},
                    "edges": {"type": "array", "items": {"type": "object"}},
                    "variables": {"type": "object"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_workflow",
            "description": "Replace an existing workflow's content (full workflow JSON). "
            "The result includes validation errors to fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "workflow": {"type": "object"},
                },
                "required": ["workflow_id", "workflow"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_workflow",
            "description": "Delete a workflow permanently. Only call after the user clearly "
            "confirmed the deletion in the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "reason": {"type": "string", "description": "Why the user asked to delete it"},
                },
                "required": ["workflow_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_workflow",
            "description": "Run a workflow and wait for it to finish (up to 60s). Use "
            "dry_run=true (practice mode, no real clicks/typing) unless the user "
            "explicitly asked for a real run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": True},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_run",
            "description": "Stop a running workflow run.",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run",
            "description": "Get the status and per-node states of a run.",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_runs",
            "description": "List past runs of a workflow.",
            "parameters": {
                "type": "object",
                "properties": {"workflow_id": {"type": "string"}},
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_catalog",
            "description": "Get the full node catalog: every node type, its params and "
            "branch handles. Use it to build valid workflows.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot (optional region). Returns width, height and "
            "the saved PNG path — not image data.",
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "object"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test_match",
            "description": "Test whether a template image (name from assets/templates) is "
            "currently visible on screen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {"type": "string"},
                    "threshold": {"type": "number", "default": 0.8},
                },
                "required": ["template"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "List visible top-level windows with title and rect.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class ToolContext:
    """Runtime services the tools operate on."""

    def __init__(self, capture: Capture, run_manager: RunManager) -> None:
        self.capture = capture
        self.run_manager = run_manager


def _result(ok: bool, summary: str, result: Any,
            workflow_id: Optional[str] = None) -> dict:
    out = {"ok": ok, "summary": summary, "result": result}
    if workflow_id:
        out["workflow_id"] = workflow_id
    return out


# ------------------------------------------------------------------ executors


def _t_list_workflows(ctx: ToolContext, args: dict) -> dict:
    flows = workflows_store.list_workflows()
    return _result(True, f"{len(flows)} workflow(s) saved", flows)


def _t_get_workflow(ctx: ToolContext, args: dict) -> dict:
    workflow_id = str(args.get("workflow_id", ""))
    try:
        workflow = workflows_store.load_workflow(workflow_id)
    except (FileNotFoundError, ValueError):
        return _result(False, f"workflow {workflow_id!r} not found",
                       {"error": "not_found"})
    return _result(True, f"Loaded “{workflow.get('name', workflow_id)}”", workflow,
                   workflow_id=workflow_id)


def _t_create_workflow(ctx: ToolContext, args: dict) -> dict:
    name = str(args.get("name") or "Untitled workflow")
    workflow = {
        "id": workflows_store.new_workflow_id(),
        "name": name,
        "description": str(args.get("description") or ""),
        "nodes": args.get("nodes") or [],
        "edges": args.get("edges") or [],
        "variables": args.get("variables") or {},
    }
    validation = validate_workflow(workflow)
    workflows_store.save_workflow(workflow["id"], workflow)
    steps = len(workflow["nodes"])
    if validation["valid"]:
        summary = f"Created {workflow['id']} ({steps} steps, valid)"
    else:
        summary = f"Created {workflow['id']} but validation found " \
                  f"{len(validation['errors'])} error(s) — fix them with update_workflow"
    return _result(
        validation["valid"],
        summary,
        {
            "workflow_id": workflow["id"],
            "valid": validation["valid"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        },
        workflow_id=workflow["id"],
    )


def _t_update_workflow(ctx: ToolContext, args: dict) -> dict:
    workflow_id = str(args.get("workflow_id", ""))
    new_workflow = args.get("workflow")
    if not isinstance(new_workflow, dict):
        return _result(False, "missing 'workflow' object", {"error": "bad_args"})
    try:
        existing = workflows_store.load_workflow(workflow_id)
    except (FileNotFoundError, ValueError):
        return _result(False, f"workflow {workflow_id!r} not found",
                       {"error": "not_found"})
    merged = {**existing, **new_workflow, "id": workflow_id}
    validation = validate_workflow(merged)
    workflows_store.save_workflow(workflow_id, merged)
    steps = len(merged.get("nodes", []))
    if validation["valid"]:
        summary = f"Updated {workflow_id} ({steps} steps, valid)"
    else:
        summary = f"Updated {workflow_id} but validation found " \
                  f"{len(validation['errors'])} error(s) — fix them and update again"
    return _result(
        validation["valid"],
        summary,
        {
            "workflow_id": workflow_id,
            "valid": validation["valid"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        },
        workflow_id=workflow_id,
    )


def _t_delete_workflow(ctx: ToolContext, args: dict) -> dict:
    workflow_id = str(args.get("workflow_id", ""))
    reason = str(args.get("reason") or "(no reason given)")
    try:
        workflow = workflows_store.load_workflow(workflow_id)
        name = workflow.get("name", workflow_id)
        workflows_store.delete_workflow(workflow_id)
    except (FileNotFoundError, ValueError):
        return _result(False, f"workflow {workflow_id!r} not found",
                       {"error": "not_found"})
    logger.info("workflow %s (%s) deleted via assistant; reason: %s",
                workflow_id, name, reason)
    return _result(True, f"Deleted “{name}”", {"deleted": workflow_id, "reason": reason})


def _t_run_workflow(ctx: ToolContext, args: dict) -> dict:
    workflow_id = str(args.get("workflow_id", ""))
    dry_run = bool(args.get("dry_run", True))
    try:
        workflow = workflows_store.load_workflow(workflow_id)
    except (FileNotFoundError, ValueError):
        return _result(False, f"workflow {workflow_id!r} not found",
                       {"error": "not_found"})
    run = ctx.run_manager.start(workflow, dry_run=dry_run)
    finished = run.done_event.wait(RUN_TIMEOUT_S)
    logs = [e.get("message", "") for e in run.events if e.get("event") == "log"]
    status = run.status if finished else "running (still going after 60s)"
    if not finished:
        ctx.run_manager.stop(run.run_id)
        status = "stopped (timed out after 60s)"
    ok = run.status == "success"
    return _result(
        ok,
        f"Run finished: {status}",
        {
            "run_id": run.run_id,
            "status": run.status if finished else "timeout_stopped",
            "error": run.error,
            "dry_run": dry_run,
            "last_logs": logs[-MAX_LOG_LINES:],
        },
        workflow_id=workflow_id,
    )


def _t_stop_run(ctx: ToolContext, args: dict) -> dict:
    run_id = str(args.get("run_id", ""))
    if not ctx.run_manager.stop(run_id):
        return _result(False, f"run {run_id!r} not found", {"error": "not_found"})
    return _result(True, f"Stop requested for {run_id}", {"run_id": run_id})


def _t_get_run(ctx: ToolContext, args: dict) -> dict:
    run_id = str(args.get("run_id", ""))
    run = ctx.run_manager.get(run_id)
    if run is None:
        return _result(False, f"run {run_id!r} not found", {"error": "not_found"})
    return _result(run.status == "success", f"Run {run_id}: {run.status}", run.to_dict())


def _t_list_runs(ctx: ToolContext, args: dict) -> dict:
    workflow_id = str(args.get("workflow_id", ""))
    runs = ctx.run_manager.runs_for(workflow_id)
    return _result(True, f"{len(runs)} run(s)", runs, workflow_id=workflow_id)


def _t_get_node_catalog(ctx: ToolContext, args: dict) -> dict:
    catalog = get_catalog()
    return _result(True, f"{len(catalog['nodes'])} node types", catalog)


def _t_screenshot(ctx: ToolContext, args: dict) -> dict:
    region = args.get("region") if isinstance(args.get("region"), dict) else None
    try:
        frame = ctx.capture.grab(region)
    except Exception as exc:
        return _result(False, f"capture failed: {exc}", {"error": str(exc)})
    out_dir = ROOT / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"assistant_shot_{int(time.time() * 1000)}.png"
    if not cv2.imwrite(str(path), frame):
        return _result(False, "failed to save screenshot", {"error": "imwrite"})
    h, w = frame.shape[:2]
    return _result(True, f"Screenshot {w}x{h} saved", {"width": w, "height": h,
                                                      "path": str(path)})


def _t_test_match(ctx: ToolContext, args: dict) -> dict:
    template = str(args.get("template", ""))
    threshold = float(args.get("threshold", 0.8))
    try:
        template_img = assets.load_template(template)
    except (FileNotFoundError, ValueError) as exc:
        return _result(False, str(exc), {"error": str(exc)})
    match = vision.test_match(ctx.capture.grab(), template_img, threshold)
    state = "found" if match["found"] else "not found"
    return _result(True, f"{template}: {state} (score {match['score']})", match)


def _t_list_windows(ctx: ToolContext, args: dict) -> dict:
    try:
        windows = inp.list_windows()
    except Exception as exc:
        return _result(False, f"could not list windows: {exc}", {"error": str(exc)})
    return _result(True, f"{len(windows)} window(s)", windows)


_EXECUTORS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "list_workflows": _t_list_workflows,
    "get_workflow": _t_get_workflow,
    "create_workflow": _t_create_workflow,
    "update_workflow": _t_update_workflow,
    "delete_workflow": _t_delete_workflow,
    "run_workflow": _t_run_workflow,
    "stop_run": _t_stop_run,
    "get_run": _t_get_run,
    "list_runs": _t_list_runs,
    "get_node_catalog": _t_get_node_catalog,
    "screenshot": _t_screenshot,
    "test_match": _t_test_match,
    "list_windows": _t_list_windows,
}


def execute_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    executor = _EXECUTORS.get(name)
    if executor is None:
        return _result(False, f"unknown tool {name!r}", {"error": "unknown_tool"})
    try:
        return executor(ctx, args)
    except Exception as exc:  # never let a tool crash the agent loop
        logger.warning("tool %s failed: %s", name, exc)
        return _result(False, f"{name} failed: {exc}", {"error": str(exc)})


# ------------------------------------------------------------------ summaries


def tool_call_summary(name: str, args: dict, ctx: Optional[ToolContext] = None) -> str:
    """Short human label for the ``tool_start`` SSE event."""
    if name == "list_workflows":
        return "List workflows"
    if name == "get_workflow":
        return f"Open workflow {args.get('workflow_id', '?')}"
    if name == "create_workflow":
        return f"Create workflow “{args.get('name', 'Untitled')}”"
    if name == "update_workflow":
        return f"Update workflow {args.get('workflow_id', '?')}"
    if name == "delete_workflow":
        return f"Delete workflow {args.get('workflow_id', '?')}"
    if name == "run_workflow":
        label = _workflow_name(ctx, args.get("workflow_id"))
        mode = "practice mode" if args.get("dry_run", True) else "REAL run"
        return f"Run “{label}” ({mode})"
    if name == "stop_run":
        return f"Stop run {args.get('run_id', '?')}"
    if name == "get_run":
        return f"Check run {args.get('run_id', '?')}"
    if name == "list_runs":
        return f"List runs of {args.get('workflow_id', '?')}"
    if name == "get_node_catalog":
        return "Read node catalog"
    if name == "screenshot":
        return "Take a screenshot"
    if name == "test_match":
        return f"Look for “{args.get('template', '?')}” on screen"
    if name == "list_windows":
        return "List open windows"
    return name


def _workflow_name(ctx: Optional[ToolContext], workflow_id: Any) -> str:
    if ctx is None or not workflow_id:
        return str(workflow_id or "?")
    try:
        return str(workflows_store.load_workflow(str(workflow_id)).get("name", workflow_id))
    except Exception:
        return str(workflow_id)


def serialize_result(result: Any) -> str:
    """Compact JSON for the tool message fed back to the model."""
    return json.dumps(result, ensure_ascii=False, default=str)[:8000]
