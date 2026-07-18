from datetime import datetime, timezone, timedelta
from src.agents.snapshot import build_snapshot


def _row(**over):
    base = {
        "market_id": "m1",
        "current_price": 0.42,
        "total_volume": 123456.0,
        "liquidity": 5000.0,
        "resolution_date": datetime.now(timezone.utc) + timedelta(hours=48),
    }
    base.update(over)
    return base


def test_snapshot_maps_direct_fields():
    snap = build_snapshot(_row())
    assert snap["current_price"] == 0.42
    assert snap["total_volume"] == 123456.0
    assert snap["liquidity"] == 5000.0


def test_hours_to_resolution_positive():
    snap = build_snapshot(_row())
    assert 47 < snap["hours_to_resolution"] < 49


def test_missing_resolution_date_yields_large_number():
    snap = build_snapshot(_row(resolution_date=None))
    assert snap["hours_to_resolution"] > 10**6


def test_price_change_defaults_zero():
    snap = build_snapshot(_row())
    assert snap["price_change_1h_pct"] == 0.0
    assert snap["price_change_24h_pct"] == 0.0


def test_none_price_coerced():
    snap = build_snapshot(_row(current_price=None))
    assert snap["current_price"] == 0.0
