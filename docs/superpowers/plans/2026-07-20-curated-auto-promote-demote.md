# Curated Auto-Promote / Demote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically promote qualifying active wallets into the CURATED tier and demote curated wallets that fall below threshold, replacing the leaderboard-top-100-only engine.

**Architecture:** Two SQL sweeps added to the existing `stats_refresher.py` worker loop (runs every 10 min). Promote scans active STANDARD wallets; demote reverts non-`custom` curated wallets whose stats dropped. Both read `wallet_metrics_v2` (already populated). The old `check_and_promote_curated` in `poly_leaderboard_sync.py` is retired so that worker becomes discovery-only.

**Tech Stack:** Python 3, asyncpg, PostgreSQL, pytest + pytest-asyncio (integration tests against local `poly_db`).

---

## Decisions locked (from spec 2026-07-20)

- **Promote rule:** `is_dormant = FALSE` AND `tier = 'STANDARD'` AND `resolved_count >= CURATED_MIN_RESOLVED` AND (`roi_pct > CURATED_MIN_ROI` OR `total_pnl > CURATED_MIN_PNL`). Restricting to `STANDARD` automatically excludes NEW, LOW_BALANCE, DEAD, CURATED, UNCLASSIFIED.
- **Demote rule:** `tier = 'CURATED'` AND no `wallet_sources_v2` row with `source='custom'` AND the wallet FAILS the stats test (`resolved_count < MIN` OR (`roi_pct <= MIN_ROI` AND `total_pnl <= MIN_PNL`)). **Dormancy does NOT demote.** Target tier = canonical CASE (DEAD/LOW_BALANCE/NEW/STANDARD).
- **Sticky:** `source='custom'` wallets never demote.
- **Thresholds:** `CURATED_MIN_ROI = 30`, `CURATED_MIN_PNL = 10000`, `CURATED_MIN_RESOLVED = 10`.

## File structure

- Modify: `src/workers/stats_refresher.py` — add threshold constants + `sweep_curated_tiers(conn)`; call it from `refresh_tracked_wallets`.
- Modify: `src/workers/poly_leaderboard_sync.py` — remove `check_and_promote_curated` and its call site (discovery-only).
- Modify: `frontend/src/app/wallets/curated/page.tsx` — fix stale criteria copy.
- Create: `tests/test_curated_auto_promote.py` — integration tests for the sweep.

## Task 1: Threshold constants + sweep function

**Files:**
- Modify: `src/workers/stats_refresher.py` (add constants near line 20; add `sweep_curated_tiers` before `refresh_tracked_wallets`)
- Test: `tests/test_curated_auto_promote.py`

- [ ] **Step 1: Write the failing test (promote path)**

```python
# tests/test_curated_auto_promote.py
import os
import pytest
import pytest_asyncio
import asyncpg
from src.workers.stats_refresher import sweep_curated_tiers

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")


@pytest_asyncio.fixture
async def conn():
    c = await asyncpg.connect(DB_URL)
    # isolate: work inside a transaction we roll back
    tx = c.transaction()
    await tx.start()
    yield c
    await tx.rollback()
    await c.close()


async def _seed(conn, address, tier, roi, pnl, resolved, dormant, custom=False):
    await conn.execute(
        "INSERT INTO wallets_v2 (address, tier, is_dormant) VALUES ($1,$2,$3)",
        address, tier, dormant,
    )
    await conn.execute(
        "INSERT INTO wallet_metrics_v2 (address, roi_pct, total_pnl, resolved_count, computed_at) "
        "VALUES ($1,$2,$3,$4, NOW())",
        address, roi, pnl, resolved,
    )
    if custom:
        await conn.execute(
            "INSERT INTO wallet_sources_v2 (address, source, spotted_at) VALUES ($1,'custom',NOW())",
            address,
        )


@pytest.mark.asyncio
async def test_promotes_qualifying_standard_wallet(conn):
    addr = "0x" + "a1" * 20
    await _seed(conn, addr, "STANDARD", roi=45.0, pnl=500.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    tier = await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr)
    assert tier == "CURATED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curated_auto_promote.py::test_promotes_qualifying_standard_wallet -v`
Expected: FAIL with `ImportError: cannot import name 'sweep_curated_tiers'`

- [ ] **Step 3: Add constants**

In `src/workers/stats_refresher.py`, after the existing `POLL_INTERVAL = 600` line (~line 22), add:

```python
CURATED_MIN_ROI = 30.0
CURATED_MIN_PNL = 10_000.0
CURATED_MIN_RESOLVED = 10
```

- [ ] **Step 4: Implement `sweep_curated_tiers`**

Add this function just above `async def refresh_tracked_wallets(`:

