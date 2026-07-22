import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    val = await conn.fetchval("SELECT SUM(position_value) FROM tracked_wallets")
    print(val)
    await conn.close()

asyncio.run(run())
