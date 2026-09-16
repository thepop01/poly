"""
One-time fetch: win_rate, roi_pct, resolved_count, winning_count
from Supabase wallet_profile API for all wallets that were in DB
but NOT in the extract files.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
import asyncpg
from dotenv import load_dotenv

load_dotenv()

EXTRACT_DIR = Path(__file__).resolve().parent.parent.parent / "extract"
JSON_FILES = [
    "w.json", "w2.json", "wc.json", "trade.json", "roi.json",
    "wp.json", "ws.json", "wo.json", "tableConvert.com_ew669z.json",
]

SUPABASE_URL = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api"
SUPABASE_KEY = "psk_484dc263029d449f94dffa4da813ddff"
SUPABASE_DELAY = 2.0  # 30 calls/min rate limit


def load_extract_addresses() -> set[str]:
    addrs: set[str] = set()
    for fname in JSON_FILES:
        fpath = EXTRACT_DIR / fname
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for _key, entry in data.items():
            a = (entry.get("Wallet") or "").strip().lower()
            if a and a.startswith("0x") and len(a) == 42:
                addrs.add(a)
    return addrs


def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def fetch_supabase_profile(session: aiohttp.ClientSession, address: str) -> dict | None:
    url = f"{SUPABASE_URL}?endpoint=wallet_profile&address={address}"
    headers = {"x-api-key": SUPABASE_KEY}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 429:
                await asyncio.sleep(60)
                return None
            if resp.status != 200:
                return None
            body = await resp.json()
            data = body.get("data", {})
            if not data:
                return None
            win_rate_raw = data.get("win_rate")
            roi = data.get("roi")
            wins = data.get("wins")
            losses = data.get("losses")
            wr = _parse(win_rate_raw) / 100.0 if win_rate_raw is not None else None
            resolved = int(_parse(wins)) + int(_parse(losses))
            winning = int(_parse(wins))
            return {
                "win_rate": wr,
                "roi_pct": _parse(roi),
                "resolved_count": resolved,
                "winning_count": winning,
            }
    except Exception:
        return None


async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    extract_addrs = load_extract_addresses()
    print(f"Extract wallets: {len(extract_addrs)}")

    conn = await asyncpg.connect(db_url)
    # Get all wallets NOT in extract
    all_rows = await conn.fetch("SELECT address FROM tracked_wallets")
    all_addrs = {r["address"].lower() for r in all_rows}
    non_extract = all_addrs - extract_addrs
    await conn.close()

    print(f"Total wallets in DB: {len(all_addrs)}")
    print(f"Non-extract wallets to fetch: {len(non_extract)}")
    print(f"Estimated time: {len(non_extract) * SUPABASE_DELAY / 60:.0f} minutes\n")

    conn = await asyncpg.connect(db_url)
    success = 0
    failed = 0
    no_data = 0

    try:
        async with aiohttp.ClientSession() as session:
            for i, addr in enumerate(sorted(non_extract)):
                profile = await fetch_supabase_profile(session, addr)

                if not profile:
                    no_data += 1
                    failed += 1
                else:
                    if profile["win_rate"] is not None or profile["resolved_count"] > 0:
                        await conn.execute("""
                            UPDATE wallet_stats SET
                                win_rate = COALESCE($2, win_rate),
                                roi_pct = COALESCE($3, roi_pct),
                                resolved_count = GREATEST($4, resolved_count),
                                winning_count = GREATEST($5, winning_count),
                                sb_win_rate = $2, sb_roi_pct = $3,
                                sb_resolved_count = $4, sb_winning_count = $5,
                                last_updated = NOW()
                            WHERE address = $1
                        """, addr, profile["win_rate"], profile["roi_pct"],
                            profile["resolved_count"], profile["winning_count"])

                        await conn.execute("""
                            UPDATE tracked_wallets SET
                                win_rate = COALESCE($2, win_rate),
                                roi_pct = COALESCE($3, roi_pct),
                                resolved_count = GREATEST($4, resolved_count),
                                winning_count = GREATEST($5, winning_count),
                                sb_win_rate = $2, sb_roi_pct = $3,
                                sb_resolved_count = $4, sb_winning_count = $5,
                                sb_updated_at = NOW()
                            WHERE address = $1
                        """, addr, profile["win_rate"], profile["roi_pct"],
                            profile["resolved_count"], profile["winning_count"])

                    success += 1

                done = success + failed
                if done % 100 == 0:
                    print(f"  [{done}/{len(non_extract)}] ok={success} fail={failed} no_data={no_data}")

                await asyncio.sleep(SUPABASE_DELAY)

        print(f"\nDone! ok={success} fail={failed} no_data={no_data}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
