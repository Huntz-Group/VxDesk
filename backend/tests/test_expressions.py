"""Safe condition-expression evaluator tests."""

from __future__ import annotations

import pytest

from vxdesk.engine.expressions import ExpressionError, evaluate, evaluate_bool


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 + 2 * 3", 7),
        ("10 / 4", 2.5),
        ("7 % 3", 1),
        ("0.9 > 0.8", True),
        ("0.5 >= 0.5", True),
        ("1 < 2 and 2 < 3", True),
        ("1 > 2 or 3 > 2", True),
        ("not (1 > 2)", True),
        ("'a' == 'a'", True),
        ("'abc' != 'abd'", True),
        ("len('hello') == 5", True),
        ("len([1, 2, 3])", 3),
        ("int('42') + 1", 43),
        ("float('0.5') * 2", 1.0),
        ("str(5) == '5'", True),
        ("contains('hello world', 'world')", True),
        ("contains([1, 2, 3], 2)", True),
        ("contains('abc', 'z')", False),
        ("true and not false", True),
        ("1 < 2 < 3", True),  # chained comparison
        ("-5 < 0", True),
    ],
)
def test_allowed_expressions(expr, expected):
    assert evaluate(expr) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "().__class__",
        "open('x')",
        "eval('1')",
        "exec('1')",
        "globals()",
        "x.__class__.__bases__",
        "import os",
        "a = 1",
        "lambda: 1",
        "[x for x in range(3)]",
        "range(10)",  # not whitelisted
        "foo.bar",
        "{'a': 1}['a']",  # subscript not allowed
        "unknown_name == 1",
    ],
)
def test_dangerous_expressions_rejected(expr):
    with pytest.raises((ExpressionError, SyntaxError)):
        evaluate(expr)


def test_evaluate_bool_coerces():
    assert evaluate_bool("0") is False
    assert evaluate_bool("''") is False
    assert evaluate_bool("len('x')") is True
