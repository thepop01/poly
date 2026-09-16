# Curated Trade Feed + global_wallet_trades Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store raw individual trades for curated wallets in a dedicated table with a per-wallet sync cursor, fed by incremental Polygon polls, and retire the unused `global_wallet_trades` table.

**Architecture:** A `curated_trades` table (one row per fill) plus a `curated_trade_sync` cursor table (per-wallet `last_synced_block`). A worker polls each curated wallet's OrderFilled logs from `last_synced_block+1` via the existing `fetch_historical_trades_polygonscan`, upserts fills, advances the cursor. This pipeline is independent of the win-rate/positions pipeline (separate plan) — trades drive a future feed UI only, never metrics. Finally, drop `global_wallet_trades` after confirming it has no readers.

**Tech Stack:** Python 3, asyncpg, PostgreSQL, aiohttp, alembic, pytest.

---

## Verified facts (code, 2026-07-20)

- `fetch_historical_trades_polygonscan(session, addresses: list[str]) -> list[dict]` — `etherscan_client.py:304`. Returns dicts with: `wallet, size, token_size, price, usd_volume, asset, conditionId, transactionHash, timestamp, side, title, category, subcategory, market_id, blockNumber`.
- **No per-wallet sync cursor table exists.** Only `trade_tracker.py:29` keeps a flat global file `.whale_last_block`. Task 2 adds a real per-wallet cursor.
- `global_wallet_trades`: ONE writer (`leaderboard_stats.py:1517`, curated branch), **zero readers**. `trades_v2.py` + frontend read `wallet_activity_v2` instead. Dropping is low-risk — but re-grep at implementation time.
- Existing table unique key on `global_wallet_trades` is `(wallet_address, tx_hash)` — insufficient for multi-fill txs; `curated_trades` uses `(tx_hash, log_index)`.

## Sequencing note

This plan is **independent** of the win-rate plan and can run in parallel. The
`global_wallet_trades` drop (Task 4) must come LAST and only after Task 5's
reader-grep confirms zero readers.

## File structure

- Create: `alembic/versions/<rev>_add_curated_trades.py` — `curated_trades` + `curated_trade_sync`.
- Create: `src/workers/curated_trade_feed.py` — incremental per-wallet poll + upsert.
- Create: `tests/test_curated_trade_feed.py`.
- Modify (Task 4): `src/workers/leaderboard_stats.py` — remove `global_wallet_trades` writer; drop table via migration.

## Task 1: `curated_trades` + `curated_trade_sync` tables

**Files:**
- Create: `alembic/versions/<rev>_add_curated_trades.py`

- [ ] **Step 1: Generate a revision stub**

Run: `python -m alembic revision -m "add curated_trades and sync cursor"`
Expected: prints the new file path. Open it.

- [ ] **Step 2: Fill in `upgrade()` / `downgrade()`**

```python
def upgrade():
    op.create_table(
        "curated_trades",
        sa.Column("tx_hash", sa.Text, nullable=False),
        sa.Column("log_index", sa.Integer, nullable=False),
        sa.Column("wallet_address", sa.Text, nullable=False),
        sa.Column("condition_id", sa.Text, nullable=True),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("side", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric, server_default="0"),
        sa.Column("size", sa.Numeric, server_default="0"),
        sa.Column("amount_usdc", sa.Numeric, server_default="0"),
        sa.Column("traded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("market_name", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("subcategory", sa.Text, nullable=True),
        sa.Column("block_number", sa.BigInteger, nullable=True),
        sa.PrimaryKeyConstraint("tx_hash", "log_index"),
    )
    op.create_index("ix_curated_trades_wallet_time",
                    "curated_trades", ["wallet_address", "traded_at"])
    op.create_table(
        "curated_trade_sync",
        sa.Column("wallet_address", sa.Text, primary_key=True),
        sa.Column("last_synced_block", sa.BigInteger, server_default="0"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("curated_trade_sync")
    op.drop_index("ix_curated_trades_wallet_time", table_name="curated_trades")
    op.drop_table("curated_trades")
```

- [ ] **Step 3: Apply + verify clean replay**

Run: `python -m alembic upgrade head && python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: upgrade, downgrade, re-upgrade, all without error.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat(trades): add curated_trades + curated_trade_sync tables"
```

## Task 2: Incremental trade-feed worker

**Files:**
- Create: `src/workers/curated_trade_feed.py`
- Test: `tests/test_curated_trade_feed.py`

