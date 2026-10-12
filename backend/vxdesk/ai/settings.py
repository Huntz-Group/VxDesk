"""Assistant settings store: ``ai-settings.json`` at the repo root.

The API key is write-only: :func:`get_settings` never returns it, and nothing
in this package logs it. :func:`get_credentials` is the only accessor and is
used exclusively to build request headers.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import httpx

from ..paths import ROOT

logger = logging.getLogger("vxdesk.ai.settings")

SETTINGS_FILE = ROOT / "ai-settings.json"

PRESETS: list[dict] = [
    {"id": "ollama", "label": "Ollama (local)", "base_url": "http://localhost:11434/v1",
     "needs_key": False, "model_hint": "qwen2.5:7b"},
    {"id": "lmstudio", "label": "LM Studio (local)", "base_url": "http://localhost:1234/v1",
     "needs_key": False, "model_hint": "local-model"},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1",
     "needs_key": True, "model_hint": "gpt-4o-mini"},
    {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "needs_key": True, "model_hint": "openai/gpt-4o-mini"},
    {"id": "moonshot", "label": "Moonshot (Kimi)", "base_url": "https://api.moonshot.ai/v1",
     "needs_key": True, "model_hint": "kimi-k2-0711-preview"},
    {"id": "custom", "label": "Custom (OpenAI-compatible)", "base_url": "",
     "needs_key": True, "model_hint": ""},
]

_DEFAULTS = {
    "provider": "ollama",
    "base_url": "http://localhost:11434/v1",
    "model": "",
    "api_key": None,
}

_UNSET = object()
_lock = threading.Lock()


def _load_raw() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("ai-settings.json unreadable (%s); using defaults", exc)
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    for key in _DEFAULTS:
        if key in data:
            merged[key] = data[key]
    return merged


def _save_raw(data: dict) -> None:
    with _lock:
        SETTINGS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _public(raw: dict) -> dict:
    return {
        "provider": raw.get("provider", "ollama"),
        "base_url": raw.get("base_url", ""),
        "model": raw.get("model", ""),
        "has_api_key": bool(raw.get("api_key")),
        "presets": PRESETS,
    }


def get_settings() -> dict:
    """Public shape for ``GET /api/ai/settings`` (never contains the key)."""
    return _public(_load_raw())


def update_settings(
    provider: Any = _UNSET,
    base_url: Any = _UNSET,
    model: Any = _UNSET,
    api_key: Any = _UNSET,
) -> dict:
    """Apply a ``PUT /api/ai/settings`` body; returns the public shape.

    ``api_key`` omitted or empty string keeps the existing key; explicit
    ``None`` clears it.
    """
    raw = _load_raw()
    if provider is not _UNSET and provider is not None:
        raw["provider"] = str(provider)
    if base_url is not _UNSET and base_url is not None:
        raw["base_url"] = str(base_url).rstrip("/")
    if model is not _UNSET and model is not None:
        raw["model"] = str(model)
    if api_key is not _UNSET:
        if api_key is None:
            raw["api_key"] = None
        elif str(api_key) != "":
            raw["api_key"] = str(api_key)
        # empty string -> keep existing
    _save_raw(raw)
    return _public(raw)


def get_credentials() -> dict:
    """Internal view including the API key — never serialize to responses/logs."""
    raw = _load_raw()
    return {
        "provider": raw.get("provider", "ollama"),
        "base_url": str(raw.get("base_url") or "").rstrip("/"),
        "model": raw.get("model", ""),
        "api_key": raw.get("api_key") or None,
    }


def probe_status(timeout: float = 4.0) -> dict:
    """Shape for ``GET /api/ai/status``; never raises."""
    creds = get_credentials()
    model = creds["model"]
    base_url = creds["base_url"]
    if not model or not base_url:
        return {
            "configured": False,
            "reachable": False,
            "model": model,
            "detail": "no model chosen yet — pick a provider and model in settings",
        }
    headers = {}
    if creds["api_key"]:
        headers["Authorization"] = f"Bearer {creds['api_key']}"
    try:
        resp = httpx.get(f"{base_url}/models", headers=headers, timeout=timeout)
        if resp.status_code == 401:
            detail = "authentication failed — check the API key"
            return {"configured": True, "reachable": False, "model": model, "detail": detail}
        if resp.status_code >= 400:
            return {
                "configured": True,
                "reachable": False,
                "model": model,
                "detail": f"endpoint returned HTTP {resp.status_code}",
            }
        return {"configured": True, "reachable": True, "model": model, "detail": "connected"}
    except httpx.ConnectError:
        detail = f"could not reach {base_url} — is the model server running?"
    except httpx.TimeoutException:
        detail = f"{base_url} did not answer within {int(timeout)}s"
    except Exception as exc:
        detail = f"probe failed: {exc}"
    return {"configured": True, "reachable": False, "model": model, "detail": detail}
