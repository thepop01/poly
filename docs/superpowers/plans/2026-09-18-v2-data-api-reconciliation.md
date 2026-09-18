# v2 Data API — Reconciliation & Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the PnL pipeline onto the Polymarket v2 Data API so that `Σ total_pnl (OPEN + CLOSED)` reproduces v2's position PnL to the cent, repair rules are demoted to logged fallbacks, and the ~9 k divergence roster is re-classified with a stored, decomposed residual instead of a scaled-away error.

**Architecture:** v2 positions are the single source of cost basis; `/activity` is evidence for provenance only, not a PnL source. Reconciliation happens at event grain (not market grain). A quarantine table holds rows that fail hard identity checks instead of silently zeroing them.

**Tech Stack:** Python 3.11+, asyncpg, asyncio, Alembic, pytest-asyncio, PostgreSQL 15.

---

## Phase 0 — Blockers (nothing else can start)

> All five tasks in this phase are independent and can be implemented in any order. The exit gate is: one known wallet round-trips through the v2 adapter and `Σ total_pnl` matches v2 to the cent.

---

### Task 0-A: Build `src/pnl/v2_adapter.py`

**Files:**
- Create: `src/pnl/v2_adapter.py`
- Test: `tests/pnl/test_v2_adapter.py`

This file does **not** exist. It is the only place that knows how to speak to the v2 Data API positions envelope.

- [ ] **Step 1: Write the failing test**

```python
# tests/pnl/test_v2_adapter.py
import pytest
from unittest.mock import AsyncMock, patch
from src.pnl.v2_adapter import V2Adapter, PositionRow

SAMPLE_ENVELOPE = {
    "data": [
        {
            "proxyWallet": "0xabc",
            "conditionId": "0x111",
            "eventId": "evt_1",
            "status": "OPEN",
            "outcomeIndex": 0,
            "totalPnl": "1234.56",
            "realizedPnl": "0.00",
            "unrealizedPnl": "1234.56",
            "entryCostUsdc": "800.00",
            "totalCostUsdc": "808.00",
            "entryFeesUsdc": "8.00",
            "avgPrice": "0.80",
            "currentSize": "1000",
            "totalSize": "1000",
            "mergeable": True,
        }
    ],
    "nextCursor": None,
}


@pytest.mark.asyncio
async def test_normalize_open_row():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = SAMPLE_ENVELOPE
        rows = await adapter.fetch_positions("0xabc", status="OPEN")
    assert len(rows) == 1
    r: PositionRow = rows[0]
    assert r.event_id == "evt_1"
    assert r.entry_cost_usdc == 800.00
    assert r.total_cost_usdc == 808.00
    assert r.entry_fees_usdc == 8.00
    assert r.mergeable is True
    assert r.outcome_index == 0
    assert r.source_total_pnl == 1234.56


@pytest.mark.asyncio
async def test_cursor_pagination():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    page1 = {**SAMPLE_ENVELOPE, "nextCursor": "tok_2"}
    page2 = {
        "data": [{**SAMPLE_ENVELOPE["data"][0], "conditionId": "0x222"}],
        "nextCursor": None,
    }
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = [page1, page2]
        rows = await adapter.fetch_positions("0xabc", status="OPEN")
    assert len(rows) == 2
    assert mock_fetch.call_count == 2


@pytest.mark.asyncio
async def test_condition_batching_max_20():
    adapter = V2Adapter(base_url="https://data-api.polymarket.com")
    ids = [f"0x{i:040x}" for i in range(45)]
    with patch.object(adapter, "_fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"data": [], "nextCursor": None}
        await adapter.fetch_positions_by_conditions("0xabc", ids)
    assert mock_fetch.call_count == 3  # ceil(45/20)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/pnl/test_v2_adapter.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.pnl.v2_adapter'`

- [ ] **Step 3: Implement `src/pnl/v2_adapter.py`**

```python
"""Polymarket v2 Data API adapter — envelope/cursor normalization."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Literal
import aiohttp

BASE_URL = "https://data-api.polymarket.com"
_BATCH = 20


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _b(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in {"true", "1", "yes"}
    return bool(val)


@dataclass
class PositionRow:
    proxy_wallet: str
    condition_id: str
    event_id: str | None
    status: str
    outcome_index: int | None
    source_total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    entry_cost_usdc: float
    total_cost_usdc: float
    entry_fees_usdc: float
    avg_price: float
    current_size: float
    total_size: float
    mergeable: bool
    raw: dict = field(repr=False)


def _parse_row(d: dict) -> PositionRow:
    return PositionRow(
        proxy_wallet=str(d.get("proxyWallet") or d.get("proxy_wallet") or ""),
        condition_id=str(d.get("conditionId") or d.get("condition_id") or ""),
        event_id=d.get("eventId") or d.get("event_id"),
        status=str(d.get("status") or "OPEN").upper(),
        outcome_index=d.get("outcomeIndex") or d.get("outcome_index"),
        source_total_pnl=_f(d.get("totalPnl") or d.get("total_pnl")),
        realized_pnl=_f(d.get("realizedPnl") or d.get("realized_pnl")),
        unrealized_pnl=_f(d.get("unrealizedPnl") or d.get("unrealized_pnl")),
        entry_cost_usdc=_f(d.get("entryCostUsdc") or d.get("entry_cost_usdc")),
        total_cost_usdc=_f(d.get("totalCostUsdc") or d.get("total_cost_usdc")),
        entry_fees_usdc=_f(d.get("entryFeesUsdc") or d.get("entry_fees_usdc")),
        avg_price=_f(d.get("avgPrice") or d.get("avg_price")),
        current_size=_f(d.get("currentSize") or d.get("current_size")),
        total_size=_f(d.get("totalSize") or d.get("total_size")),
        mergeable=_b(d.get("mergeable", False)),
        raw=d,
    )


class V2Adapter:
    def __init__(self, base_url: str = BASE_URL, session: aiohttp.ClientSession | None = None):
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "V2Adapter":
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    async def _fetch_page(self, url: str, params: dict) -> dict:
        from src.utils.polymarket_rate_limit import respect_retry_after
        assert self._session, "Use V2Adapter as async context manager"
        async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            await respect_retry_after(resp)
            resp.raise_for_status()
            return await resp.json()

    async def fetch_positions(
        self,
        address: str,
        status: Literal["OPEN", "REDEEMABLE", "CLOSED"] = "OPEN",
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        params: dict = {"proxyWallet": address, "status": status}
        rows: list[PositionRow] = []
        while True:
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
            cursor = envelope.get("nextCursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return rows

    async def fetch_positions_by_conditions(
        self,
        address: str,
        condition_ids: list[str],
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        rows: list[PositionRow] = []
        chunks = [condition_ids[i:i+_BATCH] for i in range(0, len(condition_ids), _BATCH)]
        for chunk in chunks:
            params: dict = {"proxyWallet": address, "conditionIds": ",".join(chunk)}
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
        return rows
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/pnl/test_v2_adapter.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/pnl/v2_adapter.py tests/pnl/test_v2_adapter.py
git commit -m "feat(pnl): add v2_adapter — envelope/cursor normalization, PositionRow dataclass"
```

