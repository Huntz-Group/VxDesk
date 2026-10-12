"""Workflow persistence: plain JSON files in ``workflows/``."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import WORKFLOWS_DIR, ensure_dirs

logger = logging.getLogger("vxdesk.workflows")

_lock = threading.Lock()
_ID_SAFE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def new_workflow_id() -> str:
    return f"wf_{uuid.uuid4().hex[:12]}"


def workflow_path(workflow_id: str) -> Path:
    if not _ID_SAFE.match(workflow_id):
        raise ValueError(f"invalid workflow id: {workflow_id!r}")
    return WORKFLOWS_DIR / f"{workflow_id}.json"


def list_workflows() -> list[dict]:
    ensure_dirs()
    out = []
    for path in sorted(WORKFLOWS_DIR.glob("wf_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("skipping unreadable workflow %s: %s", path, exc)
            continue
        out.append(
            {
                "id": data.get("id", path.stem),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "updated_at": data.get("updated_at"),
                "node_count": len(data.get("nodes", []) or []),
            }
        )
    out.sort(key=lambda w: w.get("updated_at") or "", reverse=True)
    return out


def create_workflow(name: str, description: str = "") -> dict:
    ensure_dirs()
    workflow = {
        "id": new_workflow_id(),
        "name": name,
        "description": description,
        "nodes": [
            {
                "id": "n1",
                "type": "trigger.manual",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "params": {},
                "disabled": False,
            }
        ],
        "edges": [],
        "variables": {},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    save_workflow(workflow["id"], workflow)
    return workflow


def load_workflow(workflow_id: str) -> dict:
    path = workflow_path(workflow_id)
    if not path.exists():
        raise FileNotFoundError(f"workflow not found: {workflow_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_workflow(workflow_id: str, workflow: dict) -> dict:
    ensure_dirs()
    workflow = dict(workflow)
    workflow["id"] = workflow_id
    workflow.setdefault("nodes", [])
    workflow.setdefault("edges", [])
    workflow.setdefault("variables", {})
    workflow.setdefault("description", "")
    workflow.setdefault("name", workflow_id)
    workflow["updated_at"] = _now_iso()
    path = workflow_path(workflow_id)
    with _lock:
        path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    return workflow


def delete_workflow(workflow_id: str) -> bool:
    path = workflow_path(workflow_id)
    if not path.exists():
        raise FileNotFoundError(f"workflow not found: {workflow_id}")
    path.unlink()
    return True


def find_workflow_id(id_or_name: str) -> Optional[str]:
    """Resolve a workflow by exact id, else by exact name."""
    try:
        if workflow_path(id_or_name).exists():
            return id_or_name
    except ValueError:
        pass
    for summary in list_workflows():
        if summary["name"] == id_or_name:
            return summary["id"]
    return None
