# Curated Windowed Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Source headline PnL/volume from the Polymarket leaderboard and give curated wallets per-category × per-trade-window (100/300/800/1500/2500) stats, stored in five dedicated tables, surfaced through the API and curated frontend so selecting a window swaps every metric.

**Architecture:** A pure windowing function classifies a wallet's closed positions by category and slices the last N per category — computed in-memory during the existing stats worker pass (no extra API calls). Results land in five physical tables keyed `(address, category)`. The API reads the `(category, window)` cell; the frontend filters are pure navigation. Headline PnL/volume come from the leaderboard with a computed fallback; win%/ROI formulas are unchanged.

**Tech Stack:** Python 3, asyncpg, aiohttp, Alembic, FastAPI, pytest/pytest-asyncio, Next.js (customized — read `frontend/node_modules/next/dist/docs/` before frontend code), TypeScript/React.

**Spec:** `docs/superpowers/specs/2026-07-06-curated-windowed-stats-design.md`

---

## Conventions

- **DB for tests:** local Postgres `poly_db` (see `tests/conftest.py`). Integration tests use the `test_pool` / `async_client` fixtures.
- **Run one test:** `pytest tests/path/test_file.py::test_name -v`
- **Run worker unit tests (no DB):** the pure functions in Tasks 2–3 need no DB.
- **Windows constant:** `TRADE_WINDOWS = [100, 300, 800, 1500, 2500]` (already in `leaderboard_stats.py:504`).
- **Categories:** `PM_CATEGORIES = ["SPORTS","POLITICS","CRYPTO","ESPORTS","CULTURE","TECH","FINANCE","ECONOMICS","WEATHER"]` plus synthetic `"OVERALL"`.

---

## File Structure

- **Create** `alembic/versions/<rev>_add_per_category_window_tables.py` — 5 window tables + `wallet_category_stats.last_active` + `tracked_wallets.pnl_source`.
- **Create** `alembic/versions/<rev>_drop_wallet_trade_window_stats.py` — drop the superseded table (last).
- **Create** `src/workers/window_stats.py` — pure functions `compute_category_window_stats()` and `select_headline_pnl()` (no I/O, unit-testable).
- **Modify** `src/workers/leaderboard_stats.py` — cap closed-positions at 2,500; call the pure functions; write the 5 tables; set `pnl_source`; raise curated-trade capture to 2,500 full history.
- **Modify** `src/api/routers/leaderboard.py` — `window` param; read per-category window tables; return full windowed cell.
- **Modify** `frontend/src/app/wallets/curated/page.tsx` — server-driven windowed columns; add volume + last-active; remove status.
- **Create** `src/scripts/backfill_window_stats.py` — one-off recompute for existing curated wallets.
- **Create** `tests/test_window_stats.py` — unit tests for the pure functions.
- **Create** `tests/test_curated_window_api.py` — integration test for the API cell selection.

---

## Task 1: Migration — per-category window tables + new columns

**Files:**
- Create: `alembic/versions/<rev>_add_per_category_window_tables.py`

- [ ] **Step 1: Find the current Alembic head**

Run: `cd "C:/Users/shubh/Downloads/project/poly" && alembic heads`
Expected: one revision id (e.g. `e4f5a6b7c8d9` or the merge head). Use it as `down_revision` below. If multiple heads print, run `alembic merge` first or set `down_revision` to a tuple of both.

- [ ] **Step 2: Write the migration**

Create `alembic/versions/f5a6b7c8d9e0_add_per_category_window_tables.py`:

