# Wallet Tiers + Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the v1→v2 wallet-schema migration so every wallet has a correct `tier` (NEW / LOW_BALANCE / STANDARD / CURATED / DEAD) + `is_dormant` flag + sources (trade / deposit / leaderboard / manual), then rebuild the wallet UI as a single `/wallets` page with 5 tabs (All | Standard | Low Balance | New | Hibernated) plus the existing Curated page — replacing the Global List, Might Cook, and Hibernating pages.

**Architecture:** Backend: point the two remaining v1 workers (`wallet_trade_history.py`, `poly_leaderboard_sync.py`) at `wallets_v2`/`wallet_sources_v2`, make curation write `tier='CURATED'`, make `is_dormant` the single activity flag, backfill v1 data into v2. API: one new `GET /api/v2/leaderboard/wallets?tab=` endpoint + counts. Frontend: one shared column-config-driven `WalletTable` + `useWalletList` hook driving the new tabbed page; retire 3 pages.

**Tech Stack:** FastAPI + asyncpg + Alembic (raw SQL), Next.js App Router + Tailwind, pytest.

---

## Context (from exploration, 2026-07-16)

- **v2 schema already exists** (head migration `alembic/versions/591013c5e504_ideal_v2_schema.py`, created 2026-07-15): `wallets_v2` (tier, tier_reason, might_cook_type, is_dormant, last_trade_at), `wallet_sources_v2` (PK `(address, source)`), `wallet_metrics_v2`, `category_stats_v2`, etc.
- **Split-brain:** `trade_tracker`, `deposit_tracker`, `stats_refresher`, `leaderboard_stats` write v2; `wallet_trade_history` and `poly_leaderboard_sync` still write v1 `tracked_wallets`/`wallet_stats`. So leaderboard- and queue-promoted wallets never reach v2, and `wallet_sources_v2` never gets `'leaderboard'`/`'manual'` rows.
- **Curation gap:** promotion writes legacy `is_curated` boolean (`leaderboard_stats.py:1336-1357`, `poly_leaderboard_sync.py:219-225`), but v2 endpoints filter `tier = 'CURATED'` (`leaderboard_v2.py:203`) → curated list is invisible/stale in v2.
- **Known bugs:** `ON CONFLICT (address)` against `wallet_sources_v2` whose PK is `(address, source)` (`trade_tracker.py:101`, `deposit_tracker.py:167`); `leaderboard_stats.py` writes `wallets_v2` columns not in the v2 migration (`status`, `next_check_at`, `is_zero_balance`, `is_curated`, `curated_at`, `last_checked_for_curated`, `pnl_source`, `website_pnl*`); v2 `/global-wallets` drops `include_dormant`/`filter_category` params; `deposit_tracker` tier_reason strings say "$10k" but threshold is $5k.
- **Frontend:** zero shared code between the 4 wallet-list pages (`formatAddress` ×7, `SOURCE_LABELS` ×3, identical `renderCell`/pagination forks). Hibernating page has dead sort/search/source UI. Unused `getGlobalWalletList` in `api.ts:179`. Sidebar: Activity, Might Cook, Global List, Curated, My Tracker.
- **User decisions (2026-07-16):** one `/wallets` page with 5 tabs; retire Might Cook (its signal becomes a badge on the New tab); finish the v2 migration rather than build on stale data.

## Canonical wallet model (the target state machine)

- `tier` (mutually exclusive): `DEAD` (balance+position ≤ 0) → `LOW_BALANCE` (0 < bal+pos < $1k) → `NEW` (bal+pos ≥ $1k, never traded) → `STANDARD` (bal+pos ≥ $1k, has traded) → `CURATED` (meets curation criteria; never auto-demoted by the balance state machine).
- `is_dormant` (orthogonal): `last_trade_at < NOW() - 30 days` → hibernated. Never traded (`last_trade_at IS NULL`) is NOT dormant — it's `NEW`.
- `might_cook_type` stays as a badge column (deposit ≥ $5k with 0 trades); `tier='MIGHT_COOK'` is retired as a tier value.
- `wallet_sources_v2.source` ∈ `trade | deposit | leaderboard | manual` (multi-row per wallet).
- Tab mapping: **All** = `tier != 'DEAD'`; **Standard** = `tier='STANDARD' AND NOT is_dormant`; **Low Balance** = `tier='LOW_BALANCE' AND NOT is_dormant`; **New** = `tier='NEW' AND NOT is_dormant`; **Hibernated** = `is_dormant AND tier != 'DEAD'`.

---

# Phase 1 — Database reconciliation

### Task 1: Migration — reconcile `wallets_v2` drift columns + retire MIGHT_COOK tier

`leaderboard_stats.py` writes operational columns that the ideal-v2 migration never created. Add them properly instead of relying on drift.

