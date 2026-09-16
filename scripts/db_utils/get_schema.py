import asyncpg, asyncio, os
from dotenv import load_dotenv

load_dotenv()

async def get_schema():
    c = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    tables = ['curated_category_tags', 'leaderboard', 'tracked_wallets',
              'wallet_stats', 'wallet_category_stats', 'wallet_subcategory_stats',
              'wallet_tags', 'wallet_window_100', 'wallet_txn_windows', 'wallet_window_300',
              'wallet_window_800', 'wallet_window_1500', 'wallet_window_2500']
    
    for table in tables:
        rows = await c.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1 ORDER BY ordinal_position",
            table
        )
        print(f"\n=== {table} ===")
        for r in rows:
            print(f"  {r['column_name']}: {r['data_type']}")
    
    await c.close()

asyncio.run(get_schema())
