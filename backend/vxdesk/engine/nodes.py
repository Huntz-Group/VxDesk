"""Node registry: maps workflow node ``type`` strings to handler functions.

Handlers receive the :class:`~vxdesk.engine.executor.ExecutionContext` and the
node's *template-resolved* params, and return a JSON-able output dict. Branch
selection for conditional nodes is declared via ``branch`` callables.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

import cv2

from .. import input as inp
from .. import vision
from ..assets import load_template
from ..paths import ROOT
from .expressions import evaluate, evaluate_bool

if TYPE_CHECKING:  # pragma: no cover
    from .executor import ExecutionContext

logger = logging.getLogger("vxdesk.engine.nodes")

Handler = Callable[["ExecutionContext", dict], dict]


# ---------------------------------------------------------------- helpers


def _region(params: dict) -> Optional[dict]:
    region = params.get("region")
    if not region:
        return None
    return {
        "x": int(region.get("x", 0)),
        "y": int(region.get("y", 0)),
        "w": int(region["w"]),
        "h": int(region["h"]),
    }


def _load_template_image(params: dict):
    name = params.get("template")
    if not name:
        raise ValueError("param 'template' is required")
    return load_template(str(name))


def _find_image_on_screen(rt: "ExecutionContext", params: dict) -> dict:
    screen = rt.capture.grab()
    template = _load_template_image(params)
    return vision.find_image(
        screen,
        template,
        threshold=float(params.get("threshold", 0.8)),
        region=_region(params),
        scales=params.get("scales"),
    )


def _find_text_on_screen(rt: "ExecutionContext", params: dict) -> dict:
    text = params.get("text")
    if not text:
        raise ValueError("param 'text' is required")
    screen = rt.capture.grab()
    return vision.find_text(
        screen,
        str(text),
        case_sensitive=bool(params.get("case_sensitive", False)),
        region=_region(params),
        engine=rt.ocr,
    )


def _last_found_point(rt: "ExecutionContext") -> tuple[int, int]:
    """Center of the most recent successful find (used by click/drag targets)."""
    point = rt.last_found_point()
    if point is None:
        raise ValueError("no previous match to use as 'last_found' target")
    return point


def _check_stop(rt: "ExecutionContext") -> None:
    if rt.stop_event.is_set():
        raise RunStopped()


class RunStopped(Exception):
    """Raised inside nodes when the run's stop event is set."""


# ---------------------------------------------------------------- handlers


def h_trigger_manual(rt: "ExecutionContext", params: dict) -> dict:
    return dict(rt.inputs)


def h_data_table(rt: "ExecutionContext", params: dict) -> dict:
    csv_text = params.get("csv_text")
    csv_path = params.get("csv_path")
    if csv_text:
        content = str(csv_text)
    elif csv_path:
        from pathlib import Path

        p = Path(str(csv_path))
        if not p.is_absolute():
            p = ROOT / p
        content = p.read_text(encoding="utf-8-sig")
    else:
        raise ValueError("input.data_table requires 'csv_text' or 'csv_path'")
    rows = [dict(r) for r in csv.DictReader(io.StringIO(content))]
    return {"rows": rows, "count": len(rows)}


def h_condition(rt: "ExecutionContext", params: dict) -> dict:
    expression = params.get("expression")
    if expression is None or str(expression).strip() == "":
        raise ValueError("control.condition requires 'expression'")
    if isinstance(expression, bool):
        result = expression
    elif isinstance(expression, (int, float)):
        result = bool(expression)
    else:
        result = evaluate_bool(str(expression))
    rt.log("info", f"condition {expression!r} -> {result}")
    return {"result": bool(result)}


def h_wait(rt: "ExecutionContext", params: dict) -> dict:
    ms = max(0, int(float(params.get("ms", 1000))))
    deadline = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < deadline:
        _check_stop(rt)
        time.sleep(min(0.05, deadline - time.perf_counter()))
    return {}


def h_wait_for(rt: "ExecutionContext", params: dict) -> dict:
    target = params.get("target", "image")
    timeout_ms = max(0, int(float(params.get("timeout_ms", 10000))))
    poll_ms = max(50, int(float(params.get("poll_ms", 500))))
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while True:
        _check_stop(rt)
        if target == "image":
            match = _find_image_on_screen(rt, params)
        elif target == "text":
            match = _find_text_on_screen(rt, params)
        else:
            raise ValueError(f"control.wait_for: unknown target {target!r}")
        if match.get("found"):
            out = dict(match)
            out["found"] = True
            return out
        if time.perf_counter() >= deadline:
            out = dict(match)
            out["found"] = False
            out["timed_out"] = True
            return out
        time.sleep(min(poll_ms / 1000.0, max(0.0, deadline - time.perf_counter())))


