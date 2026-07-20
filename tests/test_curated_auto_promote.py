# tests/test_curated_auto_promote.py
import os
import pytest
import pytest_asyncio
import asyncpg
from src.workers.stats_refresher import sweep_curated_tiers

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")


@pytest_asyncio.fixture
async def conn():
    c = await asyncpg.connect(DB_URL)
    # isolate: work inside a transaction we roll back
    tx = c.transaction()
    await tx.start()
    yield c
    await tx.rollback()
    await c.close()


async def _seed(conn, address, tier, roi, pnl, resolved, dormant, custom=False):
    await conn.execute(
        "INSERT INTO wallets_v2 (address, tier, is_dormant) VALUES ($1,$2,$3)",
        address, tier, dormant,
    )
    await conn.execute(
        "INSERT INTO wallet_metrics_v2 (address, roi_pct, total_pnl, resolved_count, computed_at) "
        "VALUES ($1,$2,$3,$4, NOW())",
        address, roi, pnl, resolved,
    )
    if custom:
        await conn.execute(
            "INSERT INTO wallet_sources_v2 (address, source, spotted_at) VALUES ($1,'custom',NOW())",
            address,
        )


@pytest.mark.asyncio
async def test_promotes_qualifying_standard_wallet(conn):
    addr = "0x" + "a1" * 20
    await _seed(conn, addr, "STANDARD", roi=45.0, pnl=500.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    tier = await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr)
    assert tier == "CURATED"

@pytest.mark.asyncio
async def test_promotes_on_pnl_alone(conn):
    addr = "0x" + "a2" * 20
    await _seed(conn, addr, "STANDARD", roi=5.0, pnl=15_000.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"


@pytest.mark.asyncio
async def test_promotes_regardless_of_resolved_count(conn):
    # Resolved-count gate was removed (Supabase retired). A qualifying wallet
    # promotes on ROI/PnL alone, even with a tiny resolved_count.
    addr = "0x" + "a3" * 20
    await _seed(conn, addr, "STANDARD", roi=99.0, pnl=99_000.0, resolved=3, dormant=False)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"


@pytest.mark.asyncio
async def test_does_not_promote_below_thresholds(conn):
    # Low ROI and low PnL → stays STANDARD.
    addr = "0x" + "a8" * 20
    await _seed(conn, addr, "STANDARD", roi=5.0, pnl=500.0, resolved=99, dormant=False)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_does_not_promote_dormant(conn):
    addr = "0x" + "a4" * 20
    await _seed(conn, addr, "STANDARD", roi=99.0, pnl=99_000.0, resolved=25, dormant=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_does_not_promote_new_or_low_balance(conn):
    for tier in ("NEW", "LOW_BALANCE"):
        addr = "0x" + ("b" + tier[0].lower()) * 20
        await _seed(conn, addr, tier, roi=99.0, pnl=99_000.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    for tier in ("NEW", "LOW_BALANCE"):
        addr = "0x" + ("b" + tier[0].lower()) * 20
        assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == tier


@pytest.mark.asyncio
async def test_demotes_curated_that_dropped(conn):
    addr = "0x" + "a5" * 20
    # curated but stats now fail; has balance so canonical tier = STANDARD
    await _seed(conn, addr, "CURATED", roi=1.0, pnl=100.0, resolved=25, dormant=False)
    await conn.execute(
        "UPDATE wallet_metrics_v2 SET balance=5000, position_value=0 WHERE address=$1", addr)
    await conn.execute(
        "UPDATE wallets_v2 SET last_trade_at=NOW() WHERE address=$1", addr)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_custom_wallet_never_demoted(conn):
    addr = "0x" + "a6" * 20
    await _seed(conn, addr, "CURATED", roi=1.0, pnl=100.0, resolved=1, dormant=False, custom=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"


@pytest.mark.asyncio
async def test_dormancy_alone_does_not_demote(conn):
    addr = "0x" + "a7" * 20
    # still qualifies on stats, but dormant → stays CURATED (list query hides it)
    await _seed(conn, addr, "CURATED", roi=45.0, pnl=500.0, resolved=25, dormant=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"
