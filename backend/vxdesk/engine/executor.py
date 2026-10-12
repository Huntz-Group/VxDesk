"""Workflow DAG executor, run state and run persistence.

Execution starts at trigger nodes (in-degree 0 or ``trigger.manual``), follows
edges honoring ``sourceHandle`` branches, resolves ``{{ }}`` templates against
``{node_id: {"output": ...}}`` plus ``vars`` and the current loop ``item``, and
checks a stop event between nodes and inside wait/poll loops (~50 ms slices).
Finished runs are persisted to ``workflows/.runs/<run_id>.json``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..capture import Capture
from ..paths import RUNS_DIR, ensure_dirs
from ..vision import OCREngine, get_ocr_engine
from .nodes import RunStopped, get_spec
from .templating import TemplateError, resolve

logger = logging.getLogger("vxdesk.engine.executor")

EmitFn = Callable[[dict], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ExecutionContext:
    """Mutable state shared by all node handlers of one run."""

    def __init__(
        self,
        *,
        capture: Capture,
        ocr: OCREngine,
        variables: dict,
        inputs: dict,
        outputs: dict[str, dict],
        execution_order: list[str],
        stop_event: threading.Event,
        dry_run: bool,
        emit: EmitFn,
    ) -> None:
        self.capture = capture
        self.ocr = ocr
        self.vars = variables
        self.inputs = inputs
        self.outputs = outputs
        self.execution_order = execution_order
        self.stop_event = stop_event
        self.dry_run = dry_run
        self._emit = emit
        self.current_node_id: Optional[str] = None
        self.item: Any = None

    def log(self, level: str, message: str, node_id: Optional[str] = None) -> None:
        node_id = node_id or self.current_node_id
        logger.info("[%s] %s", node_id or "run", message)
        self._emit({"event": "log", "node_id": node_id, "level": level, "message": message})

    def last_found_point(self) -> Optional[tuple[int, int]]:
        """Center of the most recent successful find in execution order."""
        for node_id in reversed(self.execution_order):
            output = (self.outputs.get(node_id) or {}).get("output") or {}
            if output.get("found") and isinstance(output.get("center"), dict):
                return int(output["center"]["x"]), int(output["center"]["y"])
            first = output.get("first")
            if output.get("found") and isinstance(first, dict) and isinstance(
                first.get("center"), dict
            ):
                return int(first["center"]["x"]), int(first["center"]["y"])
        return None

    def template_context(self) -> dict:
        return {**self.outputs, "vars": self.vars, "item": self.item}


class Run:
    def __init__(self, run_id: str, workflow_id: str, dry_run: bool) -> None:
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.dry_run = dry_run
        self.status = "running"
        self.started_at = _now_iso()
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None
        self.node_states: dict[str, dict] = {}
        self.stop_event = threading.Event()
        self.done_event = threading.Event()  # set once persisted/final
        self.events: list[dict] = []
        self.lock = threading.RLock()

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "run_id": self.run_id,
                "workflow_id": self.workflow_id,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "dry_run": self.dry_run,
                "node_states": dict(self.node_states),
            }

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class WorkflowEngine:
    """Executes one workflow graph against a capture/ocr runtime."""

    def __init__(self, capture: Optional[Capture] = None, ocr: Optional[OCREngine] = None) -> None:
        self.capture = capture or Capture()
        self.ocr = ocr or get_ocr_engine()

    # -- public ---------------------------------------------------------

    def execute(
        self,
        run: Run,
        workflow: dict,
        inputs: Optional[dict] = None,
        emit: Optional[EmitFn] = None,
    ) -> Run:
        """Run ``workflow`` synchronously, updating ``run`` in place."""
        emit = emit or (lambda event: None)
        nodes = {n["id"]: n for n in workflow.get("nodes", [])}
        edges = workflow.get("edges", [])
        variables = dict(workflow.get("variables", {}) or {})
        outputs: dict[str, dict] = {}
        order: list[str] = []

        ctx = ExecutionContext(
            capture=self.capture,
            ocr=self.ocr,
            variables=variables,
            inputs=dict(inputs or {}),
            outputs=outputs,
            execution_order=order,
            stop_event=run.stop_event,
            dry_run=run.dry_run,
            emit=emit,
        )
        self._ctx = ctx

        try:
            visited: set[str] = set()
            for start in self._start_nodes(workflow):
                if run.stop_event.is_set():
                    raise RunStopped()
                if start in visited:
                    continue
                visited.add(start)
                self._execute_node(nodes, edges, start, ctx, run, emit, visited)
            if run.stop_event.is_set():
                raise RunStopped()
            run.status = "success"
        except RunStopped:
            run.status = "stopped"
            ctx.log("info", "run stopped by user")
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.error("run %s failed: %s\n%s", run.run_id, exc, traceback.format_exc())
        finally:
            run.finished_at = _now_iso()
        return run

    # -- graph walking ----------------------------------------------------

    @staticmethod
    def _start_nodes(workflow: dict) -> list[str]:
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])
        has_incoming = {e["target"] for e in edges}
        starts = [
            n["id"]
            for n in nodes
            if n["id"] not in has_incoming or n.get("type") == "trigger.manual"
        ]
        return starts

    @staticmethod
    def _successors(edges: list[dict], node_id: str, handle: str) -> list[str]:
        """Targets of ``node_id`` for the taken branch.

        Branch edges fire when their ``sourceHandle`` matches the taken branch;
        ``default`` edges are plain sequence and fire on every outcome.
        """
        out = []
        for edge in edges:
            if edge.get("source") != node_id:
                continue
            edge_handle = edge.get("sourceHandle") or "default"
            if edge_handle in ("default", "") or edge_handle == handle:
                out.append(edge["target"])
        return out

    def _follow(
        self,
        nodes: dict[str, dict],
        edges: list[dict],
        node_id: str,
        handle: str,
        ctx: ExecutionContext,
        run: Run,
        emit: EmitFn,
        visited: set[str],
    ) -> None:
        for target in self._successors(edges, node_id, handle):
            if target in visited or target not in nodes:
                continue
            visited.add(target)
            self._execute_node(nodes, edges, target, ctx, run, emit, visited)

    def _execute_node(
        self,
        nodes: dict[str, dict],
        edges: list[dict],
        node_id: str,
        ctx: ExecutionContext,
        run: Run,
        emit: EmitFn,
        visited: set[str],
    ) -> None:
        if run.stop_event.is_set():
            raise RunStopped()
        node = nodes[node_id]
        node_type = node.get("type", "")
        name = node.get("name") or node_id

        def set_state(status: str, output: Any = None, duration_ms: float = 0, error=None):
            with run.lock:
                run.node_states[node_id] = {
                    "status": status,
                    "output": output,
                    "duration_ms": round(duration_ms, 2),
                    "error": error,
                }

        if node.get("disabled"):
            set_state("skipped")
            emit({"event": "node_finished", "node_id": node_id, "status": "skipped",
                  "output": None, "duration_ms": 0})
            # pass-through: default successors still run
            self._follow(nodes, edges, node_id, "default", ctx, run, emit, visited)
            return

        try:
            spec = get_spec(node_type)
        except ValueError as exc:
            set_state("failed", error=str(exc))
            raise

        emit({"event": "node_started", "node_id": node_id, "name": name})
        prev_node = ctx.current_node_id
        ctx.current_node_id = node_id

        started = time.perf_counter()
        try:
            if spec.is_loop:
                output = self._execute_loop(nodes, edges, node, ctx, run, emit)
                branch = "done"
            else:
                params = resolve(node.get("params", {}) or {}, ctx.template_context())
                output = spec.handler(ctx, params) if spec.handler else {}
                output = output or {}
                branch = spec.branch(output) if spec.branch else "default"

            duration = (time.perf_counter() - started) * 1000
            ctx.outputs[node_id] = {"output": output}
            ctx.execution_order.append(node_id)
            set_state("success", output=_json_safe(output), duration_ms=duration)
            emit({"event": "node_finished", "node_id": node_id, "status": "success",
                  "output": _json_safe(output), "duration_ms": round(duration, 2)})
        except RunStopped:
            duration = (time.perf_counter() - started) * 1000
            set_state("stopped", duration_ms=duration)
            emit({"event": "node_finished", "node_id": node_id, "status": "stopped",
                  "output": None, "duration_ms": round(duration, 2)})
            raise
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            set_state("failed", duration_ms=duration, error=str(exc))
            emit({"event": "node_finished", "node_id": node_id, "status": "failed",
                  "output": None, "duration_ms": round(duration, 2)})
            ctx.log("error", f"node {name} failed: {exc}")
            raise
        finally:
            ctx.current_node_id = prev_node

        self._follow(nodes, edges, node_id, branch, ctx, run, emit, visited)

    def _execute_loop(
        self,
        nodes: dict[str, dict],
        edges: list[dict],
        node: dict,
        ctx: ExecutionContext,
        run: Run,
        emit: EmitFn,
    ) -> dict:
        node_id = node["id"]
        params = resolve(node.get("params", {}) or {}, ctx.template_context())
        mode = params.get("mode", "count")
        max_iterations = int(float(params.get("max_iterations", 1000)))
        max_iterations = max(1, min(max_iterations, 100000))

        if mode == "count":
            count = int(float(params.get("count", 1)))
            items: list[Any] = [{"index": i} for i in range(max(0, count))]
        elif mode == "rows":
            source = params.get("source")
            if not source:
                raise ValueError("control.loop (rows mode) requires 'source' node id")
            source_output = (ctx.outputs.get(str(source)) or {}).get("output")
            if not source_output or "rows" not in source_output:
                raise ValueError(
                    f"control.loop source {source!r} has no 'rows' output "
                    "(expected an input.data_table node executed earlier)"
                )
            items = list(source_output["rows"])
        else:
            raise ValueError(f"control.loop: unknown mode {mode!r}")

        if len(items) > max_iterations:
            ctx.log("warning",
                    f"loop capped at max_iterations={max_iterations} (was {len(items)})")
            items = items[:max_iterations]

        last_output: dict = {"index": -1, "item": None, "iterations": 0}
        prev_item = ctx.item
        try:
            for i, raw_item in enumerate(items):
                if run.stop_event.is_set():
                    raise RunStopped()
                item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}
                if mode == "count":
                    item = {**item, "index": i}
                ctx.item = item
                last_output = {"index": i, "item": item, "iterations": i + 1}
                ctx.outputs[node_id] = {"output": last_output}
                # fresh visited set per iteration: body nodes re-run each pass,
                # but a converging node inside the body still runs once per pass
                self._follow(nodes, edges, node_id, "body", ctx, run, emit, set())
        finally:
            ctx.item = prev_item
        return last_output


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


class RunManager:
    """Owns run lifecycle: background threads, stop requests, persistence."""

    def __init__(self, engine: Optional[WorkflowEngine] = None) -> None:
        ensure_dirs()
        self.engine = engine or WorkflowEngine()
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._listeners: dict[str, list[Callable[[dict], None]]] = {}

    # -- listeners (WS fanout) -------------------------------------------

    def add_listener(self, run_id: str, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._listeners.setdefault(run_id, []).append(fn)

    def remove_listener(self, run_id: str, fn: Callable[[dict], None]) -> None:
        with self._lock:
            listeners = self._listeners.get(run_id, [])
            if fn in listeners:
                listeners.remove(fn)

    def _emit(self, run: Run, event: dict) -> None:
        event = {**event, "run_id": run.run_id}
        with run.lock:
            run.events.append(event)
        with self._lock:
            listeners = list(self._listeners.get(run.run_id, []))
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:
                logger.debug("listener error: %s", exc)

    # -- lifecycle ----------------------------------------------------------

    def start(self, workflow: dict, inputs: Optional[dict] = None, dry_run: bool = False) -> Run:
        run = Run(_new_id("run"), workflow.get("id", "unknown"), dry_run)
        with self._lock:
            self._runs[run.run_id] = run

        def _worker() -> None:
            try:
                self._emit(run, {"event": "run_started"})
                self.engine.execute(run, workflow, inputs=inputs,
                                    emit=lambda e: self._emit(run, e))
                self._emit(run, {"event": "run_finished", "status": run.status,
                                 "error": run.error})
                self._persist(run)
            finally:
                run.done_event.set()

        thread = threading.Thread(target=_worker, name=f"vxdesk-run-{run.run_id}", daemon=True)
        thread.start()
        return run

    def stop(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None:
            return False
        run.stop_event.set()
        return True

    def get(self, run_id: str) -> Optional[Run]:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            run = self._load_persisted(run_id)
        return run

    def runs_for(self, workflow_id: str) -> list[dict]:
        seen: dict[str, dict] = {}
        for path in sorted(RUNS_DIR.glob("run_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("workflow_id") == workflow_id:
                seen[data["run_id"]] = {
                    k: data.get(k)
                    for k in ("run_id", "workflow_id", "status", "started_at", "finished_at", "error")
                }
        with self._lock:
            for run in self._runs.values():
                if run.workflow_id == workflow_id:
                    seen[run.run_id] = run.summary()
        return sorted(seen.values(), key=lambda r: r.get("started_at") or "", reverse=True)

    # -- persistence ---------------------------------------------------------

    def _persist(self, run: Run) -> None:
        try:
            ensure_dirs()
            path = RUNS_DIR / f"{run.run_id}.json"
            path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("failed to persist run %s: %s", run.run_id, exc)

    def _load_persisted(self, run_id: str) -> Optional[Run]:
        path = RUNS_DIR / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        run = Run(run_id, data.get("workflow_id", "unknown"), bool(data.get("dry_run")))
        run.status = data.get("status", "failed")
        run.started_at = data.get("started_at", run.started_at)
        run.finished_at = data.get("finished_at")
        run.error = data.get("error")
        run.node_states = data.get("node_states", {})
        with self._lock:
            self._runs[run_id] = run
        return run
