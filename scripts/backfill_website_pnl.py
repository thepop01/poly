"""Backfill website_pnl for all tracked wallets not yet populated."""
import asyncio, asyncpg, aiohttp
from src.workers.leaderboard_stats import fetch_website_pnl

CONCURRENCY = 15

async def process_one(session, pool, sem, addr, i, total):
    async with sem:
        w = await fetch_website_pnl(session, addr)
        if w:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE tracked_wallets SET website_pnl=$2, website_volume=$3, website_rank=$4, username=$5, website_pnl_updated_at=NOW() WHERE address=$1",
                    addr, w["pnl"], w["volume"], w["rank"], w["username"],
                )
        if i % 50 == 0:
            print(f"  [{i}/{total}] done")

async def backfill():
    pool = await asyncpg.create_pool("postgresql://poly_user:poly_password@localhost:5432/poly_db", min_size=3, max_size=10)
    rows = await pool.fetch("SELECT address FROM tracked_wallets WHERE website_pnl IS NULL ORDER BY added_at ASC")
    total = len(rows)
    print(f"Backfilling {total} wallets...")
    sem = asyncio.Semaphore(CONCURRENCY)
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        tasks = [process_one(session, pool, sem, r["address"], i+1, total) for i, r in enumerate(rows)]
        await asyncio.gather(*tasks)
    await pool.close()
    print("Done.")

asyncio.run(backfill())