---

### Task 0-B: Extend `src/pnl/rules.py` to snake_case

**Files:**
- Modify: `src/pnl/rules.py`
- Test: `tests/pnl/test_rules_snake_case.py`

**Context:** `rules.py` reads only camelCase keys. v2 rows are snake_case. Every v2 row silently parses as cost = 0 — a production silent-zero bug.

- [ ] **Step 1: Write failing tests**

```python
# tests/pnl/test_rules_snake_case.py
from src.pnl.rules import is_synthetic_mint, cost_basis, open_contribution, CostRule

def test_is_synthetic_mint_snake():
    assert is_synthetic_mint({"avg_price": 0.50, "total_sold": 0.0}) is True

def test_is_synthetic_mint_camel_still_works():
    assert is_synthetic_mint({"avgPrice": 0.50, "totalSold": 0.0}) is True

def test_cost_basis_snake_cash_spent():
    row = {"avg_price": 0.65, "total_bought": 100.0, "total_sold": 0.0, "initial_value": 70.0}
    cost, rule = cost_basis(row)
    assert rule == CostRule.CASH_SPENT
    assert abs(cost - 65.0) < 0.01

def test_open_contribution_snake():
    row = {
        "avg_price": 0.65, "total_bought": 100.0, "total_sold": 0.0,
        "initial_value": 70.0, "realized_pnl": 0.0, "current_value": 80.0,
    }
    assert abs(open_contribution(row) - 15.0) < 0.01
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/pnl/test_rules_snake_case.py -v
```

- [ ] **Step 3: Add `_get` helper + update all field reads in `src/pnl/rules.py`**

```python
# Add after imports:
def _get(row: dict, camel: str, snake: str):
    """Try snake_case (v2) first, fall back to camelCase (v1/legacy)."""
    return row.get(snake) if snake in row else row.get(camel)

# Update is_synthetic_mint:
def is_synthetic_mint(row: dict) -> bool:
    avg_price = parse_num(_get(row, "avgPrice", "avg_price"))
    if not (SYNTHETIC_MINT_LOW <= avg_price <= SYNTHETIC_MINT_HIGH):
        return False
    return parse_num(_get(row, "totalSold", "total_sold")) == 0.0

# Update cost_basis:
def cost_basis(row: dict) -> tuple[float, CostRule]:
    total_bought  = parse_num(_get(row, "totalBought",   "total_bought"))
    avg_price     = parse_num(_get(row, "avgPrice",      "avg_price"))
    initial_value = parse_num(_get(row, "initialValue",  "initial_value"))
    if total_bought <= ZERO_BOUGHT_EPSILON:
        return 0.0, CostRule.ZERO_BOUGHT
    cost = total_bought * avg_price
    if initial_value > 0:
        cost = min(cost, initial_value)
    if is_synthetic_mint(row):
        return cost, CostRule.SYNTHETIC_MINT
    return cost, CostRule.CASH_SPENT

# Update closed_contribution and open_contribution similarly.
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/pnl/test_rules_snake_case.py tests/pnl/ -v
```

- [ ] **Step 5: Commit**

```bash
git add src/pnl/rules.py tests/pnl/test_rules_snake_case.py
git commit -m "fix(pnl): rules.py — accept snake_case v2 fields, camelCase fallback preserved"
```

---

### Task 0-C: Alembic migration — `event_id` + cost/provenance/residual columns

**Files:**
- Create: `alembic/versions/<hash>_add_v2_cost_and_provenance_columns.py`

**Columns to add (all nullable, additive only):**

| Table | Column | Type |
|---|---|---|
| `markets_v2` | `event_id` | TEXT |
| `wallet_positions_v2` | `event_id`, `entry_cost_usdc`, `total_cost_usdc`, `entry_fees_usdc`, `source_total_pnl`, `outcome_index` (SMALLINT), `mergeable` (BOOLEAN), `cost_basis_confidence` | mixed |
| `wallet_closed_positions_v2` | same minus `outcome_index` and `mergeable` | mixed |
| `wallet_metrics_v2` | `residual`, `residual_explained_rewards`, `residual_explained_rebates`, `residual_explained_yield`, `unexplained_residual`, `position_pnl` | NUMERIC |