def h_set_variable(rt: "ExecutionContext", params: dict) -> dict:
    name = params.get("name")
    if not name:
        raise ValueError("control.set_variable requires 'name'")
    value = params.get("value")
    rt.vars[str(name)] = value
    return {"name": str(name), "value": value}


def h_log(rt: "ExecutionContext", params: dict) -> dict:
    message = params.get("message", "")
    rt.log("info", str(message))
    return {}


def h_screenshot(rt: "ExecutionContext", params: dict) -> dict:
    frame = rt.capture.grab(_region(params))
    h, w = frame.shape[:2]
    save_as = params.get("save_as")
    image_path: Optional[str] = None
    if save_as:
        image_path = _save_png(frame, str(save_as))
    return {"image_path": image_path, "width": w, "height": h}


def _save_png(frame, save_as: str) -> str:
    from pathlib import Path

    p = Path(save_as)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(p), frame):
        raise IOError(f"failed to write screenshot to {p}")
    return str(p)


def h_find_image(rt: "ExecutionContext", params: dict) -> dict:
    return _find_image_on_screen(rt, params)


def h_find_text(rt: "ExecutionContext", params: dict) -> dict:
    return _find_text_on_screen(rt, params)


def _click_point(rt: "ExecutionContext", params: dict) -> tuple[int, int]:
    target = params.get("target", "point")
    if target == "point":
        return int(float(params.get("x", 0))), int(float(params.get("y", 0)))
    if target == "last_found":
        return _last_found_point(rt)
    if target == "image":
        match = _find_image_on_screen(rt, params)
        if not match["found"]:
            raise ValueError("click target image not found on screen")
        return match["center"]["x"], match["center"]["y"]
    if target == "text":
        match = _find_text_on_screen(rt, params)
        if not match["found"]:
            raise ValueError("click target text not found on screen")
        first = match["first"]
        return first["center"]["x"], first["center"]["y"]
    raise ValueError(f"action.click: unknown target {target!r}")


def h_click(rt: "ExecutionContext", params: dict) -> dict:
    x, y = _click_point(rt, params)
    button = str(params.get("button", "left"))
    clicks = int(float(params.get("clicks", 1)))
    if rt.dry_run:
        rt.log("info", f"DRY-RUN click x={x} y={y} button={button} clicks={clicks}")
        return {"x": x, "y": y}
    return inp.click(x, y, button=button, clicks=clicks)


def h_move(rt: "ExecutionContext", params: dict) -> dict:
    x = int(float(params.get("x", 0)))
    y = int(float(params.get("y", 0)))
    duration_ms = int(float(params.get("duration_ms", 0)))
    if rt.dry_run:
        rt.log("info", f"DRY-RUN move x={x} y={y}")
        return {}
    inp.move(x, y, duration_ms=duration_ms)
    return {}


def _point_of(rt: "ExecutionContext", spec: Any) -> tuple[int, int]:
    if isinstance(spec, str) and spec == "last_found":
        return _last_found_point(rt)
    if isinstance(spec, dict) and "x" in spec and "y" in spec:
        return int(float(spec["x"])), int(float(spec["y"]))
    raise ValueError(f"invalid point spec: {spec!r}")


def h_drag(rt: "ExecutionContext", params: dict) -> dict:
    x1, y1 = _point_of(rt, params.get("from"))
    x2, y2 = _point_of(rt, params.get("to"))
    duration_ms = int(float(params.get("duration_ms", 300)))
    button = str(params.get("button", "left"))
    if rt.dry_run:
        rt.log("info", f"DRY-RUN drag ({x1},{y1}) -> ({x2},{y2})")
        return {}
    inp.drag(x1, y1, x2, y2, duration_ms=duration_ms, button=button)
    return {}


def h_type_text(rt: "ExecutionContext", params: dict) -> dict:
    text = params.get("text", "")
    interval_ms = int(float(params.get("interval_ms", 0)))
    if rt.dry_run:
        rt.log("info", f"DRY-RUN type_text len={len(str(text))}")
        return {}
    inp.type_text(str(text), interval_ms=interval_ms)
    return {}


def h_press_key(rt: "ExecutionContext", params: dict) -> dict:
    keys = params.get("keys")
    if keys is None:
        raise ValueError("action.press_key requires 'keys'")
    if rt.dry_run:
        rt.log("info", f"DRY-RUN press_key keys={keys}")
        return {}
    inp.press_key(keys)
    return {}


