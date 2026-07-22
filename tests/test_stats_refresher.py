import asyncio
import asyncpg
import aiohttp
import os
import logging
from src.workers.stats_refresher import refresh_tracked_wallets

logging.basicConfig(level=logging.INFO)

async def main():
    conn = await asyncpg.connect(os.environ.get('DATABASE_URL', 'postgresql://poly_user:poly_password@localhost:5432/poly_db'))
    async with aiohttp.ClientSession() as s:
        await refresh_tracked_wallets(conn, s)
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
