# VxDesk — Architecture

VxDesk is a fully-local desktop automation platform: "Playwright MCP, but for the desktop",
with an n8n-style visual workflow editor. Windows-first, designed to be portable
(macOS/Linux later via pluggable capture/input backends).

## Components

```
VxDesk/
├── backend/               # Python package `vxdesk` + project venv at backend/.venv
│   ├── vxdesk/
│   │   ├── capture/       # Screen capture: DXcam (DXGI, GPU) primary, mss fallback
│   │   ├── vision/        # Template matching (OpenCV), OCR (RapidOCR / ONNX Runtime DirectML)
│   │   ├── input/         # Mouse/keyboard/window control (pyautogui + pywin32)
│   │   ├── engine/        # Workflow graph executor, node registry, templating, run state
│   │   ├── server/        # FastAPI app: REST + WebSocket, static asset serving
│   │   └── mcp_server.py  # MCP stdio server exposing desktop tools to AI agents
│   ├── tests/             # pytest suite
│   └── requirements.txt
├── frontend/              # React + Vite + TypeScript + React Flow (n8n-like editor)
├── workflows/             # Saved workflow JSON files (runtime data)
├── assets/templates/      # Template images for find-image nodes (runtime data)
├── scripts/dev.js         # Root `npm run dev`: spawns backend + frontend together
└── docs/                  # This file + api-contract.md
```

## Design decisions

- **GPU acceleration (AMD Radeon target)**: no CUDA. Use:
  - **DXcam** for capture — uses DXGI Desktop Duplication, GPU-side, ~240 Hz capable.
  - **ONNX Runtime DirectML** for OCR (RapidOCR models) — DirectML runs on any DX12 GPU incl. AMD.
  - OpenCV template matching stays on CPU (SIMD, fast at downscaled resolutions) with optional
    downscale factor; expose `gpu` capability flags in `/api/system/info` so the UI can show what is active.
  - Every GPU feature must have a CPU fallback and a runtime capability probe. Never hard-fail on missing GPU.
- **Workflow model**: directed graph of nodes. Execution starts at trigger nodes (in-degree 0 or
  type `trigger.manual`). Edges may carry a `sourceHandle` (e.g. `true`/`false`, `found`/`timeout`,
  `body`/`done`) for branching and loops. Node outputs are JSON-able dicts stored per node id.
- **Templating**: string params may embed `{{ n1.output.score }}`, `{{ vars.name }}`,
  `{{ item.column }}` (current loop row). Resolved at runtime by the engine (dot-path lookup).
- **Data-driven runs**: `input.data_table` node loads CSV text or a CSV file path; a
  `control.loop` node in `rows` mode iterates it, exposing `{{ item.* }}` to the loop body.
- **Virtual screen for tests**: the capture layer accepts an override source (image file or
  numpy frame provider) so the full engine can be E2E-tested without touching the real desktop.
  Activated via env var `VXDESK_CAPTURE_SOURCE=file:<path>` or API field; never used by default.
- **Safety**: input actions go through a global "dry-run" flag (`VXDESK_DRY_RUN=1` or per-run
  `dry_run: true`) that logs instead of clicking/typing. A fail-safe corner (pyautogui FAILSAFE)
  stays enabled.
- **Persistence**: workflows are plain JSON files in `workflows/`. Templates are PNG files in
  `assets/templates/`. No database.
- **Ports**: backend on `127.0.0.1:8765`. Vite dev server proxies `/api` and `/ws` to it.

## Node catalog (v1) — engine `type` strings

| type | params (key ones) | outputs | branch handles |
|---|---|---|---|
| `trigger.manual` | — | `{}` | — |
| `input.data_table` | `csv_text` or `csv_path` | `{rows, count}` | — |
| `control.loop` | `mode: count\|rows`, `count`, `source` (node id), `max_iterations` | `{index, item}` | `body`, `done` |
| `control.condition` | `expression` (templated, truthy) | `{result}` | `true`, `false` |
| `control.wait` | `ms` | `{}` | — |
| `control.wait_for` | `target: image\|text`, `template`/`text`, `timeout_ms`, `poll_ms` | `{found, ...match}` | `found`, `timeout` |
| `control.set_variable` | `name`, `value` (templated) | `{name, value}` | — |
| `control.log` | `message` (templated) | `{}` | — |
| `capture.screenshot` | `region?` `{x,y,w,h}`, `save_as?` | `{image_path, width, height}` | — |
| `vision.find_image` | `template` (asset name), `threshold` (0-1), `region?`, `scales?` | `{found, x, y, w, h, score, center:{x,y}}` | `found`, `not_found` |
| `vision.find_text` | `text`, `region?`, `case_sensitive?` | `{found, boxes[], first:{x,y,w,h,center}}` | `found`, `not_found` |
| `action.click` | `target: point\|last_found\|image\|text`, `x`,`y`, `template`/`text`, `button`, `clicks` | `{x, y}` | — |
| `action.move` | `x`, `y` | `{}` | — |
| `action.drag` | `from`/`to` points or `last_found` | `{}` | — |
| `action.type_text` | `text` (templated), `interval_ms` | `{}` | — |
| `action.press_key` | `keys` (e.g. `["ctrl","s"]` or `"enter"`) | `{}` | — |
| `action.focus_window` | `title` (substring) | `{found, rect}` | `found`, `not_found` |
| `action.launch` | `command`, `wait_ms` | `{pid?}` | — |
| `script.python` | `code` (gets `ctx`, sets `result`) | `{result}` | — |
| `output.save_screenshot` | `path`, `region?` | `{path}` | — |

## MCP server tools (v1)

`screenshot`, `find_image`, `find_text`, `click`, `type_text`, `press_key`,
`list_windows`, `run_workflow`. Stdio transport via the official `mcp` Python SDK if it
installs cleanly; otherwise a minimal JSON-RPC stdio implementation with the same tool names.
