"""Evaluate the condition strings on If / While blocks.

These blocks have carried a `condition` input since they were added, and
nothing ever evaluated it - the block returned the string back as
`status: "simulated"` and the runner then took every outgoing edge anyway. So
`if` ran both branches and `while` ran its body exactly once. This module is
the missing half: it turns that string into a decision.

Deliberately NOT `eval`. A condition comes from a workflow file, which is data
- it can be edited by hand, copied between machines, or arrive from someone
else. Running it as Python would make "open this workflow" mean "run this
code", on a machine wired to motors. Only a small, explicitly allowed grammar
is accepted:

    $in.temperature > 40
    $blocks.calibrate_z.calibrated == true
    item.volume_ml >= 1 and not $in.aborted
    $run.iteration < 5

Anything outside it - calls, attribute access on arbitrary objects, imports,
comprehensions - is refused with a message naming what was rejected, rather
than silently evaluating to false. A condition nobody can read is worse than
one that fails loudly.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any

# n8n-style {{ ... }} wrapping is accepted so a condition copied from that
# world still works; the braces are just stripped.
_TEMPLATE = re.compile(r"^\s*\{\{(?P<body>.*)\}\}\s*$", re.DOTALL)

# `$in.x` is the documented way to reach run data, but `$` is not valid Python
# so it cannot reach the parser as written. Rewrite `$name` to a plain
# identifier first - matching quoted strings in the same pass so a `$` inside a
# string literal is left exactly as the author typed it.
_SIGIL = re.compile(r"""(?P<string>"[^"]*"|'[^']*')|\$(?P<name>[A-Za-z_]\w*)""")
_SIGIL_PREFIX = "_ctx_"


def _rewrite_sigils(expression: str) -> str:
    def replace(match: "re.Match[str]") -> str:
        if match.group("string") is not None:
            return match.group("string")
        return _SIGIL_PREFIX + match.group("name")

    return _SIGIL.sub(replace, expression)


def _rewrite_context(context: dict) -> dict:
    """Expose `$in` as the identifier the rewritten expression will look for."""
    rewritten: dict = {}
    for key, value in context.items():
        rewritten[key] = value
        if isinstance(key, str) and key.startswith("$"):
            rewritten[_SIGIL_PREFIX + key[1:]] = value
    return rewritten

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


_LITERAL_NAMES: dict[str, Any] = {
    "true": True, "True": True,
    "false": False, "False": False,
    "null": None, "none": None, "None": None,
}


class ConditionError(ValueError):
    """The condition could not be understood, or referred to missing data."""


@dataclass(frozen=True)
class ConditionResult:
    value: bool
    expression: str
    detail: str

    def as_dict(self) -> dict:
        return {"value": self.value, "expression": self.expression, "detail": self.detail}


def _lookup(context: dict, parts: list[str], original: str) -> Any:
    """Walk a dotted path through plain dicts/lists from the run context."""
    current: Any = context
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if isinstance(current, dict):
            if part not in current:
                raise ConditionError(
                    f"'{original}' refers to {'.'.join(walked).replace('_ctx_', '$')}, which is not in the "
                    f"data available here. Available at that level: "
                    f"{', '.join(sorted(str(k) for k in current if not str(k).startswith('_ctx_'))) or '(nothing)'}."
                )
            current = current[part]
            continue
        if isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                raise ConditionError(
                    f"'{original}' indexes {'.'.join(walked[:-1])} with '{part}', which is not a valid position."
                ) from None
        raise ConditionError(
            f"'{original}' tries to read '{part}' from a {type(current).__name__}, which has no fields."
        )
    return current


