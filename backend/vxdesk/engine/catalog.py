"""Schema-driven node catalog served at ``GET /api/nodes/catalog``.

This drives the frontend's property panels; keep it in sync with
``vxdesk.engine.nodes.REGISTRY``.
"""

from __future__ import annotations

from typing import Any


def _p(name: str, label: str, kind: str, **extra: Any) -> dict:
    return {"name": name, "label": label, "kind": kind, **extra}


REGION = _p("region", "Region", "region", required=False)
MODE_SELECT = [
    {"value": "count", "label": "Count"},
    {"value": "rows", "label": "Rows (data table)"},
]
CLICK_TARGET = [
    {"value": "point", "label": "Point (x, y)"},
    {"value": "last_found", "label": "Last found match"},
    {"value": "image", "label": "Image template"},
    {"value": "text", "label": "Text (OCR)"},
]
WAIT_TARGET = [
    {"value": "image", "label": "Image template"},
    {"value": "text", "label": "Text (OCR)"},
]
BUTTONS = [
    {"value": "left", "label": "Left"},
    {"value": "right", "label": "Right"},
    {"value": "middle", "label": "Middle"},
]

CATALOG: list[dict] = [
    {
        "type": "trigger.manual",
        "category": "trigger",
        "label": "Manual Trigger",
        "description": "Starts the workflow when the user clicks Run.",
        "icon": "play",
        "branch_handles": [],
        "params": [],
    },
    {
        "type": "input.data_table",
        "category": "input",
        "label": "Data Table (CSV)",
        "description": "Loads CSV text or a CSV file and exposes rows for a loop node.",
        "icon": "table",
        "branch_handles": [],
        "params": [
            _p("csv_text", "CSV text", "csv", required=False),
            _p("csv_path", "CSV file path", "string", required=False),
        ],
    },
    {
        "type": "control.loop",
        "category": "control",
        "label": "Loop",
        "description": "Iterates N times or over rows of a data-table node. "
        "Connect the loop body to the 'body' handle and the rest to 'done'.",
        "icon": "repeat",
        "branch_handles": ["body", "done"],
        "params": [
            _p("mode", "Mode", "select", required=True, default="count", options=MODE_SELECT),
            _p("count", "Count", "number", required=False, default=1, min=0, step=1),
            _p("source", "Source node id (rows mode)", "string", required=False),
            _p("max_iterations", "Max iterations (safety cap)", "number",
               required=False, default=1000, min=1, step=1),
        ],
    },
    {
        "type": "control.condition",
        "category": "control",
        "label": "Condition",
        "description": "Evaluates a templated expression and branches on true/false. "
        "Supports comparisons, and/or/not, len(), int/float/str, contains(a, b).",
        "icon": "git-branch",
        "branch_handles": ["true", "false"],
        "params": [
            _p("expression", "Expression", "string", required=True,
               placeholder="{{ n1.output.score }} > 0.8"),
        ],
    },
    {
        "type": "control.wait",
        "category": "control",
        "label": "Wait",
        "description": "Sleeps for the given number of milliseconds (stop-aware).",
        "icon": "clock",
        "branch_handles": [],
        "params": [
            _p("ms", "Milliseconds", "number", required=True, default=1000, min=0, step=100),
        ],
    },
    {
        "type": "control.wait_for",
        "category": "control",
        "label": "Wait For",
        "description": "Polls the screen until an image or text appears, or a timeout hits.",
        "icon": "eye",
        "branch_handles": ["found", "timeout"],
        "params": [
            _p("target", "Target", "select", required=True, default="image", options=WAIT_TARGET),
            _p("template", "Template", "template", required=False),
            _p("text", "Text", "string", required=False),
            _p("threshold", "Threshold", "number", required=False,
               default=0.8, min=0.1, max=1.0, step=0.05),
            _p("timeout_ms", "Timeout (ms)", "number", required=False, default=10000, min=0, step=500),
            _p("poll_ms", "Poll interval (ms)", "number", required=False, default=500, min=50, step=50),
            REGION,
        ],
    },
    {
        "type": "control.set_variable",
        "category": "control",
        "label": "Set Variable",
        "description": "Sets a workflow variable (value is template-resolved).",
        "icon": "variable",
        "branch_handles": [],
        "params": [
            _p("name", "Name", "string", required=True),
            _p("value", "Value", "text", required=False),
        ],
    },
    {
        "type": "control.log",
        "category": "control",
        "label": "Log",
        "description": "Emits a log message to the run event stream.",
        "icon": "terminal",
        "branch_handles": [],
        "params": [
            _p("message", "Message", "text", required=True),
        ],
    },
    {
        "type": "capture.screenshot",
        "category": "capture",
        "label": "Screenshot",
        "description": "Grabs the screen (or a region) and optionally saves it as PNG.",
        "icon": "camera",
        "branch_handles": [],
        "params": [
            REGION,
            _p("save_as", "Save as (path)", "string", required=False),
        ],
    },
    {
        "type": "vision.find_image",
        "category": "vision",
        "label": "Find Image",
        "description": "Locates a template image on screen via OpenCV template matching.",
        "icon": "image",
        "branch_handles": ["found", "not_found"],
        "params": [
            _p("template", "Template", "template", required=True),
            _p("threshold", "Threshold", "number", default=0.8, min=0.1, max=1.0, step=0.05),
            REGION,
            _p("scales", "Scales (multi-scale match)", "string", required=False,
               placeholder="[0.8, 1.0, 1.25]"),
        ],
    },
    {
        "type": "vision.find_text",
        "category": "vision",
        "label": "Find Text",
        "description": "Finds text on screen via OCR (RapidOCR, DirectML when available).",
        "icon": "type",
        "branch_handles": ["found", "not_found"],
        "params": [
            _p("text", "Text", "string", required=True),
            REGION,
            _p("case_sensitive", "Case sensitive", "boolean", required=False, default=False),
        ],
    },
    {
        "type": "action.click",
        "category": "action",
        "label": "Click",
        "description": "Clicks a point, the last found match, or an image/text target.",
        "icon": "mouse-pointer",
        "branch_handles": [],
        "params": [
            _p("target", "Target", "select", required=True, default="point", options=CLICK_TARGET),
            _p("x", "X", "number", required=False),
            _p("y", "Y", "number", required=False),
            _p("template", "Template", "template", required=False),
            _p("text", "Text", "string", required=False),
            _p("threshold", "Threshold", "number", required=False,
               default=0.8, min=0.1, max=1.0, step=0.05),
            _p("button", "Button", "select", required=False, default="left", options=BUTTONS),
            _p("clicks", "Clicks", "number", required=False, default=1, min=1, step=1),
        ],
    },
    {
        "type": "action.move",
        "category": "action",
        "label": "Move Mouse",
        "description": "Moves the mouse cursor to an absolute position.",
        "icon": "move",
        "branch_handles": [],
        "params": [
            _p("x", "X", "number", required=True),
            _p("y", "Y", "number", required=True),
            _p("duration_ms", "Duration (ms)", "number", required=False, default=0, min=0, step=50),
        ],
    },
    {
        "type": "action.drag",
        "category": "action",
        "label": "Drag",
        "description": "Drags from one point to another (points may be 'last_found').",
        "icon": "move-diagonal",
        "branch_handles": [],
        "params": [
            _p("from", "From", "point", required=True),
            _p("to", "To", "point", required=True),
            _p("duration_ms", "Duration (ms)", "number", required=False, default=300, min=0, step=50),
            _p("button", "Button", "select", required=False, default="left", options=BUTTONS),
        ],
    },
    {
        "type": "action.type_text",
        "category": "action",
        "label": "Type Text",
        "description": "Types text with the keyboard (template-resolved).",
        "icon": "keyboard",
        "branch_handles": [],
        "params": [
            _p("text", "Text", "text", required=True),
            _p("interval_ms", "Interval per key (ms)", "number", required=False, default=0, min=0, step=10),
        ],
    },
    {
        "type": "action.press_key",
        "category": "action",
        "label": "Press Key",
        "description": "Presses a single key ('enter') or a chord (['ctrl', 's']).",
        "icon": "command",
        "branch_handles": [],
        "params": [
            _p("keys", "Keys", "keys", required=True),
        ],
    },
    {
        "type": "action.focus_window",
        "category": "action",
        "label": "Focus Window",
        "description": "Focuses the first window whose title contains the substring.",
        "icon": "app-window",
        "branch_handles": ["found", "not_found"],
        "params": [
            _p("title", "Title substring", "string", required=True),
        ],
    },
    {
        "type": "action.launch",
        "category": "action",
        "label": "Launch",
        "description": "Launches a shell command and optionally waits.",
        "icon": "rocket",
        "branch_handles": [],
        "params": [
            _p("command", "Command", "string", required=True),
            _p("wait_ms", "Wait after launch (ms)", "number", required=False, default=0, min=0, step=100),
        ],
    },
    {
        "type": "script.python",
        "category": "script",
        "label": "Python Script",
        "description": "Runs Python code with a 'ctx' accessor (ctx.output(id), ctx.vars, "
        "ctx.item); assign the outcome to 'result'.",
        "icon": "code",
        "branch_handles": [],
        "params": [
            _p("code", "Code", "code", required=True),
        ],
    },
    {
        "type": "output.save_screenshot",
        "category": "output",
        "label": "Save Screenshot",
        "description": "Saves the screen (or a region) to a PNG file.",
        "icon": "save",
        "branch_handles": [],
        "params": [
            _p("path", "Path", "string", required=True),
            REGION,
        ],
    },
]


def get_catalog() -> dict:
    return {"nodes": CATALOG}
