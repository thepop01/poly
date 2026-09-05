import pytest
from datetime import datetime, timezone
import json
from decimal import Decimal

def test_db_normalize_db_url():
    from src.db import _normalize_db_url
    
    # 1. Localhost replaced with 127.0.0.1 without touching user/pass
    url1, ssl1 = _normalize_db_url("postgresql://user:pass_localhost@localhost:5432/mydb")
    assert "127.0.0.1:5432" in url1
    assert "pass_localhost" in url1
    assert ssl1 is False

    # 2. Remote host requires SSL
    url2, ssl2 = _normalize_db_url("postgres://user:pass@db.example.com:5432/mydb")
    assert url2.startswith("postgresql://")
    assert ssl2 == "require"

    # 3. Explicit sslmode=disable
    url3, ssl3 = _normalize_db_url("postgresql://user:pass@db.example.com:5432/mydb?sslmode=disable")
    assert ssl3 is False


def test_etherscan_client_empty_key():
    import src.utils.etherscan_client as ec
    ec._polygonscan_keys = []
    ec._polygonscan_key_cycle = None
    
    # Mock _load_polygonscan_keys to return []
    orig_load = ec._load_polygonscan_keys
    try:
        ec._load_polygonscan_keys = lambda: []
        key = ec._get_next_polygonscan_key()
        assert key == ""
    finally:
        ec._load_polygonscan_keys = orig_load


def test_dust_position_win_rate_logic():
    from src.workers.leaderboard_stats import compute_stats

    # A losing dust position (curPrice=0.01, currentValue=10, not redeemable)
    dust_pos = [{
        "conditionId": "0x123",
        "asset": "YES",
        "avgPrice": "0.50",
        "curPrice": "0.01",
        "currentValue": "10.0",
        "cashPnl": "-490.0",
        "realizedPnl": "0.0",
        "redeemable": False,
    }]
    
    res = compute_stats(dust_pos, [], 0.0, 0.0, None, 0.0)
    # Dust position should be counted as resolved loss, NOT a win
    assert res["resolved_count"] == 1
    assert res["winning_count"] == 0
    assert res["win_rate"] == 0.0


def test_redeemable_win_rate_logic():
    from src.workers.leaderboard_stats import compute_stats

    # A winning redeemable position (redeemable=True, currentValue=500.0)
    win_pos = [{
        "conditionId": "0x123",
        "asset": "YES",
        "avgPrice": "0.50",
        "curPrice": "1.0",
        "currentValue": "500.0",
        "cashPnl": "250.0",
        "realizedPnl": "0.0",
        "redeemable": True,
    }]
    
    res = compute_stats(win_pos, [], 0.0, 0.0, None, 0.0)
    assert res["resolved_count"] == 1
    assert res["winning_count"] == 1
    assert res["win_rate"] == 100.0


def test_is_parlay_heuristics():
    from src.workers.positions_winrate_backfill import _is_parlay as backfill_is_parlay
    from src.api.routers.wallets_v2 import _is_parlay_position as api_is_parlay

    # Title with "AND" in text should NOT be falsely classified as parlay
    regular_pos = {"title": "Will Trump AND Harris debate in September?"}
    assert backfill_is_parlay(regular_pos) is False
    assert api_is_parlay(regular_pos) is False

    # Title with "PARLAY" or "COMBO" or isCombo=True
    parlay_pos1 = {"title": "3-Leg NBA Parlay #1234"}
    parlay_pos2 = {"isCombo": True}
    assert backfill_is_parlay(parlay_pos1) is True
    assert backfill_is_parlay(parlay_pos2) is True
    assert api_is_parlay(parlay_pos1) is True
    assert api_is_parlay(parlay_pos2) is True


def test_ws_json_serializability():
    # Verify that datetime and decimal objects can be serialized via custom encoder or default=str
    data = {
        "id": 1,
        "address": "0x1234567890abcdef1234567890abcdef12345678",
        "event_type": "TRADE",
        "amount_usdc": 1500.50,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps({"type": "ACTIVITY_UPDATE", "data": [data]}, default=str)
    parsed = json.loads(payload)
    assert parsed["type"] == "ACTIVITY_UPDATE"
    assert parsed["data"][0]["amount_usdc"] == 1500.50
