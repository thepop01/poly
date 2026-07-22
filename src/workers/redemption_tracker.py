"""
Redemption Tracker Worker

Monitors Polymarket's live redemption feed (via polling the Etherscan API).
Identifies redemptions for tracked wallets and computes synthetic wins/losses in the test_computed_positions table.
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timezone

from src.utils.etherscan_client import fetch_recent_redemptions_etherscan, get_latest_block_etherscan
from src.utils.accounting import apply_redemption

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = 15

LAST_BLOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", ".redemption_last_block")


def read_last_block():
    if os.path.exists(LAST_BLOCK_FILE):
        with open(LAST_BLOCK_FILE, "r") as f:
            return f.read().strip()
    return "latest"


def write_last_block(block_number: int):
    with open(LAST_BLOCK_FILE, "w") as f:
        f.write(str(block_number))


async def run_redemption_tracker(pool: asyncpg.Pool):
    logger.info("Redemption tracker started (scanning CTF and NegRisk Adapter).")
    last_block = read_last_block()

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        while True:
            try:
                redemptions = await fetch_recent_redemptions_etherscan(session, from_block=last_block, to_block="latest")

                if redemptions:
                    highest_block = 0

                    async with pool.acquire() as conn:
                        for red in redemptions:
                            b_num = red.get("blockNumber", 0)
                            if b_num > highest_block:
                                highest_block = b_num

                            wallet = red.get("wallet")
                            if not wallet:
                                continue

                            is_tracked = await conn.fetchval("SELECT address FROM wallets_v2 WHERE address = $1", wallet) is not None
                            
                            if is_tracked:
                                payout = red.get("payout", 0.0)
                                condition_id = red.get("condition_id")
                                
                                # 1. Fetch current state
                                row = await conn.fetchrow("""
                                    SELECT total_bought_usd, total_buy_tokens, total_sold_usd, total_sell_tokens, realized_pnl
                                    FROM test_computed_positions
                                    WHERE address = $1 AND condition_id = $2
                                """, wallet, condition_id)
                                
                                current_state = dict(row) if row else {}
                                
                                # 2. Apply math
                                new_state = apply_redemption(current_state, red)
                                
                                # 3. Upsert
                                await conn.execute("""
                                    INSERT INTO test_computed_positions (
                                        address, condition_id, total_bought_usd, total_buy_tokens, 
                                        total_sold_usd, total_sell_tokens, realized_pnl,
                                        cash_pnl, is_resolved, is_win
                                    )
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                                    ON CONFLICT (address, condition_id) DO UPDATE SET
                                        total_bought_usd = EXCLUDED.total_bought_usd,
                                        total_buy_tokens = EXCLUDED.total_buy_tokens,
                                        total_sold_usd = EXCLUDED.total_sold_usd,
                                        total_sell_tokens = EXCLUDED.total_sell_tokens,
                                        realized_pnl = EXCLUDED.realized_pnl,
                                        cash_pnl = EXCLUDED.cash_pnl,
                                        is_resolved = EXCLUDED.is_resolved,
                                        is_win = EXCLUDED.is_win,
                                        updated_at = NOW()
                                """, wallet, condition_id, 
                                new_state["total_bought_usd"], new_state["total_buy_tokens"],
                                new_state["total_sold_usd"], new_state["total_sell_tokens"],
                                new_state["realized_pnl"], new_state["cash_pnl"], 
                                new_state["is_resolved"], new_state["is_win"])
                                
                                logger.info(f"Redemption for tracked wallet {wallet[:10]}... payout=${payout:.2f}")

                    if highest_block > 0:
                        last_block = str(highest_block + 1)
                        write_last_block(highest_block + 1)
                else:
                    current_tip = await get_latest_block_etherscan(session)
                    if current_tip and current_tip != "89410000":
                        last_block = current_tip
                        write_last_block(int(current_tip))

            except Exception as e:
                logger.error(f"Redemption tracker error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


async def _standalone():
    pool = await asyncpg.create_pool(DB_URL)
    await run_redemption_tracker(pool)
    await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_standalone())
