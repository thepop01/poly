import pytest


# NOTE: The shared DB fixtures (`test_pool`, `async_client`) are session-scoped
# pytest_asyncio fixtures. Running the test on the session loop (via loop_scope)
# is required so the pool and the request share one event loop; the `anyio`
# marker binds a different loop and errors out (affects the whole DB suite).
@pytest.mark.asyncio(loop_scope="session")
async def test_curated_window_returns_windowed_metrics(async_client, test_pool):
    addr = "0x" + "a" * 40
    async with test_pool.acquire() as conn:
        await conn.execute("INSERT INTO tracked_wallets (address, source_type, added_at, is_curated) "
                           "VALUES ($1,'leaderboard',NOW(),TRUE) ON CONFLICT (address) DO UPDATE SET is_curated=TRUE", addr)
        await conn.execute("DELETE FROM wallet_window_100 WHERE address=$1", addr)
        await conn.execute("INSERT INTO wallet_window_100 (address,category,pnl,volume,win_rate,roi_pct,resolved_count,winning_count) "
                           "VALUES ($1,'OVERALL',777.0,1000.0,0.7,77.7,10,7)", addr)
    resp = await async_client.get("/api/leaderboard/curated-wallets?category=OVERALL&window=100&limit=50")
    assert resp.status_code == 200
    row = next(w for w in resp.json()["wallets"] if w["address"] == addr)
    assert float(row["total_pnl"]) == 777.0
    assert int(row["winning_count"]) == 7
    assert float(row["win_rate"]) == 0.7