```python
"""add per-category window tables + last_active + pnl_source

Revision ID: f5a6b7c8d9e0
Revises: <PUT alembic heads OUTPUT HERE>
Create Date: 2026-07-06 12:00:00
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = '<PUT alembic heads OUTPUT HERE>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WINDOWS = [100, 300, 800, 1500, 2500]


def upgrade() -> None:
    for w in WINDOWS:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS wallet_window_{w} (
                address        VARCHAR(42) NOT NULL REFERENCES tracked_wallets(address) ON DELETE CASCADE,
                category       VARCHAR(20) NOT NULL,
                pnl            NUMERIC(18,2) NOT NULL DEFAULT 0,
                volume         NUMERIC(18,2) NOT NULL DEFAULT 0,
                win_rate       NUMERIC(5,4)  NOT NULL DEFAULT 0,
                roi_pct        NUMERIC(10,4) NOT NULL DEFAULT 0,
                resolved_count INTEGER       NOT NULL DEFAULT 0,
                winning_count  INTEGER       NOT NULL DEFAULT 0,
                last_active    TIMESTAMPTZ,
                computed_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (address, category)
            );
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_ww{w}_cat_pnl ON wallet_window_{w}(category, pnl DESC);")
    op.execute("ALTER TABLE wallet_category_stats ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ;")
    op.execute("ALTER TABLE tracked_wallets ADD COLUMN IF NOT EXISTS pnl_source VARCHAR(16);")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_wallets DROP COLUMN IF EXISTS pnl_source;")
    op.execute("ALTER TABLE wallet_category_stats DROP COLUMN IF EXISTS last_active;")
    for w in WINDOWS:
        op.execute(f"DROP TABLE IF EXISTS wallet_window_{w};")
```

- [ ] **Step 3: Apply the migration**

Run: `alembic upgrade head`
Expected: no errors; `\d wallet_window_100` shows the columns.

- [ ] **Step 4: Verify tables exist**

Run: `python -c "import asyncpg,asyncio,os; asyncio.run((lambda: None)())" ` then a psql check:
`psql "$DATABASE_URL" -c "SELECT to_regclass('wallet_window_2500'), to_regclass('wallet_window_100');"`
Expected: both non-null.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/f5a6b7c8d9e0_add_per_category_window_tables.py
git commit -m "feat(db): add per-category window tables, last_active, pnl_source"
```

---

## Task 2: Pure windowing function (TDD)

**Files:**
- Create: `src/workers/window_stats.py`
- Test: `tests/test_window_stats.py`

The function takes a wallet's closed positions (already fetched) plus a category-classifier callable and returns, per `(category, window)`, the aggregated stats. No I/O.

- [ ] **Step 1: Write the failing test**

Create `tests/test_window_stats.py`:

```python
from datetime import datetime, timezone
from src.workers.window_stats import compute_category_window_stats

def _cp(cid, pnl, bought, end, cat_title):
    return {"conditionId": cid, "realizedPnl": pnl, "totalBought": bought,
            "endDate": end, "title": cat_title}

def _classify(title):
    # test stub: title *is* the category
    return title

def test_overall_and_category_slicing():
    # 3 SPORTS (2 win), 1 POLITICS (loss)
    closed = [
        _cp("a", 100.0, 50.0, "2026-01-04T00:00:00Z", "SPORTS"),
        _cp("b", -20.0, 40.0, "2026-01-03T00:00:00Z", "SPORTS"),
        _cp("c", 10.0, 5.0,  "2026-01-02T00:00:00Z", "SPORTS"),
        _cp("d", -5.0, 30.0, "2026-01-01T00:00:00Z", "POLITICS"),
    ]
    out = compute_category_window_stats(closed, [100], _classify)
    ov = out[("OVERALL", 100)]
    assert ov["resolved_count"] == 4
    assert ov["winning_count"] == 2
    assert round(ov["pnl"], 2) == 85.0
    assert round(ov["volume"], 2) == 125.0
    assert ov["win_rate"] == 0.5
    assert round(ov["roi_pct"], 2) == 68.0
    assert ov["last_active"] == datetime(2026, 1, 4, tzinfo=timezone.utc)
    sp = out[("SPORTS", 100)]
    assert sp["resolved_count"] == 3
    assert sp["winning_count"] == 2

