"""
Seed wallet data from extract/ JSON files into the database.

Only maps: win_rate, roi_pct, resolved_count, winning_count.
- Wallets in extract AND in DB: update with extract data (authoritative).
- Wallets in extract AND NOT in DB: insert into tracked_wallets + wallet_stats.
- Wallets in DB AND NOT in extract: queue for re-fetch via wallet_discovery_queue.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

EXTRACT_DIR = Path(__file__).resolve().parent.parent.parent / "extract"

JSON_FILES = [
    "w.json",
    "w2.json",
    "wc.json",
    "trade.json",
    "roi.json",
    "wp.json",
    "ws.json",
    "wo.json",
    "tableConvert.com_ew669z.json",
]


def load_extract_wallets() -> dict[str, dict]:
    """Load all wallets from extract JSON files, deduped by address."""
    wallets: dict[str, dict] = {}
    for fname in JSON_FILES:
        fpath = EXTRACT_DIR / fname
        if not fpath.exists():
            print(f"  SKIP  {fname} (not found)")
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for _key, entry in data.items():
            addr = (entry.get("Wallet") or "").strip().lower()
            if not addr or not addr.startswith("0x"):
                continue
            if addr in wallets:
                continue  # first occurrence wins (dedup)
            wins = int(entry.get("Wins") or 0)
            losses = int(entry.get("Losses") or 0)
            wallets[addr] = {
                "win_rate_raw": float(entry.get("Win Rate %") or 0),  # percentage 0-100
                "roi_pct": float(entry.get("ROI %") or 0),            # percentage
                "resolved_count": wins + losses,
                "winning_count": wins,
            }
            count += 1
        print(f"  OK    {fname}: {count} unique wallets")
    return wallets


async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print("Loading extract files...")
    extract_wallets = load_extract_wallets()
    print(f"\nTotal unique wallets from extract: {len(extract_wallets)}\n")

    if not extract_wallets:
        print("Nothing to do.")
        return

    conn = await asyncpg.connect(db_url)
    try:
        # Get all existing wallet addresses
        rows = await conn.fetch("SELECT address FROM tracked_wallets")
        db_addresses = {r["address"].lower() for r in rows}
        print(f"Wallets already in DB: {len(db_addresses)}")

        extract_addrs = set(extract_wallets.keys())
        to_update = extract_addrs & db_addresses      # in both → update
        to_insert = extract_addrs - db_addresses       # in extract only → insert
        to_refetch = db_addresses - extract_addrs      # in DB only → re-fetch

        print(f"  Update (already in DB):  {len(to_update)}")
        print(f"  Insert (new from extract): {len(to_insert)}")
        print(f"  Re-fetch (DB only, not in extract): {len(to_refetch)}\n")

        # ── UPDATE existing wallets with extract data (authoritative) ──
        if to_update:
            print(f"Updating {len(to_update)} wallets with extract data...")
            for addr in to_update:
                w = extract_wallets[addr]
                win_rate = w["win_rate_raw"] / 100.0  # convert percentage to 0-1 decimal

                await conn.execute("""
                    UPDATE wallet_stats SET
                        win_rate = $2,
                        roi_pct = $3,
                        resolved_count = $4,
                        winning_count = $5,
                        last_updated = NOW()
                    WHERE address = $1
                """, addr, win_rate, w["roi_pct"], w["resolved_count"], w["winning_count"])

                await conn.execute("""
                    UPDATE tracked_wallets SET
                        win_rate = $2,
                        roi_pct = $3,
                        resolved_count = $4,
                        winning_count = $5
                    WHERE address = $1
                """, addr, win_rate, w["roi_pct"], w["resolved_count"], w["winning_count"])

            print(f"  Updated {len(to_update)} wallets.\n")

        # ── INSERT new wallets from extract ──
        if to_insert:
            print(f"Inserting {len(to_insert)} new wallets from extract...")
            for addr in to_insert:
                w = extract_wallets[addr]
                win_rate = w["win_rate_raw"] / 100.0

                # Insert into tracked_wallets
                await conn.execute("""
                    INSERT INTO tracked_wallets
                        (address, source_type, added_at, last_indexed, is_curated, is_dormant,
                         win_rate, roi_pct, resolved_count, winning_count)
                    VALUES ($1, 'leaderboard', NOW(), NOW(), FALSE, FALSE,
                            $2, $3, $4, $5)
                    ON CONFLICT (address) DO UPDATE SET
                        win_rate = EXCLUDED.win_rate,
                        roi_pct = EXCLUDED.roi_pct,
                        resolved_count = EXCLUDED.resolved_count,
                        winning_count = EXCLUDED.winning_count
                """, addr, win_rate, w["roi_pct"], w["resolved_count"], w["winning_count"])

                # Insert into wallet_stats
                await conn.execute("""
                    INSERT INTO wallet_stats
                        (address, win_rate, roi_pct, resolved_count, winning_count,
                         total_volume, total_pnl, last_updated)
                    VALUES ($1, $2, $3, $4, $5, 0, 0, NOW())
                    ON CONFLICT (address) DO UPDATE SET
                        win_rate = EXCLUDED.win_rate,
                        roi_pct = EXCLUDED.roi_pct,
                        resolved_count = EXCLUDED.resolved_count,
                        winning_count = EXCLUDED.winning_count,
                        last_updated = NOW()
                """, addr, win_rate, w["roi_pct"], w["resolved_count"], w["winning_count"])

            print(f"  Inserted {len(to_insert)} wallets.\n")

        # ── QUEUE wallets for re-fetch (in DB but not in extract) ──
        if to_refetch:
            print(f"Queuing {len(to_refetch)} wallets for re-fetch...")
            queued = 0
            for addr in to_refetch:
                result = await conn.execute("""
                    INSERT INTO wallet_discovery_queue (address, spotted_at, processed, source)
                    VALUES ($1, NOW(), FALSE, 'extract-refresh')
                    ON CONFLICT (address) DO UPDATE SET
                        processed = FALSE,
                        spotted_at = NOW(),
                        source = CASE
                            WHEN wallet_discovery_queue.processed = TRUE THEN 'extract-refresh'
                            ELSE wallet_discovery_queue.source
                        END
                """, addr)
                queued += 1
            print(f"  Queued {queued} wallets for re-fetch.\n")

        print("Done!")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
