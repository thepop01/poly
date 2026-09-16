"""
backfill_last_trade_at.py

Nulls out last_trade_at for all tracked wallets so the worker can
refetch the real value from Polymarket's /trades?user= API.

Usage:
    python src/scripts/backfill_last_trade_at.py --dry-run   # preview
    python src/scripts/backfill_last_trade_at.py --apply     # commit
"""

import asyncio
import asyncpg
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


async def main(dry_run: bool):
    conn = await asyncpg.connect(DATABASE_URL)

    # Count how many rows will be affected
    total = await conn.fetchval("SELECT COUNT(*) FROM tracked_wallets WHERE last_trade_at IS NOT NULL")
    print(f"{'[DRY RUN] ' if dry_run else ''}Will NULL out last_trade_at for {total} wallets.")

    if not dry_run:
        result = await conn.execute("UPDATE tracked_wallets SET last_trade_at = NULL")
        print(f"Done. {result}")
        print("Workers will now refetch the real last_trade_at on next processing cycle.")
    else:
        print("Run with --apply to execute.")

    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