def h_focus_window(rt: "ExecutionContext", params: dict) -> dict:
    title = params.get("title")
    if not title:
        raise ValueError("action.focus_window requires 'title'")
    if rt.dry_run:
        # dry-run still searches the window list but never focuses
        from .. import input as _inp

        found = None
        for win in _inp.list_windows():
            if str(title).lower() in win["title"].lower():
                found = win
                break
        rt.log("info", f"DRY-RUN focus_window title={title!r} found={bool(found)}")
        return {"found": bool(found),
                "rect": found["rect"] if found else None,
                "title": found["title"] if found else None}
    result = inp.focus_window(str(title))
    return {"found": result["found"], "rect": result.get("rect"), "title": result.get("title")}


def h_launch(rt: "ExecutionContext", params: dict) -> dict:
    command = params.get("command")
    if not command:
        raise ValueError("action.launch requires 'command'")
    wait_ms = int(float(params.get("wait_ms", 0)))
    if rt.dry_run:
        rt.log("info", f"DRY-RUN launch command={command!r}")
        if wait_ms:
            time.sleep(wait_ms / 1000.0)
        return {"pid": None}
    return inp.launch(str(command), wait_ms=wait_ms)


class ScriptContext:
    """Read-mostly accessor exposed to ``script.python`` code as ``ctx``."""

    def __init__(self, rt: "ExecutionContext") -> None:
        self._rt = rt

    def output(self, node_id: str) -> dict:
        entry = self._rt.outputs.get(node_id)
        if entry is None:
            raise KeyError(f"no output for node {node_id!r}")
        return entry.get("output", {})

    def var(self, name: str, default: Any = None) -> Any:
        return self._rt.vars.get(name, default)

    @property
    def vars(self) -> dict:
        return dict(self._rt.vars)

    @property
    def item(self) -> Any:
        return self._rt.item

    def set_var(self, name: str, value: Any) -> None:
        self._rt.vars[name] = value

    def log(self, message: str) -> None:
        self._rt.log("info", str(message))


def h_script_python(rt: "ExecutionContext", params: dict) -> dict:
    code = params.get("code")
    if not code:
        raise ValueError("script.python requires 'code'")
    namespace: dict[str, Any] = {"ctx": ScriptContext(rt), "result": None}
    exec(str(code), namespace)  # noqa: S102 - intentional user scripting sandbox
    return {"result": namespace.get("result")}


def h_save_screenshot(rt: "ExecutionContext", params: dict) -> dict:
    path = params.get("path")
    if not path:
        raise ValueError("output.save_screenshot requires 'path'")
    frame = rt.capture.grab(_region(params))
    return {"path": _save_png(frame, str(path))}


# ---------------------------------------------------------------- registry

_BRANCH_FOUND = lambda out: "found" if out.get("found") else "not_found"  # noqa: E731


class NodeSpec:
    def __init__(
        self,
        type: str,
        handler: Optional[Handler],
        branch: Optional[Callable[[dict], str]] = None,
        is_loop: bool = False,
    ) -> None:
        self.type = type
        self.handler = handler
        self.branch = branch
        self.is_loop = is_loop


REGISTRY: dict[str, NodeSpec] = {
    spec.type: spec
    for spec in [
        NodeSpec("trigger.manual", h_trigger_manual),
        NodeSpec("input.data_table", h_data_table),
        NodeSpec("control.loop", None, is_loop=True),  # executed specially
        NodeSpec("control.condition", h_condition, branch=lambda o: "true" if o.get("result") else "false"),
        NodeSpec("control.wait", h_wait),
        NodeSpec(
            "control.wait_for",
            h_wait_for,
            branch=lambda o: "found" if o.get("found") else "timeout",
        ),
        NodeSpec("control.set_variable", h_set_variable),
        NodeSpec("control.log", h_log),
        NodeSpec("capture.screenshot", h_screenshot),
        NodeSpec("vision.find_image", h_find_image, branch=_BRANCH_FOUND),
        NodeSpec("vision.find_text", h_find_text, branch=_BRANCH_FOUND),
        NodeSpec("action.click", h_click),
        NodeSpec("action.move", h_move),
        NodeSpec("action.drag", h_drag),
        NodeSpec("action.type_text", h_type_text),
        NodeSpec("action.press_key", h_press_key),
        NodeSpec("action.focus_window", h_focus_window, branch=_BRANCH_FOUND),
        NodeSpec("action.launch", h_launch),
        NodeSpec("script.python", h_script_python),
        NodeSpec("output.save_screenshot", h_save_screenshot),
    ]
}


def get_spec(node_type: str) -> NodeSpec:
    spec = REGISTRY.get(node_type)
    if spec is None:
        raise ValueError(f"unknown node type: {node_type!r}")
    return spec


__all__ = ["REGISTRY", "NodeSpec", "RunStopped", "ScriptContext", "get_spec", "evaluate"]
