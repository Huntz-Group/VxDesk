"""Static workflow validation used by ``POST /api/workflows/{id}/validate``."""

from __future__ import annotations

from typing import Any

from .catalog import CATALOG
from .nodes import REGISTRY

_REQUIRED_PARAMS: dict[str, list[str]] = {
    entry["type"]: [p["name"] for p in entry["params"] if p.get("required")]
    for entry in CATALOG
}


def validate_workflow(workflow: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    nodes: list[dict] = workflow.get("nodes", []) or []
    edges: list[dict] = workflow.get("edges", []) or []

    ids: list[str] = []
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("a node is missing its 'id'")
            continue
        if node_id in ids:
            errors.append(f"duplicate node id: {node_id}")
        ids.append(node_id)

        node_type = node.get("type", "")
        if node_type not in REGISTRY:
            errors.append(f"node {node_id}: unknown type {node_type!r}")
            continue
        params = node.get("params", {}) or {}
        for required in _REQUIRED_PARAMS.get(node_type, []):
            value = params.get(required)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"node {node_id} ({node_type}): missing required param '{required}'")
        if node_type == "control.loop":
            mode = params.get("mode", "count")
            if mode not in ("count", "rows"):
                errors.append(f"node {node_id}: loop mode must be 'count' or 'rows'")
            if mode == "rows" and not params.get("source"):
                errors.append(f"node {node_id}: rows mode requires 'source' (data-table node id)")

    id_set = set(ids)
    for edge in edges:
        if edge.get("source") not in id_set:
            errors.append(f"edge {edge.get('id', '?')}: unknown source {edge.get('source')!r}")
        if edge.get("target") not in id_set:
            errors.append(f"edge {edge.get('id', '?')}: unknown target {edge.get('target')!r}")

    if not any(n.get("type") == "trigger.manual" for n in nodes):
        warnings.append("workflow has no trigger.manual node")

    # cycle detection (ignoring loop body back-edges is not needed: body edges
    # point away from the loop node; any cycle through plain edges is an error)
    cycle = _find_cycle(nodes, edges)
    if cycle:
        errors.append(f"graph contains a cycle: {' -> '.join(cycle)}")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _find_cycle(nodes: list[dict], edges: list[dict]) -> list[str]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.get("source"), []).append(edge.get("target"))

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n.get("id"): WHITE for n in nodes}
    stack: list[str] = []
    cycle: list[str] = []

    def dfs(node_id: Any) -> bool:
        color[node_id] = GRAY
        stack.append(node_id)
        for nxt in adjacency.get(node_id, []):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                cycle.extend(stack[stack.index(nxt):] + [nxt])
                return True
            if color[nxt] == WHITE and dfs(nxt):
                return True
        stack.pop()
        color[node_id] = BLACK
        return False

    for node in nodes:
        node_id = node.get("id")
        if node_id and color.get(node_id) == WHITE and dfs(node_id):
            return cycle
    return []
