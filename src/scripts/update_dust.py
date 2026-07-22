import asyncio, asyncpg, os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    
    result = await conn.execute(
        "UPDATE tracked_wallets SET is_zero_balance = TRUE WHERE is_zero_balance = FALSE AND balance < 1.0"
    )
    print(f"Update result: {result}")
    
    await conn.close()

asyncio.run(run())