**Files:**
- Create: `alembic/versions/<autogen>_reconcile_wallets_v2_operational_columns.py`

- [ ] **Step 1: Check live DB state first** (drift may mean some columns already exist):

Run: `python get_schema.py` (prints information_schema for key tables). Note which of `status, next_check_at, is_zero_balance, is_curated, curated_at, last_checked_for_curated, pnl_source` already exist on `wallets_v2`.

- [ ] **Step 2: Create migration** `alembic revision -m "reconcile wallets_v2 operational columns"` with:

```python
def upgrade() -> None:
    op.execute("""
        ALTER TABLE wallets_v2
          ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS last_checked_for_curated TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS pnl_source VARCHAR(16)
    """)
    # Retire MIGHT_COOK as a tier: it's a badge, not a tier.
    op.execute("""
        UPDATE wallets_v2
           SET might_cook_type = COALESCE(might_cook_type, 'deposit_no_trades'),
               tier = 'NEW',
               tier_reason = 'might-cook reclassified: deposit >= $5k, 0 trades'
         WHERE tier = 'MIGHT_COOK'
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_wallets_v2_tier_dormant ON wallets_v2 (tier, is_dormant)")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wallets_v2_tier_dormant")
    op.execute("""
        ALTER TABLE wallets_v2
          DROP COLUMN IF EXISTS next_check_at,
          DROP COLUMN IF EXISTS curated_at,
          DROP COLUMN IF EXISTS last_checked_for_curated,
          DROP COLUMN IF EXISTS pnl_source
    """)
```

Deliberately NOT adding `status` / `is_zero_balance` / `is_curated` — those v1 concepts are replaced by `is_dormant` and `tier` (Tasks 5–6 remove the writes).

- [ ] **Step 3:** `alembic upgrade head` — verify with `python get_schema.py` that columns exist and `SELECT count(*) FROM wallets_v2 WHERE tier='MIGHT_COOK'` returns 0.

- [ ] **Step 4: Commit** — `git add alembic/versions/... && git commit -m "feat(db): reconcile wallets_v2 operational columns, retire MIGHT_COOK tier"`

### Task 2: Backfill v1 `tracked_wallets` → v2

Leaderboard/queue-promoted wallets exist only in v1. Without this the New Wallets tabs are missing thousands of rows.

**Files:**
- Create: `scripts/backfill_v1_to_v2.py` (dry-run by default, `--apply` to commit — same pattern as `scripts/backfill_last_trade_at.py`)

- [ ] **Step 1: Write the script.** Core SQL (one transaction when `--apply`):

```sql
-- 1) wallets_v2 rows for v1-only wallets
INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
SELECT tw.address, tw.username,
  CASE
    WHEN COALESCE(tw.is_curated, FALSE) THEN 'CURATED'
    WHEN COALESCE(tw.balance,0) + COALESCE(tw.position_value,0) <= 0 THEN 'DEAD'
    WHEN COALESCE(tw.balance,0) + COALESCE(tw.position_value,0) < 1000 THEN 'LOW_BALANCE'
    WHEN tw.last_trade_at IS NULL THEN 'NEW'
    ELSE 'STANDARD'
  END,
  'backfill from tracked_wallets',
  COALESCE(tw.is_dormant, FALSE) OR (tw.last_trade_at IS NOT NULL AND tw.last_trade_at < NOW() - INTERVAL '30 days'),
  tw.last_trade_at, COALESCE(tw.added_at, NOW()), NOW()
FROM tracked_wallets tw
ON CONFLICT (address) DO NOTHING;   -- never clobber wallets already living in v2

-- 2) sources from v1 source_type (+ discovery_source fallback)
INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
SELECT tw.address, tw.source_type, LEFT(tw.added_reason, 255), COALESCE(tw.added_at, NOW())
FROM tracked_wallets tw
WHERE tw.source_type IN ('trade','deposit','leaderboard','manual')
ON CONFLICT (address, source) DO NOTHING;

-- 3) metrics for wallets that have none yet
INSERT INTO wallet_metrics_v2 (address, total_pnl, total_volume, roi_pct, win_rate, resolved_count,
                               winning_count, balance, deposits, withdrawals, position_value,
                               pm_pnl, pm_volume, pm_rank, computed_at)
SELECT tw.address, tw.total_pnl, tw.total_volume, ws.roi_pct, ws.win_rate, ws.resolved_count,
       ws.winning_count, tw.balance, tw.deposits, tw.withdrawals, tw.position_value,
       tw.website_pnl, tw.website_volume, tw.website_rank, NOW()
FROM tracked_wallets tw
LEFT JOIN wallet_stats ws ON ws.address = tw.address
ON CONFLICT (address) DO NOTHING;

-- 4) curation flag for wallets already in v2 but curated only in v1
UPDATE wallets_v2 w SET tier = 'CURATED', curated_at = COALESCE(tw.curated_at, NOW())
FROM tracked_wallets tw
WHERE tw.address = w.address AND COALESCE(tw.is_curated, FALSE) AND w.tier NOT IN ('CURATED','DEAD');
```

