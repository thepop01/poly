import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    val = await conn.fetchval("SELECT COUNT(*) FROM tracked_wallets WHERE COALESCE(balance, 0) > 0 AND status = 'HIBERNATING' AND is_zero_balance = FALSE")
    print(f"Total count: {val}")
    await conn.close()

asyncio.run(run())
