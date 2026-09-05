"""Rebuild undercounted aggregates for wallets trimmed before the refill.

Wallets whose raw events were trimmed to the 500-event hot cache BEFORE
backfill_market_activity --refill ran got aggregates covering only the latest
500 events. This rebuilds exactly the recoverable share from permanent stores:

- non-exact markets: full event history lives in
  wallet_activity_exception_events_v2 (+ latest 500 in main) -> exact rebuild.
- exact markets: old events are gone (never copied to exception); sums exist
  in reconciliations but per-side fill counts do not -> SKIPPED, queued for
  API refetch. Untouched rows stay as they are (consistent 500-window).
- unattributed (null condition_id) and activity-only markets: skipped.

Usage:
    python src/scripts/rebuild_trimmed_aggregates.py --dry-run
    python src/scripts/rebuild_trimmed_aggregates.py --wallet 0xabc...
    python src/scripts/rebuild_trimmed_aggregates.py --all --concurrency 8
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("rebuild_trimmed")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace(
    "localhost", "127.0.0.1")

TOKEN_RE = re.compile(r"^[0-9]+$")


def token_of(asset):
    a = str(asset or "")
    return int(a) if TOKEN_RE.match(a) else 0


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def find_targets(conn) -> list[str]:
    """Trimmed wallets whose stored aggregates sit below audit truth."""
    rows = await conn.fetch("""
        WITH raw AS (SELECT address, COUNT(*) rc FROM wallet_activity_events_v2 GROUP BY 1),
        agg AS (SELECT address, COALESCE(SUM(event_count), 0) sc
                FROM wallet_market_activity_v2 GROUP BY 1),
        rec AS (SELECT address, SUM(activity_event_count) tc
                FROM (SELECT DISTINCT ON (address, condition_id, outcome) address,
                             activity_event_count
                      FROM wallet_position_activity_reconciliations_v2
                      ORDER BY address, condition_id, outcome, created_at DESC) t
                GROUP BY 1)
        SELECT r.address FROM raw r
        LEFT JOIN agg a USING (address) LEFT JOIN rec c USING (address)
        WHERE r.rc <= 500 AND COALESCE(a.sc, 0) < COALESCE(c.tc, 0)
    """)
    return [r["address"] for r in rows]


async def rebuild_wallet(pool: asyncpg.Pool, address: str, dry_run: bool = False) -> dict:
    """Rebuild non-exact groups for one wallet from exception + hot rows."""
    async with pool.acquire() as conn:
        recs = await conn.fetch("""
            SELECT DISTINCT ON (condition_id, outcome) condition_id, outcome,
                   comparison_quality, activity_event_count
            FROM wallet_position_activity_reconciliations_v2
            WHERE address = $1
            ORDER BY condition_id, outcome, created_at DESC
        """, address)
    quality = {(r["condition_id"], str(r["outcome"] or "").lower()): r["comparison_quality"]
               for r in recs}
    # Completeness is per-market: the audit copies ALL of a market's events to
    # exception evidence when ANY of its legs is non-exact, and none when all
    # legs are exact. So a token group is rebuildable iff its market has at
    # least one non-exact pair (empty-outcome events ride along with their
    # market and must not disqualify it).
    cid_nonexact = {cid for (cid, _), q in quality.items() if q != "exact_activity_buy"}
    cid_known = {cid for (cid, _) in quality}
    truth = sum(int(r["activity_event_count"] or 0) for r in recs)
    if not recs:
        return {"address": address, "status": "no_audit_cover", "truth": 0}

    async with pool.acquire() as conn:
        exc = await conn.fetch("""
            SELECT condition_id, asset, outcome, event_type, side, size, price,
                   usdc_size, event_timestamp, event_sha256
            FROM wallet_activity_exception_events_v2 WHERE address = $1
        """, address)
        hot = await conn.fetch("""
            SELECT condition_id, asset, outcome, event_type, side, size, price,
                   usdc_size, event_timestamp, event_sha256
            FROM wallet_activity_events_v2 WHERE address = $1
        """, address)

    # Union, dedup by sha (hot rows may duplicate exception evidence).
    seen, events = set(), []
    for row in list(exc) + list(hot):
        sha = row["event_sha256"]
        if sha in seen:
            continue
        seen.add(sha)
        events.append(row)

    groups: dict[tuple, list] = defaultdict(list)
    for e in events:
        cid = str(e["condition_id"] or "")
        if not cid:
            continue
        groups[(cid, token_of(e["asset"]))].append(e)

    rebuilt, skipped_exact, skipped_norec = 0, 0, 0
    upserts = []
    for (cid, token), evs in groups.items():
        if cid not in cid_known:
            skipped_norec += 1
            continue
        if cid not in cid_nonexact:
            skipped_exact += 1
            continue
        agg = aggregate_events(address, cid, token, evs)
        upserts.append(agg)
        rebuilt += 1

    if not dry_run and upserts:
        async with pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO wallet_market_activity_v2 (
                    address, condition_id, outcome_token_id, outcome_label,
                    trade_buys, buy_shares, buy_cost, trade_sells, sell_shares,
                    sell_proceeds, redeem_count, redeem_usdc, split_shares,
                    merge_shares, conversion_events, reward_usdc, event_count,
                    first_event_at, last_event_at, last_event_ts, last_event_sha,
                    updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                          $17,$18,$19,$20,$21,NOW())
                ON CONFLICT (address, condition_id, outcome_token_id) DO UPDATE SET
                    outcome_label = EXCLUDED.outcome_label,
                    trade_buys = EXCLUDED.trade_buys, buy_shares = EXCLUDED.buy_shares,
                    buy_cost = EXCLUDED.buy_cost,
                    trade_sells = EXCLUDED.trade_sells, sell_shares = EXCLUDED.sell_shares,
                    sell_proceeds = EXCLUDED.sell_proceeds,
                    redeem_count = EXCLUDED.redeem_count, redeem_usdc = EXCLUDED.redeem_usdc,
                    split_shares = EXCLUDED.split_shares, merge_shares = EXCLUDED.merge_shares,
                    conversion_events = EXCLUDED.conversion_events,
                    reward_usdc = EXCLUDED.reward_usdc,
                    event_count = EXCLUDED.event_count,
                    first_event_at = EXCLUDED.first_event_at,
                    last_event_at = EXCLUDED.last_event_at,
                    last_event_ts = EXCLUDED.last_event_ts,
                    last_event_sha = EXCLUDED.last_event_sha,
                    updated_at = NOW()
            """, upserts)

    async with pool.acquire() as conn:
        stored = await conn.fetchval(
            "SELECT COALESCE(SUM(event_count), 0) FROM wallet_market_activity_v2 "
            "WHERE address = $1", address)
    return {"address": address, "status": "rebuilt" if not dry_run else "dry_run",
            "truth": truth, "stored": int(stored), "rebuilt_groups": rebuilt,
            "skipped_exact": skipped_exact, "skipped_norec": skipped_norec}


