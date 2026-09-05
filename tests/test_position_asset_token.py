"""Tests for asset_token_id persistence in position sync upserts."""

import pytest

from src.workers.positions_closed_backfill import _parse_token_id as closed_parse
from src.workers.positions_open_backfill import _parse_token_id as open_parse

TOKEN_77 = "112506135920499895973036194948205811788595587475440410000783705571222669619858"
assert len(TOKEN_77) > 70  # far beyond float64's ~16 exact digits


def test_parse_keeps_full_precision():
    assert open_parse(TOKEN_77) == TOKEN_77
    assert closed_parse(TOKEN_77) == TOKEN_77
    assert open_parse("") is None
    assert open_parse(None) is None
    assert open_parse("yes") is None
    assert open_parse("  12345  ") == "12345"


@pytest.mark.asyncio
async def test_open_upsert_stores_exact_token(test_pool):
    from src.workers.positions_open_backfill import aggregate_and_upsert_positions_v2
    addr = "0x0000000000000000000000000000000000009999"
    cid = "0x" + "cc" * 31 + "01"
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO wallets_v2 (address) VALUES ($1) ON CONFLICT DO NOTHING", addr)
            await aggregate_and_upsert_positions_v2(conn, addr, [{
                "conditionId": cid, "outcome": "Yes", "size": 10, "avgPrice": 0.5,
                "currentValue": 5, "asset": TOKEN_77}])
            row = await conn.fetchrow(
                "SELECT size, asset_token_id FROM wallet_positions_v2 "
                "WHERE address=$1 AND condition_id=$2", addr, cid)
            assert float(row["size"]) == 10
            assert str(int(row["asset_token_id"])) == TOKEN_77
        finally:
            await conn.execute("DELETE FROM wallet_positions_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallets_v2 WHERE address=$1", addr)


@pytest.mark.asyncio
async def test_closed_upsert_stores_exact_token(test_pool):
    from src.workers.positions_closed_backfill import upsert_closed_positions_v2
    addr = "0x0000000000000000000000000000000000009998"
    cid = "0x" + "cc" * 31 + "02"
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO wallets_v2 (address) VALUES ($1) ON CONFLICT DO NOTHING", addr)
            n = await upsert_closed_positions_v2(conn, addr, [{
                "conditionId": cid, "outcome": "No", "avgPrice": 0.4,
                "totalBought": 100, "totalSold": 100, "realizedPnl": 5,
                "asset": TOKEN_77}])
            assert n == 1
            row = await conn.fetchrow(
                "SELECT asset_token_id, source_asset FROM wallet_closed_positions_v2 "
                "WHERE address=$1 AND condition_id=$2", addr, cid)
            assert str(int(row["asset_token_id"])) == TOKEN_77
            assert row["source_asset"] == TOKEN_77
        finally:
            await conn.execute(
                "DELETE FROM wallet_closed_positions_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallets_v2 WHERE address=$1", addr)