```python
async def sweep_curated_tiers(conn: asyncpg.Connection):
    """Promote qualifying active STANDARD wallets to CURATED; demote curated
    wallets (except source='custom') that no longer qualify. Dormancy does NOT
    demote — the curated list query already filters is_dormant=FALSE."""
    # PROMOTE: active STANDARD wallets meeting the threshold rule.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = 'CURATED',
            tier_reason = 'auto: roi/pnl threshold',
            curated_at = NOW(),
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'STANDARD'
          AND w.is_dormant = FALSE
          AND COALESCE(m.resolved_count, 0) >= $3
          AND (COALESCE(m.roi_pct, 0) > $1 OR COALESCE(m.total_pnl, 0) > $2)
        """,
        CURATED_MIN_ROI, CURATED_MIN_PNL, CURATED_MIN_RESOLVED,
    )

    # DEMOTE: curated, non-custom wallets that fail the rule → canonical tier.
    await conn.execute(
        """
        UPDATE wallets_v2 w
        SET tier = CASE
                WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) <= 0 THEN
                    CASE WHEN w.last_trade_at IS NULL THEN 'DEAD' ELSE 'LOW_BALANCE' END
                WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
                WHEN w.last_trade_at IS NULL THEN 'NEW'
                ELSE 'STANDARD'
            END,
            tier_reason = 'auto: demoted below curated threshold',
            updated_at = NOW()
        FROM wallet_metrics_v2 m
        WHERE m.address = w.address
          AND w.tier = 'CURATED'
          AND NOT EXISTS (
              SELECT 1 FROM wallet_sources_v2 s
              WHERE s.address = w.address AND s.source = 'custom'
          )
          AND (
              COALESCE(m.resolved_count, 0) < $3
              OR (COALESCE(m.roi_pct, 0) <= $1 AND COALESCE(m.total_pnl, 0) <= $2)
          )
        """,
        CURATED_MIN_ROI, CURATED_MIN_PNL, CURATED_MIN_RESOLVED,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_curated_auto_promote.py::test_promotes_qualifying_standard_wallet -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_curated_auto_promote.py src/workers/stats_refresher.py
git commit -m "feat(curated): add sweep_curated_tiers promote/demote logic"
```

## Task 2: Boundary-case tests (demote, sticky, dormant, thresholds)

**Files:**
- Test: `tests/test_curated_auto_promote.py` (append)

- [ ] **Step 1: Add the boundary tests**

Append to `tests/test_curated_auto_promote.py`:

```python
@pytest.mark.asyncio
async def test_promotes_on_pnl_alone(conn):
    addr = "0x" + "a2" * 20
    await _seed(conn, addr, "STANDARD", roi=5.0, pnl=15_000.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"


@pytest.mark.asyncio
async def test_does_not_promote_below_min_resolved(conn):
    addr = "0x" + "a3" * 20
    await _seed(conn, addr, "STANDARD", roi=99.0, pnl=99_000.0, resolved=3, dormant=False)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_does_not_promote_dormant(conn):
    addr = "0x" + "a4" * 20
    await _seed(conn, addr, "STANDARD", roi=99.0, pnl=99_000.0, resolved=25, dormant=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_does_not_promote_new_or_low_balance(conn):
    for tier in ("NEW", "LOW_BALANCE"):
        addr = "0x" + ("b" + tier[0].lower()) * 20
        await _seed(conn, addr, tier, roi=99.0, pnl=99_000.0, resolved=25, dormant=False)
    await sweep_curated_tiers(conn)
    for tier in ("NEW", "LOW_BALANCE"):
        addr = "0x" + ("b" + tier[0].lower()) * 20
        assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == tier


@pytest.mark.asyncio
async def test_demotes_curated_that_dropped(conn):
    addr = "0x" + "a5" * 20
    # curated but stats now fail; has balance so canonical tier = STANDARD
    await _seed(conn, addr, "CURATED", roi=1.0, pnl=100.0, resolved=25, dormant=False)
    await conn.execute(
        "UPDATE wallet_metrics_v2 SET balance=5000, position_value=0 WHERE address=$1", addr)
    await conn.execute(
        "UPDATE wallets_v2 SET last_trade_at=NOW() WHERE address=$1", addr)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "STANDARD"


@pytest.mark.asyncio
async def test_custom_wallet_never_demoted(conn):
    addr = "0x" + "a6" * 20
    await _seed(conn, addr, "CURATED", roi=1.0, pnl=100.0, resolved=1, dormant=False, custom=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"


@pytest.mark.asyncio
async def test_dormancy_alone_does_not_demote(conn):
    addr = "0x" + "a7" * 20
    # still qualifies on stats, but dormant → stays CURATED (list query hides it)
    await _seed(conn, addr, "CURATED", roi=45.0, pnl=500.0, resolved=25, dormant=True)
    await sweep_curated_tiers(conn)
    assert await conn.fetchval("SELECT tier FROM wallets_v2 WHERE address=$1", addr) == "CURATED"
```

