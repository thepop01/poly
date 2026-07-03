"""Tests for src.data_client — hits the live Polymarket Data API."""

import pytest
from src.data_client import fetch_user_activity, fetch_market_trades, _parse_trade

@pytest.mark.skip(reason="Hits live API - needs mocking for CI")
@pytest.mark.asyncio
async def test_fetch_user_activity_handles_no_user():
    # Provide a dummy wallet
    trades = await fetch_user_activity("0x0000000000000000000000000000000000000000", limit=1)
    # The API might return empty or 404
    assert isinstance(trades, list)

@pytest.mark.skip(reason="Hits live API - needs mocking for CI")
@pytest.mark.asyncio
async def test_fetch_market_trades_returns_list():
    # Use a dummy or generic market id, the API might return empty list
    trades = await fetch_market_trades("dummy_market_id", limit=1)
    assert isinstance(trades, list)

def test_parse_trade():
    raw = {
        "transactionHash": "0xabc123",
        "user": "0xuser456",
        "conditionId": "cond789",
        "asset": "tokenXYZ",
        "outcome": "YES",
        "price": "0.45",
        "size": "100.5",
        "fee": "0",
        "timestamp": "2026-01-01T12:00:00Z"
    }
    trade = _parse_trade(raw)
    assert trade.tx_hash == "0xabc123"
    assert trade.wallet_address == "0xuser456"
    assert trade.market_id == "cond789"
    assert trade.side == "YES"
    assert trade.price == 0.45
    assert trade.size == 100.5
