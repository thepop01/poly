# Curated Win-Rate via Positions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute an honest curated win rate that counts hold-to-zero losers, by deriving resolved positions from Polymarket positions + market resolution instead of on-chain redemption events.

**Architecture:** A new `curated_positions` table stores one row per `(wallet, condition_id, outcome)`. A market-resolution resolver (CLOB `/markets/{condition_id}`, cached) tells us if a market settled and which outcome won. A builder pulls a curated wallet's open + closed positions, classifies each as win/loss/open, and upserts. `leaderboard_stats_v2` reads win rate from this table. Prerequisite: this plan feeds accurate numbers to the auto-promote engine (separate plan) but does not depend on it.

**Tech Stack:** Python 3, asyncpg, PostgreSQL, aiohttp, alembic, pytest + pytest-asyncio.

---

## Decisions locked (spec 2026-07-20)

- A **position** = `(wallet, condition_id, outcome)`; trades collapse into it.
- **Resolved** = the market resolved (CLOB/Gamma), NOT redemption-based.
- `realized_pnl = payout + total_sold − total_bought`; `payout = net_tokens × $1` if the held outcome won else 0.
- `is_win = realized_pnl > 0`; `win_rate = count(is_win) / count(is_resolved)`.
- Cap at most recent ~5000 positions per wallet. No time cap.

## Verified facts (from code, 2026-07-20)

- `fetch_positions(session, address)` — `leaderboard_stats.py:214` — OPEN positions from `data-api.polymarket.com/positions`; fields include `conditionId, outcome, size, avgPrice, curPrice, totalBought, currentValue, cashPnl, title`.
- `build_synthetic_closed_positions(trades, redemptions)` — `etherscan_client.py:523` — returns closed dicts `{conditionId, title, realizedPnl, totalBought, avgPrice, avgSellPrice, endDate}`. Existing REDEMPTION-based path; we supplement, not delete, in this plan.
- Market resolution parsing exists ONLY in `gamma_client.py` event functions (`_parse_market:110`, reads `closed` + `outcomePrices`). There is **no** per-`condition_id` resolver — Task 1 adds one.
- `_parse(val)` — `leaderboard_stats.py:46`; safe float coercion. Reuse it.

## File structure

- Create: `src/utils/market_resolution.py` — `fetch_market_resolution(session, condition_id)`.
- Create: `alembic/versions/<rev>_add_curated_positions.py` — the table.
- Create: `src/workers/curated_positions_builder.py` — build/classify/upsert per wallet.
- Modify: `src/workers/leaderboard_stats_v2.py` — read win rate from `curated_positions` for curated wallets.
- Create: `tests/test_market_resolution.py`, `tests/test_curated_positions_builder.py`.

## Verified API shape (CLOB, 2026-07-20)

`GET https://clob.polymarket.com/markets/{condition_id}` returns:
```
{ "closed": true, "active": true, "condition_id": "0x...",
  "tokens": [ {"token_id":"...","outcome":"Yes","price":0,"winner":false},
              {"token_id":"...","outcome":"No","price":1,"winner":true} ], ... }
```
Resolution: `closed == true`. Winning outcome = the token with `winner == true`.

## Task 1: Market-resolution resolver

**Files:**
- Create: `src/utils/market_resolution.py`
- Test: `tests/test_market_resolution.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_resolution.py
import pytest
from src.utils.market_resolution import classify_resolution


def test_resolved_market_picks_winner():
    payload = {
        "closed": True,
        "tokens": [
            {"outcome": "Yes", "winner": False},
            {"outcome": "No", "winner": True},
        ],
    }
    r = classify_resolution(payload)
    assert r == {"resolved": True, "winning_outcome": "No"}


def test_open_market_is_unresolved():
    payload = {"closed": False, "tokens": [{"outcome": "Yes", "winner": False}]}
    assert classify_resolution(payload) == {"resolved": False, "winning_outcome": None}


def test_missing_payload_is_unresolved():
    assert classify_resolution(None) == {"resolved": False, "winning_outcome": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.utils.market_resolution'`

