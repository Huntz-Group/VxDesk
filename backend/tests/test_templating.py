"""Templating ({{ }}) resolution tests."""

from __future__ import annotations

import pytest

from vxdesk.engine.templating import TemplateError, lookup_path, resolve, resolve_string

CTX = {
    "n1": {"output": {"score": 0.87, "center": {"x": 10, "y": 20}}},
    "vars": {"name": "vx", "count": 3},
    "item": {"col": "abc", "num": 42},
    "rows_src": {"output": {"rows": [{"a": 1}, {"a": 2}]}},
}


def test_full_string_token_returns_native_value():
    assert resolve_string("{{ n1.output.score }}", CTX) == 0.87
    assert isinstance(resolve_string("{{ n1.output.score }}", CTX), float)
    assert resolve_string("{{ item.num }}", CTX) == 42
    assert resolve_string("{{ n1.output.center }}", CTX) == {"x": 10, "y": 20}


def test_mixed_string_substitution():
    assert resolve_string("score={{ n1.output.score }}!", CTX) == "score=0.87!"
    assert resolve_string("hello {{ vars.name }} / {{ item.col }}", CTX) == "hello vx / abc"


def test_nested_dict_and_list_resolution():
    value = {"a": "{{ vars.name }}", "b": ["{{ item.num }}", 1], "c": 5}
    assert resolve(value, CTX) == {"a": "vx", "b": [42, 1], "c": 5}


def test_non_string_passthrough():
    assert resolve(42, CTX) == 42
    assert resolve(None, CTX) is None
    assert resolve({"x": 1}, CTX) == {"x": 1}


def test_missing_path_raises():
    with pytest.raises(TemplateError):
        resolve_string("{{ n9.output.score }}", CTX)
    with pytest.raises(TemplateError):
        resolve_string("{{ n1.output.missing_key }}", CTX)
    with pytest.raises(TemplateError):
        resolve_string("{{ vars }}", {})  # no 'vars' root


def test_list_indexing():
    assert lookup_path("rows_src.output.rows[1].a", CTX) == 2
    with pytest.raises(TemplateError):
        lookup_path("rows_src.output.rows[9].a", CTX)


def test_dot_path_deep_lookup():
    assert lookup_path("n1.output.center.x", CTX) == 10