Dry-run mode prints the row counts each statement WOULD affect (wrap in `SELECT count(*)` versions).

- [ ] **Step 2:** Run dry-run: `python scripts/backfill_v1_to_v2.py` — sanity-check counts against `SELECT count(*) FROM tracked_wallets` vs `wallets_v2`.
- [ ] **Step 3:** Run `python scripts/backfill_v1_to_v2.py --apply`. Verify: `SELECT tier, count(*) FROM wallets_v2 GROUP BY tier` shows plausible distribution; `SELECT source, count(*) FROM wallet_sources_v2 GROUP BY source` now includes `leaderboard`.
- [ ] **Step 4: Commit** the script.

---

# Phase 2 — Workers write v2 only

### Task 3: Fix `wallet_sources_v2` ON CONFLICT bug (trade + deposit trackers)

**Files:**
- Modify: `src/workers/trade_tracker.py:98-102`, `src/workers/deposit_tracker.py:158-168`
- Test: `tests/test_wallet_sources_conflict.py`

- [ ] **Step 1: Failing test** — assert the INSERT statements in both workers target the composite key:

```python
import re
from pathlib import Path

def _source_inserts(text: str) -> list[str]:
    return [m for m in re.findall(r"INSERT INTO wallet_sources_v2.*?(?:\)|;)", text, re.S)]

def test_trade_tracker_conflict_targets_composite_pk():
    text = Path("src/workers/trade_tracker.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (address, source)" in text
    assert "ON CONFLICT (address)\n" not in text.replace("ON CONFLICT (address, source)", "")

def test_deposit_tracker_conflict_targets_composite_pk():
    text = Path("src/workers/deposit_tracker.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (address, source)" in text
```

(Repo already uses this source-assertion test style in `tests/test_task2_bug_condition_category.py`.)

- [ ] **Step 2:** Run `pytest tests/test_wallet_sources_conflict.py -v` → FAIL.
- [ ] **Step 3:** In both workers change `ON CONFLICT (address) DO NOTHING` → `ON CONFLICT (address, source) DO NOTHING` on the `wallet_sources_v2` inserts. Also fix the stale `tier_reason` strings in `deposit_tracker.py` (`'deposit >= $10k'` → `'deposit >= $5k'`) and its docstring thresholds.
- [ ] **Step 4:** `pytest tests/test_wallet_sources_conflict.py -v` → PASS. **Commit.**

### Task 4: Point `wallet_trade_history.py` at v2

The queue processor still writes v1 `tracked_wallets`. Rewrite its four insert paths to v2 while keeping the vetting gates.

**Files:**
- Modify: `src/workers/wallet_trade_history.py` (insert blocks around lines 292-414)
- Test: `tests/test_wallet_trade_history_v2.py`

- [ ] **Step 1:** Map queue `source` strings to canonical sources at the top of the module:

```python
def canonical_source(queue_source: str) -> str:
    s = (queue_source or "").lower()
    if "deposit" in s:
        return "deposit"
    if "trade" in s or "whale" in s:
        return "trade"
    if "leaderboard" in s:
        return "leaderboard"
    return "manual"
```

- [ ] **Step 2:** Replace each v1 write with the v2 equivalent. Same helper for all four gates:

```python
async def upsert_wallet_v2(conn, address, *, tier, tier_reason, is_dormant, last_trade_at, source, source_detail):
    await conn.execute(
        """
        INSERT INTO wallets_v2 (address, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
        ON CONFLICT (address) DO UPDATE SET
            tier = CASE WHEN wallets_v2.tier IN ('CURATED','DEAD') THEN wallets_v2.tier ELSE EXCLUDED.tier END,
            tier_reason = EXCLUDED.tier_reason,
            is_dormant = EXCLUDED.is_dormant,
            last_trade_at = COALESCE(GREATEST(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), wallets_v2.last_trade_at, EXCLUDED.last_trade_at),
            updated_at = NOW()
        """,
        address, tier, tier_reason, is_dormant, last_trade_at,
    )
    await conn.execute(
        """
        INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
        VALUES ($1, $2, $3, NOW()) ON CONFLICT (address, source) DO NOTHING
        """,
        address, source, source_detail,
    )
```