- [ ] **Step 1: Write the failing test for the pure row mapper**

```python
# tests/test_curated_trade_feed.py
from src.workers.curated_trade_feed import trade_to_row


def test_trade_to_row_maps_fields():
    t = {
        "wallet": "0xabc", "transactionHash": "0xdead", "conditionId": "0xcid",
        "side": "BUY", "price": 0.4, "size": 100.0, "usd_volume": 40.0,
        "timestamp": 1700000000, "title": "Team A wins", "category": "SPORTS",
        "subcategory": "NFL", "blockNumber": 555, "outcome": "Yes",
    }
    row = trade_to_row(t, log_index=3)
    assert row["tx_hash"] == "0xdead"
    assert row["log_index"] == 3
    assert row["wallet_address"] == "0xabc"
    assert row["amount_usdc"] == 40.0
    assert row["block_number"] == 555
    assert row["traded_at"] is not None  # epoch converted to datetime
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_curated_trade_feed.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement mapper + worker**

```python
# src/workers/curated_trade_feed.py
"""Incremental per-wallet trade feed for curated wallets. Independent of the
win-rate pipeline — feeds a future trade-feed UI only."""
import logging
from datetime import datetime, timezone

import aiohttp
import asyncpg

from src.utils.etherscan_client import fetch_historical_trades_polygonscan

logger = logging.getLogger(__name__)


def trade_to_row(t: dict, log_index: int) -> dict:
    ts = t.get("timestamp")
    traded_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    return {
        "tx_hash": t.get("transactionHash") or "",
        "log_index": log_index,
        "wallet_address": (t.get("wallet") or "").lower(),
        "condition_id": t.get("conditionId") or t.get("market_id"),
        "outcome": t.get("outcome"),
        "side": t.get("side"),
        "price": float(t.get("price") or 0),
        "size": float(t.get("size") or 0),
        "amount_usdc": float(t.get("usd_volume") or 0),
        "traded_at": traded_at,
        "market_name": t.get("title"),
        "category": t.get("category"),
        "subcategory": t.get("subcategory"),
        "block_number": t.get("blockNumber"),
    }


