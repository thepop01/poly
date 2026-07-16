"""
cleanup_deposit_last_trade_at.py

One-time cleanup for wallets whose last_trade_at was stamped by something
other than a real trade. Two corruption sources, each matched precisely:

1. Deposit stamps: deposit_tracker wrote the deposit's own timestamp into
   last_trade_at (fixed in the worker). The same timestamp was recorded in
   wallet_activity_v2 as a DEPOSIT event, so an exact match on
   (address, event_at) identifies these without touching wallets whose
   last_trade_at came from actual trades.

2. Migration batch stamps: on 2026-07-12 ~21:40-22:20 UTC a v1->v2 batch
   job stamped groups of wallets with a transaction-frozen NOW() —
   visible as >=5 wallets sharing the exact same second, across mixed
   sources (leaderboard/trade/deposit/custom). Real same-second trades do
   occur (many trades share one Polygon block), so this criterion is
   restricted to that migration window.

Nulled wallets reappear in the New Wallets tab and the trade-based
workers will stamp the real last_trade_at on their next pass.

Usage:
    python src/scripts/cleanup_deposit_last_trade_at.py --dry-run   # preview
    python src/scripts/cleanup_deposit_last_trade_at.py --apply     # commit
"""

import asyncio
import asyncpg
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

DEPOSIT_STAMP_FILTER = """
    w.last_trade_at IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM wallet_activity_v2 a
        WHERE a.address = w.address
          AND a.event_type = 'DEPOSIT'
          AND a.event_at = w.last_trade_at
    )
"""

BATCH_STAMP_FILTER = """
    w.last_trade_at IN (
        SELECT last_trade_at FROM wallets_v2
        WHERE last_trade_at >= '2026-07-12 21:40:00+00'
          AND last_trade_at <  '2026-07-12 22:20:00+00'
        GROUP BY last_trade_at
        HAVING COUNT(*) >= 5
    )
"""


async def main(dry_run: bool):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        deposit_count = await conn.fetchval(
            f"SELECT COUNT(*) FROM wallets_v2 w WHERE {DEPOSIT_STAMP_FILTER}"
        )
        batch_count = await conn.fetchval(
            f"SELECT COUNT(*) FROM wallets_v2 w WHERE {BATCH_STAMP_FILTER}"
        )
        prefix = "[DRY RUN] " if dry_run else ""
        print(f"{prefix}Deposit-stamped wallets: {deposit_count}")
        print(f"{prefix}Migration batch-stamped wallets: {batch_count}")

        if dry_run:
            rows = await conn.fetch(f"""
                SELECT w.last_trade_at, COUNT(*) c FROM wallets_v2 w
                WHERE {BATCH_STAMP_FILTER}
                GROUP BY 1 ORDER BY c DESC
            """)
            print("Batch-stamp groups:")
            for r in rows:
                print(f"  {r['last_trade_at']}  x{r['c']}")
            sample = await conn.fetch(f"""
                SELECT w.address, w.last_trade_at FROM wallets_v2 w
                WHERE {DEPOSIT_STAMP_FILTER} LIMIT 10
            """)
            print("Deposit-stamp sample:")
            for row in sample:
                print(f"  {row['address']}  last_trade_at={row['last_trade_at']}")
            print("Run with --apply to execute.")
        else:
            result = await conn.execute(f"""
                UPDATE wallets_v2 w
                SET last_trade_at = NULL, updated_at = NOW()
                WHERE {DEPOSIT_STAMP_FILTER} OR {BATCH_STAMP_FILTER}
            """)
            print(f"Done. {result}")
            print("Trade workers will refetch the real last_trade_at on the next cycle.")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
