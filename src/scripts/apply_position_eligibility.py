"""Apply only evidence-proven position exclusions; dry-run by default."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

import asyncpg
from dotenv import load_dotenv

from src.workers.compute_category_stats import compute_category_stats_for_wallet
from src.workers.compute_core_metrics import compute_core_metrics_for_wallet
from src.workers.compute_historical_windows import compute_historical_windows_for_wallet

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")


async def apply_audit(audit_id: uuid.UUID, apply: bool) -> dict:
    conn = await asyncpg.connect(DB_URL)
    try:
        decisions = await conn.fetch("""
            SELECT address, condition_id, outcome, reason
            FROM wallet_position_audit_decisions_v2
            WHERE audit_id=$1 AND status='excluded_proven'
            ORDER BY address, condition_id, outcome
        """, audit_id)
        if not decisions:
            raise ValueError("audit has no evidence-proven exclusions")
        addresses = sorted({row["address"] for row in decisions})
        result = {"audit_id": str(audit_id), "rows": len(decisions), "addresses": addresses, "applied": apply}
        if not apply:
            return result
        async with conn.transaction():
            await conn.executemany("""
                UPDATE wallet_closed_positions_v2
                SET metrics_eligible=FALSE, exclusion_reason=$4, excluded_at=NOW()
                WHERE address=$1 AND condition_id=$2 AND outcome=$3
            """, [(row["address"], row["condition_id"], row["outcome"], row["reason"]) for row in decisions])
            for address in addresses:
                await compute_core_metrics_for_wallet(conn, address)
                await compute_category_stats_for_wallet(conn, address)
                await compute_historical_windows_for_wallet(conn, address)
                ledger = await conn.fetchval("SELECT COALESCE(SUM(realized_pnl),0) FROM wallet_closed_positions_v2 WHERE address=$1 AND COALESCE(metrics_eligible,TRUE)", address)
                metric = await conn.fetchval("SELECT total_pnl FROM wallet_metrics_v2 WHERE address=$1", address)
                if abs(float(ledger)-float(metric or 0)) > 0.01:
                    raise RuntimeError(f"post-apply metric mismatch for {address}")
        return result
    finally:
        await conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-id", type=uuid.UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(await apply_audit(args.audit_id, args.apply))


if __name__ == "__main__":
    asyncio.run(main())