Gate mapping (replaces the v1 blocks):
- balance ≤ 0 → `tier='DEAD'`, `is_dormant=False`, reason `'zero balance at vetting'` (was `is_zero_balance=TRUE` insert, lines 292-307)
- 0 < balance < $1k → `tier='LOW_BALANCE'` (was: skipped entirely, lines 312-316 — **behavior change on purpose**: Low Balance is now a first-class tab so these wallets must be stored)
- balance ≥ $1k, no trades → `tier='NEW'`, `last_trade_at=None` (was plain insert, 327-349)
- balance ≥ $1k, last trade > 30d → `tier='STANDARD'`, `is_dormant=True` (was `status='HIBERNATING'`, 356-374)
- balance ≥ $1k, recent trade → `tier='STANDARD'`, `is_dormant=False`; seed `wallet_metrics_v2` row instead of `wallet_stats` (INSERT ... ON CONFLICT (address) DO NOTHING)

- [ ] **Step 3:** Test: source-level assertions that the module no longer references `tracked_wallets`/`wallet_stats` and covers all five gates:

```python
from pathlib import Path

def test_wallet_trade_history_writes_v2_only():
    text = Path("src/workers/wallet_trade_history.py").read_text(encoding="utf-8")
    assert "INSERT INTO tracked_wallets" not in text
    assert "INSERT INTO wallet_stats" not in text
    assert "wallets_v2" in text and "wallet_sources_v2" in text
    for tier in ("'DEAD'", "'LOW_BALANCE'", "'NEW'", "'STANDARD'"):
        assert tier in text
```

- [ ] **Step 4:** `pytest tests/test_wallet_trade_history_v2.py -v` → PASS; run one queue wallet end-to-end: `python scripts/test_process_wallet.py <address>` (existing harness) and confirm a `wallets_v2` row appears. **Commit.**

### Task 5: Point `poly_leaderboard_sync.py` at v2

**Files:**
- Modify: `src/workers/poly_leaderboard_sync.py` (insert block 107-115, curated block 197-225)
- Test: `tests/test_poly_leaderboard_sync_v2.py` (same source-assertion style as Task 4)

- [ ] **Step 1:** New-wallet insert (was v1 lines 107-115) → v2:

```python
await conn.execute(
    """
    INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
    VALUES ($1, $2, 'NEW', 'Polymarket leaderboard sync', FALSE, NULL, NOW(), NOW())
    ON CONFLICT (address) DO UPDATE SET username = COALESCE(EXCLUDED.username, wallets_v2.username), updated_at = NOW()
    """,
    address, username,
)
await conn.execute(
    """
    INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
    VALUES ($1, 'leaderboard', $2, NOW()) ON CONFLICT (address, source) DO NOTHING
    """,
    address, f"Polymarket leaderboard ({board_label})",
)
```

**Critical regression guard:** keep `last_trade_at = NULL` on insert — the 2026-07-12 corruption fix (`docs/plan/last_trade_at_fix_and_pnl_cleanup_plan.md` §2 bug 6) exists precisely because this worker used to stamp `NOW()`.

Also write the PM headline numbers to `wallet_metrics_v2 (pm_pnl, pm_volume, pm_rank, pm_synced_at)` via upsert instead of v1 columns.

- [ ] **Step 2:** Curated promotion (was `is_curated=TRUE` on v1, lines 219-225) → `UPDATE wallets_v2 SET tier='CURATED', curated_at=NOW(), tier_reason=$2 WHERE address=$1 AND tier != 'DEAD'`. Keep the existing qualification thresholds unchanged.
- [ ] **Step 3:** Category stats writes: keep `wallet_category_stats` upserts (windowed-stats pipeline on this branch reads them) — only the wallet identity/curation writes move to v2.
- [ ] **Step 4:** Test asserts no `INSERT INTO tracked_wallets`, presence of `'leaderboard'` source insert, presence of `tier='CURATED'`... run → PASS. **Commit.**

### Task 6: `leaderboard_stats.py` — v2-clean status handling + curated tier

**Files:**
- Modify: `src/workers/leaderboard_stats.py` (non-curated status writes ~966-1066; dormancy 1322-1334; curated promotion 1336-1357)
- Test: `tests/test_leaderboard_stats_v2_columns.py`

- [ ] **Step 1:** Replace every `status = 'HIBERNATING'` / `status = 'ACTIVE'` write on `wallets_v2` (lines ~981, 1002, 1055-1066, 1487) with `is_dormant = TRUE/FALSE`; replace `is_zero_balance = TRUE` writes (966-972) with `tier = 'DEAD'` when balance+position ≤ 0, `tier = 'LOW_BALANCE'` when 0 < bal+pos < 1000 (guard: `WHERE tier NOT IN ('CURATED','DEAD')` for the LOW_BALANCE write).
- [ ] **Step 2:** Curated promotion (1336-1357): replace `is_curated = TRUE, curated_at = ...` with `tier = 'CURATED', curated_at = NOW(), last_checked_for_curated = NOW()`. The read at line 878 (`tier = 'CURATED' as is_curated`) already works.
- [ ] **Step 3:** Keep `next_check_at` writes (column added in Task 1).
- [ ] **Step 4:** Test (source assertions): no `status =` writes targeting `wallets_v2`, no `is_zero_balance`, no `is_curated =` writes; `tier = 'CURATED'` present. Run → PASS.
- [ ] **Step 5:** Smoke: `python scripts/test_process_wallet.py <curated-address>` runs without `UndefinedColumnError`. **Commit.**

