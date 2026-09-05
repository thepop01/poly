from scripts.backtest_activity_pnl import activity_cash_delta
from src.scripts.archive_activity_parquet import archive_events
from src.scripts.audit_position_activity_coverage import (
    _activity_lifecycle_summary,
    _restore_activity_event,
)
import pytest


def test_activity_cash_delta_uses_real_cash_fields():
    assert activity_cash_delta({"type": "TRADE", "side": "BUY", "usdcSize": 25}) == (-25.0, "buys")
    assert activity_cash_delta({"type": "TRADE", "side": "SELL", "usdcSize": 30}) == (30.0, "sells")
    assert activity_cash_delta({"type": "REDEEM", "usdcSize": 100}) == (100.0, "redeem")
    assert activity_cash_delta({"type": "CONVERSION", "size": 90, "usdcSize": 0}) == (0.0, "noncash:conversion")
    assert activity_cash_delta({"type": "MAKER_REBATE", "usdcSize": 12}) == (12.0, "maker_rebate")


def test_unknown_activity_is_not_silently_counted():
    assert activity_cash_delta({"type": "TRANSFER", "usdcSize": 100}) == (0.0, "unhandled:TRANSFER")


def test_lifecycle_summary_keeps_buy_sell_redeem_separate():
    summary = _activity_lifecycle_summary([
        {"type": "TRADE", "side": "BUY", "timestamp": 10, "size": 10, "usdcSize": 4},
        {"type": "TRADE", "side": "SELL", "timestamp": 20, "size": 3, "usdcSize": 2},
        {"type": "REDEEM", "timestamp": 30, "size": 7, "usdcSize": 7},
    ])
    assert summary["activity_buy_shares"] == 10
    assert summary["activity_sell_shares"] == 3
    assert summary["activity_redeem_shares"] == 7
    assert summary["activity_net_shares"] == 0
    assert summary["activity_event_count"] == summary["activity_distinct_event_count"] == 3


def test_stored_activity_payload_restores_api_keys():
    event = _restore_activity_event({
        "payload": '{"conditionId":"0x1","type":"TRADE","side":"BUY","usdcSize":4}',
        "condition_id": "wrong-fallback",
        "event_type": "REDEEM",
        "side": None,
        "size": 10,
        "usdc_size": 99,
        "price": 0.4,
    })
    assert event["conditionId"] == "0x1"
    assert event["type"] == "TRADE"
    assert event["side"] == "BUY"
    assert event["usdcSize"] == 4


def test_activity_archive_round_trip(tmp_path):
    try:
        import pyarrow  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("PyArrow native runtime is unavailable in this environment")
    info = archive_events([
        {"conditionId": "0x1", "outcome": "Yes", "type": "TRADE", "side": "BUY",
         "timestamp": 10, "size": 2, "usdcSize": 1, "price": 0.5},
        {"conditionId": "0x1", "outcome": "Yes", "type": "REDEEM",
         "timestamp": 20, "size": 2, "usdcSize": 2},
    ], "0x" + "1" * 40, tmp_path)
    assert info["row_count"] == 2
    assert len(info["sha256"]) == 64