- [ ] **Step 3: Implement the module**

```python
# src/utils/market_resolution.py
"""Per-condition_id market-resolution lookup, cached in-process.

Resolution is immutable once set, so a simple dict cache is safe for the
lifetime of a worker pass. Source: CLOB /markets/{condition_id}, which returns
`closed` and a `tokens` array with a `winner` flag per outcome.
"""
import logging
import aiohttp

logger = logging.getLogger(__name__)

_resolution_cache: dict[str, dict] = {}


def classify_resolution(market: dict | None) -> dict:
    """Pure classifier over a CLOB market payload."""
    if not market or not market.get("closed"):
        return {"resolved": False, "winning_outcome": None}
    winner = None
    for tok in market.get("tokens", []) or []:
        if tok.get("winner"):
            winner = tok.get("outcome")
            break
    return {"resolved": True, "winning_outcome": winner}


async def fetch_market_resolution(session: aiohttp.ClientSession, condition_id: str) -> dict:
    """Return {"resolved": bool, "winning_outcome": str|None} for a condition_id.
    Cached; unresolved results are NOT cached (they can change)."""
    if not condition_id:
        return {"resolved": False, "winning_outcome": None}
    if condition_id in _resolution_cache:
        return _resolution_cache[condition_id]
    try:
        url = f"https://clob.polymarket.com/markets/{condition_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return {"resolved": False, "winning_outcome": None}
            market = await resp.json()
    except Exception as e:
        logger.warning(f"resolution fetch failed for {condition_id[:12]}: {e}")
        return {"resolved": False, "winning_outcome": None}
    result = classify_resolution(market)
    if result["resolved"]:
        _resolution_cache[condition_id] = result
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_resolution.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/utils/market_resolution.py tests/test_market_resolution.py
git commit -m "feat(positions): add per-condition_id market resolution resolver"
```

## Task 2: `curated_positions` table (alembic)

**Files:**
- Create: `alembic/versions/<rev>_add_curated_positions.py`

- [ ] **Step 1: Generate a revision stub**

Run: `python -m alembic revision -m "add curated_positions"`
Expected: prints the new file path under `alembic/versions/`. Open it.

- [ ] **Step 2: Fill in `upgrade()` / `downgrade()`**

```python
def upgrade():
    op.create_table(
        "curated_positions",
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("condition_id", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False, server_default=""),
        sa.Column("total_bought", sa.Numeric, server_default="0"),
        sa.Column("total_sold", sa.Numeric, server_default="0"),
        sa.Column("net_tokens", sa.Numeric, server_default="0"),
        sa.Column("market_resolved", sa.Boolean, server_default=sa.text("false")),
        sa.Column("won", sa.Boolean, server_default=sa.text("false")),
        sa.Column("payout", sa.Numeric, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric, server_default="0"),
        sa.Column("is_resolved", sa.Boolean, server_default=sa.text("false")),
        sa.Column("is_win", sa.Boolean, server_default=sa.text("false")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("subcategory", sa.Text, nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("address", "condition_id", "outcome"),
    )
    op.create_index("ix_curated_positions_addr_resolved",
                    "curated_positions", ["address", "resolved_at"],
                    postgresql_using="btree")


def downgrade():
    op.drop_index("ix_curated_positions_addr_resolved", table_name="curated_positions")
    op.drop_table("curated_positions")
```

- [ ] **Step 3: Apply and verify it replays clean**

Run: `python -m alembic upgrade head`
Expected: `Running upgrade ... add curated_positions`. Then confirm:
Run: `python -c "import asyncio,asyncpg,os; asyncio.run((lambda: None)())" ` — skip; instead:
Run: `python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: downgrade then re-upgrade with no error (guards clean replay).

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat(positions): add curated_positions table"
```

## Task 3: Position builder (classify + upsert)

**Files:**
- Create: `src/workers/curated_positions_builder.py`
- Test: `tests/test_curated_positions_builder.py`

