# Contributing to VxDesk

Thanks for your interest! VxDesk is a fully-local desktop automation platform —
contributions of all kinds are welcome: bug reports, feature ideas, docs, new node
types, and ports (macOS/Linux capture & input backends especially).

## Getting set up

See **Path B — Run from source** in the [README](README.md):

```bash
git clone https://github.com/Huntz-Group/VxDesk.git
cd VxDesk
npm run setup   # creates backend venv, installs Python + npm deps
npm run dev     # backend on 127.0.0.1:8765 + editor on localhost:7100
```

Prerequisites: Windows 10/11, Python 3.12, Node.js ≥ 20.

## Before you open a PR

1. **Run the tests** — both suites must pass:

   ```bash
   backend/.venv/Scripts/python.exe -m pytest backend/tests -q
   cd frontend && npm test
   ```

   The backend suite runs against a virtual screen; it never touches your real desktop.

2. **Keep it local** — VxDesk's core promise is *no cloud, no telemetry*. PRs that add
   network calls to third parties need a strong justification and an opt-in toggle.

3. **One concern per PR** — small, focused pull requests review faster and land sooner.

4. **Docs** — if you change a contract (REST/WebSocket shapes, node params, recorder or
   assistant behavior), update the matching file in `docs/`.

## Where things live

| Area | Path | Notes |
|---|---|---|
| Workflow engine | `backend/vxdesk/engine/` | DAG executor, node registry, templating |
| Capture / vision / input | `backend/vxdesk/capture|vision|input/` | pluggable backends |
| API server | `backend/vxdesk/server/` | FastAPI REST + WebSocket |
| Editor UI | `frontend/src/` | React Flow canvas, property panels |
| MCP server | `backend/vxdesk/mcp_server.py` | stdio JSON-RPC for AI agents |

Adding a node type? Register it in the engine's node registry and describe its params
schema — the editor's property panels are generated from that schema automatically.

## Reporting bugs

Open an issue with the **bug report** template. Include:

- VxDesk version (`GET /api/system/info` or the About line),
- Windows version and GPU (capture/OCR issues especially),
- the workflow JSON if relevant (remove anything sensitive first),
- logs from `logs/` (dev) or `%LOCALAPPDATA%\VxDesk\logs` (installed app).

## Security issues

**Do not open a public issue.** See [SECURITY.md](SECURITY.md).

## Code of conduct

All participation is covered by our [Code of Conduct](CODE_OF_CONDUCT.md).