def test_window_smaller_than_count():
    closed = [_cp(str(i), 1.0, 1.0, f"2026-01-{i+1:02d}T00:00:00Z", "CRYPTO") for i in range(5)]
    out = compute_category_window_stats(closed, [2], _classify)
    # only the 2 most recent (endDate desc) count
    assert out[("CRYPTO", 2)]["resolved_count"] == 2
    assert out[("OVERALL", 2)]["resolved_count"] == 2

def test_empty():
    out = compute_category_window_stats([], [100], _classify)
    assert out == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_window_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.workers.window_stats'`.

- [ ] **Step 3: Implement the function**

Create `src/workers/window_stats.py`:

```python
"""Pure, I/O-free helpers for windowed and headline stats.

Kept separate from leaderboard_stats.py so they can be unit-tested without a DB
or network. compute_category_window_stats groups closed positions by category and
slices the last N (by endDate desc) for each window.
"""
from datetime import datetime, timezone
from typing import Callable


def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _parse_end(val):
    if not val:
        return None
    try:
        s = str(val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _aggregate(positions: list[dict]) -> dict:
    pnl = 0.0
    volume = 0.0
    wins = 0
    last_active = None
    for cp in positions:
        rpnl = _parse(cp.get("realizedPnl"))
        pnl += rpnl
        volume += _parse(cp.get("totalBought"))
        if rpnl > 0:
            wins += 1
        end = _parse_end(cp.get("endDate"))
        if end and (last_active is None or end > last_active):
            last_active = end
    resolved = len(positions)
    return {
        "pnl": pnl,
        "volume": volume,
        "resolved_count": resolved,
        "winning_count": wins,
        "win_rate": (wins / resolved) if resolved else 0.0,
        "roi_pct": (pnl / volume * 100) if volume else 0.0,
        "last_active": last_active,
    }


def compute_category_window_stats(
    closed_positions: list[dict],
    windows: list[int],
    classify: Callable[[str], str],
) -> dict[tuple[str, int], dict]:
    """Return {(category, window): stats} plus ('OVERALL', window).

    `classify(title) -> CATEGORY` maps a position's market title to a category.
    Positions are sliced by endDate desc within each category (and overall).
    """
    if not closed_positions:
        return {}

    ordered = sorted(
        closed_positions,
        key=lambda cp: _parse_end(cp.get("endDate")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    by_cat: dict[str, list[dict]] = {}
    for cp in ordered:
        cat = (classify(cp.get("title") or "") or "OTHER").upper()
        by_cat.setdefault(cat, []).append(cp)

    result: dict[tuple[str, int], dict] = {}
    for window in windows:
        result[("OVERALL", window)] = _aggregate(ordered[:window])
        for cat, positions in by_cat.items():
            result[(cat, window)] = _aggregate(positions[:window])
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_window_stats.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/workers/window_stats.py tests/test_window_stats.py
git commit -m "feat(worker): pure per-category window stats function"
```

---

## Task 3: Headline PnL source selection (TDD)

**Files:**
- Modify: `src/workers/window_stats.py`
- Modify: `tests/test_window_stats.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_window_stats.py`:

```python
from src.workers.window_stats import select_headline_pnl

def test_headline_uses_leaderboard_when_present():
    r = select_headline_pnl(website={"pnl": 1234.5, "volume": 999.0},
                            computed_pnl=10.0, computed_volume=20.0)
    assert r == {"pnl": 1234.5, "volume": 999.0, "pnl_source": "leaderboard"}

def test_headline_falls_back_when_absent():
    r = select_headline_pnl(website=None, computed_pnl=10.0, computed_volume=20.0)
    assert r == {"pnl": 10.0, "volume": 20.0, "pnl_source": "computed"}

def test_headline_leaderboard_zero_still_leaderboard():
    # A genuine break-even wallet on the leaderboard keeps leaderboard source
    r = select_headline_pnl(website={"pnl": 0.0, "volume": 0.0},
                            computed_pnl=99.0, computed_volume=99.0)
    assert r["pnl_source"] == "leaderboard"
    assert r["pnl"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_window_stats.py -k headline -v`
