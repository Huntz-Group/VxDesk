---
title: VxDesk Documentation
---

# VxDesk Documentation

**Fully-local desktop automation with an n8n-style visual workflow editor —
"Playwright MCP, but for the desktop."**

New here? Start with the
[interactive getting-started guide](https://github.com/Huntz-Group/VxDesk#readme) —
it walks you from install to your first workflow in about five minutes.

## Guides

| Document | What it covers |
|---|---|
| [Architecture](architecture.md) | Components, capture/vision/input backends, workflow engine, data flow |
| [API contract](api-contract.md) | REST + WebSocket surface between the editor and the backend |
| [Recorder](recorder.md) | Recording desktop interactions and converting them to workflows |
| [AI Assistant](ai-assistant.md) | Chat-driven workflow building; OpenAI-compatible providers |
| [Remote services](remote-services.md) | Hub ↔ agents over WebSocket / TCP / edge polling, tokens, TLS |

## Quick links

- [Repository](https://github.com/Huntz-Group/VxDesk) — source, issues, discussions
- [Releases](https://github.com/Huntz-Group/VxDesk/releases) — signed installer
  (`VxDeskSetup-x.y.z.exe`) and source archives
- [Contributing](https://github.com/Huntz-Group/VxDesk/blob/main/CONTRIBUTING.md)
- [Security policy](https://github.com/Huntz-Group/VxDesk/blob/main/SECURITY.md)
- [Changelog](https://github.com/Huntz-Group/VxDesk/blob/main/CHANGELOG.md)

## The 30-second tour

```bash
git clone https://github.com/Huntz-Group/VxDesk.git
cd VxDesk
npm run setup   # one-time: backend venv + Python/npm deps
npm run dev     # backend on 127.0.0.1:8765, editor on localhost:7100
```

Then open the UI, run the pre-loaded **Welcome · VxDesk tour (safe)** workflow, and
check `runs/` for the screenshot it saves. Everything runs on your machine — no cloud,
no telemetry.
