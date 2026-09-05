"""Materialize canonical P2P transfer history into the lineage trade ledger.

The source of truth remains ``wallet_position_transfers_v2``.  This command
is resumable by source ID and does not fetch APIs or alter positions/metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg


DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
SOURCE_NAME = "wallet_position_transfers_v2"


async def materialize(batch_size: int = 25_000, max_batches: int | None = None) -> dict[str, int | bool]:
    conn = await asyncpg.connect(DB_URL)
    batches = source_rows = 0
    try:
        await conn.execute("""
            INSERT INTO lineage_ledger_materialization_state_v2 (source_name)
            VALUES ($1) ON CONFLICT (source_name) DO NOTHING
        """, SOURCE_NAME)
        while max_batches is None or batches < max_batches:
            state = await conn.fetchrow("""
                SELECT last_source_id, complete
                FROM lineage_ledger_materialization_state_v2 WHERE source_name=$1
                FOR UPDATE
            """, SOURCE_NAME)
            if state["complete"]:
                max_source_id = await conn.fetchval("SELECT COALESCE(MAX(id), 0) FROM wallet_position_transfers_v2")
                if state["last_source_id"] >= max_source_id:
                    break
                await conn.execute("""
                    UPDATE lineage_ledger_materialization_state_v2
                    SET complete=FALSE, updated_at=NOW() WHERE source_name=$1
                """, SOURCE_NAME)
            rows = await conn.fetch("""
                SELECT id, from_address, to_address, token_id, amount, tx_hash,
                       block_number, transferred_at, log_index
                FROM wallet_position_transfers_v2
                WHERE id > $1
                ORDER BY id
                LIMIT $2
            """, state["last_source_id"], batch_size)
            if not rows:
                await conn.execute("""
                    UPDATE lineage_ledger_materialization_state_v2
                    SET complete=TRUE, updated_at=NOW(), last_error=NULL
                    WHERE source_name=$1
                """, SOURCE_NAME)
                break
            async with conn.transaction():
                await conn.executemany("""
                    INSERT INTO wallet_lineage_trades_v2 (
                        wallet_address, event_type, counterparty, asset, amount, amount_usd,
                        tx_hash, block_number, event_at, log_index
                    ) VALUES ($1,$2,$3,$4,$5,0,$6,$7,$8,$9)
                    ON CONFLICT DO NOTHING
                """, [entry for row in rows for entry in (
                    (row["from_address"], "TRANSFER_OUT", row["to_address"], row["token_id"], row["amount"], row["tx_hash"], row["block_number"], row["transferred_at"], row["log_index"]),
                    (row["to_address"], "TRANSFER_IN", row["from_address"], row["token_id"], row["amount"], row["tx_hash"], row["block_number"], row["transferred_at"], row["log_index"]),
                )])
                await conn.execute("""
                    UPDATE lineage_ledger_materialization_state_v2
                    SET last_source_id=$2, updated_at=NOW(), last_error=NULL
                    WHERE source_name=$1
                """, SOURCE_NAME, rows[-1]["id"])
            batches += 1
            source_rows += len(rows)
    except Exception as exc:
        await conn.execute("""
            UPDATE lineage_ledger_materialization_state_v2
            SET last_error=$2, updated_at=NOW() WHERE source_name=$1
        """, SOURCE_NAME, str(exc)[:2000])
        raise
    finally:
        await conn.close()
    final_state = await asyncpg.connect(DB_URL)
    try:
        complete = bool(await final_state.fetchval(
            "SELECT complete FROM lineage_ledger_materialization_state_v2 WHERE source_name=$1", SOURCE_NAME
        ))
    finally:
        await final_state.close()
    return {"batches": batches, "source_rows": source_rows, "complete": complete}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=25_000)
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args()
    print(await materialize(args.batch_size, args.max_batches))


if __name__ == "__main__":
    asyncio.run(main())
