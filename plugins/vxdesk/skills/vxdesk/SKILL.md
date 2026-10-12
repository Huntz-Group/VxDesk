---
name: vxdesk
description: Use when the user wants Kimi to operate their Windows desktop through VxDesk — take a screenshot, see what's on screen, find/click buttons or text (GPU-accelerated vision), type text, press hotkeys, list windows, or run/manage a saved VxDesk workflow by name. Triggers include "control my desktop", "click X for me", "what's on my screen", "run my ... workflow", "automate this app".
---

# VxDesk

Kimi Work connects to the local **VxDesk** desktop-automation app through its MCP
server. All tools run fully locally against the user's real screen, mouse, and
keyboard.

## Tools (mcp__plugin-vxdesk_vxdesk__*)

- `screenshot(x?, y?, w?, h?)` — capture the screen or a region (absolute pixels). **Always look before acting.**
- `find_text(text, case_sensitive?)` — locate text on screen via GPU OCR; returns boxes with centers.
- `find_image(template, threshold?)` — locate a saved template image (from the VxDesk app's assets).
- `click(x, y, button?, clicks?)` — click absolute coordinates (use a found center, never guessed pixels).
- `type_text(text, interval_ms?)` — type a string.
- `press_key(keys)` — single key `["enter"]` or chord `["ctrl", "s"]`.
- `list_windows()` — titles + rects of top-level windows.
- `run_workflow(workflow, dry_run?, timeout_s?)` — run a saved workflow **by id or name**, waits for the result. Shares its workflow library with the installed VxDesk app.

## Workflow

1. Prefer `run_workflow` for anything repetitive — if a suitable workflow exists (or the user has one in the app), use it instead of hand-driving the mouse.
2. For ad-hoc control: `screenshot` first → decide target → `find_text`/`find_image` when possible (robust to window moves) → `click` the returned center → `screenshot` again to confirm the result.
3. For multi-step ad-hoc tasks that work well, suggest saving them as a VxDesk workflow (the app has a Recorder and an AI assistant for that).

## Safety

- These tools move the REAL mouse and type on the REAL keyboard. Confirm with the user before irreversible actions (sending messages, deleting, submitting forms).
- Use `dry_run: true` on `run_workflow` first when the workflow performs real input and the user hasn't run it before.
- PyAutoGUI fail-safe is active: slamming the mouse into a screen corner aborts input.
- Never type passwords, OTPs, or secrets on the user's behalf unless they explicitly dictate them in this conversation.
