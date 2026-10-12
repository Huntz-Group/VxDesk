"""Deterministic converter: recorded events -> validated workflow JSON.

Implements all 7 conversion rules from ``docs/recorder.md``:

1. gap > 750 ms between events -> ``control.wait`` (capped at 5000 ms)
2. window change -> ``action.focus_window`` (one focus per distinct title in a row)
3. click -> smart: ``vision.find_image`` (0.85) + ``action.click`` (last_found,
   raw x/y kept as fallback); coordinates: single ``action.click`` (point)
4. char runs (gaps < 800 ms, same window) -> one ``action.type_text`` (interval 30)
5. key -> ``action.press_key`` ("enter" or ["ctrl", "s"] conventions)
6. leading waits/focuses kept, trailing wait dropped
7. plain-language node names (truncated)
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import cv2
import numpy as np

from ..assets import TEMPLATES_DIR, ensure_dirs
from ..workflows_store import new_workflow_id

logger = logging.getLogger("vxdesk.recorder.convert")

GAP_WAIT_S = 0.75
WAIT_CAP_MS = 5000
CHAR_RUN_GAP_S = 0.8
CHAR_INTERVAL_MS = 30
SMART_THRESHOLD = 0.85
LAYOUT_X_STEP = 220
LAYOUT_Y = 120

TemplateWriter = Callable[[str, int, np.ndarray], str]


def default_template_writer(session_id: str, n: int, crop: np.ndarray) -> str:
    """Save a click crop to ``assets/templates/rec_<session>_<n>.png``."""
    ensure_dirs()
    name = f"rec_{session_id}_{n}.png"
    path = TEMPLATES_DIR / name
    if not cv2.imwrite(str(path), crop):
        raise IOError(f"could not save click template {path}")
    return name


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _key_display(combo: str) -> str:
    """ctrl+s -> Ctrl+S, enter -> Enter."""
    parts = []
    for part in combo.split("+"):
        parts.append(part.upper() if len(part) == 1 else part.capitalize())
    return "+".join(parts)


class _StepBuilder:
    def __init__(self, mode: str, session_id: str,
                 template_writer: Optional[TemplateWriter]) -> None:
        if mode not in ("smart", "coordinates"):
            raise ValueError(f"mode must be 'smart' or 'coordinates', got {mode!r}")
        self.mode = mode
        self.session_id = session_id
        self.template_writer = template_writer
        self.steps: list[dict] = []
        self.click_n = 0
        self._node_n = 1  # n1 is the trigger

    # -- node factory ------------------------------------------------------

    def _add(self, type_: str, name: str, params: dict) -> dict:
        self._node_n += 1
        node = {
            "id": f"n{self._node_n}",
            "type": type_,
            "name": name,
            "position": {"x": (self._node_n - 1) * LAYOUT_X_STEP, "y": LAYOUT_Y},
            "params": params,
            "disabled": False,
        }
        self.steps.append(node)
        return node

    def add_wait(self, gap_s: float) -> None:
        ms = min(WAIT_CAP_MS, int(round(gap_s * 1000)))
        label = f"{ms / 1000:.1f}".rstrip("0").rstrip(".")
        self._add("control.wait", f"Wait {label}s", {"ms": ms})

    def add_focus(self, title: str) -> None:
        self._add("action.focus_window", f"Focus “{_truncate(title, 24)}”",
                  {"title": title})

    def add_click(self, event: dict) -> None:
        x, y = int(event["x"]), int(event["y"])
        button = event.get("button", "left")
        crop = event.get("_crop")
        if self.mode == "smart" and isinstance(crop, np.ndarray) and crop.size:
            self.click_n += 1
            if self.template_writer is not None:
                template = self.template_writer(self.session_id, self.click_n, crop)
            else:  # preview mode: same name, nothing saved
                template = f"rec_{self.session_id}_{self.click_n}.png"
            self._add("vision.find_image", f"Find click target at ({x}, {y})",
                      {"template": template, "threshold": SMART_THRESHOLD})
            self._add("action.click", f"Click at ({x}, {y})",
                      {"target": "last_found", "x": x, "y": y, "button": button})
        else:
            self._add("action.click", f"Click at ({x}, {y})",
                      {"target": "point", "x": x, "y": y, "button": button})

    def add_type(self, text: str) -> None:
        self._add("action.type_text", f"Type “{_truncate(text, 10)}”",
                  {"text": text, "interval_ms": CHAR_INTERVAL_MS})

    def add_key(self, combo: str) -> None:
        keys: object = combo if "+" not in combo else combo.split("+")
        self._add("action.press_key", f"Press {_key_display(combo)}", {"keys": keys})


def build_steps(
    events: list[dict],
    mode: str = "smart",
    session_id: str = "preview",
    template_writer: Optional[TemplateWriter] = default_template_writer,
) -> list[dict]:
    """Convert normalized events into the ordered list of step nodes."""
    builder = _StepBuilder(mode, session_id, template_writer)
    steps = builder.steps

    chars: list[str] = []
    char_window: Optional[str] = None

    def flush_chars() -> None:
        nonlocal chars, char_window
        if chars:
            builder.add_type("".join(chars))
            chars = []
            char_window = None

    prev_t = 0.0  # recording start: leading gaps become leading waits
    last_window: Optional[str] = None

    for event in events:
        kind = event.get("kind")
        t = float(event.get("t", 0.0))
        window = event.get("window") or (event.get("title") if kind == "window" else None)

        # rule 4: does this char continue the current run? (gap < 800 ms,
        # same window) — continuing runs absorb the gap (no wait inside typing)
        continuing_char_run = bool(
            chars
            and kind == "char"
            and t - prev_t < CHAR_RUN_GAP_S
            and not (window and char_window and window != char_window)
        )
        if chars and not continuing_char_run:
            flush_chars()

        # rule 1: gap -> wait
        if not continuing_char_run and t - prev_t > GAP_WAIT_S:
            builder.add_wait(t - prev_t)

        # rule 2: window change -> focus (deduped per title in a row)
        if window and window != last_window:
            flush_chars()
            builder.add_focus(window)
            last_window = window

        if kind == "click":
            builder.add_click(event)
        elif kind == "char":
            if not chars:
                char_window = window or last_window
            chars.append(str(event.get("text", "")))
        elif kind == "key":
            builder.add_key(str(event.get("key", "")))
        # kind == "window" was fully handled by the window rule

        prev_t = t

    flush_chars()

    # rule 6: trailing wait(s) after the last real action are dropped
    while steps and steps[-1]["type"] == "control.wait":
        steps.pop()

    return steps


def build_workflow(
    events: list[dict],
    name: str,
    mode: str = "smart",
    session_id: Optional[str] = None,
    template_writer: Optional[TemplateWriter] = default_template_writer,
) -> dict:
    """Build the full workflow dict (trigger + sequential default edges)."""
    session_id = session_id or f"{int(time.time())}"
    steps = build_steps(events, mode=mode, session_id=session_id,
                        template_writer=template_writer)
    trigger = {
        "id": "n1",
        "type": "trigger.manual",
        "name": "Start",
        "position": {"x": 0, "y": LAYOUT_Y},
        "params": {},
        "disabled": False,
    }
    nodes = [trigger] + steps
    edges = [
        {
            "id": f"e{i + 1}",
            "source": nodes[i]["id"],
            "target": nodes[i + 1]["id"],
            "sourceHandle": "default",
        }
        for i in range(len(nodes) - 1)
    ]
    return {
        "id": new_workflow_id(),
        "name": name,
        "description": f"Recorded session {session_id} ({mode} mode)",
        "nodes": nodes,
        "edges": edges,
        "variables": {},
    }


def step_preview(events: list[dict], mode: str = "smart",
                 session_id: str = "preview") -> list[dict]:
    """Human-readable step summaries — the same names conversion produces.

    Returns one ``{"type": <node type>, "name": <plain-language name>}`` per
    step so the UI can style rows by node category and show the label.
    """
    steps = build_steps(events, mode=mode, session_id=session_id,
                        template_writer=None)
    return [{"type": node["type"], "name": node["name"]} for node in steps]
