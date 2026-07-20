# tests/test_curated_positions_builder.py
import pytest
from src.workers.curated_positions_builder import classify_position


def test_hold_to_zero_loser_counts_as_loss():
    # open position on a resolved market, rode to zero: realizedPnl + cashPnl < 0
    pos = {"redeemable": True, "realizedPnl": 0.0, "cashPnl": -100.0,
           "totalBought": 100.0, "size": 200.0, "currentValue": 0.0, "outcome": "Yes"}
    r = classify_position(pos, is_closed_endpoint=False)
    assert r["is_resolved"] is True
    assert r["is_win"] is False
    assert r["realized_pnl"] == -100.0


def test_sold_before_resolution_at_profit_is_a_win():
    # Held the LOSING outcome but exited early at a profit — must count as a WIN.
    # This is the case the old outcome-matching logic scored as a loss.
    pos = {"redeemable": True, "realizedPnl": 6103.9, "cashPnl": -177.0,
           "totalBought": 189281.0, "size": 177048.0, "currentValue": 0.0, "outcome": "DN SOOPers"}
    r = classify_position(pos, is_closed_endpoint=False)
    assert r["is_win"] is True
    assert round(r["realized_pnl"], 1) == 5926.9


def test_closed_position_uses_realized_pnl():
    pos = {"realizedPnl": 139020.2, "totalBought": 5000.0, "outcome": "Yes"}
    r = classify_position(pos, is_closed_endpoint=True)
    assert r["is_resolved"] is True
    assert r["is_win"] is True
    assert r["realized_pnl"] == 139020.2


def test_open_unresolved_is_excluded():
    pos = {"redeemable": False, "realizedPnl": 0.0, "cashPnl": 50.0,
           "totalBought": 100.0, "size": 200.0, "outcome": "Yes"}
    assert classify_position(pos, is_closed_endpoint=False) is None


import os, pytest_asyncio, asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")


@pytest.mark.asyncio
async def test_win_rate_query_counts_losers():
    c = await asyncpg.connect(DB_URL)
    tx = c.transaction(); await tx.start()
    addr = "0x" + "cc" * 20
    await c.execute("INSERT INTO curated_positions (address,condition_id,outcome,is_resolved,is_win) VALUES ($1,'0x1','Yes',true,true)", addr)
    await c.execute("INSERT INTO curated_positions (address,condition_id,outcome,is_resolved,is_win) VALUES ($1,'0x2','No',true,false)", addr)
    row = await c.fetchrow("SELECT COUNT(*) FILTER (WHERE is_resolved) r, COUNT(*) FILTER (WHERE is_win) w FROM curated_positions WHERE address=$1", addr)
    assert row["r"] == 2 and row["w"] == 1  # loser is in the denominator
    await tx.rollback(); await c.close()