New tables: `position_quarantine`, `wallet_v2_sweep_watermarks`.

- [ ] **Step 1: Generate stub**

```bash
alembic revision --autogenerate -m "add_v2_cost_and_provenance_columns"
```

- [ ] **Step 2: Write the upgrade/downgrade body**

```python
def upgrade() -> None:
    op.add_column("markets_v2", sa.Column("event_id", sa.Text(), nullable=True))
    op.create_index("ix_markets_v2_event_id", "markets_v2", ["event_id"])

    for col, typ in [
        ("event_id", sa.Text()), ("entry_cost_usdc", sa.Numeric()),
        ("total_cost_usdc", sa.Numeric()), ("entry_fees_usdc", sa.Numeric()),
        ("source_total_pnl", sa.Numeric()), ("outcome_index", sa.SmallInteger()),
        ("mergeable", sa.Boolean()), ("cost_basis_confidence", sa.Text()),
    ]:
        op.add_column("wallet_positions_v2", sa.Column(col, typ, nullable=True))
    op.create_index("ix_wp_v2_event_id", "wallet_positions_v2", ["event_id"])

    for col, typ in [
        ("event_id", sa.Text()), ("entry_cost_usdc", sa.Numeric()),
        ("total_cost_usdc", sa.Numeric()), ("entry_fees_usdc", sa.Numeric()),
        ("source_total_pnl", sa.Numeric()), ("cost_basis_confidence", sa.Text()),
    ]:
        op.add_column("wallet_closed_positions_v2", sa.Column(col, typ, nullable=True))

    for col in ["residual","residual_explained_rewards","residual_explained_rebates",
                "residual_explained_yield","unexplained_residual","position_pnl"]:
        op.add_column("wallet_metrics_v2", sa.Column(col, sa.Numeric(), nullable=True))

    op.create_table("position_quarantine",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("condition_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("raw_row", sa.JSON()),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pq_address", "position_quarantine", ["address"])

    op.create_table("wallet_v2_sweep_watermarks",
        sa.Column("address", sa.Text(), primary_key=True),
        sa.Column("last_swept_at", sa.DateTime(timezone=True)),
        sa.Column("rows_ok", sa.Integer(), server_default="0"),
        sa.Column("rows_quarantined", sa.Integer(), server_default="0"),
    )
```

- [ ] **Step 3: Apply and verify**

```bash
alembic upgrade head
psql $DATABASE_URL -c "\d wallet_positions_v2" | grep entry_cost
psql $DATABASE_URL -c "\d position_quarantine"
alembic downgrade -1
alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat(db): add v2 cost columns, residual columns, position_quarantine, sweep_watermarks"
```

---

### Task 0-D: Honor `Retry-After` in rate limiter

**Files:**
- Modify: `src/utils/polymarket_rate_limit.py`
- Test: `tests/utils/test_rate_limit_retry_after.py`

- [ ] **Step 1: Write failing test**

```python
# tests/utils/test_rate_limit_retry_after.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.utils.polymarket_rate_limit import respect_retry_after

@pytest.mark.asyncio
async def test_sleeps_on_retry_after_header():
    response = MagicMock()
    response.status = 429
    response.headers = {"Retry-After": "2"}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(response)
    mock_sleep.assert_called_once_with(2.0)

@pytest.mark.asyncio
async def test_no_sleep_on_200():
    response = MagicMock()
    response.status = 200
    response.headers = {}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(response)
    mock_sleep.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/utils/test_rate_limit_retry_after.py -v
```

- [ ] **Step 3: Add `respect_retry_after` to `src/utils/polymarket_rate_limit.py`**

```python
async def respect_retry_after(response) -> None:
    """Sleep for the duration specified in a 429 Retry-After header."""
    if getattr(response, "status", None) != 429:
        return
    header = (response.headers or {}).get("Retry-After", "")
    try:
        wait = float(header)
        if wait > 0:
            await asyncio.sleep(wait)
    except (TypeError, ValueError):
        pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/utils/test_rate_limit_retry_after.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/utils/polymarket_rate_limit.py tests/utils/test_rate_limit_retry_after.py
git commit -m "fix(rate-limit): honor Retry-After header on 429 responses"
```

---

### Task 0-E: Fix REDEEM aggregation — sum by `transactionHash`

**Files:**
- Modify: `src/workers/wallet_trade_history.py`
- Test: `tests/workers/test_redeem_aggregation.py`

**Context:** Since Aug 10, Polymarket emits two rows per redemption tx — one with real `usdcSize` and one with `usdcSize = 0`. Fix: group by `transactionHash` and sum.

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_redeem_aggregation.py
from src.workers.wallet_trade_history import aggregate_redeem_events

def test_two_row_redeem_sums_to_single_row():
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00"},
    ]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 50.0

def test_single_row_unchanged():
    events = [{"type": "REDEEM", "transactionHash": "0xbbb", "usdcSize": "100.00"}]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 100.0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/workers/test_redeem_aggregation.py -v
```

- [ ] **Step 3: Add `aggregate_redeem_events` to `src/workers/wallet_trade_history.py`**

```python
def aggregate_redeem_events(events: list[dict]) -> list[dict]:
    """Collapse multi-row redemptions sharing a transactionHash by summing usdcSize."""
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for ev in events:
        tx = str(ev.get("transactionHash") or "")
        if tx not in grouped:
            grouped[tx] = dict(ev)
            order.append(tx)
        else:
            try:
                grouped[tx]["usdcSize"] = str(
                    float(grouped[tx].get("usdcSize") or 0)
                    + float(ev.get("usdcSize") or 0)
                )
            except (TypeError, ValueError):
                pass
    return [grouped[tx] for tx in order]
