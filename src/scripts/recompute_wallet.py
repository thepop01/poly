import asyncio
import aiohttp
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from src.db import get_pool
from src.workers.positions_metrics_compute import compute_metrics_for_wallet

async def main():
    pool = await get_pool()
    wallet = (sys.argv[1] if len(sys.argv) > 1 else '0xf0318c32136c2db7fec88b84869aee6a1106c80c').lower()
    
    async with aiohttp.ClientSession() as session:
        async with pool.acquire() as conn:
            print(f"Recomputing metrics for {wallet}...")
            await compute_metrics_for_wallet(conn, session, wallet)
            
            # Read back metrics
            m = await conn.fetchrow("SELECT * FROM wallet_metrics_v2 WHERE address = $1", wallet)
            print("\n=== RECOMPUTED METRICS ===")
            print(f"  total_pnl: {m['total_pnl']:,.2f}")
            print(f"  win_rate: {m['win_rate']:.2f}% ({m['winning_count']}W / {m['resolved_count'] - m['winning_count']}L)")
            print(f"  pnl_100: {m['pnl_100']:,.2f}")
            print(f"  pnl_200: {m['pnl_200']:,.2f}")
            print(f"  pnl_300: {m['pnl_300']:,.2f}")
            print(f"  pnl_500: {m['pnl_500']:,.2f}")
            print(f"  pnl_750: {m['pnl_750']:,.2f}")
            print(f"  pnl_1000: {m['pnl_1000']:,.2f}")
            print(f"  pnl_1500: {m['pnl_1500']:,.2f}")
            print(f"  pnl_2000: {m['pnl_2000']:,.2f}")
            print(f"  pnl_3500: {m['pnl_3500']:,.2f}")
            print(f"  pnl_5000: {m['pnl_5000']:,.2f}")

asyncio.run(main())
