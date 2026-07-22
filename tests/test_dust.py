import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()
async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    count = await conn.fetchval('SELECT COUNT(*) FROM tracked_wallets WHERE is_zero_balance = FALSE AND balance < 1.0')
    print("Dust wallets (< $1.00):", count)
    await conn.close()
asyncio.run(run())