```

Then in the `REDEEM`/`REDEMPTION` branch at line ~122, wrap the event list through `aggregate_redeem_events` before processing.

- [ ] **Step 4: Run tests**

```bash
pytest tests/workers/test_redeem_aggregation.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/workers/wallet_trade_history.py tests/workers/test_redeem_aggregation.py
git commit -m "fix(redeem): aggregate multi-row redemptions by transactionHash, sum usdcSize"
```

---

### Phase 0 Exit Gate

- [ ] **Round-trip smoke test for wallet `esennt`**

```bash
python -c "
import asyncio
from src.pnl.v2_adapter import V2Adapter

async def check():
    async with V2Adapter() as a:
        rows  = await a.fetch_positions('ESENNT_PROXY_ADDR', status='OPEN')
        rows += await a.fetch_positions('ESENNT_PROXY_ADDR', status='CLOSED')
        total = sum(r.source_total_pnl for r in rows)
        print(f'position_pnl = {total:.2f}')

asyncio.run(check())
"
```
Expected: `position_pnl = 1754036.82`

---

## Phase 1 — Row Ledger with Hard Identity Checks

> Exit gate: for a 20-wallet cohort, `Σ total_pnl (OPEN + CLOSED)` matches v2 exactly.

---

### Task 1-A: Implement invariants + quarantine logic

**Files:**
- Create: `src/pnl/invariants.py`
- Test: `tests/pnl/test_invariants.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/pnl/test_invariants.py
from src.pnl.invariants import check_row_invariants, InvariantFailure

VALID = {
    "total_cost_usdc": 808.0, "entry_cost_usdc": 800.0, "entry_fees_usdc": 8.0,
    "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 60.0,
    "avg_price": 0.80, "total_size": 1000.0, "current_size": 500.0,
}

def test_valid_row_passes():
    assert check_row_invariants(VALID) == []

def test_cost_mismatch_flagged():
    bad = {**VALID, "entry_fees_usdc": 9.0}
    assert any(f.rule == "cost_decomposition" for f in check_row_invariants(bad))

def test_pnl_mismatch_flagged():
    bad = {**VALID, "unrealized_pnl": 70.0}
    assert any(f.rule == "pnl_decomposition" for f in check_row_invariants(bad))

def test_size_sanity_flagged():
    bad = {**VALID, "current_size": 1500.0}
    assert any(f.rule == "size_sanity" for f in check_row_invariants(bad))
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/pnl/test_invariants.py -v
```

- [ ] **Step 3: Implement `src/pnl/invariants.py`**

```python
"""Hard identity checks for v2 position rows. Failing rows are quarantined."""
from __future__ import annotations
from dataclasses import dataclass

_TOL = 0.01  # 1-cent tolerance


@dataclass
class InvariantFailure:
    rule: str
    expected: str
    actual: str


