# VxDesk — API Contract (backend ↔ frontend)

Base URL: `http://127.0.0.1:8765`. All REST paths below are prefixed with `/api`.
WebSocket: `/ws/...`. CORS: allow `http://localhost:*` and `http://127.0.0.1:*` (dev only).
The Vite dev server proxies `/api` and `/ws` to the backend, so the frontend uses relative paths.

## System

### GET /api/system/info
```json
{
  "version": "0.1.0",
  "os": "windows",
  "python": "3.12.14",
  "capture": {"backend": "dxcam", "gpu": true, "fps_hint": 120},
  "ocr": {"available": true, "backend": "rapidocr-onnxruntime", "gpu": true, "provider": "DmlExecutionProvider"},
  "gpu": {"name": "AMD Radeon (TM) Graphics", "directml": true},
  "screens": [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080}]
}
```
Every capability probe must degrade gracefully (e.g. `"backend": "mss"`, `"gpu": false`).

## Workflows

Workflow JSON shape (what the editor saves/loads):
```json
{
  "id": "wf_8f3a...",
  "name": "My workflow",
  "description": "",
  "nodes": [
    {"id": "n1", "type": "trigger.manual", "name": "Start", "position": {"x": 0, "y": 0},
     "params": {}, "disabled": false}
  ],
  "edges": [
    {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"}
  ],
  "variables": {"my_var": "initial"}
}
```
- Edge `sourceHandle` is `"default"` for plain sequence; branch handles per node type
  (`true`/`false`, `found`/`not_found`/`timeout`, `body`/`done`).
- Node `position` is editor-only; the engine ignores it.

Endpoints:
- `GET  /api/workflows` → `[{id, name, description, updated_at, node_count}]`
- `POST /api/workflows` body `{name, description?}` → full workflow (created with one `trigger.manual` node)
- `GET  /api/workflows/{id}` → full workflow JSON
- `PUT  /api/workflows/{id}` body = full workflow JSON → saved workflow JSON
- `DELETE /api/workflows/{id}` → `{ok: true}`
- `POST /api/workflows/{id}/validate` → `{valid: bool, errors: [str], warnings: [str]}`
- `POST /api/workflows/{id}/run` body `{inputs?: {}, dry_run?: bool}` → `{run_id}`
- `GET  /api/workflows/{id}/runs` → run summaries for that workflow

## Runs

- `GET /api/runs/{run_id}` →
```json
{"run_id": "...", "workflow_id": "...", "status": "running|success|failed|stopped",
 "started_at": "...", "finished_at": null, "error": null,
 "node_states": {"n1": {"status": "success", "output": {...}, "duration_ms": 12, "error": null}}}
```
- `POST /api/runs/{run_id}/stop` → `{ok: true}`

### WS /ws/runs/{run_id}
Server pushes JSON events:
```json
{"event": "run_started",   "run_id": "..."}
{"event": "node_started",  "node_id": "n2", "name": "Find button"}
{"event": "node_finished", "node_id": "n2", "status": "success", "output": {...}, "duration_ms": 34}
{"event": "log",           "node_id": "n2", "level": "info", "message": "..."}
{"event": "run_finished",  "status": "success", "error": null}
```
A client connecting mid-run must first receive a `snapshot` event with the same shape as
`GET /api/runs/{run_id}`, then live events.

## Capture / vision utilities (used by the editor's picker & node debugging)

- `POST /api/capture/screenshot` body `{region?: {x,y,w,h}, format?: "png"|"jpeg"}` →
  binary image response (`image/png`). Editor uses this for the region/template picker.
- `GET /api/windows` → `[{hwnd, title, rect: {x,y,w,h}, visible: true}]`
- `POST /api/vision/test-match` body `{template: "name.png", threshold?: 0.8, region?}` →
  `{found, x, y, w, h, score, center, elapsed_ms}`
- `POST /api/vision/test-ocr` body `{region?, text?}` →
  `{boxes: [{text, confidence, x, y, w, h}], elapsed_ms}` (if `text` given, only matches)

## Template assets

- `GET  /api/assets/templates` → `[{name, width, height, size_bytes}]`
- `POST /api/assets/templates` multipart form: `file` (PNG) + `name` → `{name, width, height}`
- `GET  /api/assets/templates/{name}` → binary PNG
- `DELETE /api/assets/templates/{name}` → `{ok: true}`

## Node catalog (for the editor)

- `GET /api/nodes/catalog` →
```json
{"nodes": [
  {"type": "vision.find_image", "category": "vision", "label": "Find Image",
   "description": "...", "icon": "image",
   "branch_handles": ["found", "not_found"],
   "params": [
     {"name": "template", "label": "Template", "kind": "template", "required": true},
     {"name": "threshold", "label": "Threshold", "kind": "number", "default": 0.8, "min": 0.1, "max": 1.0, "step": 0.05},
     {"name": "region", "label": "Region", "kind": "region", "required": false}
   ]}
]}
```
`kind` ∈ `string | text | number | boolean | select | template | region | point | csv | code | keys`.
`select` params include `options: [{value, label}]`. `branch_handles` omits the implicit
`"default"` handle. The frontend fetches this at startup and must keep a bundled fallback copy
in case the backend is unreachable.

## Conventions

- Errors: HTTP 4xx/5xx with body `{"detail": "human readable message"}`.
- All timestamps ISO-8601 local time with offset.
- Coordinates are absolute virtual-screen pixels (multi-monitor safe).
- Long-running runs must honour stop requests within ~200 ms (engine checks a stop event
  between nodes and inside wait/poll loops).