### Task 7: `stats_refresher.py` — complete the tier state machine

**Files:**
- Modify: `src/workers/stats_refresher.py:96-107`
- Test: `tests/test_stats_refresher_tiers.py`

- [ ] **Step 1:** Extend the existing two-way STANDARD/LOW_BALANCE flip to the full machine (never touches CURATED; DEAD requires zero balance):

```python
TIER_SQL = """
UPDATE wallets_v2 w SET tier = sub.new_tier, tier_reason = sub.reason, updated_at = NOW()
FROM (
    SELECT w2.address,
        CASE
            WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) <= 0 THEN 'DEAD'
            WHEN COALESCE(m.balance,0) + COALESCE(m.position_value,0) < 1000 THEN 'LOW_BALANCE'
            WHEN w2.last_trade_at IS NULL THEN 'NEW'
            ELSE 'STANDARD'
        END AS new_tier,
        'stats_refresher reclassify' AS reason
    FROM wallets_v2 w2
    JOIN wallet_metrics_v2 m ON m.address = w2.address
    WHERE w2.tier NOT IN ('CURATED')
) sub
WHERE sub.address = w.address AND sub.new_tier != w.tier
"""
```

Keep the existing auto-hibernate query (`is_dormant = TRUE WHERE last_trade_at < NOW() - 30 days`, lines 40-44) and add the reverse: `is_dormant = FALSE WHERE is_dormant AND last_trade_at >= NOW() - INTERVAL '30 days'` (trade_tracker already un-dormants on new trades; this catches stats-refresh discoveries).

- [ ] **Step 2:** Test: source assertions that all four CASE branches exist and `'CURATED'` is excluded. Run → PASS. **Commit.**

---

# Phase 3 — API

### Task 8: New `GET /api/v2/leaderboard/wallets` (tabbed) + `/wallets/counts`

**Files:**
- Modify: `src/api/routers/leaderboard_v2.py`
- Test: `tests/test_leaderboard_v2_wallets_endpoint.py`

- [ ] **Step 1:** Add the endpoint. Tab → WHERE mapping is the canonical model:

```python
TAB_FILTERS = {
    "all":         "w.tier != 'DEAD'",
    "standard":    "w.tier = 'STANDARD' AND w.is_dormant = FALSE",
    "low_balance": "w.tier = 'LOW_BALANCE' AND w.is_dormant = FALSE",
    "new":         "w.tier = 'NEW' AND w.is_dormant = FALSE",
    "hibernated":  "w.is_dormant = TRUE AND w.tier != 'DEAD'",
}
SORT_COLUMNS = {
    "pnl": "COALESCE(m.pm_pnl, m.total_pnl)", "volume": "COALESCE(m.pm_volume, m.total_volume)",
    "roi": "m.roi_pct", "balance": "m.balance", "position_value": "m.position_value",
    "last_trade_at": "w.last_trade_at", "added_at": "w.added_at",
}

@router.get("/wallets")
async def wallet_list(
    tab: str = Query("all"),
    source: str | None = Query(None),          # trade|deposit|leaderboard|manual
    search: str | None = Query(None),
    sort_by: str = Query("pnl"),
    sort_order: str = Query("desc"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    if tab not in TAB_FILTERS:
        raise HTTPException(400, f"invalid tab: {tab}")
    order = SORT_COLUMNS.get(sort_by, SORT_COLUMNS["pnl"])
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    where = [TAB_FILTERS[tab]]
    params: list = []
    if source in ("trade", "deposit", "leaderboard", "manual"):
        params.append(source)
        where.append(f"EXISTS (SELECT 1 FROM wallet_sources_v2 s WHERE s.address = w.address AND s.source = ${len(params)})")
    if search:
        params.append(f"%{search}%")
        where.append(f"(w.address ILIKE ${len(params)} OR w.username ILIKE ${len(params)})")
    params.extend([limit, offset])
    sql = f"""
        SELECT w.address, w.username, w.tier, w.is_dormant, w.might_cook_type,
               w.last_trade_at, w.added_at,
               COALESCE(m.pm_pnl, m.total_pnl) AS pnl,
               COALESCE(m.pm_volume, m.total_volume) AS volume,
               m.roi_pct, m.win_rate, m.balance, m.position_value,
               (SELECT array_agg(s.source ORDER BY s.spotted_at) FROM wallet_sources_v2 s WHERE s.address = w.address) AS sources,
               COUNT(*) OVER() AS total_count
        FROM wallets_v2 w
        LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
        WHERE {' AND '.join(where)}
        ORDER BY {order} {direction} NULLS LAST
        LIMIT ${len(params)-1} OFFSET ${len(params)}
    """
    # execute with pool, return {"wallets": rows, "total": rows[0]["total_count"] if rows else 0}
```