def _f(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def check_row_invariants(row: dict) -> list[InvariantFailure]:
    failures: list[InvariantFailure] = []

    tc = _f(row.get("total_cost_usdc"))
    ec = _f(row.get("entry_cost_usdc"))
    ef = _f(row.get("entry_fees_usdc"))
    if tc > 0 and abs(tc - (ec + ef)) > _TOL:
        failures.append(InvariantFailure("cost_decomposition", f"total={tc}", f"net+fees={ec+ef}"))

    tp = _f(row.get("source_total_pnl"))
    rp = _f(row.get("realized_pnl"))
    up = _f(row.get("unrealized_pnl"))
    if tp != 0.0 and abs(tp - (rp + up)) > _TOL:
        failures.append(InvariantFailure("pnl_decomposition", f"total={tp}", f"realized+unrealized={rp+up}"))

    cs = _f(row.get("current_size"))
    ts = _f(row.get("total_size"))
    if ts > 0 and cs > ts + _TOL:
        failures.append(InvariantFailure("size_sanity", f"current<={ts}", f"current={cs}"))

    return failures


def compute_cost_basis_confidence(row: dict) -> str:
    """Return 'high' or 'low'. Low when any shares have no acquisition price."""
    if _f(row.get("transfer_in_size")) > 0 or _f(row.get("unattributed_size")) > 0:
        return "low"
    return "high"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/pnl/test_invariants.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/pnl/invariants.py tests/pnl/test_invariants.py
git commit -m "feat(pnl): invariants.py — hard identity checks and cost_basis_confidence"
```

---

### Task 1-B: Wire invariants into positions ingest

**Files:**
- Modify: `src/workers/positions_open_backfill.py`
- Modify: `src/workers/positions_closed_backfill.py`
- Test: `tests/workers/test_positions_ingest_quarantine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_positions_ingest_quarantine.py
import pytest
from unittest.mock import AsyncMock
from src.workers.positions_open_backfill import upsert_position_with_quarantine

@pytest.mark.asyncio
async def test_bad_row_goes_to_quarantine():
    conn = AsyncMock()
    bad_row = {
        "address": "0xabc", "condition_id": "0x1", "outcome": "YES", "status": "OPEN",
        "total_cost_usdc": 808.0, "entry_cost_usdc": 800.0, "entry_fees_usdc": 9.0,  # mismatch
        "source_total_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
        "avg_price": 0.80, "total_size": 1000.0, "current_size": 500.0,
    }
    result = await upsert_position_with_quarantine(conn, bad_row)
    assert result == "quarantined"
    call_sql = conn.execute.call_args[0][0]
    assert "position_quarantine" in call_sql
```

- [ ] **Step 2: Add `upsert_position_with_quarantine` to `positions_open_backfill.py`**

```python
import json
from src.pnl.invariants import check_row_invariants

async def upsert_position_with_quarantine(conn, row: dict) -> str:
    failures = check_row_invariants(row)
    if failures:
        reasons = "; ".join(f"{f.rule}: expected {f.expected}, got {f.actual}" for f in failures)
        await conn.execute(
            """INSERT INTO position_quarantine
               (address, condition_id, outcome, status, failure_reason, raw_row)
               VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING""",
            row.get("address"), row.get("condition_id"), row.get("outcome"),
            row.get("status"), reasons, json.dumps(row),
        )
        return "quarantined"
    # ... existing upsert logic ...
    return "ok"
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/workers/test_positions_ingest_quarantine.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/workers/positions_open_backfill.py src/workers/positions_closed_backfill.py tests/workers/test_positions_ingest_quarantine.py
git commit -m "feat(ingest): quarantine rows failing invariant checks; never repair silently"
```

---

### Task 1-C: Fix `remaining_cost` + demote legacy repair rules

**Files:**
- Modify: `src/pnl/rules.py`
- Modify: `src/workers/positions_open_backfill.py`
- Test: `tests/pnl/test_remaining_cost.py`

- [ ] **Step 1: Write failing test**

```python
# tests/pnl/test_remaining_cost.py
from src.pnl.rules import remaining_cost

def test_remaining_cost_uses_current_size():
    assert remaining_cost({"current_size": 500.0, "avg_price": 0.80}) == 400.0

def test_remaining_cost_ignores_initial_value():
    # Old formula: min(900, 800) = 800. New: 500 * 0.80 = 400
    row = {"current_size": 500.0, "avg_price": 0.80, "total_bought": 1000.0, "initial_value": 900.0}
    assert remaining_cost(row) == 400.0
```

- [ ] **Step 2: Add `remaining_cost` to `src/pnl/rules.py`**

```python
def remaining_cost(row: dict) -> float:
    """Replaces min(initialValue, totalBought*avgPrice). current_size * avg_price is exact."""
    current_size = parse_num(_get(row, "currentSize", "current_size")) or 0.0
    avg_price    = parse_num(_get(row, "avgPrice",    "avg_price"))    or 0.0
    return current_size * avg_price
```

- [ ] **Step 3: Add legacy repair gate to `positions_open_backfill.py`**

```python
from datetime import datetime, timezone

V2_EPOCH = datetime(2026, 9, 7, tzinfo=timezone.utc)

def _should_apply_legacy_repair(fetched_at: datetime | None) -> bool:
    return fetched_at is not None and fetched_at < V2_EPOCH

def _log_repair_fired(rule_name: str, row: dict) -> None:
    import logging
    logging.getLogger("data_quality").warning(
        "Legacy repair rule fired: rule=%s wallet=%s condition=%s",
        rule_name, row.get("address"), row.get("condition_id"),
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/pnl/test_remaining_cost.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/pnl/rules.py src/workers/positions_open_backfill.py tests/pnl/test_remaining_cost.py
git commit -m "fix(pnl): remaining_cost=current_size*avg_price; gate legacy repair on pre-Sept-7 fetched_at"
```

---

### Task 1-D: Purge 3.25 M synthetic opposite legs

**Files:**
- Create: `src/scripts/purge_synthetic_opposite_legs.py`

- [ ] **Step 1: Create script with `--dry-run`**

```python
# src/scripts/purge_synthetic_opposite_legs.py
"""Remove fabricated opposite-leg rows from the old reconcile script."""
import argparse, asyncio, logging, os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
logger = logging.getLogger("purge_synthetic")

FILTER = """
    data_quality_flag IN ('minted_shares', 'synthetic_liquidation_artifact', 'synthetic_mint')
    OR provenance = 'synthetic_artifact'
    OR synthetic_artifact = TRUE
"""

async def run(dry_run: bool) -> None:
    conn = await asyncpg.connect(DB_URL)
    try:
        n_open   = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_positions_v2 WHERE {FILTER}")
        n_closed = await conn.fetchval(f"SELECT COUNT(*) FROM wallet_closed_positions_v2 WHERE {FILTER}")
        logger.info("Synthetic rows — open: %d  closed: %d", n_open, n_closed)
        if dry_run:
            logger.info("DRY RUN — no rows deleted"); return
        await conn.execute(f"DELETE FROM wallet_positions_v2 WHERE {FILTER}")
        await conn.execute(f"DELETE FROM wallet_closed_positions_v2 WHERE {FILTER}")
        logger.info("Purge complete")
    finally:
        await conn.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(p.parse_args().dry_run))
```

- [ ] **Step 2: Dry-run first**

```bash
python -m src.scripts.purge_synthetic_opposite_legs --dry-run
```

- [ ] **Step 3: Execute purge**

```bash
python -m src.scripts.purge_synthetic_opposite_legs
```

- [ ] **Step 4: Commit**

```bash
git add src/scripts/purge_synthetic_opposite_legs.py
git commit -m "fix(data): purge 3.25M fabricated synthetic opposite-leg positions"
```

---

### Task 1-E: Verify `pm_pnl` anchoring is gone

**Files:**
- Verify: `src/workers/compute_core_metrics.py`
- Verify: `src/workers/leaderboard_stats.py`

- [ ] **Step 1: Grep**

```bash
grep -n "pm_pnl" src/workers/compute_core_metrics.py
grep -n "total_pnl.*pm_pnl\|pm_pnl.*total_pnl" src/workers/leaderboard_stats.py
```

- [ ] **Step 2: If found, remove anchoring**

If any line scales or clips `total_pnl` using `pm_pnl`, remove it. `total_pnl` must come purely from the position ledger sum.

- [ ] **Step 3: Commit**

```bash
git add src/workers/compute_core_metrics.py src/workers/leaderboard_stats.py
git commit -m "fix(metrics): remove any remaining pm_pnl anchoring from total_pnl computation"
```

---

### Phase 1 Exit Gate

- [ ] **Cohort regression test**

```bash
python -m src.scripts.regression_check_position_pnl \
  --wallets wallets_cohort_20.txt \
  --expected-wallet esennt \
  --expected-pnl 1754036.82
```
Expected: `✓ esennt: 1,754,036.82 (match)` and all 20 wallets match v2.

---

## Phase 2 — Residual as a First-Class Number

> Exit gate: the ~9k divergence roster is re-classified into four buckets.

---

### Task 2-A: Compute and store `position_pnl` + `residual`

**Files:**
- Modify: `src/workers/compute_core_metrics.py`
- Test: `tests/workers/test_residual_compute.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_residual_compute.py
import pytest
from unittest.mock import AsyncMock
from src.workers.compute_core_metrics import compute_residual_for_wallet

@pytest.mark.asyncio
async def test_residual_is_stored_not_scaled():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[1800000.0, 1810000.0])
    conn.execute = AsyncMock()
    await compute_residual_for_wallet(conn, "0xabc")
    call_sql = conn.execute.call_args[0][0]
    assert "residual" in call_sql
    assert "position_pnl" in call_sql
