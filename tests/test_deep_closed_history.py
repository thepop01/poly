import pytest

from src.workers import wallet_trade_history as history


@pytest.mark.asyncio
async def test_activity_market_discovery_returns_ids_from_complete_window(monkeypatch):
    async def fake_page(_session, _address, _start, _end, offset, _limiter):
        if offset == 0:
            return [{"timestamp": 10, "conditionId": "market-a"}, {"timestamp": 11, "conditionId": "market-b"}]
        return []

    monkeypatch.setattr(history, "_activity_page", fake_page)
    market_ids, complete = await history.fetch_activity_market_ids(object(), "0xabc")

    assert complete is True
    assert market_ids == {"market-a", "market-b"}


@pytest.mark.asyncio
async def test_activity_market_discovery_does_not_claim_complete_after_request_failure(monkeypatch):
    async def failed_page(*_args, **_kwargs):
        return None

    monkeypatch.setattr(history, "_activity_page", failed_page)
    market_ids, complete = await history.fetch_activity_market_ids(object(), "0xabc")

    assert market_ids == set()
    assert complete is False
