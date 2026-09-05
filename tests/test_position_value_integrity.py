import pytest


@pytest.mark.asyncio
async def test_balance_is_not_a_copy_of_position_value(test_pool):
    """balance is cash; position_value is marked-to-market holdings.

    Baseline on 2026-08-30 was 90,014 duplicated wallets. This test locks in
    improvement and fails if a regression pushes the count back up.
    """
    async with test_pool.acquire() as conn:
        duplicated = await conn.fetchval("""
            SELECT count(*) FROM wallet_metrics_v2
            WHERE balance IS NOT NULL AND position_value IS NOT NULL
              AND position_value <> 0
              AND abs(balance - position_value) < 0.01
        """)
    assert duplicated < 90_014, (
        f"{duplicated} wallets still have balance == position_value"
    )


@pytest.mark.asyncio
async def test_total_pnl_is_not_a_verbatim_copy_of_pm_pnl(test_pool):
    """Baseline was 38,769 wallets with total_pnl == pm_pnl exactly."""
    async with test_pool.acquire() as conn:
        overridden = await conn.fetchval("""
            SELECT count(*) FROM wallet_metrics_v2
            WHERE pm_pnl IS NOT NULL AND total_pnl IS NOT NULL
              AND pm_pnl <> 0
              AND abs(pm_pnl - total_pnl) < 0.01
        """)
    assert overridden < 38_769, (
        f"{overridden} wallets still mirror pm_pnl into total_pnl"
    )


@pytest.mark.asyncio
async def test_position_value_is_populated_where_open_rows_exist(test_pool):
    """No wallet should hold open rows yet report zero position_value."""
    async with test_pool.acquire() as conn:
        gap = await conn.fetchval("""
            SELECT count(*)
            FROM wallet_metrics_v2 m
            JOIN (
                SELECT address, SUM(current_value) AS total_val
                FROM wallet_positions_v2
                GROUP BY address
            ) p ON p.address = m.address
            WHERE (m.position_value IS NULL OR m.position_value = 0)
              AND p.total_val > 0
        """)
    assert gap == 0, f"{gap} wallets have open rows but position_value = 0"