- [ ] **Step 2: Run the full test file**

Run: `python -m pytest tests/test_curated_auto_promote.py -v`
Expected: all PASS. If `test_demotes_curated_that_dropped` fails, check the demote CASE uses `balance + position_value` from `wallet_metrics_v2`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_curated_auto_promote.py
git commit -m "test(curated): cover demote, sticky-custom, dormant, threshold edges"
```

## Task 3: Wire the sweep into the worker loop

**Files:**
- Modify: `src/workers/stats_refresher.py` (inside `refresh_tracked_wallets`, after the existing tier reclassify block ~line 77)

- [ ] **Step 1: Add the call**

In `refresh_tracked_wallets`, immediately after the big reclassify `UPDATE ... sub` statement (the one ending near line 77) and before the "Fetch active wallets to refresh" comment, add:

```python
    # Promote/demote the curated tier on fresh metrics (spec 2026-07-20).
    await sweep_curated_tiers(conn)
```

- [ ] **Step 2: Verify the module imports and parses**

Run: `python -c "import src.workers.stats_refresher"`
Expected: no output, exit 0.

- [ ] **Step 3: Confirm existing tier guard test still passes**

Run: `python -m pytest tests/test_stats_refresher_tiers.py -v`
Expected: all PASS (the file's `'CURATED', 'UNCLASSIFIED'` guard is untouched).

- [ ] **Step 4: Commit**

```bash
git add src/workers/stats_refresher.py
git commit -m "feat(curated): run tier sweep each stats_refresher cycle"
```

## Task 4: Retire leaderboard-only promotion (discovery-only worker)

**Files:**
- Modify: `src/workers/poly_leaderboard_sync.py` (delete `check_and_promote_curated` ~lines 181-253; delete its call + step-5 block ~lines 301-306; update docstring)

- [ ] **Step 1: Remove the call site**

In `run_weekly_sync`, delete the block:

```python
            # 5. Check curated conditions for category top-100
            total_promoted = 0
            for cat, entries in category_entries.items():
                promoted = await check_and_promote_curated(conn, entries, cat)
                total_promoted += promoted
            logger.info(f"Promoted {total_promoted} wallets to curated")
```

- [ ] **Step 2: Remove the function**

Delete the entire `async def check_and_promote_curated(...)` function (from its `async def` line through its `return promoted`).

- [ ] **Step 3: Update the docstring**

Change the module docstring's numbered list so it ends at step 5 and states promotion moved out:

```python
"""
Polymarket Leaderboard Sync Worker

Discovery only. Weekly sync that:
1. Fetches top 5000 wallets from Polymarket ALL leaderboard
2. Fetches top 2000 from SPORTS leaderboard
3. Fetches top 500 from each category leaderboard
4. Adds new wallets to wallets_v2 (source='leaderboard')
5. Stores per-category PnL/volume stats

Curated promotion/demotion is handled by stats_refresher.py
(see docs/CORE_LOGIC.md section 1). This worker no longer promotes.

Runs once per week on Monday at 2 PM UTC.
"""
```

- [ ] **Step 4: Verify no dangling references**

Run: `grep -rn "check_and_promote_curated" src/`
Expected: no matches.

- [ ] **Step 5: Verify module parses**

Run: `python -c "import src.workers.poly_leaderboard_sync"`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/workers/poly_leaderboard_sync.py
git commit -m "refactor(sync): remove leaderboard-only curated promotion (moved to stats_refresher)"
```

## Task 5: Fix stale curated-page criteria copy

**Files:**
- Modify: `frontend/src/app/wallets/curated/page.tsx:256`

- [ ] **Step 1: Update the string**

Replace the subtitle text (currently at line 256):

```tsx
              : "ROI > 30% OR Win Rate > 70% OR PnL > $10k - active in last 30 days"
```

with:

```tsx
              : "ROI > 30% OR PnL > $10k - active in last 30 days"
```

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors from `page.tsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/wallets/curated/page.tsx
git commit -m "fix(curated-ui): drop win-rate from criteria copy"
```

## Manual verification (after all tasks)

- [ ] Run full suite: `python -m pytest tests/test_curated_auto_promote.py tests/test_stats_refresher_tiers.py -v` → all PASS.
- [ ] Start the stack (`.venv`, `python -m src.orchestrator` + uvicorn) and confirm `stats_refresher` logs a cycle without error.
- [ ] Hit `GET /api/v2/leaderboard/curated-wallets` and confirm it returns wallets (count may grow after the first sweep on real data).

