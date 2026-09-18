import pytest
from unittest.mock import AsyncMock, patch
from src.pnl.v2_adapter import V2Adapter, PositionRow, _parse_row, MISSING


def test_zero_pnl_not_silently_dropped():
    """totalPnl=0 must produce source_total_pnl=0, not fall through to total_pnl key."""
    row = {"totalPnl": "0", "total_pnl": "999.99"}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl == 0.0
    assert parsed.source_total_pnl_present is True


def test_missing_pnl_is_explicit_sentinel():
    """A row with no PnL field at all must be distinguishable from a zero."""
    row = {}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl_present is False


def test_outcome_index_zero_preserved():
    """outcomeIndex=0 must not be treated as falsey."""
    row = {"outcomeIndex": 0}
    parsed = _parse_row(row)
    assert parsed.outcome_index == 0


def test_malformed_pnl_marked_invalid():
    """A string like 'N/A' must not silently become 0."""
    row = {"totalPnl": "N/A"}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl_valid is False

SAMPLE_ENVELOPE = {
    "data": [
        {
            "proxyWallet": "0xabc",
            "conditionId": "0x111",
            "eventId": "evt_1",
            "status": "OPEN",
            "outcomeIndex": 0,
            "totalPnl": "1234.56",
            "realizedPnl": "0.00",
            "unrealizedPnl": "1234.56",
            "entryCostUsdc": "800.00",
            "totalCostUsdc": "808.00",
            "entryFeesUsdc": "8.00",
            "avgPrice": "0.80",
            "currentSize": "1000",
            "totalSize": "1000",
            "mergeable": True,
        }
    ],
    "nextCursor": None,
}


@pytest.mark.asyncio
async def test_normalize_open_row():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = SAMPLE_ENVELOPE
        rows = await adapter.fetch_positions("0xabc", status="OPEN")
    assert len(rows) == 1
    r: PositionRow = rows[0]
    assert r.event_id == "evt_1"
    assert r.entry_cost_usdc == 800.00
    assert r.total_cost_usdc == 808.00
    assert r.entry_fees_usdc == 8.00
    assert r.mergeable is True
    assert r.outcome_index == 0
    assert r.source_total_pnl == 1234.56


@pytest.mark.asyncio
async def test_cursor_pagination():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    page1 = {**SAMPLE_ENVELOPE, "nextCursor": "tok_2"}
    page2 = {
        "data": [{**SAMPLE_ENVELOPE["data"][0], "conditionId": "0x222"}],
        "nextCursor": None,
    }
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = [page1, page2]
        rows = await adapter.fetch_positions("0xabc", status="OPEN")
    assert len(rows) == 2
    assert mock_fetch.call_count == 2


@pytest.mark.asyncio
async def test_condition_batching_max_20():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    ids = [f"0x{i:040x}" for i in range(45)]
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"data": [], "nextCursor": None}
        await adapter.fetch_positions_by_conditions("0xabc", ids)
    assert mock_fetch.call_count == 3  # ceil(45/20)