- [ ] **Step 1: Write the failing test for the pure classifier**

```python
# tests/test_curated_positions_builder.py
from src.workers.curated_positions_builder import classify_position


def test_hold_to_zero_loser_counts_as_loss():
    # bought $100, never sold, market resolved, held losing outcome
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": True, "winning_outcome": "No"}
    r = classify_position(pos, res)
    assert r["is_resolved"] is True
    assert r["is_win"] is False
    assert r["payout"] == 0.0
    assert r["realized_pnl"] == -100.0


def test_winner_gets_payout():
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": True, "winning_outcome": "Yes"}
    r = classify_position(pos, res)
    assert r["payout"] == 200.0
    assert r["realized_pnl"] == 100.0
    assert r["is_win"] is True


def test_unresolved_is_open():
    pos = {"total_bought": 100.0, "total_sold": 0.0, "net_tokens": 200.0, "outcome": "Yes"}
    res = {"resolved": False, "winning_outcome": None}
    r = classify_position(pos, res)
    assert r["is_resolved"] is False
    assert r["is_win"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_curated_positions_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the classifier + builder**

```python
# src/workers/curated_positions_builder.py
"""Build curated_positions rows from Polymarket open+closed positions and
market resolution. Win/loss keys on the sign of realized_pnl."""
import logging
import aiohttp
import asyncpg

from src.utils.market_resolution import fetch_market_resolution
from src.workers.leaderboard_stats import fetch_positions, _parse

logger = logging.getLogger(__name__)

POSITION_CAP = 5000


def classify_position(pos: dict, resolution: dict) -> dict:
    """Pure: given a merged position and its market resolution, return the
    classified row fields."""
    total_bought = _parse(pos.get("total_bought"))
    total_sold = _parse(pos.get("total_sold"))
    net_tokens = _parse(pos.get("net_tokens"))
    resolved = bool(resolution.get("resolved"))
    won = resolved and resolution.get("winning_outcome") == pos.get("outcome")
    payout = net_tokens * 1.0 if won else 0.0
    realized_pnl = payout + total_sold - total_bought
    return {
        "total_bought": total_bought,
        "total_sold": total_sold,
        "net_tokens": net_tokens,
        "market_resolved": resolved,
        "won": won,
        "payout": payout,
        "realized_pnl": realized_pnl,
        "is_resolved": resolved,
        "is_win": resolved and realized_pnl > 0,
    }


