"""Backfill wallet_market_activity_v2 from stored activity events.

One-shot full aggregation per wallet (idempotent overwrite), resumable by
skipping wallets already present. For ongoing deltas see the watermark merge
in the activity backfill path.

Usage:
    python src/scripts/backfill_market_activity.py --all --concurrency 40
    python src/scripts/backfill_market_activity.py --wallet 0xabc... --concurrency 4
    python src/scripts/bench_market_activity.py --levels 20,40,80
"""

import argparse
import asyncio
import logging
import os
import sys
import time

import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("backfill_market_activity")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace(
    "localhost", "127.0.0.1")

AGGREGATE_SQL = """
INSERT INTO wallet_market_activity_v2 (
    address, condition_id, outcome_token_id, outcome_label,
    trade_buys, buy_shares, buy_cost,
    trade_sells, sell_shares, sell_proceeds,
    redeem_count, redeem_usdc,
    split_shares, merge_shares, conversion_events, reward_usdc,
    event_count, first_event_at, last_event_at,
    last_event_ts, last_event_sha, updated_at
)
SELECT * FROM (
SELECT
    $1::varchar AS address,
    condition_id,
    CASE WHEN asset ~ '^[0-9]+$' THEN asset::numeric ELSE 0 END AS outcome_token_id,
    MODE() WITHIN GROUP (ORDER BY outcome) AS outcome_label,
    COUNT(*) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY') AS trade_buys,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY'), 0) AS buy_shares,
    COALESCE(SUM(size * price) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY'), 0) AS buy_cost,
    COUNT(*) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL') AS trade_sells,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL'), 0) AS sell_shares,
    COALESCE(SUM(size * price) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL'), 0) AS sell_proceeds,
    COUNT(*) FILTER (WHERE event_type = 'REDEEM') AS redeem_count,
    COALESCE(SUM(usdc_size) FILTER (WHERE event_type = 'REDEEM'), 0) AS redeem_usdc,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'SPLIT'), 0) AS split_shares,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'MERGE'), 0) AS merge_shares,
    COUNT(*) FILTER (WHERE event_type = 'CONVERSION') AS conversion_events,
    COALESCE(SUM(usdc_size) FILTER (WHERE event_type IN ('REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE')), 0) AS reward_usdc,
    COUNT(*) AS event_count,
    MIN(event_timestamp) AS first_event_at,
    MAX(event_timestamp) AS last_event_at,
    COALESCE(EXTRACT(EPOCH FROM MAX(event_timestamp))::bigint, 0) AS last_event_ts,
    COALESCE((ARRAY_AGG(event_sha256 ORDER BY event_timestamp DESC, event_sha256 DESC))[1], '') AS last_event_sha,
    NOW() AS updated_at
FROM {src}
WHERE address = $1 AND condition_id IS NOT NULL AND condition_id <> ''
GROUP BY condition_id,
         CASE WHEN asset ~ '^[0-9]+$' THEN asset::numeric ELSE 0 END
UNION ALL
SELECT
    $1::varchar AS address,
    '' AS condition_id,
    0 AS outcome_token_id,
    'unattributed' AS outcome_label,
    COUNT(*) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY') AS trade_buys,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY'), 0) AS buy_shares,
    COALESCE(SUM(size * price) FILTER (WHERE event_type = 'TRADE' AND side = 'BUY'), 0) AS buy_cost,
    COUNT(*) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL') AS trade_sells,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL'), 0) AS sell_shares,
    COALESCE(SUM(size * price) FILTER (WHERE event_type = 'TRADE' AND side = 'SELL'), 0) AS sell_proceeds,
    COUNT(*) FILTER (WHERE event_type = 'REDEEM') AS redeem_count,
    COALESCE(SUM(usdc_size) FILTER (WHERE event_type = 'REDEEM'), 0) AS redeem_usdc,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'SPLIT'), 0) AS split_shares,
    COALESCE(SUM(size) FILTER (WHERE event_type = 'MERGE'), 0) AS merge_shares,
    COUNT(*) FILTER (WHERE event_type = 'CONVERSION') AS conversion_events,
    COALESCE(SUM(usdc_size) FILTER (WHERE event_type IN ('REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE')), 0) AS reward_usdc,
    COUNT(*) AS event_count,
    MIN(event_timestamp) AS first_event_at,
    MAX(event_timestamp) AS last_event_at,
    COALESCE(EXTRACT(EPOCH FROM MAX(event_timestamp))::bigint, 0) AS last_event_ts,
    COALESCE((ARRAY_AGG(event_sha256 ORDER BY event_timestamp DESC, event_sha256 DESC))[1], '') AS last_event_sha,
    NOW() AS updated_at
FROM {src}
WHERE address = $1 AND (condition_id IS NULL OR condition_id = '')
HAVING COUNT(*) > 0
) all_groups
ON CONFLICT (address, condition_id, outcome_token_id) DO UPDATE SET
    outcome_label = EXCLUDED.outcome_label,
    trade_buys = EXCLUDED.trade_buys, buy_shares = EXCLUDED.buy_shares,
    buy_cost = EXCLUDED.buy_cost,
    trade_sells = EXCLUDED.trade_sells, sell_shares = EXCLUDED.sell_shares,
    sell_proceeds = EXCLUDED.sell_proceeds,
    redeem_count = EXCLUDED.redeem_count, redeem_usdc = EXCLUDED.redeem_usdc,
    split_shares = EXCLUDED.split_shares, merge_shares = EXCLUDED.merge_shares,
    conversion_events = EXCLUDED.conversion_events, reward_usdc = EXCLUDED.reward_usdc,
    event_count = EXCLUDED.event_count,
    first_event_at = EXCLUDED.first_event_at, last_event_at = EXCLUDED.last_event_at,
    last_event_ts = EXCLUDED.last_event_ts, last_event_sha = EXCLUDED.last_event_sha,
    updated_at = NOW()
"""