Expected: FAIL with `ImportError: cannot import name 'select_headline_pnl'`.

- [ ] **Step 3: Implement**

Append to `src/workers/window_stats.py`:

```python
def select_headline_pnl(website: dict | None, computed_pnl: float, computed_volume: float) -> dict:
    """Headline pnl/volume come from the leaderboard when the wallet appears on it
    (presence of the `website` object), else from our computed realized+unrealized.
    Presence — not `!= 0` — distinguishes a real break-even from a missing fetch."""
    if website is not None:
        return {"pnl": _parse(website.get("pnl")),
                "volume": _parse(website.get("volume")),
                "pnl_source": "leaderboard"}
    return {"pnl": computed_pnl, "volume": computed_volume, "pnl_source": "computed"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_window_stats.py -k headline -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/workers/window_stats.py tests/test_window_stats.py
git commit -m "feat(worker): explicit headline pnl source selection"
```

---

## Task 4: Wire the worker to the new functions

**Files:**
- Modify: `src/workers/leaderboard_stats.py` (fetch cap ~`79-94`; process_wallet body ~`408-618`)

- [ ] **Step 1: Cap closed-positions at 2,500**

In `fetch_closed_positions` (`src/workers/leaderboard_stats.py:79`), change the loop guard from `if offset > 10000: break` to stop at 2,500:

```python
async def fetch_closed_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_closed = []
    offset = 0
    limit = 50  # API caps closed-positions at 50/page regardless of this value
    max_closed = 2500  # largest trade window; bounds cost per wallet
    while True:
        data = await _get(session, f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_closed.extend(data)
        if len(data) < limit or len(all_closed) >= max_closed:
            break
        offset += limit
        await asyncio.sleep(API_DELAY)
    return all_closed[:max_closed]
```

- [ ] **Step 2: Import the pure helpers**

Near the top of `src/workers/leaderboard_stats.py` (after the existing `from src.utils...` imports):

```python
from src.workers.window_stats import compute_category_window_stats, select_headline_pnl
```

- [ ] **Step 3: Use `select_headline_pnl` for headline + `pnl_source`**

In `process_wallet`, replace the headline handling. After `total_pnl = realized_pnl + unrealized_pnl` (around line 438), and before `stats = compute_stats(...)`, compute the headline and persist the source:

```python
    headline = select_headline_pnl(website, total_pnl, _computed_volume(trades))
    await conn.execute(
        "UPDATE tracked_wallets SET pnl_source=$2 WHERE address=$1",
        address, headline["pnl_source"],
    )
```

Add a small helper near `_parse` (top of file) so computed volume is available before `compute_stats`:

```python
def _computed_volume(trades) -> float:
    v = 0.0
    for t in trades:
        v += _parse(t.get("size")) * _parse(t.get("price"))
    return v
```

Then change `compute_stats` (line 213-214) so the headline is authoritative instead of the `!= 0` sentinel. Replace:

```python
    effective_volume = website_volume if website_volume > 0 else total_volume
    effective_pnl = website_pnl if website_pnl != 0 else total_pnl
```

with a signature that receives the resolved headline. Update the `compute_stats` call and definition to take `headline_pnl`/`headline_volume`:

```python
# definition (line 170): add headline_pnl, headline_volume params, and use them:
    effective_volume = headline_volume
    effective_pnl = headline_pnl
```

```python
# call site (was line 439):
    stats = compute_stats(trades, positions, closed,
                          headline["pnl"], headline["volume"],
                          total_pnl, realized_pnl, unrealized_pnl, start_stats_at)
```

