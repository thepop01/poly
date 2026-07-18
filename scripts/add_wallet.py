#!/usr/bin/env python3
"""Add a wallet directly to tracked_wallets, bypassing the discovery queue."""

import asyncio
import asyncpg
import aiohttp
import os
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("add_wallet")

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    from src.utils.alchemy_client import alchemy_get_token_balances, USDC_CONTRACT
    try:
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance: {e}")
    return 0.0


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_positions = []
    offset = 0
    limit = 500
    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data or not isinstance(data, list):
                        break
                    all_positions.extend(data)
                    if len(data) < limit:
                        break
                    offset += limit
                else:
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")
            break
    return all_positions


async def add_wallet(address: str):
    address = address.lower().strip()
    logger.info(f"\n{'='*60}")
    logger.info(f"Adding wallet: {address}")
    logger.info(f"{'='*60}\n")

    conn = await asyncpg.connect(DB_URL)

    # Check if already tracked
    existing = await conn.fetchrow("SELECT 1 FROM tracked_wallets WHERE address = $1", address)
    if existing:
        logger.info(f"✅ Wallet already in tracked_wallets!")
        await conn.close()
        return

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        balance = await fetch_balance(session, address)
        positions = await fetch_positions(session, address)

        position_value = 0.0
        for pos in (positions or []):
            curr_val = float(pos.get("currentValue", 0) or 0)
            if curr_val > 0:
                position_value += curr_val

        logger.info(f"  Balance:        ${balance:,.2f}")
        logger.info(f"  Position Value: ${position_value:,.2f}")
        logger.info(f"  Open Positions: {len([p for p in (positions or []) if float(p.get('currentValue',0) or 0) > 0])}")

        # Insert into tracked_wallets
        await conn.execute("""
            INSERT INTO tracked_wallets (
                address, discovery_source, total_pnl, realized_pnl, unrealized_pnl, total_volume,
                pnl_weekly, pnl_monthly, volume_weekly, volume_monthly, alpha_score,
                last_indexed, max_trade_size, balance, deposits, withdrawals, position_value,
                start_balance, start_deposits, start_withdrawals, start_stats_at
            ) VALUES ($1, $2, 0, 0, 0, 0, 0, 0, 0, 0, 0, NOW(), 0, $3, 0, 0, $4,
                     $3, 0, 0, NOW())
            ON CONFLICT (address) DO UPDATE SET
                balance = EXCLUDED.balance,
                position_value = EXCLUDED.position_value,
                last_indexed = NOW()
        """, address, ["Manual"], balance, position_value)

        # Insert into wallet_stats
        await conn.execute("""
            INSERT INTO wallet_stats (
                address, total_pnl, total_volume, win_rate, roi_pct,
                resolved_count, winning_count, active_days,
                avg_position_size, avg_hold_time_hours,
                biggest_win, biggest_loss, unrealised_pnl,
                alpha_score, last_updated,
                trades_2x, trades_1_5x, strategy, added_reason
            ) VALUES ($1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, NOW(), 0, 0, 'Unknown', 'Manual')
            ON CONFLICT (address) DO NOTHING
        """, address)

        # Also enqueue for worker processing
        await conn.execute("""
            INSERT INTO wallet_discovery_queue (address, spotted_at, processed, source)
            VALUES ($1, NOW(), FALSE, 'Manual')
            ON CONFLICT (address) DO UPDATE SET
                processed = FALSE,
                source = CASE WHEN wallet_discovery_queue.source = 'Unknown' THEN 'Manual' ELSE wallet_discovery_queue.source END
        """, address)

        logger.info(f"\n✅ Wallet {address[:10]}... added to tracked_wallets!\n")

    await conn.close()


if __name__ == "__main__":
    wallet = sys.argv[1] if len(sys.argv) > 1 else "0x9ee8bbc36d378af72e5f6b8e2ea2eb67c05a89de"
    asyncio.run(add_wallet(wallet))
