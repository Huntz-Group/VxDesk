# Changelog

All notable changes to VxDesk are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-12

First public release. 🎉

### Added

- **Visual workflow editor** — n8n-style React Flow canvas with schema-driven property
  panels and a live run console over WebSocket.
- **Workflow engine** — Python DAG executor with 20 node types: loops, conditions,
  variables, `{{ node.output }}` templating, dry-run mode, stop-aware execution.
- **GPU screen capture** — DXcam (DXGI Desktop Duplication) at ~120+ fps, `mss` fallback.
- **GPU vision** — RapidOCR on ONNX Runtime DirectML (any DX12 GPU) and OpenCV
  multi-scale template matching with per-node threshold/region/scale control.
- **Input control** — clicks, drags, typing, hotkeys, window focus via pyautogui/pywin32;
  PyAutoGUI corner failsafe enabled.
- **Recorder** — record clicks/typing/hotkeys/window switches, convert to a workflow in
  Smart (template-matching) or Exact-positions mode.
- **AI Assistant** — chat to build/run/manage workflows against any OpenAI-compatible
  endpoint (Ollama, LM Studio, OpenAI, OpenRouter, Moonshot…); API keys stored locally.
- **MCP server** — stdio server exposing `screenshot`, `find_image`, `find_text`,
  `click`, `type_text`, `press_key`, `list_windows`, `run_workflow` to AI agents.
- **Remote services** — hub with per-agent tokens over WebSocket, TCP JSON-lines, and a
  stdlib-only edge polling API for legacy/XP-class machines; optional TLS listener.
- **Desktop app** — PyInstaller + Inno Setup installer; installs without admin rights,
  runs the UI in a native WebView2 window, fully offline.
- **Test suites** — 134 backend tests (virtual screen; never touches your desktop),
  12 frontend tests, plus a live-stack integration check script.

### Security

- Remote access is off by default; agent tokens are hashed and revocable.
- AI-assistant API keys are write-only: never returned by endpoints, never logged.

[0.1.0]: https://github.com/Huntz-Group/VxDesk/releases/tag/v0.1.0