(Remove the now-unused `website_pnl`/`website_volume` params from `compute_stats` and pass `headline` values instead. The `tracked_wallets`/`wallet_stats` writes at lines 442-469 already store `stats["total_pnl"]` = headline pnl — no further change there.)

- [ ] **Step 4: Replace the overall window write with per-category window write**

Delete the existing overall-only window loop (`src/workers/leaderboard_stats.py:504-536`, the `TRADE_WINDOWS` block writing `wallet_trade_window_stats`) and replace with a per-category write into the five tables:

```python
    TRADE_WINDOWS = [100, 300, 800, 1500, 2500]
    window_stats = compute_category_window_stats(
        closed or [], TRADE_WINDOWS, lambda title: classify_tags([title])[0] if title else "OTHER"
    )
    for (cat, window), s in window_stats.items():
        await conn.execute(f"""
            INSERT INTO wallet_window_{window}
                (address, category, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, last_active, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (address, category) DO UPDATE SET
                pnl=EXCLUDED.pnl, volume=EXCLUDED.volume, win_rate=EXCLUDED.win_rate,
                roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, last_active=EXCLUDED.last_active, computed_at=NOW()
        """, address, cat.upper(), s["pnl"], s["volume"], s["win_rate"], s["roi_pct"],
             s["resolved_count"], s["winning_count"], s["last_active"])
```

> `classify_tags` is already imported at `leaderboard_stats.py:27` and returns `(category, subcategory)`; we take `[0]` and uppercase to match the classifier stub contract in Task 2.

- [ ] **Step 5: Add `last_active` to the per-category all-time write**

Where `compute_category_stats` results are written to `wallet_category_stats` (around `leaderboard_stats.py:494-500`), add `last_active` (max endDate per category). Extend `compute_category_stats` (line 276) to also track and return `last_active` per category (compute from `cp.get("endDate")` using the same `_parse_end` logic — import it from `window_stats`), then include it in the INSERT column list and the `ON CONFLICT DO UPDATE SET`.

- [ ] **Step 6: Raise curated-trade capture to 2,500 full history**

In `fetch_trades_after` (`leaderboard_stats.py:97-126`), for curated wallets we need full history, not just after `start_stats_at`. Change `max_trades = 2000` → `max_trades = 2500`. The `start_stats_at` cutoff is used for the general trade pull; for the curated-trades storage block (`leaderboard_stats.py:591-618`) it already iterates `trades`. Bump the storage cap by ensuring `trades` holds up to 2,500 (the raised `max_trades` covers it). No cutoff change needed if `start_stats_at` for curated wallets is their `added_at`; if fuller history is required, pass `datetime.min` for curated wallets — leave as-is unless verification shows truncation.

- [ ] **Step 7: Run the worker unit tests + a smoke import**

Run: `pytest tests/test_window_stats.py -v && python -c "import src.workers.leaderboard_stats"`
Expected: tests pass; import succeeds (no syntax/name errors).

- [ ] **Step 8: Live smoke against one wallet**

Create a throwaway `smoke_one.py` at repo root and run it against a real leaderboard whale (already curated or insert it first):

```python
import asyncio, aiohttp, asyncpg
from src.workers.leaderboard_stats import process_wallet, DB_URL

ADDR = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"  # Theo4, rank 1

async def main():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("INSERT INTO tracked_wallets (address, source_type, added_at, is_curated) "
                       "VALUES ($1,'leaderboard',NOW(),TRUE) ON CONFLICT (address) DO UPDATE SET is_curated=TRUE", ADDR)
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as s:
        await process_wallet(conn, s, ADDR)
    for w in (100, 2500):
        rows = await conn.fetch(f"SELECT category, pnl, resolved_count FROM wallet_window_{w} WHERE address=$1 ORDER BY pnl DESC", ADDR)
        print(f"window {w}:", [(r['category'], float(r['pnl']), r['resolved_count']) for r in rows])
    hp = await conn.fetchval("SELECT total_pnl FROM wallet_stats WHERE address=$1", ADDR)
    print("headline total_pnl:", hp)
    await conn.close()

asyncio.run(main())
```

