"""
Tests for Modular Metrics Computation Workers
=============================================
Verifies Worker A (Core Metrics), Worker B (Category Stats), and Worker C (Historical Windows)
individually and collectively.
"""

import pytest
import pytest_asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

from src.workers.compute_core_metrics import compute_core_metrics_for_wallet
from src.workers.compute_category_stats import compute_category_stats_for_wallet
from src.workers.compute_historical_windows import compute_historical_windows_for_wallet
from src.workers.positions_metrics_compute import compute_metrics_for_wallet

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
TEST_WALLET = "0xf0318c32136c2db7fec88b84869aee6a1106c80c" # BreakTheBank

@pytest.mark.asyncio
async def test_worker_a_core_metrics():
    conn = await asyncpg.connect(DB_URL)
    res = await compute_core_metrics_for_wallet(conn, TEST_WALLET)
    assert res is not None
    assert "win_rate" in res
    assert res["resolved_count"] > 0

    # Verify database write
    row = await conn.fetchrow("SELECT win_rate, resolved_count, total_pnl, buys_below_15c FROM wallet_metrics_v2 WHERE address = $1;", TEST_WALLET)
    assert row is not None
    assert row["win_rate"] is not None
    assert float(row["win_rate"]) > 0
    await conn.close()

@pytest.mark.asyncio
async def test_worker_b_category_stats():
    conn = await asyncpg.connect(DB_URL)
    cat_count = await compute_category_stats_for_wallet(conn, TEST_WALLET)
    assert cat_count > 0

    # Verify category scaling: sum of root categories must equal total_pnl
    m = await conn.fetchrow("SELECT total_pnl FROM wallet_metrics_v2 WHERE address = $1;", TEST_WALLET)
    root_cats = await conn.fetch("""
        SELECT SUM(pnl) as root_sum FROM category_stats_v2
        WHERE address = $1 AND window_size = 0 AND subcategory = '' AND league = '' AND category != 'OVERALL';
    """, TEST_WALLET)
    
    assert root_cats[0]["root_sum"] is not None
    assert abs(float(root_cats[0]["root_sum"]) - float(m["total_pnl"])) < 0.01
    await conn.close()

@pytest.mark.asyncio
async def test_worker_c_historical_windows():
    conn = await asyncpg.connect(DB_URL)
    windows = await compute_historical_windows_for_wallet(conn, TEST_WALLET)
    assert "pnl_100" in windows
    assert "pnl_all" in windows

    # Verify database write
    m = await conn.fetchrow("SELECT pnl_100, pnl_200, pnl_300, pnl_5000, pnl_all, total_pnl FROM wallet_metrics_v2 WHERE address = $1;", TEST_WALLET)
    # pnl_all must match pure database total_pnl
    expected_pnl = float(m["total_pnl"] or 0)
    assert abs(float(m["pnl_all"]) - expected_pnl) < 0.01
    await conn.close()

@pytest.mark.asyncio
async def test_master_coordinator():
    conn = await asyncpg.connect(DB_URL)
    await compute_metrics_for_wallet(conn, None, TEST_WALLET)

    m = await conn.fetchrow("SELECT win_rate, total_pnl, pnl_100, pnl_5000, computed_at FROM wallet_metrics_v2 WHERE address = $1;", TEST_WALLET)
    assert m["computed_at"] is not None
    assert m["win_rate"] is not None
    assert m["pnl_100"] is not None
    await conn.close()