```

- [ ] **Step 2: Add function to `compute_core_metrics.py`**

```python
async def compute_residual_for_wallet(conn, address: str) -> None:
    """Store position_pnl and residual = pm_pnl - position_pnl. Never scale."""
    position_pnl = await conn.fetchval("""
        SELECT COALESCE(SUM(source_total_pnl), 0) FROM (
            SELECT source_total_pnl FROM wallet_positions_v2 WHERE address = $1
            UNION ALL
            SELECT source_total_pnl FROM wallet_closed_positions_v2 WHERE address = $1
        ) t
    """, address)
    pm_pnl = await conn.fetchval(
        "SELECT pm_pnl FROM wallet_metrics_v2 WHERE address = $1", address
    )
    residual = (float(pm_pnl) - float(position_pnl)) if pm_pnl is not None else None
    await conn.execute("""
        UPDATE wallet_metrics_v2
        SET position_pnl = $2, residual = $3 WHERE address = $1
    """, address, position_pnl, residual)
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/workers/test_residual_compute.py -v
git add src/workers/compute_core_metrics.py tests/workers/test_residual_compute.py
git commit -m "feat(metrics): compute position_pnl and residual=pm_pnl-position_pnl as stored columns"
```

---

### Task 2-B: Re-baseline the escalation trigger

**Files:**
- Modify: `src/workers/activity_backfiller_worker.py` (lines 38–75)
- Test: `tests/workers/test_escalation_trigger.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_escalation_trigger.py
from src.workers.activity_backfiller_worker import _should_escalate

def test_escalates_on_large_unexplained_residual():
    assert _should_escalate(unexplained_residual=15000, phase1_failure=False)

def test_escalates_on_phase1_failure():
    assert _should_escalate(unexplained_residual=0, phase1_failure=True)

def test_no_escalation_small_residual():
    assert not _should_escalate(unexplained_residual=500, phase1_failure=False)
```

- [ ] **Step 2: Add `_should_escalate` and update the SQL WHERE clause**

```python
def _should_escalate(unexplained_residual: float, phase1_failure: bool) -> bool:
    if phase1_failure:
        return True
    return abs(unexplained_residual) >= 10_000
```

Replace the old `WHERE` in `select_candidates`:
```sql
-- OLD
ABS(m.total_pnl - m.pm_pnl) >= 10000 OR (...)

-- NEW
(m.unexplained_residual IS NOT NULL AND ABS(m.unexplained_residual) >= 10000)
OR EXISTS (
    SELECT 1 FROM position_quarantine pq
    WHERE pq.address = m.address AND pq.resolved_at IS NULL
)
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/workers/test_escalation_trigger.py -v
git add src/workers/activity_backfiller_worker.py tests/workers/test_escalation_trigger.py
git commit -m "fix(escalation): trigger on unexplained_residual and Phase-1 failures, not raw pm_pnl delta"
```

---

### Task 2-C: Quarantine Aug 7 / Aug 24 / Aug 31 bug wallets

**Files:**
- Create: `src/scripts/quarantine_aug_bug_wallets.py`

- [ ] **Step 1: Create script**

```python
# src/scripts/quarantine_aug_bug_wallets.py
"""Flag wallets affected by the Aug 7/24/31 Polymarket settlement bug.
Populate AUG_BUG_CONDITIONS when Polymarket provides the correction list.
"""
import asyncio, logging, os
import asyncpg
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
logger = logging.getLogger("aug_bug_quarantine")

AUG_BUG_CONDITIONS: list[str] = []  # populate from Polymarket correction list

