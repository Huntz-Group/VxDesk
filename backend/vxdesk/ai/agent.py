"""Agent loop: LLM ↔ local tools, emitting SSE event dicts.

The loop calls the chat-completions endpoint; while the model requests tool
calls it executes them locally, feeds results back, and repeats — capped at
10 tool rounds and 120 s overall. Every invocation ends with exactly one
``done`` or ``error`` event.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from ..engine.catalog import CATALOG
from ..workflows_store import load_workflow
from .client import LLMError, ToolsUnsupported, chat_completions
from .settings import get_credentials
from .tools import (
    TOOL_DEFINITIONS,
    ToolContext,
    execute_tool,
    serialize_result,
    tool_call_summary,
)

logger = logging.getLogger("vxdesk.ai.agent")

MAX_TOOL_ROUNDS = 10
TIME_LIMIT_S = 120.0
NO_TOOLS_NOTE = ("\n\n(Note: this model/endpoint does not support tool calling, "
                 "so I could only answer in text — no actions were performed.)")

EmitFn = Callable[[dict], None]

SAFETY_RULES = """\
Safety rules (always follow them):
1. Always validate a workflow after creating or updating it — the create/update
   tools do this automatically and report validation errors back to you; fix
   them with update_workflow before declaring success.
2. Default to dry_run=true (practice mode) when running workflows that perform
   real input; ask the user before a real run.
3. Ask before deleting anything; only call delete_workflow after the user
   clearly confirmed the deletion in the conversation.
4. Prefer simple, few-step workflows; use plain-language node names."""


def _catalog_summary() -> str:
    lines = []
    for entry in CATALOG:
        params = ", ".join(
            f"{p['name']}{'*' if p.get('required') else ''}" for p in entry["params"]
        )
        branches = f" | branches: {', '.join(entry['branch_handles'])}" \
            if entry["branch_handles"] else ""
        lines.append(f"- {entry['type']} — {entry['label']} ({params or 'no params'}){branches}")
    return "\n".join(lines)


def build_system_prompt(workflow_id: Optional[str] = None) -> str:
    prompt = f"""\
You are the VxDesk assistant. VxDesk is a fully-local desktop automation
platform for Windows: "Playwright MCP, but for the desktop". Users build
automation workflows as directed graphs of nodes (n8n-style) and run them
against the real screen (template matching, OCR, mouse/keyboard control).

You help the user create, fix, run and manage workflows by calling the local
tools provided to you. Never invent workflow JSON by guesswork alone: use the
node catalog below (or call get_node_catalog for the full schema).

Workflow JSON shape:
{{
  "id": "wf_...", "name": "...", "description": "",
  "nodes": [{{"id": "n1", "type": "trigger.manual", "name": "Start",
             "position": {{"x": 0, "y": 0}}, "params": {{}}, "disabled": false}}],
  "edges": [{{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"}}],
  "variables": {{}}
}}
- Every workflow starts with a trigger.manual node.
- Edge sourceHandle is "default" for plain sequence; branch handles per node
  type: true/false (condition), found/not_found (find_image, find_text,
  focus_window), found/timeout (wait_for), body/done (loop).
- Node params may embed templates: {{{{ n1.output.score }}}}, {{{{ vars.name }}}},
  {{{{ item.column }}}} (current loop row).

Node catalog (type — label (params, * = required) | branch handles):
{_catalog_summary()}

{SAFETY_RULES}
"""
    if workflow_id:
        try:
            workflow = load_workflow(workflow_id)
            prompt += (
                f"\nThe user currently has this workflow open in the editor "
                f"(id {workflow_id}); modify it via update_workflow when asked:\n"
                f"```json\n{json.dumps(workflow, ensure_ascii=False, indent=2)[:6000]}\n```\n"
            )
        except Exception:
            prompt += f"\n(The open workflow {workflow_id} could not be loaded.)\n"
    return prompt


def _sanitize_messages(messages: Any) -> list[dict]:
    """Keep only well-formed user/assistant turns from the client history."""
    out = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def _assistant_message_dict(message: dict) -> dict:
    """Re-serializable assistant message for the next request."""
    out: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    return out


def run_agent(
    messages: list[dict],
    workflow_id: Optional[str],
    ctx: ToolContext,
    emit: EmitFn,
) -> None:
    """Run the agent loop synchronously; emits SSE event dicts via ``emit``.

    Guarantees exactly one terminal ``done`` or ``error`` event.
    """
    try:
        _run_agent_inner(messages, workflow_id, ctx, emit)
    except Exception as exc:  # last-resort guard: the stream must terminate
        logger.exception("agent loop crashed")
        emit({"event": "error", "message": f"Something went wrong in the assistant: {exc}"})


def _run_agent_inner(
    messages: list[dict],
    workflow_id: Optional[str],
    ctx: ToolContext,
    emit: EmitFn,
) -> None:
    creds = get_credentials()
    if not creds.get("base_url") or not creds.get("model"):
        emit({
            "event": "error",
            "message": "The assistant is not configured yet — open the assistant "
                       "settings and pick a provider and model.",
        })
        return

    history = [{"role": "system", "content": build_system_prompt(workflow_id)}]
    history += _sanitize_messages(messages)
    if not any(m["role"] == "user" for m in history):
        emit({"event": "error", "message": "Say something first — the chat is empty."})
        return

    deadline = time.monotonic() + TIME_LIMIT_S
    use_tools = True

    for round_no in range(MAX_TOOL_ROUNDS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            emit({"event": "done",
                  "content": "I ran out of time (120s) while working on that. "
                             "What I finished so far is saved — ask me to continue."})
            return
        try:
            response = chat_completions(
                creds,
                history,
                tools=TOOL_DEFINITIONS if use_tools else None,
                timeout=min(60.0, max(5.0, remaining)),
            )
        except ToolsUnsupported:
            if use_tools:
                use_tools = False
                continue  # retry once without tools
            emit({"event": "error",
                  "message": "The model endpoint rejects tool calling entirely."})
            return
        except LLMError as exc:
            emit({"event": "error", "message": str(exc)})
            return

        message = response["choices"][0].get("message", {})
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        if content.strip() and tool_calls:
            emit({"event": "assistant_message", "content": content})

        if not tool_calls:
            final = content.strip() or "(the model returned an empty reply)"
            if not use_tools:
                final += NO_TOOLS_NOTE
            emit({"event": "done", "content": final})
            return

        history.append(_assistant_message_dict(message))
        for call in tool_calls:
            if time.monotonic() > deadline:
                emit({"event": "done",
                      "content": "I ran out of time (120s) mid-task. What I finished "
                                 "so far is saved — ask me to continue."})
                return
            call_id = str(call.get("id") or f"call_{round_no}")
            name = str(call.get("function", {}).get("name", ""))
            raw_args = call.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except (ValueError, TypeError):
                args = {}

            emit({"event": "tool_start", "id": call_id, "name": name,
                  "summary": tool_call_summary(name, args, ctx)})
            result = execute_tool(ctx, name, args)
            end_event = {"event": "tool_end", "id": call_id, "name": name,
                         "ok": result["ok"], "summary": result["summary"]}
            if result.get("workflow_id"):
                end_event["workflow_id"] = result["workflow_id"]
            emit(end_event)

            history.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": serialize_result({
                    "ok": result["ok"],
                    "summary": result["summary"],
                    "result": result["result"],
                }),
            })

    emit({"event": "done",
          "content": "I hit the step limit (10 tool rounds) for one reply. What I "
                     "finished so far is saved — ask me to continue."})
