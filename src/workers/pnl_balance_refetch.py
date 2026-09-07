# src/workers/pnl_balance_refetch.py
"""
Worker 4: PnL & Balance Refetch Worker
======================================
Refetches official Polymarket website PnL, Volume, Rank, Username,
and on-chain/API portfolio Balance across all wallets in the database.
High concurrency (concurrency=40) with real-time throughput metrics.
"""

import asyncio
import logging
import os
import sys
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

from datetime import datetime, timezone
import aiohttp
import asyncpg
from typing import Optional

from src.utils.alchemy_client import alchemy_get_token_balances, PUSD_CONTRACT

logger = logging.getLogger("pnl_balance_refetch")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 60
BATCH_SIZE = 500


def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


async def fetch_leaderboard_stats(session: aiohttp.ClientSession, address: str) -> dict:
    url = f"https://data-api.polymarket.com/v1/leaderboard?user={address}&category=OVERALL&timePeriod=ALL"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8, connect=3, sock_read=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data:
                    item = data[0]
                    raw_name = str(item.get("userName") or "").strip()[:255]
                    if raw_name.lower().startswith("0x") and len(raw_name) > 10:
                        raw_name = ""
                    return {
                        "pnl": _parse(item.get("pnl")),
                        "volume": _parse(item.get("vol")),
                        "rank": int(item.get("rank") or 0) if item.get("rank") else None,
                        "username": raw_name,
                    }
    except Exception:
        pass
    return {"pnl": 0.0, "volume": 0.0, "rank": None, "username": ""}


async def fetch_wallet_balance(session: aiohttp.ClientSession, address: str) -> float:
    # Fast path: Polymarket /value API endpoint (concurrent, zero-latency)
    url = f"https://data-api.polymarket.com/value?user={address}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6, connect=3, sock_read=4)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data:
                    return _parse(data[0].get("value", 0.0))
    except Exception:
        pass

    return 0.0


async def process_wallet_pnl_balance(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
):
    # Official synchronization publishes only the Polymarket snapshot.  The
    # capital worker owns balance and its freshness cursor.
    lb = await fetch_leaderboard_stats(session, address)
    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, pm_pnl, pm_volume, pm_rank, pm_synced_at
        ) VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (address) DO UPDATE SET
            pm_pnl = EXCLUDED.pm_pnl,
            pm_volume = EXCLUDED.pm_volume,
            pm_rank = COALESCE(EXCLUDED.pm_rank, wallet_metrics_v2.pm_rank),
            pm_synced_at = NOW()
    """, address, lb["pnl"], lb["volume"], lb["rank"])

    # 2. Update username in wallets_v2 if available
    if lb["username"]:
        await conn.execute("""
            UPDATE wallets_v2
            SET username = $2, updated_at = NOW()
            WHERE address = $1 AND (username IS NULL OR username = '' OR username != $2)
        """, address, lb["username"])


async def main_loop(db_url: str = DB_URL):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logger.info(f"=== PNL & BALANCE REFETCH WORKER STARTED (CONCURRENCY={CONCURRENCY}) ===")

    from src.db import get_pool
    pool = await get_pool()
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 6,
        limit_per_host=CONCURRENCY * 4,
        keepalive_timeout=30,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=12, connect=3, sock_read=6),
    ) as session:
        while True:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT w.address
                        FROM wallets_v2 w
                        LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
                        WHERE w.is_dormant = FALSE
                          AND (
                              m.pm_synced_at IS NULL
                              OR m.capital_synced_at IS NULL
                              OR m.pm_synced_at < NOW() - INTERVAL '48 hours'
                          )
                        ORDER BY
                          CASE WHEN m.pm_synced_at IS NULL THEN 0 ELSE 1 END ASC,
                          CASE
                            WHEN w.tier IN ('CURATED', 'CUSTOM') THEN 0
                            WHEN w.tier = 'STANDARD' THEN 1
                            WHEN w.tier = 'NEW' THEN 2
                            WHEN w.tier = 'LOW_BALANCE' THEN 3
                            ELSE 4
                          END ASC,
                          COALESCE(m.pm_synced_at, '1970-01-01'::TIMESTAMPTZ) ASC
                        LIMIT $1
                    """, BATCH_SIZE)
                    wallets = [r["address"] for r in rows]
                    total = len(wallets)

                if total == 0:
                    logger.info("All active wallets have fresh PnL & Balance metrics! Sleeping 60s...")
                    await asyncio.sleep(60)
                    continue

                done, errors = 0, 0
                t0 = time.time()

                async def _process_one(addr):
                    nonlocal done, errors
                    async with sem:
                        try:
                            async with pool.acquire() as conn:
                                await asyncio.wait_for(
                                    process_wallet_pnl_balance(conn, session, addr),
                                    timeout=20,
                                )
                            done += 1
                        except Exception as e:
                            errors += 1
                            logger.debug(f"Error {addr[:12]}...: {e}")

                        if (done + errors) % 25 == 0 or (done + errors) == total:
                            rate = (done + errors) / max(0.1, time.time() - t0)
                            logger.info(f"Progress: {done+errors}/{total} (ok={done} err={errors}) | Speed: {rate:.1f} wallets/s")

                await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)
                logger.info(f"=== BATCH COMPLETE: {done} ok, {errors} errors / {total} (Elapsed: {time.time()-t0:.1f}s) ===")
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error in PnL/Balance refetch loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main_loop())