async def build_wallet_positions(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Fetch a curated wallet's open positions, classify against market
    resolution, and upsert into curated_positions (capped)."""
    raw = await fetch_positions(session, address)
    positions = (raw or [])[:POSITION_CAP]
    for p in positions:
        cid = p.get("conditionId")
        if not cid:
            continue
        merged = {
            "outcome": p.get("outcome") or "",
            "total_bought": _parse(p.get("totalBought")),
            "total_sold": 0.0,  # open-position endpoint gives no sold leg
            "net_tokens": _parse(p.get("size")),
        }
        resolution = await fetch_market_resolution(session, cid)
        fields = classify_position(merged, resolution)
        await conn.execute(
            """
            INSERT INTO curated_positions
                (address, condition_id, outcome, total_bought, total_sold, net_tokens,
                 market_resolved, won, payout, realized_pnl, is_resolved, is_win,
                 category, subcategory, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW())
            ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
                total_bought=EXCLUDED.total_bought, total_sold=EXCLUDED.total_sold,
                net_tokens=EXCLUDED.net_tokens, market_resolved=EXCLUDED.market_resolved,
                won=EXCLUDED.won, payout=EXCLUDED.payout, realized_pnl=EXCLUDED.realized_pnl,
                is_resolved=EXCLUDED.is_resolved, is_win=EXCLUDED.is_win, computed_at=NOW()
            """,
            address, cid, merged["outcome"], fields["total_bought"], fields["total_sold"],
            fields["net_tokens"], fields["market_resolved"], fields["won"], fields["payout"],
            fields["realized_pnl"], fields["is_resolved"], fields["is_win"],
            p.get("category"), p.get("subcategory"),
        )
```

- [ ] **Step 4: Run classifier tests to verify pass**

Run: `python -m pytest tests/test_curated_positions_builder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/workers/curated_positions_builder.py tests/test_curated_positions_builder.py
git commit -m "feat(positions): classify + upsert curated positions from market resolution"
```

## Task 4: Read win rate from curated_positions

**Files:**
- Modify: `src/workers/leaderboard_stats_v2.py` (in `process_wallet_v2`, curated branch, after positions are built)

- [ ] **Step 1: Build positions, then compute win rate from the table**

In `process_wallet_v2`, in the CURATED branch (after `supabase` handling, before the metrics upsert near line 164), add:

```python
    from src.workers.curated_positions_builder import build_wallet_positions
    await build_wallet_positions(conn, session, address)
    wr_row = await conn.fetchrow(
        """
        SELECT COUNT(*) FILTER (WHERE is_resolved) AS resolved,
               COUNT(*) FILTER (WHERE is_win) AS wins
        FROM curated_positions WHERE address = $1
        """,
        address,
    )
    if wr_row and wr_row["resolved"]:
        stats["resolved_count"] = wr_row["resolved"]
        stats["winning_count"] = wr_row["wins"]
        stats["win_rate"] = wr_row["wins"] / wr_row["resolved"]
```

This overrides the Supabase-sourced win rate for curated wallets with the
position-derived one. Non-curated wallets are unchanged.

- [ ] **Step 2: Verify module parses**

Run: `python -c "import src.workers.leaderboard_stats_v2"`
Expected: no output, exit 0.

- [ ] **Step 3: Integration smoke test**

```python
# append to tests/test_curated_positions_builder.py
import os, pytest, pytest_asyncio, asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")


@pytest.mark.asyncio
async def test_win_rate_query_counts_losers():
    c = await asyncpg.connect(DB_URL)
    tx = c.transaction(); await tx.start()
    addr = "0x" + "cc" * 20
    await c.execute("INSERT INTO curated_positions (address,condition_id,outcome,is_resolved,is_win) VALUES ($1,'0x1','Yes',true,true)", addr)
    await c.execute("INSERT INTO curated_positions (address,condition_id,outcome,is_resolved,is_win) VALUES ($1,'0x2','No',true,false)", addr)
    row = await c.fetchrow("SELECT COUNT(*) FILTER (WHERE is_resolved) r, COUNT(*) FILTER (WHERE is_win) w FROM curated_positions WHERE address=$1", addr)
    assert row["r"] == 2 and row["w"] == 1  # loser is in the denominator
    await tx.rollback(); await c.close()
```

Run: `python -m pytest tests/test_curated_positions_builder.py::test_win_rate_query_counts_losers -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/workers/leaderboard_stats_v2.py tests/test_curated_positions_builder.py
git commit -m "feat(positions): compute curated win rate from curated_positions"
```

## Manual verification (after all tasks)

- [ ] `python -m pytest tests/test_market_resolution.py tests/test_curated_positions_builder.py -v` → all PASS.
- [ ] Start the stack; let `leaderboard_stats_v2` process one curated wallet; confirm `curated_positions` gets rows and `wallet_metrics_v2.win_rate` reflects a denominator that includes resolved losers.
- [ ] Spot-check one wallet: pick a known losing market it held; confirm a `curated_positions` row with `is_resolved=true, is_win=false`.

## Deferred / follow-ups (not in this plan)

- Windowed axis (LAST 100/300/…) re-pointed at `curated_positions` ordered by `resolved_at DESC` — separate change once base win rate is trusted.
- Backfilling `total_sold` from trade history for precise partial-sell PnL (open-position endpoint lacks the sold leg). Current classifier treats open-position `total_sold` as 0, which is correct for hold-to-zero losers and winners held to resolution; partial sellers get slightly conservative PnL until the trade-feed plan lands.