Run: `python smoke_one.py` then `rm smoke_one.py`
Expected: an `OVERALL` row plus category rows in both `wallet_window_100` and `wallet_window_2500`; `OVERALL` pnl ≈ the leaderboard headline (~22,053,933 for Theo4) within rounding.

- [ ] **Step 9: Commit**

```bash
git add src/workers/leaderboard_stats.py
git commit -m "feat(worker): per-category window tables, leaderboard headline, 2500 cap"
```

---

## Task 5: API — category + window cell selection

**Files:**
- Modify: `src/api/routers/leaderboard.py` (curated endpoint ~`730-900`)
- Test: `tests/test_curated_window_api.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_curated_window_api.py`:

```python
import pytest

@pytest.mark.anyio
async def test_curated_window_returns_windowed_metrics(async_client, test_pool):
    addr = "0x" + "a" * 40
    async with test_pool.acquire() as conn:
        await conn.execute("INSERT INTO tracked_wallets (address, source_type, added_at, is_curated) "
                           "VALUES ($1,'leaderboard',NOW(),TRUE) ON CONFLICT (address) DO UPDATE SET is_curated=TRUE", addr)
        await conn.execute("DELETE FROM wallet_window_100 WHERE address=$1", addr)
        await conn.execute("INSERT INTO wallet_window_100 (address,category,pnl,volume,win_rate,roi_pct,resolved_count,winning_count) "
                           "VALUES ($1,'OVERALL',777.0,1000.0,0.7,77.7,10,7)", addr)
    resp = await async_client.get("/leaderboard/curated?category=OVERALL&window=100&limit=50")
    assert resp.status_code == 200
    row = next(w for w in resp.json()["wallets"] if w["address"] == addr)
    assert float(row["total_pnl"]) == 777.0
    assert int(row["winning_count"]) == 7
    assert float(row["win_rate"]) == 0.7
```

> Confirm the actual curated route path (`/leaderboard/curated` vs another) by checking the `@router.get(...)` decorator above the function at `src/api/routers/leaderboard.py:730`ish; adjust the URL accordingly.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_curated_window_api.py -v`
Expected: FAIL — either 422 (no `window` param yet) or the windowed values don't override the base columns.

- [ ] **Step 3: Add the `window` param and windowed source**

In the curated endpoint signature add `window: Optional[int] = None`. When `window in (100,300,800,1500,2500)`, source the metric columns from `wallet_window_<window>` joined on `(address, category)` (category = `cat_upper` or `'OVERALL'`), returning its `pnl/volume/win_rate/roi_pct/resolved_count/winning_count/last_active` as `total_pnl/total_volume/win_rate/roi_pct/resolved_count/winning_count/last_active`. Replace the five `LEFT JOIN wallet_trade_window_stats twwNNN` joins (lines 791-795 and 834-838) with a single join to the selected window table:

```python
    win = window if window in (100, 300, 800, 1500, 2500) else None
    win_cat = cat_upper if use_category else "OVERALL"
    if win:
        wtable = f"wallet_window_{win}"
        select_metrics = (
            "COALESCE(ww.pnl,0) as total_pnl, COALESCE(ww.win_rate,0) as win_rate, "
            "COALESCE(ww.roi_pct,0) as roi_pct, COALESCE(ww.volume,0) as total_volume, "
            "COALESCE(ww.resolved_count,0) as resolved_count, COALESCE(ww.winning_count,0) as winning_count, "
            "ww.last_active"
        )
        window_join = f"LEFT JOIN {wtable} ww ON tw.address=ww.address AND ww.category=$WINCAT"
        order_col = "COALESCE(ww.pnl,0)" if sort_by in ("total_pnl","pnl_100","pnl_300","pnl_800","pnl_1500","pnl_2500") else order_col