async def aggregate_wallet(pool: asyncpg.Pool, address: str) -> int:
    async with pool.acquire() as conn:
        tag = await conn.execute(AGGREGATE_SQL.format(src="wallet_activity_events_v2"), address)
    try:
        return int(tag.split()[-1])
    except (ValueError, IndexError):
        return 0


INCREMENTAL_SQL = """
INSERT INTO wallet_market_activity_v2 (
    address, condition_id, outcome_token_id, outcome_label,
    trade_buys, buy_shares, buy_cost,
    trade_sells, sell_shares, sell_proceeds,
    redeem_count, redeem_usdc,
    split_shares, merge_shares, conversion_events, reward_usdc,
    event_count, first_event_at, last_event_at,
    last_event_ts, last_event_sha, updated_at
)
SELECT
    $1::varchar AS address,
    d.condition_id,
    d.outcome_token_id,
    d.outcome_label,
    COALESCE(w.trade_buys, 0) + d.trade_buys AS trade_buys,
    COALESCE(w.buy_shares, 0) + d.buy_shares AS buy_shares,
    COALESCE(w.buy_cost, 0) + d.buy_cost AS buy_cost,
    COALESCE(w.trade_sells, 0) + d.trade_sells AS trade_sells,
    COALESCE(w.sell_shares, 0) + d.sell_shares AS sell_shares,
    COALESCE(w.sell_proceeds, 0) + d.sell_proceeds AS sell_proceeds,
    COALESCE(w.redeem_count, 0) + d.redeem_count AS redeem_count,
    COALESCE(w.redeem_usdc, 0) + d.redeem_usdc AS redeem_usdc,
    COALESCE(w.split_shares, 0) + d.split_shares AS split_shares,
    COALESCE(w.merge_shares, 0) + d.merge_shares AS merge_shares,
    COALESCE(w.conversion_events, 0) + d.conversion_events AS conversion_events,
    COALESCE(w.reward_usdc, 0) + d.reward_usdc AS reward_usdc,
    COALESCE(w.event_count, 0) + d.event_count AS event_count,
    CASE WHEN w.first_event_at IS NULL THEN d.first_event_at
         WHEN d.first_event_at IS NULL THEN w.first_event_at
         ELSE LEAST(w.first_event_at, d.first_event_at) END AS first_event_at,
    d.last_event_at AS last_event_at,
    d.last_event_ts AS last_event_ts,
    d.last_event_sha AS last_event_sha,
    NOW() AS updated_at
FROM (
    SELECT
        e.condition_id,
        CASE WHEN e.asset ~ '^[0-9]+$' THEN e.asset::numeric ELSE 0 END AS outcome_token_id,
        MODE() WITHIN GROUP (ORDER BY e.outcome) AS outcome_label,
        COUNT(*) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'BUY') AS trade_buys,
        COALESCE(SUM(e.size) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'BUY'), 0) AS buy_shares,
        COALESCE(SUM(e.size * e.price) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'BUY'), 0) AS buy_cost,
        COUNT(*) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'SELL') AS trade_sells,
        COALESCE(SUM(e.size) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'SELL'), 0) AS sell_shares,
        COALESCE(SUM(e.size * e.price) FILTER (WHERE e.event_type = 'TRADE' AND e.side = 'SELL'), 0) AS sell_proceeds,
        COUNT(*) FILTER (WHERE e.event_type = 'REDEEM') AS redeem_count,
        COALESCE(SUM(e.usdc_size) FILTER (WHERE e.event_type = 'REDEEM'), 0) AS redeem_usdc,
        COALESCE(SUM(e.size) FILTER (WHERE e.event_type = 'SPLIT'), 0) AS split_shares,
        COALESCE(SUM(e.size) FILTER (WHERE e.event_type = 'MERGE'), 0) AS merge_shares,
        COUNT(*) FILTER (WHERE e.event_type = 'CONVERSION') AS conversion_events,
        COALESCE(SUM(e.usdc_size) FILTER (WHERE e.event_type IN ('REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE')), 0) AS reward_usdc,
        COUNT(*) AS event_count,
        MIN(e.event_timestamp) AS first_event_at,
        MAX(e.event_timestamp) AS last_event_at,
        COALESCE(EXTRACT(EPOCH FROM MAX(e.event_timestamp))::bigint, 0) AS last_event_ts,
        COALESCE((ARRAY_AGG(e.event_sha256 ORDER BY e.event_timestamp DESC, e.event_sha256 DESC))[1], '') AS last_event_sha
    FROM wallet_activity_events_v2 e
    LEFT JOIN wallet_market_activity_v2 w
      ON w.address = e.address
      AND w.condition_id = e.condition_id
      AND w.outcome_token_id = CASE WHEN e.asset ~ '^[0-9]+$' THEN e.asset::numeric ELSE 0 END
    WHERE e.address = $1
      AND e.condition_id IS NOT NULL AND e.condition_id <> ''
      AND e.event_timestamp IS NOT NULL
      AND (w.last_event_at IS NULL OR e.event_timestamp > w.last_event_at)
    GROUP BY e.condition_id,
             CASE WHEN e.asset ~ '^[0-9]+$' THEN e.asset::numeric ELSE 0 END
) d
LEFT JOIN wallet_market_activity_v2 w
  ON w.address = $1
  AND w.condition_id = d.condition_id
  AND w.outcome_token_id = d.outcome_token_id
ON CONFLICT (address, condition_id, outcome_token_id) DO UPDATE SET
    outcome_label = EXCLUDED.outcome_label,
    trade_buys = EXCLUDED.trade_buys, buy_shares = EXCLUDED.buy_shares,
    buy_cost = EXCLUDED.buy_cost,
    trade_sells = EXCLUDED.trade_sells, sell_shares = EXCLUDED.sell_shares,
    sell_proceeds = EXCLUDED.sell_proceeds,
    redeem_count = EXCLUDED.redeem_count, redeem_usdc = EXCLUDED.redeem_usdc,
    split_shares = EXCLUDED.split_shares, merge_shares = EXCLUDED.merge_shares,
    conversion_events = EXCLUDED.conversion_events, reward_usdc = EXCLUDED.reward_usdc,
    event_count = EXCLUDED.event_count,
    first_event_at = EXCLUDED.first_event_at, last_event_at = EXCLUDED.last_event_at,
    last_event_ts = EXCLUDED.last_event_ts, last_event_sha = EXCLUDED.last_event_sha,
    updated_at = NOW()
"""


