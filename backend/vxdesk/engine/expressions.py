"""Safe expression evaluator for ``control.condition`` nodes.

Parses with :mod:`ast` and walks a strict whitelist: comparisons, boolean ops,
arithmetic, numbers/strings/booleans/None, and the helper functions ``len()``,
``int()``, ``float()``, ``str()``, ``contains(a, b)``. Attribute access, imports,
subscripts and every other builtin are rejected — ``eval()`` is never used on
arbitrary code.
"""

from __future__ import annotations

import ast
from typing import Any


class ExpressionError(Exception):
    """The condition expression is not allowed or could not be evaluated."""


def _contains(a: Any, b: Any) -> bool:
    try:
        return b in a
    except TypeError:
        return False


_FUNCTIONS = {
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "contains": _contains,
}

_NAMES = {"true": True, "false": False, "True": True, "False": False, "None": None, "null": None}

_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}

_CMP_OPS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.BinOp,
    ast.Compare,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.List,
    ast.Tuple,
) + tuple(_BIN_OPS) + tuple(_CMP_OPS)


def evaluate(expression: str) -> Any:
    """Evaluate ``expression`` under the whitelist; returns the native result."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expression!r}: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(
                f"disallowed syntax in expression {expression!r}: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in _NAMES and node.id not in _FUNCTIONS:
            raise ExpressionError(f"unknown name in expression {expression!r}: {node.id!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise ExpressionError(f"only whitelisted functions allowed in {expression!r}")
            if node.keywords:
                raise ExpressionError(f"keyword arguments not allowed in {expression!r}")

    return _eval(tree.body)


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return _NAMES[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e) for e in node.elts]
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _eval(value)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _eval(value)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.left), _eval(node.right))
    if isinstance(node, ast.Compare):
        left = _eval(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _CMP_OPS.get(type(op_node))
            if op is None:
                raise ExpressionError(f"comparison not allowed: {type(op_node).__name__}")
            right = _eval(comparator)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        func = _FUNCTIONS[node.func.id]  # type: ignore[union-attr]
        return func(*[_eval(a) for a in node.args])
    raise ExpressionError(f"unsupported expression element: {type(node).__name__}")


def evaluate_bool(expression: str) -> bool:
    return bool(evaluate(expression))