async def sync_wallet_trades(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Fetch new fills for one curated wallet since its cursor, upsert, advance."""
    address = address.lower()
    trades = await fetch_historical_trades_polygonscan(session, [address])
    if not trades:
        return 0
    max_block = 0
    inserted = 0
    # log_index is not returned by the parser; synthesize a stable per-tx index
    # by ordering fills within a tx. Two fills sharing (tx_hash) get 0,1,2...
    seen_tx: dict[str, int] = {}
    for t in sorted(trades, key=lambda x: (x.get("transactionHash") or "", x.get("blockNumber") or 0)):
        txh = t.get("transactionHash") or ""
        idx = seen_tx.get(txh, 0)
        seen_tx[txh] = idx + 1
        row = trade_to_row(t, idx)
        if not row["tx_hash"] or row["wallet_address"] != address:
            continue
        await conn.execute(
            """
            INSERT INTO curated_trades
                (tx_hash, log_index, wallet_address, condition_id, outcome, side,
                 price, size, amount_usdc, traded_at, market_name, category,
                 subcategory, block_number)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (tx_hash, log_index) DO NOTHING
            """,
            row["tx_hash"], row["log_index"], row["wallet_address"], row["condition_id"],
            row["outcome"], row["side"], row["price"], row["size"], row["amount_usdc"],
            row["traded_at"], row["market_name"], row["category"], row["subcategory"],
            row["block_number"],
        )
        inserted += 1
        max_block = max(max_block, int(row["block_number"] or 0))
    await conn.execute(
        """
        INSERT INTO curated_trade_sync (wallet_address, last_synced_block, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (wallet_address) DO UPDATE SET
            last_synced_block = GREATEST(curated_trade_sync.last_synced_block, EXCLUDED.last_synced_block),
            updated_at = NOW()
        """,
        address, max_block,
    )
    return inserted
```

Note: `fetch_historical_trades_polygonscan` currently scans from block 0. The
`last_synced_block` cursor is stored for the incremental optimization, but wiring
it INTO the fetch (a `from_block` param) is a follow-up — see Deferred. For now
the `ON CONFLICT DO NOTHING` upsert makes re-scans idempotent.

- [ ] **Step 4: Run the mapper test**

Run: `python -m pytest tests/test_curated_trade_feed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/workers/curated_trade_feed.py tests/test_curated_trade_feed.py
git commit -m "feat(trades): incremental curated trade-feed worker"
```

## Task 3: Idempotency integration test

**Files:**
- Test: `tests/test_curated_trade_feed.py` (append)

- [ ] **Step 1: Add the upsert idempotency test**

```python
import os, pytest, asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")


@pytest.mark.asyncio
async def test_upsert_is_idempotent():
    c = await asyncpg.connect(DB_URL)
    tx = c.transaction(); await tx.start()
    row = dict(tx_hash="0xfeed", log_index=0, wallet_address="0x"+"dd"*20,
               condition_id="0x1", outcome="Yes", side="BUY", price=0.5, size=10,
               amount_usdc=5, traded_at=None, market_name="m", category="SPORTS",
               subcategory=None, block_number=1)
    sql = """INSERT INTO curated_trades (tx_hash,log_index,wallet_address,condition_id,outcome,side,price,size,amount_usdc,traded_at,market_name,category,subcategory,block_number)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) ON CONFLICT (tx_hash,log_index) DO NOTHING"""
    args = list(row.values())
    await c.execute(sql, *args)
    await c.execute(sql, *args)  # second insert must be a no-op
    n = await c.fetchval("SELECT COUNT(*) FROM curated_trades WHERE tx_hash='0xfeed'")
    assert n == 1
    await tx.rollback(); await c.close()
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_curated_trade_feed.py::test_upsert_is_idempotent -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_curated_trade_feed.py
git commit -m "test(trades): curated_trades upsert idempotency"
```

## Task 4: Retire `global_wallet_trades`

**Files:**
- Modify: `src/workers/leaderboard_stats.py` (remove the INSERT near line 1517)
- Create: `alembic/versions/<rev>_drop_global_wallet_trades.py`

- [ ] **Step 1: Confirm zero readers (safety gate)**

Run: `grep -rn "global_wallet_trades" src/ frontend/src/`
Expected: only the writer in `leaderboard_stats.py`. If ANY read appears, STOP and revise.

- [ ] **Step 2: Remove the writer**

In `src/workers/leaderboard_stats.py`, delete the `INSERT INTO global_wallet_trades ... ON CONFLICT (wallet_address, tx_hash) DO NOTHING` block (~lines 1517-1524) and any loop that exists solely to feed it. Leave the rest of `process_wallet` intact.

- [ ] **Step 3: Verify module parses**

Run: `python -c "import src.workers.leaderboard_stats"`
Expected: no output, exit 0.

- [ ] **Step 4: Migration to drop the table**

Run: `python -m alembic revision -m "drop global_wallet_trades"`
Then fill:

```python
def upgrade():
    op.drop_table("global_wallet_trades")


def downgrade():
    # Recreate minimal shape for rollback safety (data is not restored).
    op.create_table(
        "global_wallet_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("wallet_address", sa.Text),
        sa.Column("tx_hash", sa.Text),
        sa.Column("condition_id", sa.Text),
        sa.Column("market_name", sa.Text),
        sa.Column("side", sa.Text),
        sa.Column("price", sa.Numeric),
        sa.Column("size", sa.Numeric),
        sa.Column("amount_usdc", sa.Numeric),
        sa.Column("traded_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("category", sa.Text),
        sa.Column("subcategory", sa.Text),
        sa.UniqueConstraint("wallet_address", "tx_hash"),
    )
```

- [ ] **Step 5: Apply**

Run: `python -m alembic upgrade head`
Expected: `Running upgrade ... drop global_wallet_trades`.

- [ ] **Step 6: Commit**

```bash
git add src/workers/leaderboard_stats.py alembic/versions/
git commit -m "refactor(trades): retire unused global_wallet_trades table"
```

## Manual verification (after all tasks)

- [ ] `python -m pytest tests/test_curated_trade_feed.py -v` → all PASS.
- [ ] Run `sync_wallet_trades` for one curated wallet; confirm `curated_trades` rows appear and `curated_trade_sync.last_synced_block` advances.
- [ ] Confirm the app still starts and `/v2/trades` + the wallet page still work (they read `wallet_activity_v2`, unaffected).

## Deferred / follow-ups (not in this plan)

- Add a `from_block` parameter to `fetch_historical_trades_polygonscan` and pass `last_synced_block+1` to make polls truly incremental (currently idempotent full re-scan).
- The trade-feed UI itself.
- Sourcing `outcome`/`log_index` more precisely from raw logs (the parser aggregates per tx today).
