"""Engine tests: DAG order, branches, loops, stop, disabled nodes, dry-run."""

from __future__ import annotations

import threading
import time

import pytest

from vxdesk.engine.executor import Run, RunManager, WorkflowEngine


@pytest.fixture()
def engine(virtual_capture) -> WorkflowEngine:
    return WorkflowEngine(capture=virtual_capture)


def run_sync(engine: WorkflowEngine, workflow: dict, dry_run: bool = True,
             events: list | None = None) -> Run:
    run = Run("run_test", workflow.get("id", "wf_test"), dry_run)
    emit = (events.append if events is not None else (lambda e: None))
    return engine.execute(run, workflow, emit=emit)


def node(node_id, type_, params=None, **kw):
    return {"id": node_id, "type": type_, "name": kw.pop("name", node_id),
            "position": {"x": 0, "y": 0}, "params": params or {}, **kw}


def edge(source, target, handle="default"):
    return {"id": f"e_{source}_{target}_{handle}", "source": source,
            "target": target, "sourceHandle": handle}


# ---------------------------------------------------------------- DAG order


def test_dag_execution_order(engine):
    events: list[dict] = []
    wf = {
        "id": "wf_order",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.set_variable", {"name": "a", "value": "1"}),
            node("n3", "control.set_variable", {"name": "b", "value": "{{ vars.a }}2"}),
            node("n4", "control.log", {"message": "b={{ vars.b }}"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3"), edge("n3", "n4")],
        "variables": {},
    }
    run = run_sync(engine, wf, events=events)
    assert run.status == "success"
    assert list(run.node_states) == ["n1", "n2", "n3", "n4"]
    assert run.node_states["n3"]["output"] == {"name": "b", "value": "12"}
    log_events = [e for e in events if e["event"] == "log"]
    assert any("b=12" in e["message"] for e in log_events)


# ---------------------------------------------------------------- conditions


@pytest.mark.parametrize("threshold, expected_branch", [(0.5, "true"), (1.5, "false")])
def test_condition_branches(engine, template_asset, threshold, expected_branch):
    wf = {
        "id": "wf_cond",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "vision.find_image",
                 {"template": template_asset, "threshold": 0.9}),
            node("n3", "control.condition",
                 {"expression": f"{{{{ n2.output.score }}}} > {threshold}"}),
            node("n4t", "control.set_variable", {"name": "branch", "value": "taken-true"}),
            node("n4f", "control.set_variable", {"name": "branch", "value": "taken-false"}),
        ],
        "edges": [
            edge("n1", "n2"), edge("n2", "n3"),
            edge("n3", "n4t", "true"), edge("n3", "n4f", "false"),
        ],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n2"]["output"]["found"] is True
    hit = "n4t" if expected_branch == "true" else "n4f"
    miss = "n4f" if expected_branch == "true" else "n4t"
    assert run.node_states[hit]["status"] == "success"
    assert miss not in run.node_states


def test_find_image_branch_handles(engine, template_asset):
    wf = {
        "id": "wf_fibranch",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "vision.find_image", {"template": template_asset, "threshold": 1.01}),
            node("n3", "control.log", {"message": "not found branch"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3", "not_found")],
        "variables": {},
    }
    # threshold > 1 is impossible, so the not_found branch must fire
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n2"]["output"]["found"] is False
    assert run.node_states["n3"]["status"] == "success"


# ---------------------------------------------------------------- loops


def test_loop_over_csv_rows(engine):
    csv_text = "name,qty\napple,2\nbanana,5\ncherry,9"
    wf = {
        "id": "wf_loop",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "input.data_table", {"csv_text": csv_text}),
            node("n3", "control.loop", {"mode": "rows", "source": "n2"}),
            node("n4", "control.set_variable",
                 {"name": "row_{{ n3.output.index }}", "value": "{{ item.name }}={{ item.qty }}"}),
            node("n5", "control.log", {"message": "done after loop"}),
        ],
        "edges": [
            edge("n1", "n2"), edge("n2", "n3"),
            edge("n3", "n4", "body"), edge("n3", "n5", "done"),
        ],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n3"]["output"]["iterations"] == 3
    assert run.node_states["n3"]["output"]["item"] == {"name": "cherry", "qty": "9"}
    assert run.node_states["n5"]["status"] == "success"


def test_loop_count_mode_and_item_index(engine):
    wf = {
        "id": "wf_loop_count",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.loop", {"mode": "count", "count": 3}),
            node("n3", "control.set_variable",
                 {"name": "i_{{ item.index }}", "value": "{{ item.index }}"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3", "body")],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n2"]["output"]["iterations"] == 3
    # variable names were template-resolved per iteration
    assert run.node_states["n3"]["output"]["name"] == "i_2"


def test_loop_max_iterations_cap(engine):
    wf = {
        "id": "wf_loop_cap",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.loop",
                 {"mode": "count", "count": 5000, "max_iterations": 5}),
            node("n3", "control.log", {"message": "iter"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3", "body")],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n2"]["output"]["iterations"] == 5


def test_loop_requires_rows_source(engine):
    wf = {
        "id": "wf_loop_bad",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.loop", {"mode": "rows"}),
        ],
        "edges": [edge("n1", "n2")],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "failed"
    assert run.node_states["n2"]["status"] == "failed"


# ---------------------------------------------------------------- stop / disabled / dry-run


def test_stop_mid_run(engine):
    wf = {
        "id": "wf_stop",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.wait", {"ms": 60000}),
            node("n3", "control.log", {"message": "should never run"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3")],
        "variables": {},
    }
    manager = RunManager(engine)
    run = manager.start(wf, dry_run=True)
    time.sleep(0.2)
    started = time.perf_counter()
    assert manager.stop(run.run_id) is True
    deadline = time.time() + 5
    while run.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert run.status == "stopped"
    assert elapsed_ms < 2000  # stop honored well within bounds (~200 ms target)
    assert run.node_states["n2"]["status"] == "stopped"
    assert "n3" not in run.node_states


def test_disabled_nodes_skipped(engine):
    wf = {
        "id": "wf_disabled",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.set_variable", {"name": "x", "value": "1"}, disabled=True),
            node("n3", "control.log", {"message": "after disabled"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3")],
        "variables": {},
    }
    run = run_sync(engine, wf)
    assert run.status == "success"
    assert run.node_states["n2"]["status"] == "skipped"
    assert run.node_states["n3"]["status"] == "success"


def test_dry_run_makes_no_input_calls(engine, monkeypatch):
    calls: list[tuple] = []

    def spy(name):
        def fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {"x": args[0] if args else 0, "y": args[1] if len(args) > 1 else 0}
        return fn

    monkeypatch.setattr("vxdesk.input.click", spy("click"))
    monkeypatch.setattr("vxdesk.input.type_text", spy("type_text"))
    monkeypatch.setattr("vxdesk.input.press_key", spy("press_key"))
    # nodes.py imported the module, so patching module attributes is enough

    wf = {
        "id": "wf_dry",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "action.click", {"target": "point", "x": 10, "y": 20}),
            node("n3", "action.type_text", {"text": "hello"}),
            node("n4", "action.press_key", {"keys": ["ctrl", "s"]}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3"), edge("n3", "n4")],
        "variables": {},
    }
    events: list[dict] = []
    run = run_sync(engine, wf, dry_run=True, events=events)
    assert run.status == "success"
    assert calls == []  # zero real input calls in dry-run
    assert run.node_states["n2"]["output"] == {"x": 10, "y": 20}


def test_script_python_node(engine):
    wf = {
        "id": "wf_script",
        "nodes": [
            node("n1", "trigger.manual"),
            node("n2", "control.set_variable", {"name": "base", "value": 40}),
            node("n3", "script.python",
                 {"code": "result = ctx.var('base') + 2\nctx.set_var('done', True)"}),
            node("n4", "control.log", {"message": "result={{ n3.output.result }}"}),
        ],
        "edges": [edge("n1", "n2"), edge("n2", "n3"), edge("n3", "n4")],
        "variables": {},
    }
    events: list[dict] = []
    run = run_sync(engine, wf, events=events)
    assert run.status == "success"
    assert run.node_states["n3"]["output"]["result"] == 42
    assert any("result=42" in e.get("message", "") for e in events
               if e["event"] == "log")


def test_run_persisted_to_disk(engine, tmp_path):
    from vxdesk.paths import RUNS_DIR

    manager = RunManager(engine)
    wf = {
        "id": "wf_persist",
        "nodes": [node("n1", "trigger.manual"),
                  node("n2", "control.log", {"message": "hi"})],
        "edges": [edge("n1", "n2")],
        "variables": {},
    }
    run = manager.start(wf, dry_run=True)
    assert run.done_event.wait(5)
    assert run.status == "success"
    path = RUNS_DIR / f"{run.run_id}.json"
    assert path.exists()
    path.unlink()
