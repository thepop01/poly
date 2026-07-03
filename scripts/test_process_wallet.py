import asyncio, asyncpg, aiohttp, logging
from src.workers.leaderboard_stats import process_wallet

logging.basicConfig(level=logging.INFO)

async def main():
    pool = await asyncpg.create_pool("postgresql://poly_user:poly_password@localhost:5432/poly_db", min_size=1, max_size=2)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT address FROM tracked_wallets ORDER BY random() LIMIT 1")
        addr = row["address"]
        print(f"Testing process_wallet for {addr}")
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            await process_wallet(conn, session, addr)
        print("process_wallet completed without error")
    await pool.close()

asyncio.run(main())
