"""Extend the phantom-loss repair to redeemable rows the first pass missed.

Applies the same principle as src/pnl/rules.py: a position cannot lose more
cash than entered it. Batched by address so a failure is resumable and the
table is never locked for long.
"""
import asyncio
import logging
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))

# Rule 1: no CLOB purchase recorded -> no cash was spent -> no loss possible.
ZERO_BOUGHT = """
UPDATE wallet_closed_positions_v2
SET realized_pnl = 0,
    data_quality_flag = 'synthetic_liquidation_artifact'
WHERE address = ANY($1::varchar[])
  AND is_redeemable
  AND COALESCE(data_quality_flag, '') = ''
  AND COALESCE(total_bought, 0) <= 0.01
  AND realized_pnl < 0
"""

# Rule 2: loss deeper than cash spent -> clamp to cash spent.
CAP_TO_CASH = """
UPDATE wallet_closed_positions_v2
SET realized_pnl = -(total_bought * avg_buy_price),
    data_quality_flag = 'mixed_minted_shares'
WHERE address = ANY($1::varchar[])
  AND is_redeemable
  AND COALESCE(data_quality_flag, '') = ''
  AND COALESCE(total_bought, 0) > 0.01
  AND realized_pnl < -(total_bought * avg_buy_price)
"""

# Rule 3: synthetic 0.50 mint price, never sold, no offsetting leg stored.
ORPHAN_SYNTHETIC_MINT = """
UPDATE wallet_closed_positions_v2 c
SET realized_pnl = 0,
    data_quality_flag = 'synthetic_mint_split'
WHERE c.address = ANY($1::varchar[])
  AND c.is_redeemable
  AND COALESCE(c.data_quality_flag, '') = ''
  AND c.avg_buy_price BETWEEN 0.4995 AND 0.5005
  AND COALESCE(c.total_sold, 0) = 0
  AND c.realized_pnl < 0
  AND NOT EXISTS (
      SELECT 1 FROM wallet_closed_positions_v2 s
      WHERE s.address = c.address
        AND s.condition_id = c.condition_id
        AND s.outcome <> c.outcome
        AND s.avg_buy_price BETWEEN 0.4995 AND 0.5005
  )
"""

BATCH = 500
STMT_TIMEOUT_MS = 120_000


def _count(tag: str) -> int:
    return int(tag.split()[-1]) if tag and tag.split()[-1].isdigit() else 0


async def _connect():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(f"SET statement_timeout = '{STMT_TIMEOUT_MS}';")
    return conn


async def main():
    conn = await _connect()
    addresses = [r["address"] for r in await conn.fetch("""
        SELECT DISTINCT address FROM wallet_closed_positions_v2
        WHERE is_redeemable AND COALESCE(data_quality_flag, '') = ''
    """)]
    logger.info("wallets to repair: %d", len(addresses))

    totals = {"zero_bought": 0, "cap_to_cash": 0, "orphan_mint": 0}
    for start in range(0, len(addresses), BATCH):
        chunk = addresses[start:start + BATCH]
        for attempt in range(3):
            try:
                async with conn.transaction():
                    totals["zero_bought"] += _count(
                        await conn.execute(ZERO_BOUGHT, chunk))
                    totals["cap_to_cash"] += _count(
                        await conn.execute(CAP_TO_CASH, chunk))
                    totals["orphan_mint"] += _count(
                        await conn.execute(ORPHAN_SYNTHETIC_MINT, chunk))
                break
            except Exception as exc:
                logger.warning("batch %d attempt %d failed: %s",
                               start, attempt, exc)
                await conn.close()
                conn = await _connect()
        else:
            logger.error("batch %d failed after 3 attempts, skipping", start)
        logger.info("progress %d/%d  %s", min(start + BATCH, len(addresses)),
                    len(addresses), totals)

    remaining = await conn.fetchrow("""
        SELECT count(*) AS rows, COALESCE(sum(realized_pnl), 0)::numeric AS pnl
        FROM wallet_closed_positions_v2
        WHERE is_redeemable AND COALESCE(data_quality_flag, '') = ''
    """)
    logger.info("repaired: %s", totals)
    logger.info("still unflagged: %s rows holding %s",
                remaining["rows"], remaining["pnl"])
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