```

Build the query so `$WINCAT` is a real bound parameter (append `win_cat` to `args` and use its positional index). Keep the all-time path (no `window`) reading `wallet_category_stats` / `wallet_stats` exactly as today, but drop the obsolete `pnl_100…pnl_2500` select columns and their joins.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_curated_window_api.py -v`
Expected: PASS.

- [ ] **Step 5: Regression — all-time path still works**

Run: `pytest tests/ -k curated -v`
Expected: existing curated tests (if any) still pass; no 500s.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/leaderboard.py tests/test_curated_window_api.py
git commit -m "feat(api): curated endpoint returns windowed cell per (category, window)"
```

---

## Task 6: Frontend — server-driven windowed columns

**Files:**
- Modify: `frontend/src/app/wallets/curated/page.tsx`
- Modify: `frontend/src/utils/api.ts` (add `window` to `getCuratedWalletList`)

- [ ] **Step 1: Read the Next.js docs**

Run: `ls frontend/node_modules/next/dist/docs/` and read the data-fetching / client-component guide relevant to this page (it is a `"use client"` page using `useEffect`). Do not assume standard Next.js behavior.

- [ ] **Step 2: Pass `window` through the API helper**

In `frontend/src/utils/api.ts`, locate `getCuratedWalletList` and add `window` to its `filters` options object, forwarding it only when set. Concretely, inside the function where the query string / params are assembled, add:

```typescript
// in the filters type and destructure:
//   filters: { ...; window?: number }
if (filters.window) params.append("window", String(filters.window));
```

Match the exact `params`/URLSearchParams (or object) style already used in that function — read the surrounding lines first and mirror them; do not introduce a new serialization pattern.

- [ ] **Step 3: Send `pnlWindow` to the server, stop client-side swapping**

In `page.tsx`:
- Add `pnlWindow` (already in state) to the `getCuratedWalletList` call's options and to the `fetchData` dependency array (already listed at line 188).
- Delete `getWindowPnl` (lines 162-166) and its usage (line 550). Render `w.total_pnl` directly — the server now returns the windowed value.
- Render `win_rate`, `roi_pct`, `total_volume`, `resolved_count`, `winning_count`, and a new **Last Active** column all from the returned row (they are already windowed server-side).

- [ ] **Step 4: Add Volume + Last Active columns; remove status**

Add a `<th>Volume</th>` (already present) and a `<th>Last Active</th>` header, plus the matching `<td>` cells rendering `formatCurrency(w.total_volume)` and `w.last_active ? new Date(w.last_active).toLocaleDateString() : "—"`. Confirm no dormant/status column is rendered (the current table already omits it — keep it omitted). Update the `CuratedWallet` interface: remove `pnl_100..pnl_2500`, add `last_active: string | null`.

- [ ] **Step 5: Build the frontend**

Run: `cd frontend && npm run build`
Expected: build succeeds, no type errors about removed `pnl_100` fields.

- [ ] **Step 6: Manual check**

Run the app (use the `run` skill or `npm run dev`), open the curated page, switch category tabs and the PnL Window filter; confirm every column (pnl, volume, win%, roi, trades, wins, last active) changes together and matches DB values for a spot-checked wallet.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/wallets/curated/page.tsx frontend/src/utils/api.ts
git commit -m "feat(ui): curated windowed columns driven by server (category, window)"
```

---

## Task 7: Backfill + drop superseded table

**Files:**
- Create: `src/scripts/backfill_window_stats.py`
- Create: `alembic/versions/<rev>_drop_wallet_trade_window_stats.py`

- [ ] **Step 1: Write the backfill script**

Create `src/scripts/backfill_window_stats.py` that iterates curated wallets and runs `process_wallet` (or a trimmed variant) once each, populating the five tables. Reuse `run_leaderboard_stats`'s connection/session setup with `CONCURRENCY` from env. Log progress every 50 wallets.

