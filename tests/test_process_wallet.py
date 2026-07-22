import asyncio
import asyncpg
import aiohttp
import logging
from dotenv import load_dotenv
import os
import sys

from src.workers.leaderboard_stats_v2 import process_wallet_v2

load_dotenv()
logging.basicConfig(level=logging.INFO)

async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/test_process_wallet.py <address>")
        return
    address = sys.argv[1]
    
    db_url = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
    
    print(f"Connecting to DB and processing {address}...")
    conn = await asyncpg.connect(db_url)
    async with aiohttp.ClientSession() as session:
        await process_wallet_v2(conn, session, address)
    await conn.close()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