def aggregate_events(address, cid, token, evs):
    buys = [e for e in evs if (e["event_type"] or "") == "TRADE" and (e["side"] or "") == "BUY"]
    sells = [e for e in evs if (e["event_type"] or "") == "TRADE" and (e["side"] or "") == "SELL"]
    labels = defaultdict(int)
    for e in evs:
        labels[str(e["outcome"] or "")] += 1
    label = max(labels.items(), key=lambda kv: (kv[1], kv[0]))[0] if labels else ""
    ts = [e["event_timestamp"] for e in evs if e["event_timestamp"] is not None]
    first, last = (min(ts), max(ts)) if ts else (None, None)
    last_sha = ""
    if ts:
        epoch_min = datetime.min.replace(tzinfo=timezone.utc)
        last_ev = max(evs, key=lambda e: (
            e["event_timestamp"] or epoch_min, str(e["event_sha256"] or "")))
        last_sha = str(last_ev["event_sha256"] or "")
    return (
        address, cid, token, label,
        len(buys), sum(_num(e["size"]) for e in buys),
        sum(_num(e["size"]) * _num(e["price"]) for e in buys),
        len(sells), sum(_num(e["size"]) for e in sells),
        sum(_num(e["size"]) * _num(e["price"]) for e in sells),
        sum(1 for e in evs if (e["event_type"] or "") == "REDEEM"),
        sum(_num(e["usdc_size"]) for e in evs if (e["event_type"] or "") == "REDEEM"),
        sum(_num(e["size"]) for e in evs if (e["event_type"] or "") == "SPLIT"),
        sum(_num(e["size"]) for e in evs if (e["event_type"] or "") == "MERGE"),
        sum(1 for e in evs if (e["event_type"] or "") == "CONVERSION"),
        sum(_num(e["usdc_size"]) for e in evs
            if (e["event_type"] or "") in ("REWARD", "YIELD", "MAKER_REBATE", "TAKER_REBATE")),
        len(evs), first, last,
        int(last.timestamp()) if last is not None else 0, last_sha,
    )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--wallet", type=str, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=args.concurrency + 5,
                                     timeout=60, command_timeout=900)
    try:
        if args.wallet:
            wallets = [args.wallet]
        elif args.all:
            async with pool.acquire() as conn:
                wallets = await find_targets(conn)
            logger.info(f"{len(wallets)} wallets need rebuild.")
        else:
            parser.error("pass --all or --wallet")
            return
        sem = asyncio.Semaphore(args.concurrency)
        done, rec_done, exact_left = 0, 0, 0
        t0 = time.time()

        async def _one(addr: str):
            nonlocal done, rec_done, exact_left
            async with sem:
                try:
                    r = await rebuild_wallet(pool, addr, dry_run=args.dry_run)
                    rec_done += r.get("rebuilt_groups", 0)
                    exact_left += r.get("skipped_exact", 0)
                except Exception as e:
                    logger.warning(f"failed {addr[:12]}: {str(e)[:150]}")
                done += 1
                if done % 25 == 0 or done == len(wallets):
                    logger.info(f"wallets {done}/{len(wallets)} rebuilt_groups={rec_done} "
                                f"({done / (time.time() - t0):.1f}/s).")

        await asyncio.gather(*[_one(a) for a in wallets])
        logger.info(f"Done {done} wallets, {rec_done} groups rebuilt, "
                    f"{exact_left} exact groups left for API refetch.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