- [ ] **Step 2:** Counts endpoint for tab badges (one grouped query, 60s cache like v1):

```python
@router.get("/wallets/counts")
async def wallet_counts():
    row = await conn.fetchrow("""
        SELECT
          COUNT(*) FILTER (WHERE tier != 'DEAD') AS all_count,
          COUNT(*) FILTER (WHERE tier = 'STANDARD' AND is_dormant = FALSE) AS standard,
          COUNT(*) FILTER (WHERE tier = 'LOW_BALANCE' AND is_dormant = FALSE) AS low_balance,
          COUNT(*) FILTER (WHERE tier = 'NEW' AND is_dormant = FALSE) AS new,
          COUNT(*) FILTER (WHERE is_dormant = TRUE AND tier != 'DEAD') AS hibernated
        FROM wallets_v2
    """)
```

- [ ] **Step 3:** Tests — use FastAPI TestClient/httpx pattern from existing API tests if present, else source assertions on the SQL (tab filter strings, `EXISTS (SELECT 1 FROM wallet_sources_v2`, no f-string interpolation of user input into SQL other than the whitelisted maps). Run → PASS.
- [ ] **Step 4:** Manual: `uvicorn src.api.main:app` then `curl "localhost:8000/api/v2/leaderboard/wallets?tab=standard&source=leaderboard&limit=5"` returns rows. **Commit.**

### Task 9: v2 router hygiene

**Files:**
- Modify: `src/api/routers/leaderboard_v2.py`

- [ ] **Step 1:** Make `/global`, `/global-wallets`, `/might-cook`, `/hibernating` thin delegates to `/wallets` (`/global` → `tab=standard`, `/might-cook?tab=new_wallets` → `tab=new`, `?tab=hibernated` → `tab=hibernated`, `?tab=zero_balance` → `tab=low_balance`, `/hibernating` → `tab=hibernated`) so old clients keep working while the frontend moves over. This also fixes the dropped `include_dormant`/`filter_category` params issue by delegation.
- [ ] **Step 2:** Fix `/might-cook` `hibernated` tab operator if still present: it filters `last_trade_at < 30d AND is_dormant = FALSE` (leaderboard_v2.py:356) — after delegation this contradiction disappears.
- [ ] **Step 3:** `pytest tests/ -v` green. **Commit.**

---

# Phase 4 — Frontend shared primitives

All paths under `frontend/src`. Follow existing styling tokens (`bg-surface`, `surface-2`, `text-muted-fg`, `border-border`, `text-primary`) — see `app/wallets/global/page.tsx` for canon. Use the `frontend-design:frontend-design` skill when building these.

### Task 10: Shared utils + hooks

**Files:**
- Modify: `frontend/src/utils/format.ts` (add `formatAddress`, `timeAgo` — single canonical copies; 6-char truncation)
- Create: `frontend/src/hooks/useWalletList.ts`, `frontend/src/hooks/useCopyAddress.ts`, `frontend/src/hooks/useWatchlistAdd.ts`
- Modify: `frontend/src/utils/api.ts`

- [ ] **Step 1:** `api.ts` additions:

```typescript
export interface WalletListParams {
  tab: 'all' | 'standard' | 'low_balance' | 'new' | 'hibernated';
  source?: string; search?: string;
  sort_by?: string; sort_order?: 'asc' | 'desc';
  limit?: number; offset?: number;
}
export const getWalletList = (p: WalletListParams) =>
  fetchAuthData(`/api/v2/leaderboard/wallets?${new URLSearchParams(
    Object.fromEntries(Object.entries(p).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))
  )}`);
export const getWalletCounts = () => fetchAuthData('/api/v2/leaderboard/wallets/counts');
```

Delete the now-dead unused fns flagged in exploration (`getGlobalWalletList`, `getCuratedWhales`, `getCuratedLeaderboard`) once nothing references them.

- [ ] **Step 2:** `useWalletList.ts` — owns the state every page currently hand-rolls (data, loading, error, sortField, sortOrder, page, search debounce, refetch on param change). Signature:

```typescript
export function useWalletList(params: WalletListParams) {
  // useState for wallets/total/loading/error; useEffect fetch with cancellation
  return { wallets, total, loading, error, refetch };
}
```