async def incremental_aggregate_wallet(pool: asyncpg.Pool, address: str) -> int:
    """Additively merge deltas for a single wallet (watermark-based).

    Only events newer than each group's ``last_event_at`` are aggregated and
    ADDED to the stored totals — never recomputed from raw. This is what makes
    the merge safe under the 100-event hot-cache trim: groups whose old raw
    rows are gone keep their history and only grow.

    Returns the number of groups upserted. For wallets with no existing
    aggregates, falls back to full aggregation.
    """
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM wallet_market_activity_v2 WHERE address=$1", address)
        if existing == 0:
            tag = await conn.execute(AGGREGATE_SQL.format(src="wallet_activity_events_v2"), address)
        else:
            tag = await conn.execute(INCREMENTAL_SQL, address)
    try:
        return int(tag.split()[-1])
    except (ValueError, IndexError):
        return 0


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--wallet", type=str, default=None)
    parser.add_argument("--refill", action="store_true",
                        help="Re-aggregate even wallets already present (e.g. after a logic fix).")
    parser.add_argument("--concurrency", type=int, default=40)
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=args.concurrency + 10,
                                     timeout=60, command_timeout=600)
    try:
        if args.wallet:
            wallets = [args.wallet]
        elif args.all:
            if args.refill:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT DISTINCT address FROM wallet_activity_events_v2")
                wallets = [r["address"] for r in rows]
                logger.info(f"{len(wallets)} wallets to refill.")
            else:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT DISTINCT e.address FROM wallet_activity_events_v2 e
                           WHERE NOT EXISTS (SELECT 1 FROM wallet_market_activity_v2 w
                                             WHERE w.address = e.address)""")
                wallets = [r["address"] for r in rows]
                logger.info(f"{len(wallets)} wallets pending aggregation.")
        else:
            parser.error("pass --all or --wallet")
            return
        sem = asyncio.Semaphore(args.concurrency)
        done, groups, t0 = 0, 0, time.time()

        async def _one(addr: str):
            nonlocal done, groups
            async with sem:
                try:
                    n = await aggregate_wallet(pool, addr)
                    groups += n
                except Exception as e:
                    logger.warning(f"failed {addr[:12]}: {str(e)[:150]}")
                done += 1
                if done % 25 == 0 or done == len(wallets):
                    dt = time.time() - t0
                    logger.info(f"wallets {done}/{len(wallets)} groups={groups} "
                                f"({done / dt:.1f}/s).")

        await asyncio.gather(*[_one(a) for a in wallets])
        logger.info(f"Done {done} wallets, {groups} groups in {(time.time() - t0) / 60:.1f} min.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
