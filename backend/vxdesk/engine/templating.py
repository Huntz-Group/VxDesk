"""``{{ ... }}`` template resolution for node params.

A string that is exactly one token (``"{{ n1.output.score }}"``) resolves to the
native value (float, dict, list...). Strings mixing tokens with literal text get
plain string substitution. Missing paths raise :class:`TemplateError`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
FULL_TOKEN_RE = re.compile(r"^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$")


class TemplateError(Exception):
    """A template expression could not be resolved."""


def lookup_path(path: str, context: Mapping[str, Any]) -> Any:
    """Resolve a dotted path (with optional ``[i]`` indexes) against ``context``."""
    cur: Any = context
    # split "a.b[0].c" -> ["a", "b", 0, "c"]
    parts: list[Any] = []
    for seg in path.strip().split("."):
        while "[" in seg:
            head, _, rest = seg.partition("[")
            if head:
                parts.append(head)
            idx, _, seg = rest.partition("]")
            if not idx.strip().isdigit():
                raise TemplateError(f"bad index in template path: {path!r}")
            parts.append(int(idx.strip()))
        if seg:
            parts.append(seg)
    if not parts:
        raise TemplateError(f"empty template path: {path!r}")
    for part in parts:
        if isinstance(part, int):
            if isinstance(cur, (list, tuple)) and 0 <= part < len(cur):
                cur = cur[part]
            else:
                raise TemplateError(f"index [{part}] not available at {path!r}")
        elif isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            raise TemplateError(f"template path not found: {path!r} (missing {part!r})")
    return cur


def resolve_string(value: str, context: Mapping[str, Any]) -> Any:
    full = FULL_TOKEN_RE.match(value)
    if full:
        return lookup_path(full.group(1), context)

    def repl(match: re.Match) -> str:
        resolved = lookup_path(match.group(1), context)
        if isinstance(resolved, (dict, list)):
            import json

            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)

    return TOKEN_RE.sub(repl, value)


def resolve(value: Any, context: Mapping[str, Any]) -> Any:
    """Deep-resolve templates in strings / lists / dicts; other types pass through."""
    if isinstance(value, str):
        return resolve_string(value, context)
    if isinstance(value, list):
        return [resolve(v, context) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, context) for k, v in value.items()}
    return value
