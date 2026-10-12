# VxDesk Backend

Python backend for VxDesk — a fully-local desktop automation platform
("Playwright MCP, but for the desktop"). Implements `docs/architecture.md` and
`docs/api-contract.md`.

## Layout

```
backend/
├── vxdesk/
│   ├── capture/       # DXcam (GPU) primary → mss fallback → file: virtual source
│   ├── vision/        # cv2.matchTemplate + RapidOCR (ONNX Runtime DirectML)
│   ├── input/         # pyautogui mouse/keyboard, pywin32 windows, dry-run flag
│   ├── engine/        # DAG executor, node registry, templating, safe expressions
│   ├── server/        # FastAPI app (REST + WebSocket), port 127.0.0.1:8765
│   └── mcp_server.py  # stdio MCP server (official SDK, JSON-RPC fallback)
├── tests/             # pytest suite (headless-safe via virtual capture source)
└── requirements.txt
```

## Setup

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

# ONNX Runtime DirectML (AMD/any DX12 GPU). onnxruntime and onnxruntime-directml
# provide the same module, so swap them explicitly:
backend/.venv/Scripts/python.exe -m pip uninstall -y onnxruntime
backend/.venv/Scripts/python.exe -m pip install --force-reinstall --no-deps onnxruntime-directml
backend/.venv/Scripts/python.exe -c "import onnxruntime; print(onnxruntime.get_available_providers())"
# -> should list 'DmlExecutionProvider'

# optional: official MCP SDK (a minimal JSON-RPC fallback ships in-tree)
backend/.venv/Scripts/python.exe -m pip install mcp
```

If the DirectML swap fails, plain `onnxruntime` (CPU) works too — OCR then
reports `gpu: false` and everything else is unaffected.

## Run the server

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn vxdesk.server.app:create_app --factory --host 127.0.0.1 --port 8765
# or: .venv/Scripts/python.exe -m vxdesk.server.app
```

API docs: `http://127.0.0.1:8765/docs`. Capabilities: `GET /api/system/info`.

## Run the tests

```bash
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```

All tests run headless-safe: they point the capture layer at a synthetic image
(`VXDESK_CAPTURE_SOURCE=file:<path>`). OCR tests skip only if the RapidOCR
models cannot be downloaded.

## Run the MCP server

```bash
cd backend
.venv/Scripts/python.exe -m vxdesk.mcp_server
```

Tools: `screenshot`, `find_image`, `find_text`, `click`, `type_text`,
`press_key`, `list_windows`, `run_workflow` (by workflow id or name).

## Environment variables

| Variable | Effect |
|---|---|
| `VXDESK_CAPTURE_SOURCE=file:<path>` | Serve a static image instead of the real screen (tests/demos) |
| `VXDESK_DRY_RUN=1` | Log input actions instead of clicking/typing |

Per-run dry-run is also available via `POST /api/workflows/{id}/run`
(`{"dry_run": true}`) — input nodes log and never touch the real desktop.

## Safety

- pyautogui `FAILSAFE` stays on: slam the mouse into a screen corner to abort.
- Loops are capped by `max_iterations` (default 1000).
- Stop requests are honored between nodes and inside wait/poll loops (~200 ms).
