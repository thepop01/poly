import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from src.db import get_pool

async def main():
    pool = await get_pool()
    wallet = '0xc2e7800b5af46e6093872b177b7a5e7f0563be51'.lower()
    
    async with pool.acquire() as conn:
        print(f"=== DETAILED AUDIT FOR WALLET {wallet} ===")

        # 1. Inspect ALL closed positions
        closed = await conn.fetch("""
            SELECT condition_id, outcome, avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, closed_at, is_redeemable
            FROM wallet_closed_positions_v2
            WHERE address = $1
            ORDER BY closed_at DESC NULLS LAST
        """, wallet)
        
        print(f"\nTotal closed positions in table: {len(closed)}")
        
        actual_total_pnl = sum(r['realized_pnl'] for r in closed)
        winning_rows = [r for r in closed if r['realized_pnl'] > 0]
        losing_rows = [r for r in closed if r['realized_pnl'] <= 0]
        
        print(f"Actual Sum of realized_pnl (all {len(closed)} rows): ${actual_total_pnl:,.2f}")
        print(f"Winning rows count: {len(winning_rows)} | Sum wins: ${sum(r['realized_pnl'] for r in winning_rows):,.2f}")
        print(f"Losing rows count: {len(losing_rows)} | Sum losses: ${sum(r['realized_pnl'] for r in losing_rows):,.2f}")

        # Check what the buggy _parse_realized_pnl gave:
        def buggy_parse(r):
            rp = float(r['realized_pnl'] or 0)
            tb = float(r['total_bought'] or 0)
            if tb > 1_000_000.0:
                rp = rp / 1_000_000.0
            elif tb == 0 and abs(rp) > 1_000_000.0:
                rp = rp / 1_000_000.0
            return rp

        buggy_sum = sum(buggy_parse(r) for r in closed)
        print(f"Buggy _parse_realized_pnl Sum: ${buggy_sum:,.2f}")

        # Check Window PnLs with actual vs buggy
        print("\n--- WINDOW PNL COMPARISON ---")
        for w in [100, 200, 300, 500, 1000, 2000, 5000]:
            slice_cp = closed[:w]
            actual_w = sum(r['realized_pnl'] for r in slice_cp)
            buggy_w = sum(buggy_parse(r) for r in slice_cp)
            print(f"  Last {w:4d}: Actual = ${actual_w:14,.2f} | Buggy = ${buggy_w:14,.2f}")

        # 2. Inspect Open Positions
        open_pos = await conn.fetch("""
            SELECT condition_id, outcome, size, avg_price, current_value, unrealized_pnl, is_resolved
            FROM wallet_positions_v2
            WHERE address = $1
        """, wallet)
        print(f"\nTotal open positions: {len(open_pos)}")
        for r in open_pos:
            print(f"  cid: {r['condition_id'][:16]} | out: {r['outcome']} | Size: {r['size']:,.2f} | AvgPrice: {r['avg_price']:.4f} | CurVal: ${r['current_value']:,.2f} | UnrealizedPnL: ${r['unrealized_pnl']:,.2f} | is_resolved: {r['is_resolved']}")

        # 3. Check "open but redeemed" positions:
        # Are there positions in wallet_positions_v2 where is_resolved=True?
        resolved_open = [r for r in open_pos if r['is_resolved']]
        print(f"\nPositions in wallet_positions_v2 marked is_resolved=True: {len(resolved_open)}")
        for r in resolved_open:
            print(f"  Resolved Open: cid: {r['condition_id'][:16]} | Size: {r['size']:,.2f} | UnrealizedPnL: ${r['unrealized_pnl']:,.2f}")

asyncio.run(main())