async def run() -> None:
    if not AUG_BUG_CONDITIONS:
        logger.warning("AUG_BUG_CONDITIONS empty — awaiting Polymarket correction list")
        return
    conn = await asyncpg.connect(DB_URL)
    try:
        affected = await conn.fetch("""
            SELECT DISTINCT address FROM wallet_positions_v2
            WHERE condition_id = ANY($1::text[])
            UNION
            SELECT DISTINCT address FROM wallet_closed_positions_v2
            WHERE condition_id = ANY($1::text[])
        """, AUG_BUG_CONDITIONS)
        for row in affected:
            await conn.execute("""
                INSERT INTO position_quarantine (address, condition_id, outcome, status, failure_reason)
                SELECT $1, condition_id, outcome, status, 'polymarket_settlement_bug_aug_2026'
                FROM wallet_positions_v2 WHERE address=$1 AND condition_id=ANY($2::text[])
                ON CONFLICT DO NOTHING
            """, row["address"], AUG_BUG_CONDITIONS)
        logger.info("Quarantined %d wallets", len(affected))
    finally:
        await conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
```

- [ ] **Step 2: Commit**

```bash
git add src/scripts/quarantine_aug_bug_wallets.py
git commit -m "feat(quarantine): script for Aug 7/24/31 Polymarket settlement bug wallets"
```

---

## Phase 3 — Provenance Flags at Event Grain

> Exit gate: on known neg-risk conversion wallets, `unattributed_size ≈ 0` and no minted leg flagged as a contradiction.

---

### Task 3-A: Re-grain the activity audit to `event_id`

**Files:**
- Modify: `src/workers/wallet_provenance_audit.py`
- Test: `tests/workers/test_event_grain_audit.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_event_grain_audit.py
from src.workers.wallet_provenance_audit import classify_position_coverage

def test_conversion_on_sibling_question_authorizes_minted_leg():
    positions = [
        {"condition_id": "0xA", "event_id": "evt_1", "total_size": 99999.0},
        {"condition_id": "0xB", "event_id": "evt_1", "total_size": 1392932.0},
    ]
    activity = [{"type": "CONVERSION", "conditionId": "0xA", "event_id": "evt_1"}]
    result = classify_position_coverage(positions, activity)
    assert result["0xB"] == "conversion_authorized"
    assert result["0xA"] == "direct_buy" or result["0xA"] == "conversion_authorized"
```

- [ ] **Step 2: Add `classify_position_coverage` to `wallet_provenance_audit.py`**

```python
def classify_position_coverage(positions: list[dict], activity: list[dict]) -> dict[str, str]:
    """Classify each position at event grain."""
    conversion_events: set[str] = set()
    for ev in activity:
        if ev.get("type") == "CONVERSION":
            eid = ev.get("event_id") or ev.get("eventId")
            if eid:
                conversion_events.add(eid)

    result: dict[str, str] = {}
    for pos in positions:
        cid = pos.get("condition_id") or pos.get("conditionId") or ""
        eid = pos.get("event_id") or pos.get("eventId")
        has_fills = float(pos.get("fills_size") or 0) > 0
        if has_fills:
            result[cid] = "direct_buy"
        elif eid and eid in conversion_events:
            result[cid] = "conversion_authorized"
        else:
            result[cid] = "activity_absent"
    return result
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/workers/test_event_grain_audit.py -v
git add src/workers/wallet_provenance_audit.py tests/workers/test_event_grain_audit.py
git commit -m "fix(audit): re-grain activity audit to event_id; CONVERSION authorizes all sibling minted legs"
```

---

### Task 3-B: Set `cost_basis_confidence` on ingest + exclude from analytics

**Files:**
- Modify: `src/workers/positions_open_backfill.py`
- Modify: `src/workers/compute_core_metrics.py`
- Test: `tests/pnl/test_cost_basis_confidence.py`

- [ ] **Step 1: Write failing test**

```python
# tests/pnl/test_cost_basis_confidence.py
from src.pnl.invariants import compute_cost_basis_confidence

def test_high_confidence():
    assert compute_cost_basis_confidence({"transfer_in_size": 0.0, "unattributed_size": 0.0}) == "high"

def test_low_on_transfer_in():
    assert compute_cost_basis_confidence({"transfer_in_size": 100.0, "unattributed_size": 0.0}) == "low"

def test_low_on_unattributed():
    assert compute_cost_basis_confidence({"transfer_in_size": 0.0, "unattributed_size": 50.0}) == "low"
```

- [ ] **Step 2: Add exclusion to `compute_core_metrics.py` query**

```sql
-- Add to the WHERE clause of the closed-position SELECT:
AND COALESCE(c.cost_basis_confidence, 'high') = 'high'
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/pnl/test_cost_basis_confidence.py -v
git add src/pnl/invariants.py src/workers/positions_open_backfill.py src/workers/compute_core_metrics.py tests/pnl/test_cost_basis_confidence.py
git commit -m "feat(pnl): cost_basis_confidence flag; exclude low-confidence rows from ROI/win-rate"
```

---

## Phase 4 — Backfill Execution (Tiered)

> Exit gate: Tier 1 sweep complete, per-wallet cursor watermarks persisted, no implicit deep crawl.

---

### Task 4-A: Tier 1 — v2 positions sweep worker

**Files:**
- Create: `src/workers/v2_positions_sweep.py`
- Test: `tests/workers/test_v2_positions_sweep.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_v2_positions_sweep.py
import pytest
from unittest.mock import AsyncMock, patch
from src.workers.v2_positions_sweep import sweep_wallet

@pytest.mark.asyncio
async def test_sweep_persists_watermark():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    with patch("src.workers.v2_positions_sweep.V2Adapter") as MockAdapter:
        instance = MockAdapter.return_value.__aenter__.return_value
        instance.fetch_positions = AsyncMock(return_value=[])
        await sweep_wallet(conn, "0xabc")
    calls = [str(c) for c in conn.execute.call_args_list]
    assert any("wallet_v2_sweep_watermarks" in c for c in calls)
