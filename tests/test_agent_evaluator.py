import pytest
from datetime import datetime, timezone, timedelta
from src.workers.agent_evaluator import evaluate_agent_against_markets


def _market(mid, price):
    return {
        "market_id": mid, "token_id": f"t{mid}", "title": f"Market {mid}",
        "current_price": price, "total_volume": 1000.0, "liquidity": 10.0,
        "resolution_date": datetime.now(timezone.utc) + timedelta(hours=10),
    }


def test_returns_first_matching_market():
    agent = {"agent_id": 1, "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.15}}
    markets = [_market("a", 0.5), _market("b", 0.10), _market("c", 0.05)]
    hit = evaluate_agent_against_markets(agent, markets)
    assert hit is not None
    market, fired, summary = hit
    assert market["market_id"] == "b"
    assert fired is True


def test_returns_none_when_no_match():
    agent = {"agent_id": 1, "rule_tree": {"field": "current_price", "cmp": "lt", "value": 0.01}}
    markets = [_market("a", 0.5), _market("b", 0.10)]
    assert evaluate_agent_against_markets(agent, markets) is None
