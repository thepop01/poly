"""One-off: recompute per-category window tables for all curated wallets."""
import asyncio, aiohttp, asyncpg, os, logging
from src.workers.leaderboard_stats import process_wallet, DB_URL

logging.basicConfig(level=logging.INFO)

async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT address FROM tracked_wallets WHERE is_curated=TRUE")
    addrs = [r["address"] for r in rows]
    logging.info(f"Backfilling {len(addrs)} curated wallets")
    sem = asyncio.Semaphore(int(os.environ.get("STATS_WORKER_CONCURRENCY", "10")))
    done = 0
    async def one(a):
        nonlocal done
        async with sem, pool.acquire() as conn, aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
            try:
                await process_wallet(conn, s, a)
            except Exception as e:
                logging.warning(f"{a[:10]} {e}")
        done += 1
        if done % 50 == 0:
            logging.info(f"progress {done}/{len(addrs)}")
    await asyncio.gather(*[one(a) for a in addrs])
    await pool.close()
    logging.info("backfill complete")

if __name__ == "__main__":
    asyncio.run(main())