```

- [ ] **Step 2: Implement `src/workers/v2_positions_sweep.py`**

```python
"""Tier 1: v2 positions sweep with per-wallet watermark."""
from __future__ import annotations
import asyncio, logging, os
import asyncpg
from dotenv import load_dotenv
from src.pnl.v2_adapter import V2Adapter
from src.workers.positions_open_backfill import upsert_position_with_quarantine

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
logger = logging.getLogger("v2_positions_sweep")


async def sweep_wallet(conn: asyncpg.Connection, address: str) -> dict:
    ok = quarantined = 0
    async with V2Adapter() as adapter:
        for status in ("OPEN", "CLOSED"):
            rows = await adapter.fetch_positions(address, status=status)
            for row in rows:
                d = {
                    "address": address, "status": status,
                    "condition_id": row.condition_id, "event_id": row.event_id,
                    "outcome_index": row.outcome_index,
                    "source_total_pnl": row.source_total_pnl,
                    "realized_pnl": row.realized_pnl,
                    "unrealized_pnl": row.unrealized_pnl,
                    "entry_cost_usdc": row.entry_cost_usdc,
                    "total_cost_usdc": row.total_cost_usdc,
                    "entry_fees_usdc": row.entry_fees_usdc,
                    "avg_price": row.avg_price,
                    "current_size": row.current_size,
                    "total_size": row.total_size,
                    "mergeable": row.mergeable,
                }
                result = await upsert_position_with_quarantine(conn, d)
                if result == "ok":
                    ok += 1
                else:
                    quarantined += 1

    await conn.execute("""
        INSERT INTO wallet_v2_sweep_watermarks (address, last_swept_at, rows_ok, rows_quarantined)
        VALUES ($1, NOW(), $2, $3)
        ON CONFLICT (address) DO UPDATE SET last_swept_at=NOW(), rows_ok=$2, rows_quarantined=$3
    """, address, ok, quarantined)
    return {"ok": ok, "quarantined": quarantined}


async def run_fleet_sweep(concurrency: int = 100, limit: int | None = None) -> None:
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=min(concurrency, 20))
    try:
        async with pool.acquire() as conn:
            q = f"SELECT address FROM wallets_v2 WHERE is_dormant=FALSE ORDER BY last_active_at DESC NULLS LAST"
            if limit:
                q += f" LIMIT {int(limit)}"
            rows = await conn.fetch(q)
        wallets = [r["address"] for r in rows]
        sem = asyncio.Semaphore(concurrency)

        async def _do(addr):
            async with sem:
                async with pool.acquire() as conn:
                    try:
                        await sweep_wallet(conn, addr)
                    except Exception:
                        logger.exception("Sweep failed: %s", addr)

        await asyncio.gather(*(_do(a) for a in wallets))
    finally:
        await pool.close()
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/workers/test_v2_positions_sweep.py -v
git add src/workers/v2_positions_sweep.py tests/workers/test_v2_positions_sweep.py
git commit -m "feat(sweep): Tier 1 v2 positions sweep worker with per-wallet cursor watermark"
```

---

### Task 4-B: Guard deep-history as explicit opt-in

**Files:**
- Modify: `src/workers/v2_positions_sweep.py`

- [ ] **Step 1: Add CLI with `--deep-history` flag**

```python
import argparse

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep-history", action="store_true",
                        help="Fetch pre-2026-09-07 data. EXPLICIT OPT-IN ONLY.")
    parser.add_argument("--wallet", help="Single wallet targeted sweep")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.deep_history:
        logger.warning("DEEP HISTORY MODE — fetching pre-Sept-7 data (explicit opt-in)")
    if args.wallet:
        pool = await asyncpg.create_pool(DB_URL)
        async with pool.acquire() as conn:
            result = await sweep_wallet(conn, args.wallet)
        print(result)
        await pool.close()
    else:
        await run_fleet_sweep(concurrency=args.concurrency, limit=args.limit)

if __name__ == "__main__":
    import asyncio, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add src/workers/v2_positions_sweep.py
git commit -m "feat(sweep): guard deep-history as explicit --deep-history flag; never implicit in scheduled runs"
```

---

## Open Questions for Polymarket (do not block Phases 0–3)

1. Is `avg_price` net (`entry_cost_usdc / total_size`) or gross (`total_cost_usdc / total_size`)?
2. **P2P transfers:** what is `avg_price`/`entry_cost_usdc` on a transferred-in position?
3. **Leaderboard parity:** should `SUM(total_pnl)` equal leaderboard PnL exactly?
4. **Resolved-but-unredeemed:** do `redeemable=true` rows appear under OPEN or CLOSED?
5. Does a `CONVERSION` activity row carry `event_id` and the minted token legs?

Phase 4 depends on answers to 2 and 3. Phases 0–3 do not.

---

## Verification Plan

### Automated Tests

```bash
pytest tests/pnl/ tests/workers/ tests/utils/ -v
```

### Manual Verification per Phase

| Phase | Smoke Test | Expected |
|---|---|---|
| 0 | Round-trip wallet `esennt` through `V2Adapter` | `1,754,036.82` |
| 1 | `regression_check_position_pnl --wallets cohort_20.txt` | All 20 match v2 |
| 2 | `SELECT COUNT(*) FROM position_quarantine` re-classified | ~9k in 4 buckets |
| 3 | Query `unattributed_size` on known conversion wallets | `≈ 0` |
| 4 | `SELECT COUNT(*) FROM wallet_v2_sweep_watermarks` | = active fleet size |