- [ ] **Step 3:** `useCopyAddress` (copied-address timeout state) and `useWatchlistAdd` (idle/adding/added per-address state machine — lift from `wallets/global/page.tsx:88-98`).
- [ ] **Step 4:** `cd frontend && npx tsc --noEmit` clean. **Commit.**

### Task 11: Shared table components

**Files:**
- Create: `frontend/src/components/wallets/WalletTable.tsx`, `WalletCell.tsx`, `SourceBadges.tsx`, `Pagination.tsx`

- [ ] **Step 1:** `WalletTable` — column-config driven; the config type is the union of everything the 4 old pages rendered:

```typescript
export interface WalletRow {
  address: string; username?: string; tier: string; is_dormant: boolean;
  might_cook_type?: string; sources?: string[];
  pnl?: number; volume?: number; roi_pct?: number; win_rate?: number;
  balance?: number; position_value?: number;
  last_trade_at?: string; added_at?: string;
}
export interface ColumnDef {
  key: string; label: string; sortable?: boolean;
  align?: 'left' | 'right';
  render: (w: WalletRow, index: number) => React.ReactNode;
}
export function WalletTable({ columns, rows, loading, sortField, sortOrder, onSort, emptyMessage }: {
  columns: ColumnDef[]; rows: WalletRow[]; loading: boolean;
  sortField: string; sortOrder: 'asc' | 'desc';
  onSort: (key: string) => void; emptyMessage: string;
}) { /* thead from columns (sort arrows on sortable), tbody rows via col.render, Skeleton rows while loading, empty row */ }
```

Port the header/body/skeleton markup verbatim from `app/wallets/global/page.tsx:210-350` (it is the newest and canonical styling), parameterized by `columns`.

- [ ] **Step 2:** `WalletCell` — username + truncated address link to `/wallet/[address]` + icon cluster (copy, Polymarket, PolyTools, watchlist star) using the Task 10 hooks. Port from `wallets/global/page.tsx:316-338`.
- [ ] **Step 3:** `SourceBadges` — renders `sources: string[]` as colored chips; single `SOURCE_LABELS` map: `{ trade: 'Trade', deposit: 'Deposit', leaderboard: 'Leaderboard', manual: 'Custom' }`. Add a `MightCookBadge` (flame icon + "Might Cook" chip) shown when `might_cook_type` is set.
- [ ] **Step 4:** `Pagination` — page buttons + jump-to-page input, ported from `wallets/global/page.tsx:352-403`.
- [ ] **Step 5:** `npx tsc --noEmit` clean. **Commit.**

---

# Phase 5 — New Wallets page + navigation

### Task 12: Build `/wallets` (tabbed page)

**Files:**
- Create: `frontend/src/app/wallets/page.tsx`

- [ ] **Step 1:** Page structure:

```tsx
const TABS = [
  { key: 'all',         label: 'All' },
  { key: 'standard',    label: 'Standard' },
  { key: 'low_balance', label: 'Low Balance' },
  { key: 'new',         label: 'New' },
  { key: 'hibernated',  label: 'Hibernated' },
] as const;
```

- Tab state read/written via `useSearchParams` (`/wallets?tab=new`) so tabs are linkable; default `all`.
- Tab bar shows counts from `getWalletCounts()` (e.g. `Standard (1,204)`); an Active/Inactive summary strip above the tabs: Active = all − hibernated, Inactive = hibernated (this is the "divide into two categories" requirement made visible).
- Below tabs: source filter pills (All / Trade / Deposit / Leaderboard / Custom — port from global page lines 230-249), search box, then `<WalletTable>` + `<Pagination>` driven by `useWalletList({ tab, source, search, sort_by, sort_order, limit: 50, offset })`.

- [ ] **Step 2:** Column sets per tab (single `ColumnDef[]` with per-tab tweaks):
- **All / Standard:** #, Wallet, Source, PnL, Volume, ROI, Balance, Open Position, Last Traded — identical to today's global page.
- **Low Balance:** same minus ROI (not computed for uncurated), plus Balance highlighted.
- **New:** #, Wallet, Source, Might Cook badge, Deposits, Balance, Open Position, Added (no PnL/Last Traded — they never traded).
- **Hibernated:** Standard set plus "Dormant since" (`last_trade_at` absolute + relative).
- Tab descriptions under the tab bar (port the wording from `might-cook/page.tsx:133-135`): e.g. New = "Balance ≥ $1k, never traded — unproven whales".

- [ ] **Step 3:** Update home redirect: `app/page.tsx` → `redirect('/wallets')`.
- [ ] **Step 4:** `npm run dev`, click through all 5 tabs, source filters, search, sort, pagination; confirm each tab's rows differ and counts match badges. **Commit.**

