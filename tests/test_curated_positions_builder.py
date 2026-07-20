# tests/test_curated_positions_builder.py
import pytest
from src.workers.curated_positions_builder import classify_position


def test_hold_to_zero_loser_counts_as_loss():
    # bought $100, never sold, market resolved, held losing outcome
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": True, "winning_outcome": "No"}
    r = classify_position(pos, res)
    assert r["is_resolved"] is True
    assert r["is_win"] is False
    assert r["payout"] == 0.0
    assert r["realized_pnl"] == -100.0


def test_winner_gets_payout():
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": True, "winning_outcome": "Yes"}
    r = classify_position(pos, res)
    assert r["payout"] == 200.0
    assert r["realized_pnl"] == 100.0
    assert r["is_win"] is True


def test_unresolved_is_open():
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": False, "winning_outcome": None}
    r = classify_position(pos, res)
    assert r["is_resolved"] is False
    assert r["is_win"] is False


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