def _flatten_attribute(node: ast.AST) -> list[str] | None:
    """Turn `$in.a.b` (parsed as nested Attribute on a Name) into a path."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return None


class _Evaluator(ast.NodeVisitor):
    def __init__(self, context: dict, expression: str) -> None:
        self.context = context
        self.expression = expression

    def generic_visit(self, node: ast.AST):  # noqa: ANN201
        raise ConditionError(
            f"'{self.expression}' uses {type(node).__name__}, which is not allowed in a condition. "
            "Conditions may only compare values, combine them with and/or/not, and do simple arithmetic."
        )

    def visit_Expression(self, node: ast.Expression):  # noqa: N802, ANN201
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant):  # noqa: N802, ANN201
        return node.value

    def visit_Name(self, node: ast.Name):  # noqa: N802, ANN201
        # Authors write these the JavaScript/n8n way, and the blocks came from
        # that world; accept both spellings rather than failing on `true`.
        if node.id in _LITERAL_NAMES:
            return _LITERAL_NAMES[node.id]
        return _lookup(self.context, [node.id], self.expression)

    def visit_Attribute(self, node: ast.Attribute):  # noqa: N802, ANN201
        parts = _flatten_attribute(node)
        if parts is None:
            raise ConditionError(f"'{self.expression}' has a reference this evaluator cannot follow.")
        return _lookup(self.context, parts, self.expression)

    def visit_Subscript(self, node: ast.Subscript):  # noqa: N802, ANN201
        target = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return target[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ConditionError(f"'{self.expression}' could not read [{key!r}]: {exc}") from None

    def visit_UnaryOp(self, node: ast.UnaryOp):  # noqa: N802, ANN201
        if isinstance(node.op, ast.Not):
            return not _truthy(self.visit(node.operand))
        if isinstance(node.op, ast.USub):
            return -self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +self.visit(node.operand)
        return self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):  # noqa: N802, ANN201
        values = node.values
        if isinstance(node.op, ast.And):
            result = True
            for value in values:
                result = _truthy(self.visit(value))
                if not result:
                    return False
            return result
        if isinstance(node.op, ast.Or):
            for value in values:
                if _truthy(self.visit(value)):
                    return True
            return False
        return self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):  # noqa: N802, ANN201
        handler = _BIN_OPS.get(type(node.op))
        if handler is None:
            return self.generic_visit(node)
        try:
            return handler(self.visit(node.left), self.visit(node.right))
        except ZeroDivisionError:
            raise ConditionError(f"'{self.expression}' divides by zero.") from None
        except TypeError as exc:
            raise ConditionError(f"'{self.expression}' cannot combine those values: {exc}") from None

    def visit_Compare(self, node: ast.Compare):  # noqa: N802, ANN201
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            handler = _COMPARE_OPS.get(type(op))
            if handler is None:
                return self.generic_visit(node)
            right = self.visit(comparator)
            try:
                if not handler(left, right):
                    return False
            except TypeError as exc:
                raise ConditionError(
                    f"'{self.expression}' compares {type(left).__name__} with {type(right).__name__}: {exc}"
                ) from None
            left = right
        return True

    def visit_List(self, node: ast.List):  # noqa: N802, ANN201
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple):  # noqa: N802, ANN201
        return tuple(self.visit(item) for item in node.elts)


def _truthy(value: Any) -> bool:
    """Python truthiness, with the string forms an operator would expect."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "no", "off", "0", ""}:
            return False
        if normalized in {"true", "yes", "on", "1"}:
            return True
        return True
    return bool(value)


def evaluate_condition(expression: str | None, context: dict) -> ConditionResult:
    """Decide a branch. Raises ConditionError when the condition is unusable."""
    raw = (expression or "").strip()
    template = _TEMPLATE.match(raw)
    if template:
        raw = template.group("body").strip()

    if not raw:
        # An empty condition is a mistake, but it must not be an infinite loop
        # or a coin toss: false stops a while loop and takes the false branch.
        return ConditionResult(
            value=False,
            expression="",
            detail="No condition was set, so it is treated as false.",
        )

    parseable = _rewrite_sigils(raw)
    try:
        tree = ast.parse(parseable, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"'{raw}' is not a condition this evaluator can read: {exc.msg}.") from None

    value = _Evaluator(_rewrite_context(context), raw).visit(tree)
    return ConditionResult(
        value=_truthy(value),
        expression=raw,
        detail=f"{raw} -> {value!r}",
    )
