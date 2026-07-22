#!/usr/bin/env python3
"""
Direct fetch of wallets with 0 balance and their open positions.
Query database for zero-balance wallets, then fetch positions for each.
"""
import asyncio
import asyncpg
import aiohttp
import os
import sys
import json
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

DB_URL = os.environ.get("DATABASE_URL")
DATA_API = "https://data-api.polymarket.com"

async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list:
    """Fetch open positions for a wallet from Polymarket API."""
    try:
        url = f"{DATA_API}/positions?user={address}&limit=500"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data if isinstance(data, list) else []
            return []
    except Exception as e:
        print(f"  [WARNING] Position fetch failed: {e}")
        return []


async def main():
    conn = await asyncpg.connect(DB_URL)
    print("\n[FETCHING WALLETS WITH ZERO BALANCE]\n")

    # Get wallets with 0 balance
    rows = await conn.fetch("""
        SELECT
            w.address,
            w.username,
            w.tier,
            m.balance,
            m.position_value,
            w.last_trade_at,
            w.added_at
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE w.tier NOT IN ('DEAD', 'UNCLASSIFIED')
          AND COALESCE(m.balance, 0) = 0
        ORDER BY m.position_value DESC NULLS LAST
        LIMIT 100
    """)

    print(f"[OK] Found {len(rows)} wallets with ZERO balance (showing first 100)\n")
    print(f"{'Address':<50} {'Username':<20} {'Balance':<12} {'Position':<15} {'Tier':<15} {'Last Trade':<20}")
    print("=" * 135)

    results = []
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for i, row in enumerate(rows, 1):
            address = row['address']
            username = row['username'] or 'N/A'
            balance = row['balance'] or 0.0
            position_value = row['position_value'] or 0.0
            tier = row['tier']
            last_trade = row['last_trade_at'].strftime("%Y-%m-%d %H:%M") if row['last_trade_at'] else "Never"

            # Fetch positions
            positions = await fetch_positions(session, address)

            # Calculate total position value
            total_position = sum(float(p.get('currentValue', 0) or 0) for p in positions if p.get('currentValue'))

            result = {
                'address': address,
                'username': username,
                'balance': balance,
                'position_value': total_position,
                'positions_count': len(positions),
                'tier': tier,
                'last_trade': last_trade,
                'added_at': row['added_at'].strftime("%Y-%m-%d") if row['added_at'] else "N/A"
            }
            results.append(result)

            print(f"{address:<50} {username:<20} ${balance:<11.2f} ${total_position:<14.2f} {tier:<15} {last_trade:<20}")

            if i % 10 == 0:
                await asyncio.sleep(0.5)  # Rate limit

    # Summary
    print("\n" + "=" * 135)
    zero_position = sum(1 for r in results if r['position_value'] == 0)
    has_position = sum(1 for r in results if r['position_value'] > 0)
    total_position_value = sum(r['position_value'] for r in results)

    print(f"\n[SUMMARY]:")
    print(f"  - Total wallets with 0 balance: {len(results)}")
    print(f"  - Wallets with 0 balance AND 0 positions: {zero_position}")
    print(f"  - Wallets with 0 balance BUT have positions: {has_position}")
    print(f"  - Total position value across all: ${total_position_value:,.2f}")

    # Save to JSON
    with open('zero_balance_wallets.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n[OK] Results saved to: zero_balance_wallets.json\n")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
