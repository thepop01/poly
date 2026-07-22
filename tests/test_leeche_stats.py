import asyncio
import asyncpg
import aiohttp
import os
import json
from dotenv import load_dotenv

load_dotenv('.env')

from src.workers.leaderboard_stats import process_wallet

async def test():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    async with pool.acquire() as conn:
        address = '0xa20b482f97063f4f88ef621c9203e60814399940'
        
        # Ensure it is curated
        await conn.execute("UPDATE tracked_wallets SET is_curated = TRUE WHERE address = $1", address)
        
        print(f"Running process_wallet for {address}...")
        async with aiohttp.ClientSession() as session:
            await process_wallet(conn, session, address)
        print("process_wallet completed.")
        
        # Check wallet_stats
        row = await conn.fetchrow("SELECT * FROM wallet_stats WHERE address = $1", address)
        if row:
            stats = dict(row)
            # Serialize dates and numerics for printing
            for k, v in stats.items():
                if v.__class__.__name__ == 'datetime':
                    stats[k] = v.isoformat()
                elif v.__class__.__name__ == 'Decimal':
                    stats[k] = float(v)
            print("--- wallet_stats ---")
            print(json.dumps(stats, indent=2))
        
        # Check wallet_position_outcomes summary
        outcomes = await conn.fetch('''
            SELECT status, COUNT(*) as count 
            FROM wallet_position_outcomes 
            WHERE address = $1 
            GROUP BY status
        ''', address)
        
        print("\n--- wallet_position_outcomes summary ---")
        for o in outcomes:
            print(f"{o['status']}: {o['count']}")

    await pool.close()

if __name__ == '__main__':
    asyncio.run(test())
