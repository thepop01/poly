import asyncio
import aiohttp
import json
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from src.db import get_pool
from src.api.routers.wallets_v2 import _pm_fetch, _parse_num

async def main():
    wallet = '0xc2e7800b5af46e6093872b177b7a5e7f0563be51'.lower()
    
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # 1. Fetch closed positions from Polymarket API
        print("Fetching closed-positions from Polymarket API...")
        closed_pm = await _pm_fetch(session, "closed-positions", {"user": wallet})
        print(f"Polymarket API returned {len(closed_pm)} closed positions.")

        # Sum realizedPnl from Polymarket API
        sum_pm_pnl = sum(_parse_num(p.get("realizedPnl")) for p in closed_pm)
        sum_pm_bought = sum(_parse_num(p.get("totalBought")) for p in closed_pm)
        sum_pm_sold = sum(_parse_num(p.get("totalSold")) for p in closed_pm)
        
        wins_pm = [p for p in closed_pm if _parse_num(p.get("realizedPnl")) > 0]
        losses_pm = [p for p in closed_pm if _parse_num(p.get("realizedPnl")) <= 0]
        
        print(f"Polymarket API closed positions PnL: ${sum_pm_pnl:,.2f}")
        print(f"Polymarket API wins: {len(wins_pm)} (Sum: ${sum(_parse_num(p.get('realizedPnl')) for p in wins_pm):,.2f})")
        print(f"Polymarket API losses: {len(losses_pm)} (Sum: ${sum(_parse_num(p.get('realizedPnl')) for p in losses_pm):,.2f})")
        print(f"Polymarket API Total Bought: ${sum_pm_bought:,.2f} | Total Sold: ${sum_pm_sold:,.2f}")

        # 2. Fetch open positions from Polymarket API
        print("\nFetching positions (open) from Polymarket API...")
        open_pm = await _pm_fetch(session, "positions", {"user": wallet})
        print(f"Polymarket API returned {len(open_pm)} open positions.")
        sum_open_cash_pnl = sum(_parse_num(p.get("cashPnl")) for p in open_pm)
        sum_open_cur_val = sum(_parse_num(p.get("currentValue")) for p in open_pm)
        sum_open_bought = sum(_parse_num(p.get("totalBought")) for p in open_pm)
        print(f"Polymarket API open positions CashPnL: ${sum_open_cash_pnl:,.2f}")
        print(f"Polymarket API open positions CurrentValue: ${sum_open_cur_val:,.2f}")
        print(f"Polymarket API open positions TotalBought: ${sum_open_bought:,.2f}")

        # Print all open positions from Polymarket API
        for p in open_pm:
            print(f"  title: {p.get('title', '')[:35]} | outcome: {p.get('outcome')} | size: {_parse_num(p.get('size')):.1f} | curVal: ${_parse_num(p.get('currentValue')):.2f} | cashPnl: ${_parse_num(p.get('cashPnl')):.2f} | curPrice: {_parse_num(p.get('curPrice')):.3f}")

        # 3. Fetch user profile / stats from Polymarket Website API
        print("\nFetching website profile stats from Polymarket...")
        async with session.get(f"https://data-api.polymarket.com/value?user={wallet}") as resp:
            if resp.status == 200:
                val_data = await resp.json()
                print("Polymarket /value endpoint:", val_data)

        # Compare with DB
        pool = await get_pool()
        async with pool.acquire() as conn:
            db_closed = await conn.fetch("SELECT * FROM wallet_closed_positions_v2 WHERE address = $1", wallet)
            print(f"\nDB has {len(db_closed)} closed positions for this wallet.")
            db_pnl = sum(r['realized_pnl'] for r in db_closed)
            print(f"DB sum realized_pnl: ${db_pnl:,.2f}")

            # Check difference between API and DB
            pm_cids = {p.get("conditionId"): p for p in closed_pm if p.get("conditionId")}
            db_cids = {r['condition_id']: r for r in db_closed}
            
            missing_in_db = set(pm_cids.keys()) - set(db_cids.keys())
            missing_in_pm = set(db_cids.keys()) - set(pm_cids.keys())
            print(f"Missing in DB: {len(missing_in_db)} positions")
            print(f"Missing in PM API: {len(missing_in_pm)} positions")

asyncio.run(main())
