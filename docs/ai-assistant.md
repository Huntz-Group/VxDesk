# VxDesk — AI Assistant contract (backend ↔ frontend)

The assistant lets the user chat with an LLM to **create**, **execute**, and **manage**
automation workflows. The backend runs an agent loop: the LLM (any OpenAI-compatible
endpoint — Ollama, LM Studio, OpenAI, OpenRouter, Moonshot, custom) calls local tools;
the backend executes them and feeds results back until the model answers.

## Settings

Stored in `ai-settings.json` at the repo root (gitignored). The API key is write-only:
never returned by any endpoint, never logged.

### GET /api/ai/settings
```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1",
  "model": "qwen2.5:7b",
  "has_api_key": false,
  "presets": [
    {"id": "ollama",   "label": "Ollama (local)",     "base_url": "http://localhost:11434/v1", "needs_key": false, "model_hint": "qwen2.5:7b"},
    {"id": "lmstudio", "label": "LM Studio (local)",  "base_url": "http://localhost:1234/v1",  "needs_key": false, "model_hint": "local-model"},
    {"id": "openai",   "label": "OpenAI",             "base_url": "https://api.openai.com/v1", "needs_key": true,  "model_hint": "gpt-4o-mini"},
    {"id": "openrouter","label": "OpenRouter",        "base_url": "https://openrouter.ai/api/v1", "needs_key": true, "model_hint": "openai/gpt-4o-mini"},
    {"id": "moonshot", "label": "Moonshot (Kimi)",    "base_url": "https://api.moonshot.ai/v1", "needs_key": true, "model_hint": "kimi-k2-0711-preview"},
    {"id": "custom",   "label": "Custom (OpenAI-compatible)", "base_url": "", "needs_key": true, "model_hint": ""}
  ]
}
```
### PUT /api/ai/settings
Body: `{provider, base_url, model, api_key?}`. `api_key` omitted/empty = keep existing;
`api_key: null` = clear. Returns the same shape as GET.

### GET /api/ai/status
```json
{"configured": true, "reachable": true, "model": "qwen2.5:7b", "detail": "connected"}
```
`reachable` probes `GET {base_url}/models` with a 4s timeout (auth header if key set).
Never fail hard — `{"configured": false}` when no model chosen yet.

## Chat — POST /api/ai/chat (SSE stream)

Request:
```json
{
  "messages": [{"role": "user", "content": "Make a workflow that types hello into Notepad"}],
  "workflow_id": "wf_abc123"         // optional: workflow currently open in the editor
}
```
`messages` is the client-kept conversation history (roles `user`/`assistant`; the client
does NOT send tool messages — the backend keeps its own tool-loop state per request).

Response: `text/event-stream`. One JSON payload per `data:` line:
```json
{"event": "assistant_message", "content": "I'll build that for you — one moment."}
{"event": "tool_start", "id": "call_1", "name": "create_workflow", "summary": "Create workflow “Notepad hello”"}
{"event": "tool_end",   "id": "call_1", "name": "create_workflow", "ok": true, "summary": "Created wf_9f2c… (6 steps, valid)", "workflow_id": "wf_9f2c…"}
{"event": "tool_start", "id": "call_2", "name": "run_workflow", "summary": "Run “Notepad hello” (practice mode)"}
{"event": "tool_end",   "id": "call_2", "name": "run_workflow", "ok": true, "summary": "Run finished: success"}
{"event": "done", "content": "Done! I created “Notepad hello” and ran it in practice mode — all 6 steps passed. Want me to run it for real?"}
{"event": "error", "message": "Could not reach the model at http://localhost:11434/v1 — is Ollama running?"}
```
Rules:
- `tool_end` carries `workflow_id` whenever a tool created/modified a workflow, so the
  frontend can refresh its list/canvas.
- The stream always ends with exactly one `done` or `error` event.
- Agent loop is capped (10 tool rounds) and has a 120s overall timeout; on cap/timeout
  the stream ends with `done` + an explanation.
- If the endpoint/model does not support tool calling (400 error mentioning tools), the
  backend retries once without tools and answers in plain text with guidance.

## Agent tools (backend-side only, never called by the frontend directly)

`list_workflows` · `get_workflow` · `create_workflow` · `update_workflow` ·
`delete_workflow` · `run_workflow(dry_run)` · `stop_run` · `get_run` · `list_runs` ·
`get_node_catalog` · `screenshot` (returns dimensions + saved path, not image data) ·
`test_match(template)` · `list_windows`

Safety rules baked into the system prompt:
1. Always validate a workflow after creating/updating it (the tools do this
   automatically and report errors back to the model for fixing).
2. Default to `dry_run: true` when running workflows that perform real input; ask the
   user before a real run.
3. Ask before deleting anything; only call `delete_workflow` after the user clearly
   confirmed in the conversation.
4. Prefer simple, few-step workflows; use plain-language node names.