```python
"""One-off: recompute per-category window tables for all curated wallets."""
import asyncio, aiohttp, asyncpg, os, logging
from src.workers.leaderboard_stats import process_wallet, DB_URL

logging.basicConfig(level=logging.INFO)

async def main():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT address FROM tracked_wallets WHERE is_curated=TRUE")
    addrs = [r["address"] for r in rows]
    sem = asyncio.Semaphore(int(os.environ.get("STATS_WORKER_CONCURRENCY", "10")))
    async def one(a):
        async with sem, pool.acquire() as conn, aiohttp.ClientSession(headers={"User-Agent":"Mozilla/5.0"}) as s:
            try: await process_wallet(conn, s, a)
            except Exception as e: logging.warning(f"{a[:10]} {e}")
    await asyncio.gather(*[one(a) for a in addrs])
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the backfill**

Run: `python -m src.scripts.backfill_window_stats`
Expected: completes; `SELECT count(*) FROM wallet_window_2500;` > 0.

- [ ] **Step 3: Verify data sanity**

Run: `psql "$DATABASE_URL" -c "SELECT category,count(*) FROM wallet_window_100 GROUP BY category ORDER BY 2 DESC LIMIT 12;"`
Expected: an `OVERALL` row plus category rows; counts plausible.

- [ ] **Step 4: Write the drop migration**

Create `alembic/versions/a6b7c8d9e0f1_drop_wallet_trade_window_stats.py` (set `down_revision` to Task 1's revision `f5a6b7c8d9e0`):

```python
from typing import Sequence, Union
from alembic import op

revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_trade_window_stats;")

def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS wallet_trade_window_stats (
            address VARCHAR(42) NOT NULL, window_size INTEGER NOT NULL,
            pnl NUMERIC(18,2) DEFAULT 0, volume NUMERIC(18,2) DEFAULT 0,
            win_rate NUMERIC(5,4) DEFAULT 0, resolved_count INTEGER DEFAULT 0,
            winning_count INTEGER DEFAULT 0, roi_pct NUMERIC(10,4) DEFAULT 0,
            computed_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (address, window_size));
    """)
```

- [ ] **Step 5: Apply + confirm nothing references the old table**

Run: `grep -rn "wallet_trade_window_stats" src/ frontend/src/` — expected: no matches (all replaced in Tasks 4–5).
Run: `alembic upgrade head`
Expected: table dropped; app + API tests still green: `pytest tests/ -k "curated or window" -v`.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/backfill_window_stats.py alembic/versions/a6b7c8d9e0f1_drop_wallet_trade_window_stats.py
git commit -m "chore: backfill window tables and drop superseded wallet_trade_window_stats"
```

---

## Note: refresh cadence (spec §6.4)

No new task is required for the hourly / ≤3-hourly cadence: the existing worker
(`run_leaderboard_stats`, `leaderboard_stats.py:623`) already loops continuously and orders
by `last_indexed ASC NULLS FIRST, last_checked_for_curated ASC NULLS FIRST`, which keeps
never-indexed and stale wallets first. At 1,675 wallets this comfortably completes within an
hour. **Optional future optimization (deferred, not in scope):** a delta gate that skips the
per-category recompute when `last_trade_at <= computed_at` for the wallet, to cut steady-state
load at the 10k peak. Add only if live metrics show the loop exceeding ~3 hours.

## Final verification (verification-before-completion skill)

- [ ] `pytest tests/test_window_stats.py tests/test_curated_window_api.py -v` — all pass.
- [ ] `cd frontend && npm run build` — succeeds.
- [ ] Live: run the stats worker one cycle; spot-check one curated wallet — `OVERALL` all-time pnl equals its leaderboard headline; window rows collapse to all-time when resolved_count < window; switching the frontend window swaps every column.
- [ ] `grep -rn "wallet_trade_window_stats\|getWindowPnl\|pnl_100" src/ frontend/src/` returns nothing.
