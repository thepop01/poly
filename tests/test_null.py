import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    rows = await conn.fetch('SELECT address, total_volume, balance FROM tracked_wallets WHERE is_zero_balance = FALSE AND total_volume > 0 AND last_trade_at IS NULL')
    print(f'Count: {len(rows)}')
    print([dict(r) for r in rows[:5]])
    await conn.close()

asyncio.run(run())
