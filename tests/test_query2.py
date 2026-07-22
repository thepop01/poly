import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    val1 = await conn.fetchval("SELECT COUNT(*) FROM tracked_wallets WHERE status = 'HIBERNATING'")
    val2 = await conn.fetchval("SELECT COUNT(*) FROM tracked_wallets WHERE last_trade_at < NOW() - INTERVAL '30 days' AND balance > 0")
    print(f"Total HIBERNATING: {val1}")
    print(f"Total >30 days inactive with >0 balance: {val2}")
    await conn.close()

asyncio.run(run())
