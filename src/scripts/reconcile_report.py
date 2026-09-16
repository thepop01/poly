"""Measure position-derived PnL against pm_pnl across a wallet cohort.

Usage:
    python -m src.scripts.reconcile_report --cohort baseline
    python -m src.scripts.reconcile_report --min-pnl 100000 --limit 200
"""
import argparse
import asyncio
import json
import os

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.pnl.reconcile import reconcile_wallet

load_dotenv()

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))
BASE = "https://data-api.polymarket.com"
OUT_PATH = "reconcile_report.json"

# The 20 wallets audited in docs/problem.md, used as the fixed regression cohort.
BASELINE = [
    ("sainttroplay", "0x9319a045cdd0c2180e5eb7ad44374383db9a6410"),
    ("Supah9ga", "0x57cd939930fd119067ca9dc42b22b3e15708a0fb"),
    ("BreakTheBank", "0xf0318c32136c2db7fec88b84869aee6a1106c80c"),
    ("gmpm", "0x14964aefa2cd7caff7878b3820a690a03c5aa429"),
    ("tdrhrhhd", "0xd7f85d0eb0fe0732ca38d9107ad0d4d01b1289e4"),
    ("afkpnlucl", "0x55eca3687ea7d69632ffe0f297ea3d5158bb8c7d"),
    ("XAE12Archangel", "0xfbfd14dd4bb607373119de95f1d4b21c3b6c0029"),
    ("wallet_2c33506", "0x2c335066fe58fe9237c3d3dc7b275c2a034a0563"),
    ("wallet_09b428f", "0x09b428f7c2b469786286214aa5c90dd9015f7320"),
    ("Gucky-45", "0xe613b515bd46b1585a8b137a4d291d9b80bd540e"),
    ("Siziriv", "0x8e9eedf20dfa70956d49f608a205e402d9df38e4"),
    ("AnonymousUsername", "0x9703676286b93c2eca71ca96e8757104519a69c2"),
    ("ImJustKen", "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"),
    ("Anjun", "0x43372356634781eea88d61bbdd7824cdce958882"),
    ("wokerjoesleeper", "0x63d43bbb87f85af03b8f2f9e2fad7b54334fa2f1"),
    ("Cannae", "0x7ea571c40408f340c1c8fc8eaacebab53c1bde7b"),
    ("ferrariChampions2026", "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"),
    ("alwayslatetotheparty", "0xb687f00464e33934f5d591f224e71c3559ecaee5"),
    ("swisstony", "0x204f72f35326db932158cba6adff0b9a1da95e14"),
    ("debased", "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1"),
]


async def _get(session, path, params, retries=6):
    for attempt in range(retries):
        try:
            async with session.get(BASE + path, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        await asyncio.sleep(1.0 * (attempt + 1))
    return None


async def _page_all(session, path, address, limit, extra, ceiling=30_000):
    """Page an endpoint, deduping because /positions wraps past the end."""
    rows, offset, seen = [], 0, set()
    while offset <= ceiling:
        params = {"user": address, "limit": limit, "offset": offset}
        params.update(extra)
        page = await _get(session, path, params)
        if not page:
            break
        fresh = 0
        for row in page:
            key = (row.get("conditionId"), row.get("outcome"), row.get("asset"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            fresh += 1
        if fresh == 0 or len(page) < limit:
            break
        offset += limit
    return rows


async def fetch_wallet(session, address):
    board = await _get(session, "/v1/leaderboard",
                       {"user": address, "category": "OVERALL",
                        "timePeriod": "ALL"})
    if isinstance(board, dict):
        pm_pnl = float(board.get("pnl") or 0)
    elif isinstance(board, list) and board:
        pm_pnl = float(board[0].get("pnl") or 0)
    else:
        pm_pnl = 0.0

    closed = await _page_all(session, "/closed-positions", address, 50,
                             {"sortBy": "TIMESTAMP", "sortDirection": "DESC"})
    open_rows = await _page_all(session, "/positions", address, 500,
                                {"sortBy": "CURRENT", "sortDirection": "DESC"})
    return pm_pnl, closed, open_rows


async def load_cohort(args):
    if args.cohort == "baseline":
        return BASELINE
    conn = await asyncpg.connect(DB_URL)
    rows = await conn.fetch("""
        SELECT m.address, COALESCE(w.username, m.address) AS username
        FROM wallet_metrics_v2 m
        LEFT JOIN wallets_v2 w ON w.address = m.address
        WHERE m.pm_pnl IS NOT NULL AND abs(m.pm_pnl) >= $1
        ORDER BY abs(m.pm_pnl) DESC
        LIMIT $2
    """, args.min_pnl, args.limit)
    await conn.close()
    return [(r["username"], r["address"]) for r in rows]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", default="baseline",
                        choices=["baseline", "db"])
    parser.add_argument("--min-pnl", type=float, default=100_000.0)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    cohort = await load_cohort(args)
    timeout = aiohttp.ClientTimeout(total=900, connect=30)
    results = []

    header = (f"{'wallet':<22}{'pm_pnl':>13}{'total_pnl':>13}"
              f"{'residual':>13}{'err%':>8}  archetype")
    print(header)
    print("-" * len(header))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, address in cohort:
            try:
                pm_pnl, closed, open_rows = await fetch_wallet(session, address)
            except Exception as exc:
                print(f"{name:<22}  ERROR {type(exc).__name__}: {exc}")
                continue
            result = reconcile_wallet(closed, open_rows, pm_pnl)
            payload = {"wallet": name, "address": address,
                       **result.__dict__}
            results.append(payload)
            print(f"{name:<22}{result.pm_pnl:>13,.0f}{result.total_pnl:>13,.0f}"
                  f"{result.residual:>13,.0f}{result.relative_error:>7.1f}%"
                  f"  {result.source}")
            with open(OUT_PATH, "w") as handle:
                json.dump(results, handle, indent=2)

    reconcilable = [r for r in results if r["source"] == "directional"]
    print("-" * len(header))
    print(f"cohort={len(results)}  directional={len(reconcilable)}")
    if reconcilable:
        errors = sorted(r["relative_error"] for r in reconcilable)
        median = errors[len(errors) // 2]
        within = sum(1 for e in errors if e <= 20)
        print(f"directional median error = {median:.1f}%   "
              f"within 20% = {within}/{len(errors)}")
        print(f"ACCEPTANCE: {'PASS' if median <= 20 else 'FAIL'} "
              f"(target median <= 20%)")
    for archetype in ("complete_set_minter", "truncated_history",
                      "no_position_data"):
        flagged = [r["wallet"] for r in results if r["source"] == archetype]
        if flagged:
            print(f"{archetype}: {flagged}")


if __name__ == "__main__":
    asyncio.run(main())
