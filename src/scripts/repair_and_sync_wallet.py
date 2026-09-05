import asyncio
import argparse
import os
import re
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv()
import aiohttp
import asyncpg

from src.workers.wallet_trade_history import fetch_closed_positions, fetch_positions
from src.workers.positions_open_backfill import (
    _is_parlay,
    aggregate_and_upsert_positions_v2,
    sync_redeemable_positions,
)
from src.workers.positions_closed_backfill import upsert_closed_positions_v2
from src.workers.positions_metrics_compute import compute_metrics_for_wallet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("repair_and_sync_wallet")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")

TARGET_WALLETS = [
    "0x7c1ee865a785de4c00ee90ed86a38489fb8bbab3",
    "0x84dbb7103982e3617704a2ed7d5b39691952aeeb",
    "0xf0318c32136c2db7fec88b84869aee6a1106c80c"
]

def _parse(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except Exception:
        return 0.0

def _parse_end(val) -> datetime | None:
    if not val:
        return None
    try:
        if isinstance(val, str) and len(val) == 10:
            val = f"{val}T00:00:00Z"
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.year <= 1970 or dt > datetime.now(tz=timezone.utc):
            return None
        return dt
    except Exception:
        return None

async def repair_single_wallet(
    conn: asyncpg.Connection,
    session: aiohttp.ClientSession,
    address: str,
    *,
    apply: bool = False,
):
    addr = address.lower()
    logger.info(f"============================================================")
    logger.info(f"REPAIRING & RE-SYNCING WALLET: {addr}")
    logger.info(f"============================================================")

    # Fetch and validate every replacement source before opening a transaction.
    # The previous script deleted first, so a timeout or API ceiling could leave
    # the wallet permanently empty or partially rebuilt.
    logger.info("Fetching complete closed and open snapshots before any write...")
    closed_result, open_result = await asyncio.gather(
        fetch_closed_positions(session, addr),
        fetch_positions(session, addr),
    )
    closed_list, closed_complete = closed_result
    open_list, open_complete = open_result
    closed_keys = {
        (cp.get("conditionId") or "", cp.get("outcome") or cp.get("asset", ""))
        for cp in closed_list
        if cp.get("conditionId")
    }
    old_count = await conn.fetchval(
        "SELECT COUNT(*) FROM wallet_closed_positions_v2 WHERE address = $1", addr
    )
    logger.info(
        "Preflight old=%s closed=%s complete=%s open=%s complete=%s",
        old_count, len(closed_keys), closed_complete, len(open_list), open_complete,
    )

    if not closed_complete or not open_complete:
        raise RuntimeError("API snapshot is incomplete; canonical rows were not changed")
    if old_count and not closed_keys and not open_list:
        raise RuntimeError("API returned an implausibly empty replacement; canonical rows were not changed")
    if not apply:
        logger.info("DRY RUN: preflight passed; use --apply for the atomic replacement")
        return {
            "address": addr,
            "old_count": old_count,
            "closed_count": len(closed_keys),
            "open_count": len(open_list),
        }

    # Delete and rebuild atomically. Any insert/metric failure restores the old
    # rows, so a repair can never strand a wallet between source snapshots.
    async with conn.transaction():
        await conn.execute("DELETE FROM wallet_closed_positions_v2 WHERE address = $1", addr)
        await conn.execute("DELETE FROM wallet_positions_v2 WHERE address = $1", addr)
        inserted = await upsert_closed_positions_v2(conn, addr, closed_list)
        await aggregate_and_upsert_positions_v2(conn, addr, open_list)
        redeemable = [p for p in open_list if p.get("redeemable", False)]
        redeemed_count = await sync_redeemable_positions(
            conn, session, addr, open_list, closed_keys
        )
        position_value = sum(_parse(p.get("currentValue")) for p in open_list)
        unrealised_pnl = sum(
            _parse(p.get("currentValue")) - _parse(p.get("initialValue"))
            for p in open_list
        )
        parlay_open = [p for p in open_list if _is_parlay(p)]
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (
                address, closed_synced_at, open_synced_at, position_value,
                unrealised_pnl, redeemable_count, redeemable_winning_count,
                parlay_open_count, parlay_open_value
            )
            VALUES ($1, NOW(), NOW(), $2, $3, $4, $5, $6, $7)
            ON CONFLICT (address) DO UPDATE SET
                closed_synced_at = NOW(), open_synced_at = NOW(),
                position_value = EXCLUDED.position_value,
                unrealised_pnl = EXCLUDED.unrealised_pnl,
                redeemable_count = EXCLUDED.redeemable_count,
                redeemable_winning_count = EXCLUDED.redeemable_winning_count,
                parlay_open_count = EXCLUDED.parlay_open_count,
                parlay_open_value = EXCLUDED.parlay_open_value
        """, addr, position_value, unrealised_pnl, len(redeemable),
             sum(1 for p in redeemable if _parse(p.get("currentValue")) > 0),
             len(parlay_open), sum(_parse(p.get("currentValue")) for p in parlay_open))
        await compute_metrics_for_wallet(conn, None, addr)
    logger.info("Atomic replacement committed: closed=%s redeemable=%s", inserted, redeemed_count)

    # 6. Fetch updated metrics and report
    m = await conn.fetchrow("SELECT * FROM wallet_metrics_v2 WHERE address = $1", addr)
    count_closed = await conn.fetchval("SELECT COUNT(*) FROM wallet_closed_positions_v2 WHERE address = $1", addr)

    logger.info(f"--- REPAIR RESULT FOR {addr} ---")
    logger.info(f"  DB pm_pnl (Leaderboard snapshot): ${_parse(m['pm_pnl']):>15,.2f}")
    logger.info(f"  DB total_pnl (Clean Stored):      ${_parse(m['total_pnl']):>15,.2f}")
    logger.info(f"  DB Total Positions Ingested:      {count_closed} positions")
    logger.info(f"  DB Total USD Volume:              ${_parse(m['total_volume']):>15,.2f}")
    logger.info(f"  DB Win Rate:                      {_parse(m['win_rate']):.2f}% ({m['winning_count']} wins / {int(m['resolved_count'] or 0) - int(m['winning_count'] or 0)} losses)")
    logger.info(f"  DB Data Completeness:             {_parse(m['data_completeness_pct']):.2f}%")
    logger.info(f"------------------------------------------------------------\n")

async def main():
    parser = argparse.ArgumentParser(description="Safely rebuild one or more wallet position ledgers")
    parser.add_argument("wallets", nargs="*", help="Wallet addresses (defaults to the audited targets)")
    parser.add_argument("--apply", action="store_true", help="Commit the replacement; default is read-only")
    parser.add_argument("--divergence-file", help="Read unique wallet addresses from the divergence markdown")
    parser.add_argument("--limit", type=int, help="Process only the first N selected wallets")
    args = parser.parse_args()
    selected = list(args.wallets)
    if args.divergence_file:
        with open(args.divergence_file, encoding="utf-8") as handle:
            selected.extend(re.findall(r"0x[a-fA-F0-9]{40}", handle.read()))
    if not selected:
        selected = list(TARGET_WALLETS)
    selected = list(dict.fromkeys(address.lower() for address in selected))
    if args.limit is not None:
        selected = selected[:args.limit]

    conn = await asyncpg.connect(DB_URL)
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        for addr in selected:
            try:
                await repair_single_wallet(conn, session, addr.strip(), apply=args.apply)
            except Exception as exc:
                logger.error("Skipped %s without mutation: %s", addr, exc)
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
