"""Plain-HTTP OpenAI-compatible chat-completions client (httpx, no SDK)."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("vxdesk.ai.client")


class LLMError(Exception):
    """Friendly, user-presentable LLM failure (never contains credentials)."""


class ToolsUnsupported(LLMError):
    """The endpoint rejected the request because of the ``tools`` payload."""


def chat_completions(
    creds: dict,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    timeout: float = 60.0,
) -> dict:
    """One non-streaming chat-completions round-trip.

    Raises :class:`ToolsUnsupported` when a 400 complains about tools, and
    :class:`LLMError` with a friendly message for every other failure.
    """
    base_url = creds.get("base_url", "")
    payload: dict = {"model": creds.get("model", ""), "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Content-Type": "application/json"}
    if creds.get("api_key"):
        headers["Authorization"] = f"Bearer {creds['api_key']}"

    try:
        resp = httpx.post(
            f"{base_url}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
    except httpx.ConnectError:
        raise LLMError(f"Could not reach the model at {base_url} — is Ollama running?")
    except httpx.TimeoutException:
        raise LLMError(f"The model at {base_url} took too long to answer (timeout).")
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not talk to the model at {base_url}: {exc}")

    if resp.status_code >= 400:
        detail = _error_detail(resp)
        if resp.status_code == 400 and "tool" in detail.lower():
            raise ToolsUnsupported(detail)
        if resp.status_code in (401, 403):
            raise LLMError("Authentication failed — check the API key in assistant settings.")
        raise LLMError(f"The model endpoint answered HTTP {resp.status_code}: {detail}")

    try:
        data = resp.json()
        choices = data["choices"]
        if not choices:
            raise KeyError("choices")
        return data
    except (ValueError, KeyError):
        raise LLMError("The model returned an unexpected response shape.")


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        error = body.get("error", {})
        if isinstance(error, dict):
            return str(error.get("message") or body)
        return str(error)
    except ValueError:
        return resp.text[:300] or f"HTTP {resp.status_code}"