### Task 13: Sidebar + retire old pages

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx:20-26`
- Delete: `frontend/src/app/might-cook/page.tsx`, `frontend/src/app/wallets/hibernating/page.tsx`
- Replace with redirects: `frontend/src/app/wallets/global/page.tsx`

- [ ] **Step 1:** Sidebar nav becomes:

```typescript
const NAV = [
  { label: 'Activity',   href: '/alpha-calls', icon: Zap },
  { label: 'Wallets',    href: '/wallets',     icon: Globe },
  { label: 'Curated',    href: '/wallets/curated', icon: Star },
  { label: 'My Tracker', href: '/tracker',     icon: Anchor },
];
```

Active-state match must treat `/wallets/curated` as Curated, not Wallets (match on exact/startsWith ordering).

- [ ] **Step 2:** `wallets/global/page.tsx` → 3-line `redirect('/wallets?tab=standard')`; delete might-cook and hibernating pages (grep for `href` references first: `wallet/[address]/page.tsx:57` back-link → change to `/wallets`).
- [ ] **Step 3:** Grep for dangling imports/links to deleted routes: `rg "might-cook|wallets/hibernating|wallets/global" frontend/src` → only the redirect file remains.
- [ ] **Step 4:** `npm run build` clean. **Commit.**

### Task 14: Refit Curated page onto shared primitives (no feature changes)

The curated page was just redesigned on this branch (windowed stats) — keep all its features; only de-duplicate.

**Files:**
- Modify: `frontend/src/app/wallets/curated/page.tsx`

- [ ] **Step 1:** Swap its local `formatAddress`, copy state, watchlist state machine, and pagination for the shared utils/hooks/`Pagination` from Tasks 10-11. Keep bespoke: category tabs, window pills, subcategory pills, filter modal, price-bucket columns with the 4-state client sort cycle.
- [ ] **Step 2:** Visual check against pre-change screenshots; `npm run build` clean. **Commit.**

---

# Phase 6 — Cleanup + docs

### Task 15: Kill remaining v1 write paths + docs

**Files:**
- Modify: `README.md`, `docs/ARCHITECTURE_AND_WORKERS.md`, `docs/CORE_LOGIC.md`, `docs/API_REFERENCE.md`, `docs/CHANGELOG.md`

- [ ] **Step 1:** `rg "INSERT INTO tracked_wallets|UPDATE tracked_wallets" src/` — remaining hits should be zero in workers (API v1 router reads are fine to leave; it's frozen).
- [ ] **Step 2:** Docs: update the wallet-tier section (NEW/LOW_BALANCE/STANDARD/CURATED/DEAD + is_dormant, the tab mapping table from "Canonical wallet model" above), the frontend routes table (`/wallets` + tabs, removed pages), and the API table (new `/api/v2/leaderboard/wallets`). Add CHANGELOG entry dated 2026-07-16.
- [ ] **Step 3:** Note in docs: `tracked_wallets`/`wallet_stats` are now legacy-read-only; dropping them is a follow-up task once the v1 router is retired. **Commit.**

---

## Verification (end-to-end, after all phases)

1. `alembic upgrade head` on a scratch DB succeeds from zero (guards the known multi-head history risk).
2. `pytest tests/ -v` — all green.
3. Start stack (`docker-compose up -d`, API, `python src/orchestrator.py`, `cd frontend && npm run dev`). Let workers run ~10 min.
4. DB spot checks:
   - `SELECT tier, is_dormant, count(*) FROM wallets_v2 GROUP BY 1,2` — all five tiers populated, no `MIGHT_COOK`/`UNCLASSIFIED` growth.
   - `SELECT source, count(*) FROM wallet_sources_v2 GROUP BY 1` — all four sources present.
   - No wallet appears in two tabs: the five tab WHERE clauses are disjoint by construction except All (superset) — verify `standard ∩ hibernated = ∅` etc. with intersect queries.
5. UI walkthrough: `/` redirects to `/wallets`; 5 tabs each render distinct data with correct counts; source pills filter; Might Cook badge visible on New tab; Curated page unchanged feature-wise; old URLs (`/wallets/global`) redirect; sidebar has 4 entries.
6. Use the `verify` skill before the final commit; then `superpowers:requesting-code-review`.

## Out of scope (explicit)

- Dropping v1 tables / retiring the v1 `/api/leaderboard` router (follow-up after this ships).
- Choosing between `leaderboard_stats.py` and the un-orchestrated `leaderboard_stats_v2.py` as the long-term stats engine — this plan keeps `leaderboard_stats.py` and only fixes its v2 writes.
- Consolidating `/tracker` vs `/tools/wallet-tracker` (two parallel watchlist systems — flagged for a future decision).
- Alpha-calls page subcategory stub and client-side-only search.
