import pytest
from unittest.mock import AsyncMock
from src.workers.positions_open_backfill import upsert_position_with_quarantine


@pytest.mark.asyncio
async def test_bad_row_goes_to_quarantine():
    conn = AsyncMock()
    bad_row = {
        "address": "0xabc", "condition_id": "0x1", "outcome": "YES", "status": "OPEN",
        "total_cost_usdc": 808.0, "entry_cost_usdc": 800.0, "entry_fees_usdc": 8.0,
        # PnL decomposition mismatch (hard): 40+80=120 ≠ 100
        "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 80.0,
        "avg_price": 0.80, "total_size": 1000.0, "current_size": 500.0,
    }
    result = await upsert_position_with_quarantine(conn, bad_row)
    assert result == "quarantined"
    call_sql = conn.execute.call_args[0][0]
    assert "position_quarantine" in call_sql
