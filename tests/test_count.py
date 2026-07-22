import asyncio, asyncpg, os
from dotenv import load_dotenv
load_dotenv()
async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    val = await conn.fetchval('SELECT COUNT(*) FROM tracked_wallets WHERE is_zero_balance = FALSE AND (total_volume = 0 OR total_volume IS NULL)')
    print("Zero volume count:", val)
    val2 = await conn.fetchval('SELECT COUNT(*) FROM tracked_wallets WHERE is_zero_balance = FALSE AND last_trade_at IS NULL')
    print("Null last_trade_at count:", val2)
    await conn.close()
asyncio.run(run())
