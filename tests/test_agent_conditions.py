import pytest
from src.agents.conditions import evaluate, validate_rule_tree, ALLOWED_FIELDS, RuleError


def test_leaf_true():
    tree = {"field": "current_price", "cmp": "lt", "value": 0.15}
    fired, summary = evaluate(tree, {"current_price": 0.10})
    assert fired is True
    assert "current_price" in summary


def test_leaf_false():
    tree = {"field": "current_price", "cmp": "lt", "value": 0.15}
    fired, _ = evaluate(tree, {"current_price": 0.20})
    assert fired is False


def test_and_requires_all():
    tree = {"op": "and", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"field": "total_volume", "cmp": "gte", "value": 100000},
    ]}
    assert evaluate(tree, {"current_price": 0.1, "total_volume": 100000})[0] is True
    assert evaluate(tree, {"current_price": 0.1, "total_volume": 50000})[0] is False


def test_or_requires_any():
    tree = {"op": "or", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"field": "total_volume", "cmp": "gte", "value": 100000},
    ]}
    assert evaluate(tree, {"current_price": 0.9, "total_volume": 100000})[0] is True
    assert evaluate(tree, {"current_price": 0.9, "total_volume": 1})[0] is False


def test_missing_field_is_false_not_crash():
    tree = {"field": "price_change_1h_pct", "cmp": "gte", "value": 20}
    fired, _ = evaluate(tree, {"current_price": 0.5})
    assert fired is False


def test_validate_rejects_unknown_field():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "wallet_balance", "cmp": "gt", "value": 1})


def test_validate_rejects_unknown_cmp():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "current_price", "cmp": "matches", "value": 1})


def test_validate_rejects_non_numeric_value():
    with pytest.raises(RuleError):
        validate_rule_tree({"field": "current_price", "cmp": "lt", "value": "cheap"})


def test_validate_accepts_nested_tree():
    tree = {"op": "and", "children": [
        {"field": "current_price", "cmp": "lt", "value": 0.15},
        {"op": "or", "children": [
            {"field": "total_volume", "cmp": "gte", "value": 100000},
            {"field": "hours_to_resolution", "cmp": "lte", "value": 24},
        ]},
    ]}
    validate_rule_tree(tree)  # should not raise
    assert "hours_to_resolution" in ALLOWED_FIELDS
