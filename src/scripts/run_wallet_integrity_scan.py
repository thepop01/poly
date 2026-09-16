"""Read-only consistency scan for the canonical wallet position ledger."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")


async def scan(
    output: Path, *, after: str = "", limit: int = 100, include_dormant: bool = False
) -> list[dict]:
    conn = await asyncpg.connect(DB_URL)
    try:
        addresses = await conn.fetch("""
            SELECT m.address
            FROM wallet_metrics_v2 m
            JOIN wallets_v2 w ON w.address=m.address
            WHERE m.address > $1
              AND ($3::boolean OR NOT w.is_dormant)
            ORDER BY m.address
            LIMIT $2
        """, after, limit, include_dormant)
        selected = [row["address"] for row in addresses]
        if not selected:
            output.write_text("[]\n", encoding="utf-8")
            return []
        rows = await conn.fetch("""
            WITH selected AS (
                SELECT unnest($1::text[]) AS address
            ), ledger AS (
                SELECT address, COUNT(*) AS closed_rows, COALESCE(SUM(realized_pnl), 0) AS ledger_pnl
                FROM wallet_closed_positions_v2
                WHERE COALESCE(metrics_eligible, TRUE) AND address = ANY($1::text[])
                GROUP BY address
            ), roots AS (
                SELECT address, COALESCE(SUM(pnl), 0) AS root_pnl
                FROM category_stats_v2
                WHERE COALESCE(subcategory, '') = '' AND COALESCE(league, '') = ''
                  AND address = ANY($1::text[])
                GROUP BY address
            )
            SELECT s.address, COALESCE(l.closed_rows, 0) AS closed_rows,
                   COALESCE(l.ledger_pnl, 0) AS ledger_pnl,
                   m.total_pnl AS metric_pnl, COALESCE(r.root_pnl, 0) AS root_pnl
            FROM selected s
            LEFT JOIN ledger l ON l.address=s.address
            LEFT JOIN wallet_metrics_v2 m ON m.address=s.address
            LEFT JOIN roots r ON r.address=s.address
            ORDER BY ABS(COALESCE(m.total_pnl, 0)-COALESCE(l.ledger_pnl, 0)) DESC
        """, selected)
    finally:
        await conn.close()

    report = [
        {
            "address": row["address"],
            "closed_rows": int(row["closed_rows"]),
            "ledger_pnl": float(row["ledger_pnl"]),
            "metric_pnl": float(row["metric_pnl"] or 0),
            "metric_delta": float((row["metric_pnl"] or 0) - row["ledger_pnl"]),
            "root_category_pnl": float(row["root_pnl"] or 0),
            "root_delta": float((row["root_pnl"] or 0) - row["ledger_pnl"]),
            # The current schema records sync timestamps, not source-cap flags.
            # Null means unknown, never "not capped".
            "positions_capped": None,
            "closed_capped": None,
            "review_candidate_rows": None,
            "requires_activity_audit": bool(
                abs(float((row["metric_pnl"] or 0) - row["ledger_pnl"])) > 0.01
                or abs(float((row["root_pnl"] or 0) - row["ledger_pnl"])) > 0.01
            ),
        }
        for row in rows
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


async def scan_all(output: Path, batch_size: int, include_dormant: bool = False) -> list[dict]:
    """Run the read-only scan in keyset batches without a full-table sort."""
    cursor = ""
    complete: list[dict] = []
    partial_output = output.with_suffix(output.suffix + ".partial")
    status_output = output.with_suffix(output.suffix + ".status.json")
    while True:
        batch = await scan(
            partial_output, after=cursor, limit=batch_size, include_dormant=include_dormant
        )
        if not batch:
            break
        complete.extend(batch)
        cursor = max(row["address"] for row in batch)
        # A durable cumulative checkpoint makes an interrupted fleet scan
        # observable without treating its partial roster as final.
        partial_output.write_text(json.dumps(complete), encoding="utf-8")
        status = {
            "wallets_scanned": len(complete),
            "requires_activity_audit": sum(row["requires_activity_audit"] for row in complete),
            "next_after": cursor,
            "complete": False,
        }
        status_output.write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(f"scanned={status['wallets_scanned']} flagged={status['requires_activity_audit']} next_after={cursor}", flush=True)
        if len(batch) < batch_size:
            break
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(complete, indent=2), encoding="utf-8")
    partial_output.unlink(missing_ok=True)
    status_output.write_text(json.dumps({
        "wallets_scanned": len(complete),
        "requires_activity_audit": sum(row["requires_activity_audit"] for row in complete),
        "next_after": cursor,
        "complete": True,
    }, indent=2), encoding="utf-8")
    return complete


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only wallet ledger integrity scan")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--after", default="", help="Resume after this lowercase wallet address")
    parser.add_argument("--limit", type=int, default=100, help="Wallets per bounded scan run")
    parser.add_argument("--all", action="store_true", help="Scan all wallets via bounded keyset batches")
    parser.add_argument("--include-dormant", action="store_true", help="Include hibernated wallets (excluded by default)")
    args = parser.parse_args()
    if args.all:
        report = await scan_all(args.output, args.limit, args.include_dormant)
    else:
        report = await scan(
            args.output, after=args.after.lower(), limit=args.limit,
            include_dormant=args.include_dormant,
        )
    print(f"wallets={len(report)} requires_activity_audit={sum(r['requires_activity_audit'] for r in report)} output={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
