"""Pure, eval-free evaluator for agent condition rule trees.

A rule tree is JSON: group nodes {"op": "and"|"or", "children": [...]} and
leaf nodes {"field": <whitelisted>, "cmp": <op>, "value": <number>}.
Evaluation is deterministic and never executes arbitrary code.
"""
from typing import Any

ALLOWED_FIELDS: set[str] = {
    "current_price",
    "total_volume",
    "liquidity",
    "price_change_1h_pct",
    "price_change_24h_pct",
    "hours_to_resolution",
}

_CMP = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


class RuleError(ValueError):
    """Raised when a rule tree is structurally invalid."""


def validate_rule_tree(node: Any) -> None:
    """Raise RuleError if the tree is malformed. No return value."""
    if not isinstance(node, dict):
        raise RuleError("node must be an object")
    if "op" in node:
        if node["op"] not in ("and", "or"):
            raise RuleError(f"unknown op: {node['op']!r}")
        children = node.get("children")
        if not isinstance(children, list):
            raise RuleError("group node needs a 'children' list")
        for child in children:
            validate_rule_tree(child)
        return
    # leaf
    field = node.get("field")
    if field not in ALLOWED_FIELDS:
        raise RuleError(f"unknown field: {field!r}")
    if node.get("cmp") not in _CMP:
        raise RuleError(f"unknown cmp: {node.get('cmp')!r}")
    if not isinstance(node.get("value"), (int, float)) or isinstance(node.get("value"), bool):
        raise RuleError("value must be a number")


def evaluate(node: dict, snapshot: dict[str, float]) -> tuple[bool, str]:
    """Return (fired, human_summary). Missing snapshot fields evaluate False."""
    if "op" in node:
        results = [evaluate(c, snapshot) for c in node.get("children", [])]
        if not results:
            return False, "(empty group)"
        if node["op"] == "and":
            fired = all(r[0] for r in results)
            joiner = " AND "
        else:
            fired = any(r[0] for r in results)
            joiner = " OR "
        summary = joiner.join(r[1] for r in results)
        return fired, f"({summary})"
    field = node["field"]
    cmp = node["cmp"]
    value = node["value"]
    actual = snapshot.get(field)
    if actual is None:
        return False, f"{field}(missing){cmp}{value}=False"
    fired = _CMP[cmp](actual, value)
    return fired, f"{field}({actual}){cmp}{value}={fired}"
