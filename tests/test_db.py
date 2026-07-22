import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    r = await conn.fetchrow("SELECT address, total_volume, balance, is_zero_balance, last_trade_at FROM tracked_wallets WHERE address='0x204f72f35326db932158cba6adff0b9a1da95e14'")
    print(dict(r) if r else "Not found")
    await conn.close()

asyncio.run(run())
