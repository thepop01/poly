import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    rows = await conn.fetch('SELECT address, total_volume, total_pnl, balance FROM tracked_wallets WHERE is_zero_balance = FALSE AND total_volume = 0 AND balance > 0 LIMIT 5')
    print([dict(r) for r in rows])
    await conn.close()

asyncio.run(run())
