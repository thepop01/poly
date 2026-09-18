# v2 Data API — Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 confirmed critical bugs in the v2 position pipeline so that a single-wallet sweep actually reads v2, validates rows, persists valid ones, and produces a trustworthy comparison report — without touching any canonical table until the read-only canary passes.

**Architecture:** All fixes are layered: adapter → invariants → upsert → sweep. Phase A must be entirely complete before running the sweep on even one wallet. Phase B must be complete before fleet rollout.

**Tech Stack:** Python 3.11+, asyncpg, pytest-asyncio, aiohttp.

---

## Phase A — Must fix before running any sweep

Tasks A1–A5 are ordered by dependency. Do them sequentially.

---

### Task A1: Fix `v2_adapter._parse_row()` — eliminate `or`-based field parsing

**Files:**
- Modify: `src/pnl/v2_adapter.py` (lines 49–71)
- Test: `tests/pnl/test_v2_adapter.py` (add new cases)

**Problem:** `d.get("totalPnl") or d.get("total_pnl")` drops any legitimate zero value. `_f(None, 0.0)` silently converts missing fields to 0.

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/pnl/test_v2_adapter.py

from src.pnl.v2_adapter import _parse_row, MISSING

def test_zero_pnl_not_silently_dropped():
    """totalPnl=0 must produce source_total_pnl=0, not fall through to total_pnl key."""
    row = {"totalPnl": "0", "total_pnl": "999.99"}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl == 0.0
    assert parsed.source_total_pnl_present is True

def test_missing_pnl_is_explicit_sentinel():
    """A row with no PnL field at all must be distinguishable from a zero."""
    row = {}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl_present is False

def test_outcome_index_zero_preserved():
    """outcomeIndex=0 must not be treated as falsey."""
    row = {"outcomeIndex": 0}
    parsed = _parse_row(row)
    assert parsed.outcome_index == 0

def test_malformed_pnl_marked_invalid():
    """A string like 'N/A' must not silently become 0."""
    row = {"totalPnl": "N/A"}
    parsed = _parse_row(row)
    assert parsed.source_total_pnl_valid is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/pnl/test_v2_adapter.py -v -k "zero_pnl or missing_pnl or outcome_index or malformed"
```
Expected: `AttributeError: 'PositionRow' object has no attribute 'source_total_pnl_present'`

- [ ] **Step 3: Rewrite `src/pnl/v2_adapter.py` — strict sentinel pattern**

Replace the entire file with:

```python
"""Polymarket v2 Data API adapter — strict field parsing, cursor pagination.

Design rules:
- Never use `field_a or field_b` for numeric values: drops legitimate zeros.
- Never default missing/malformed money to 0.0: use MISSING sentinel.
- outcome_index=0 is valid: must not be treated as falsey.
- Every numeric field carries a validity flag for the invariant layer.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import aiohttp

BASE_URL = "https://data-api.polymarket.com"
_BATCH = 20

# Sentinel: distinguishes "field absent" from "field = 0"
MISSING = object()


def _first_present(row: dict, *names: str) -> Any:
    """Return the first key that is present AND non-None. Returns MISSING if none found."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return MISSING


def _parse_decimal(raw: Any) -> tuple[float | None, bool, bool]:
    """Return (value, present, valid).

    present=False: field was absent or None.
    valid=False:   field was present but could not be parsed as a finite number.
    value=None:    when present=False or valid=False.
    """
    if raw is MISSING or raw is None:
        return None, False, False
    try:
        v = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, True, False
    import math
    if not math.isfinite(v):
        return None, True, False
    return v, True, True


def _parse_int(raw: Any) -> int | None:
    """Parse int, returning None for absent/invalid (including preserving 0)."""
    if raw is MISSING or raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() in {"true", "1", "yes"}
    return bool(raw) if raw is not MISSING else False


@dataclass
class PositionRow:
    # Identity
    proxy_wallet: str
    condition_id: str
    event_id: str | None
    status: str                    # OPEN | REDEEMABLE | CLOSED
    outcome_index: int | None      # 0 is valid
    outcome: str | None            # string label e.g. "Yes"
    asset_token_id: str | None     # ERC-1155 token id

    # PnL — each field carries presence + validity flags
    source_total_pnl: float | None
    source_total_pnl_present: bool
    source_total_pnl_valid: bool

    realized_pnl: float | None
    realized_pnl_present: bool
    realized_pnl_valid: bool

    unrealized_pnl: float | None
    unrealized_pnl_present: bool
    unrealized_pnl_valid: bool

    # Cost
    entry_cost_usdc: float | None
    entry_cost_usdc_present: bool

    total_cost_usdc: float | None
    total_cost_usdc_present: bool

    entry_fees_usdc: float | None
    entry_fees_usdc_present: bool

    avg_price: float | None
    avg_price_present: bool

    # Size
    current_size: float | None
    current_size_present: bool

    total_size: float | None
    total_size_present: bool

    # Flags
    redeemable: bool | None
    mergeable: bool

    # Raw payload (for staging/audit)
    raw: dict = field(repr=False)


def _parse_row(d: dict) -> PositionRow:
    """Parse one API dict into a PositionRow with explicit validity metadata."""

    def _pnl(camel: str, snake: str) -> tuple[float | None, bool, bool]:
        return _parse_decimal(_first_present(d, camel, snake))

    def _cost(camel: str, snake: str) -> tuple[float | None, bool]:
        v, present, valid = _parse_decimal(_first_present(d, camel, snake))
        return v if valid else None, present

    # outcome_index: use explicit None-check, not `or`, because 0 is valid
    raw_oi = _first_present(d, "outcomeIndex", "outcome_index")
    outcome_index = _parse_int(raw_oi)

    # asset_token_id: never pass through float (precision loss on 77-digit tokens)
    raw_token = _first_present(d, "assetId", "asset_token_id", "asset")
    asset_token_id = None
    if raw_token is not MISSING and raw_token is not None:
        token_str = str(raw_token).strip()
        if token_str.isdigit() or token_str.startswith("0x"):
            asset_token_id = token_str

    tp, tp_p, tp_v = _pnl("totalPnl", "total_pnl")
    rp, rp_p, rp_v = _pnl("realizedPnl", "realized_pnl")
    up, up_p, up_v = _pnl("unrealizedPnl", "unrealized_pnl")

    ec, ec_p = _cost("entryCostUsdc", "entry_cost_usdc")
    tc, tc_p = _cost("totalCostUsdc", "total_cost_usdc")
    ef, ef_p = _cost("entryFeesUsdc", "entry_fees_usdc")
    ap, ap_p = _cost("avgPrice", "avg_price")
    cs, cs_p = _cost("currentSize", "current_size")
    ts, ts_p = _cost("totalSize", "total_size")

    raw_redeemable = _first_present(d, "redeemable")
    redeemable = _parse_bool(raw_redeemable) if raw_redeemable is not MISSING else None

    return PositionRow(
        proxy_wallet=str(_first_present(d, "proxyWallet", "proxy_wallet") or ""),
        condition_id=str(_first_present(d, "conditionId", "condition_id") or ""),
        event_id=(_first_present(d, "eventId", "event_id") or None),
        status=str(_first_present(d, "status") or "OPEN").upper(),
        outcome_index=outcome_index,
        outcome=str(_first_present(d, "outcome") or "") or None,
        asset_token_id=asset_token_id,
        source_total_pnl=tp, source_total_pnl_present=tp_p, source_total_pnl_valid=tp_v,
        realized_pnl=rp, realized_pnl_present=rp_p, realized_pnl_valid=rp_v,
        unrealized_pnl=up, unrealized_pnl_present=up_p, unrealized_pnl_valid=up_v,
        entry_cost_usdc=ec, entry_cost_usdc_present=ec_p,
        total_cost_usdc=tc, total_cost_usdc_present=tc_p,
        entry_fees_usdc=ef, entry_fees_usdc_present=ef_p,
        avg_price=ap, avg_price_present=ap_p,
        current_size=cs, current_size_present=cs_p,
        total_size=ts, total_size_present=ts_p,
        redeemable=redeemable,
        mergeable=_parse_bool(_first_present(d, "mergeable")),
        raw=d,
    )


class V2Adapter:
    def __init__(self, base_url: str = BASE_URL,
                 session: aiohttp.ClientSession | None = None):
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
        async with self._session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            await respect_retry_after(resp)
            resp.raise_for_status()
            return await resp.json()

    async def _paginate(self, url: str, base_params: dict) -> list[PositionRow]:
        """Cursor-paginate to completion, guarding against infinite loops."""
        rows: list[PositionRow] = []
        params = dict(base_params)
        seen_cursors: set[str] = set()
        while True:
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
            cursor = envelope.get("nextCursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise RuntimeError(f"Cursor loop detected: {cursor}")
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        return rows

    async def fetch_positions(
        self,
        address: str,
        status: Literal["OPEN", "REDEEMABLE", "CLOSED"] = "OPEN",
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        return await self._paginate(url, {"proxyWallet": address, "status": status})

    async def fetch_positions_by_conditions(
        self,
        address: str,
        condition_ids: list[str],
    ) -> list[PositionRow]:
        """Fetch by condition IDs in batches of ≤20, paginating each batch."""
        url = f"{self._base_url}/data-api/v2/positions"
        rows: list[PositionRow] = []
        chunks = [
            condition_ids[i:i + _BATCH]
            for i in range(0, len(condition_ids), _BATCH)
        ]
        for chunk in chunks:
            chunk_rows = await self._paginate(
                url, {"proxyWallet": address, "conditionIds": ",".join(chunk)}
            )
            rows.extend(chunk_rows)
        return rows
```

- [ ] **Step 4: Run all adapter tests**

```bash
pytest tests/pnl/test_v2_adapter.py -v
```
Expected: all green including the new cases.

- [ ] **Step 5: Commit**

```bash
git add src/pnl/v2_adapter.py tests/pnl/test_v2_adapter.py
git commit -m "fix(adapter): strict field parsing — first_present sentinel, validity flags, cursor loop guard"
```

---

### Task A2: Implement `respect_retry_after` in rate limiter

**Files:**
- Modify: `src/utils/polymarket_rate_limit.py`
- Test: `tests/utils/test_rate_limit_retry_after.py`

**Context:** `v2_adapter._fetch_page()` already calls `respect_retry_after(resp)` but the function doesn't exist yet — this causes an `ImportError` on every real API call.

- [ ] **Step 1: Write failing test**

```python
# tests/utils/test_rate_limit_retry_after.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.utils.polymarket_rate_limit import respect_retry_after


@pytest.mark.asyncio
async def test_sleeps_on_retry_after_header():
    resp = MagicMock()
    resp.status = 429
    resp.headers = {"Retry-After": "3"}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(resp)
    mock_sleep.assert_called_once_with(3.0)


@pytest.mark.asyncio
async def test_no_sleep_on_200():
    resp = MagicMock()
    resp.status = 200
    resp.headers = {}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(resp)
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_no_sleep_when_header_absent():
    resp = MagicMock()
    resp.status = 429
    resp.headers = {}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(resp)
    mock_sleep.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/utils/test_rate_limit_retry_after.py -v
```
Expected: `ImportError: cannot import name 'respect_retry_after'`

- [ ] **Step 3: Add `respect_retry_after` to `src/utils/polymarket_rate_limit.py`**

Append after the existing `PostgresRateLimiter` class:

```python
async def respect_retry_after(response) -> None:
    """Honor Retry-After header on 429 responses.

    Polymarket v2 uses this header; ignoring it causes cascading 429s.
    Does nothing for non-429 responses or absent headers.
    """
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
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/utils/polymarket_rate_limit.py tests/utils/test_rate_limit_retry_after.py
git commit -m "fix(rate-limit): implement respect_retry_after — honor 429 Retry-After header"
```

---

### Task A3: Fix invariants — distinguish missing from zero, split hard/soft

**Files:**
- Modify: `src/pnl/invariants.py`
- Modify: `tests/pnl/test_invariants.py`

**Problem 1:** `_f(None) = 0.0` so a row with all missing fields passes every check.
**Problem 2:** Cost decomposition (`entry_cost + fees = total_cost`) is a hard quarantine trigger, but `avg_price` semantics (net vs gross) are still an open question — treating it as hard will quarantine valid rows.

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/pnl/test_invariants.py

from src.pnl.invariants import check_row_invariants, SoftInvariantWarning

def test_all_missing_cost_fields_passes_without_false_failure():
    """A row with no cost fields at all must not trigger cost_decomposition."""
    row = {
        "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 60.0,
        "current_size": 500.0, "total_size": 1000.0,
        # no cost fields at all
    }
    failures, warnings = check_row_invariants(row)
    assert not any(f.rule == "cost_decomposition" for f in failures)

def test_cost_mismatch_is_soft_warning_not_hard_failure():
    """Cost decomposition is soft until avg_price semantics confirmed."""
    row = {
        "total_cost_usdc": 808.0, "entry_cost_usdc": 800.0, "entry_fees_usdc": 9.0,
        "source_total_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
        "current_size": 500.0, "total_size": 1000.0,
    }
    failures, warnings = check_row_invariants(row)
    # Should be a WARNING, not a hard failure that quarantines the row
    assert len(failures) == 0
    assert any(w.rule == "cost_decomposition" for w in warnings)

def test_pnl_decomposition_is_hard_failure():
    """realized + unrealized != total_pnl is always quarantinable."""
    row = {
        "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 70.0,  # 40+70=110≠100
        "current_size": 500.0, "total_size": 1000.0,
    }
    failures, warnings = check_row_invariants(row)
    assert any(f.rule == "pnl_decomposition" for f in failures)

def test_missing_pnl_fields_skip_decomposition_check():
    """Cannot check pnl_decomposition if realized or unrealized is absent."""
    row = {
        "source_total_pnl": 100.0,
        # realized_pnl and unrealized_pnl absent
        "current_size": 500.0, "total_size": 1000.0,
    }
    failures, warnings = check_row_invariants(row)
    assert not any(f.rule == "pnl_decomposition" for f in failures)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/pnl/test_invariants.py -v
```

- [ ] **Step 3: Rewrite `src/pnl/invariants.py`**

```python
"""Hard and soft identity checks for v2 position rows.

Hard failures → quarantine (row is not persisted).
Soft warnings → logged, row is persisted with a warning flag.

Cost decomposition is SOFT until Polymarket confirms whether
avg_price is net or gross of entry_fees_usdc.
"""
from __future__ import annotations
from dataclasses import dataclass

_TOL = 0.01  # 1-cent tolerance for float arithmetic


@dataclass
class InvariantFailure:
    rule: str
    expected: str
    actual: str


@dataclass
class SoftInvariantWarning:
    rule: str
    expected: str
    actual: str


def _present(row: dict, key: str) -> bool:
    return key in row and row[key] is not None


def _f(val) -> float | None:
    """Return float or None (never silently zero for missing)."""
    if val is None:
        return None
    try:
        v = float(val)
        import math
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def check_row_invariants(
    row: dict,
) -> tuple[list[InvariantFailure], list[SoftInvariantWarning]]:
    """Return (hard_failures, soft_warnings).

    hard_failures: non-empty → quarantine the row.
    soft_warnings: non-empty → persist with warning flag.
    """
    failures: list[InvariantFailure] = []
    warnings: list[SoftInvariantWarning] = []

    # ── Hard: PnL decomposition ───────────────────────────────────────────
    # Only check when all three fields are present and parseable.
    tp = _f(row.get("source_total_pnl"))
    rp = _f(row.get("realized_pnl"))
    up = _f(row.get("unrealized_pnl"))
    if tp is not None and rp is not None and up is not None:
        if abs(tp - (rp + up)) > _TOL:
            failures.append(InvariantFailure(
                "pnl_decomposition",
                f"total_pnl={tp:.4f}",
                f"realized+unrealized={rp+up:.4f}",
            ))

    # ── Hard: size sanity ─────────────────────────────────────────────────
    cs = _f(row.get("current_size"))
    ts = _f(row.get("total_size"))
    if cs is not None and cs < 0:
        failures.append(InvariantFailure("negative_current_size", ">=0", f"{cs}"))
    if ts is not None and ts < 0:
        failures.append(InvariantFailure("negative_total_size", ">=0", f"{ts}"))
    if cs is not None and ts is not None and ts > 0 and cs > ts + _TOL:
        failures.append(InvariantFailure(
            "size_sanity", f"current_size<={ts}", f"current_size={cs}"
        ))

    # ── Soft: cost decomposition ──────────────────────────────────────────
    # SOFT until Polymarket confirms whether avg_price is net or gross.
    tc = _f(row.get("total_cost_usdc"))
    ec = _f(row.get("entry_cost_usdc"))
    ef = _f(row.get("entry_fees_usdc"))
    if tc is not None and ec is not None and ef is not None and tc > 0:
        if abs(tc - (ec + ef)) > _TOL:
            warnings.append(SoftInvariantWarning(
                "cost_decomposition",
                f"total={tc:.4f}",
                f"entry+fees={ec+ef:.4f}",
            ))

    return failures, warnings


def compute_cost_basis_confidence(row: dict) -> str:
    """Return 'high' or 'low'. Low when any shares have no acquisition price."""
    def _pos(key: str) -> bool:
        v = _f(row.get(key))
        return v is not None and v > 0
    if _pos("transfer_in_size") or _pos("unattributed_size"):
        return "low"
    return "high"
```

- [ ] **Step 4: Update callers of `check_row_invariants`**

Both `positions_open_backfill.py:225` and `positions_closed_backfill.py:125` call the old single-return signature. Update them:

```python
# OLD:
failures = check_row_invariants(row)
if failures:
    ...

# NEW:
failures, warnings = check_row_invariants(row)
if warnings:
    import logging
    logging.getLogger("data_quality").warning(
        "Soft invariant: wallet=%s condition=%s warnings=%s",
        row.get("address"), row.get("condition_id"),
        [f"{w.rule}:{w.actual}" for w in warnings],
    )
if failures:
    ...
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/pnl/test_invariants.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/pnl/invariants.py tests/pnl/test_invariants.py src/workers/positions_open_backfill.py src/workers/positions_closed_backfill.py
git commit -m "fix(invariants): distinguish missing from zero; split cost_decomposition to soft warning; fix caller signatures"
```

---

### Task A4: Implement the valid-row upsert in `upsert_position_with_quarantine`

**Files:**
- Modify: `src/workers/positions_open_backfill.py` (lines 215–237)
- Modify: `src/workers/positions_closed_backfill.py` (lines 115–137)
- Test: `tests/workers/test_upsert_with_quarantine.py`

**This is the most critical fix.** Currently valid rows are discarded with `return "ok"` and no write.

- [ ] **Step 1: Write failing tests**

```python
# tests/workers/test_upsert_with_quarantine.py
import json
import pytest
from unittest.mock import AsyncMock, call
from src.workers.positions_open_backfill import upsert_position_with_quarantine


VALID_OPEN_ROW = {
    "address": "0xabc", "condition_id": "0x111", "outcome": "Yes",
    "status": "OPEN",
    "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 60.0,
    "entry_cost_usdc": 800.0, "total_cost_usdc": None, "entry_fees_usdc": None,
    "avg_price": 0.80, "current_size": 500.0, "total_size": 1000.0,
    "event_id": "evt_1", "outcome_index": 0, "mergeable": False,
    "asset_token_id": "12345",
}

BAD_ROW = {
    **VALID_OPEN_ROW,
    "source_total_pnl": 100.0, "realized_pnl": 40.0, "unrealized_pnl": 80.0,  # 40+80≠100
}


@pytest.mark.asyncio
async def test_valid_row_is_persisted():
    conn = AsyncMock()
    result = await upsert_position_with_quarantine(conn, VALID_OPEN_ROW)
    assert result == "ok"
    # Must have called conn.execute with a wallet_positions_v2 INSERT
    calls_sql = [str(c) for c in conn.execute.call_args_list]
    assert any("wallet_positions_v2" in sql for sql in calls_sql), \
        f"Expected wallet_positions_v2 upsert, got calls: {calls_sql}"


@pytest.mark.asyncio
async def test_invalid_row_goes_to_quarantine_and_is_not_persisted():
    conn = AsyncMock()
    result = await upsert_position_with_quarantine(conn, BAD_ROW)
    assert result == "quarantined"
    calls_sql = [str(c) for c in conn.execute.call_args_list]
    assert any("position_quarantine" in sql for sql in calls_sql)
    assert not any("wallet_positions_v2" in sql for sql in calls_sql)


@pytest.mark.asyncio
async def test_soft_warning_row_is_persisted_not_quarantined():
    """A row with a soft cost mismatch should persist, not quarantine."""
    row_with_soft_warning = {
        **VALID_OPEN_ROW,
        # cost mismatch (soft): 808 ≠ 800 + 9
        "total_cost_usdc": 808.0, "entry_cost_usdc": 800.0, "entry_fees_usdc": 9.0,
    }
    conn = AsyncMock()
    result = await upsert_position_with_quarantine(conn, row_with_soft_warning)
    assert result == "ok"
    calls_sql = [str(c) for c in conn.execute.call_args_list]
    assert any("wallet_positions_v2" in sql for sql in calls_sql)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/workers/test_upsert_with_quarantine.py -v
```
Expected: `test_valid_row_is_persisted FAILED` — no `wallet_positions_v2` upsert found.

- [ ] **Step 3: Implement the upsert in `positions_open_backfill.py`**

Replace lines 215–237 (the stub) with:

```python
async def upsert_position_with_quarantine(
    conn: asyncpg.Connection, row: dict
) -> str:
    """Validate a v2 position row and upsert it.

    Hard failures → quarantine (row not written to canonical table).
    Soft warnings → logged, row written with warning flag.
    Returns 'quarantined' or 'ok'.
    """
    import json as _json
    from src.pnl.invariants import check_row_invariants
    import logging

    failures, warnings = check_row_invariants(row)

    if warnings:
        logging.getLogger("data_quality").warning(
            "Soft invariant: wallet=%s condition=%s %s",
            row.get("address"), row.get("condition_id"),
            [f"{w.rule}:{w.actual}" for w in warnings],
        )

    if failures:
        reasons = "; ".join(
            f"{f.rule}: expected {f.expected}, got {f.actual}"
            for f in failures
        )
        await conn.execute(
            """INSERT INTO position_quarantine
               (address, condition_id, outcome, status, failure_reason, raw_row)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT DO NOTHING""",
            row.get("address"), row.get("condition_id"),
            row.get("outcome"), row.get("status"),
            reasons, _json.dumps(row),
        )
        return "quarantined"

    # ── Persist the valid row ─────────────────────────────────────────────
    await conn.execute(
        """INSERT INTO wallet_positions_v2 (
               address, condition_id, outcome, size, avg_price,
               current_value, unrealized_pnl, is_parlay, is_resolved,
               asset_token_id, event_id, entry_cost_usdc, total_cost_usdc,
               entry_fees_usdc, source_total_pnl, outcome_index, mergeable,
               cost_basis_confidence, entry_at, computed_at
           ) VALUES (
               $1, $2, $3, $4, $5,
               $6, $7, FALSE, FALSE,
               $8, $9, $10, $11,
               $12, $13, $14, $15,
               'high', NOW(), NOW()
           )
           ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
               size             = EXCLUDED.size,
               avg_price        = EXCLUDED.avg_price,
               current_value    = EXCLUDED.current_value,
               unrealized_pnl   = EXCLUDED.unrealized_pnl,
               asset_token_id   = COALESCE(EXCLUDED.asset_token_id,
                                           wallet_positions_v2.asset_token_id),
               event_id         = COALESCE(EXCLUDED.event_id,
                                           wallet_positions_v2.event_id),
               entry_cost_usdc  = EXCLUDED.entry_cost_usdc,
               total_cost_usdc  = EXCLUDED.total_cost_usdc,
               entry_fees_usdc  = EXCLUDED.entry_fees_usdc,
               source_total_pnl = EXCLUDED.source_total_pnl,
               outcome_index    = EXCLUDED.outcome_index,
               mergeable        = EXCLUDED.mergeable,
               computed_at      = NOW()
        """,
        row.get("address"),
        row.get("condition_id"),
        row.get("outcome") or row.get("outcome_index"),   # fallback if label absent
        row.get("current_size"),
        row.get("avg_price"),
        None,                   # current_value — not provided by v2 positions endpoint
        row.get("unrealized_pnl"),
        row.get("asset_token_id"),
        row.get("event_id"),
        row.get("entry_cost_usdc"),
        row.get("total_cost_usdc"),
        row.get("entry_fees_usdc"),
        row.get("source_total_pnl"),
        row.get("outcome_index"),
        row.get("mergeable", False),
    )
    return "ok"
```

- [ ] **Step 4: Apply the same fix to `positions_closed_backfill.py:115`**

The closed version should upsert into `wallet_closed_positions_v2`. Mirror the pattern — quarantine on hard failures, upsert on pass. Use the existing `upsert_closed_positions_v2` helper for the actual SQL (it already exists at line 140 and has the right schema).

```python
async def upsert_position_with_quarantine(
    conn: asyncpg.Connection, row: dict
) -> str:
    import json as _json
    import logging
    from src.pnl.invariants import check_row_invariants

    failures, warnings = check_row_invariants(row)

    if warnings:
        logging.getLogger("data_quality").warning(
            "Soft invariant: wallet=%s condition=%s %s",
            row.get("address"), row.get("condition_id"),
            [f"{w.rule}:{w.actual}" for w in warnings],
        )

    if failures:
        reasons = "; ".join(
            f"{f.rule}: expected {f.expected}, got {f.actual}"
            for f in failures
        )
        await conn.execute(
            """INSERT INTO position_quarantine
               (address, condition_id, outcome, status, failure_reason, raw_row)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT DO NOTHING""",
            row.get("address"), row.get("condition_id"),
            row.get("outcome"), row.get("status"),
            reasons, _json.dumps(row),
        )
        return "quarantined"

    # Reuse existing closed upsert helper
    await upsert_closed_positions_v2(conn, row.get("address", ""), [row])
    return "ok"
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/workers/test_upsert_with_quarantine.py -v
pytest tests/pnl/ tests/workers/ -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/workers/positions_open_backfill.py src/workers/positions_closed_backfill.py tests/workers/test_upsert_with_quarantine.py
git commit -m "fix(upsert): implement actual valid-row persistence in upsert_position_with_quarantine"
```

---

### Task A5: Add `--read-only` mode + REDEEMABLE + overlap check to the sweep

**Files:**
- Modify: `src/workers/v2_positions_sweep.py`
- Test: `tests/workers/test_v2_sweep_read_only.py`

**Problems fixed:**
1. REDEEMABLE status is missing from the sweep
2. No overlap detection (same position in multiple statuses = double-count)
3. No way to run the sweep safely without writing to the DB

- [ ] **Step 1: Write failing tests**

```python
# tests/workers/test_v2_sweep_read_only.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.workers.v2_positions_sweep import sweep_wallet_read_only, detect_status_overlap
from src.pnl.v2_adapter import PositionRow

def _make_row(**kwargs) -> PositionRow:
    defaults = dict(
        proxy_wallet="0xabc", condition_id="0x1", event_id=None, status="OPEN",
        outcome_index=0, outcome="Yes", asset_token_id="123",
        source_total_pnl=100.0, source_total_pnl_present=True, source_total_pnl_valid=True,
        realized_pnl=0.0, realized_pnl_present=True, realized_pnl_valid=True,
        unrealized_pnl=100.0, unrealized_pnl_present=True, unrealized_pnl_valid=True,
        entry_cost_usdc=80.0, entry_cost_usdc_present=True,
        total_cost_usdc=None, total_cost_usdc_present=False,
        entry_fees_usdc=None, entry_fees_usdc_present=False,
        avg_price=0.80, avg_price_present=True,
        current_size=100.0, current_size_present=True,
        total_size=100.0, total_size_present=True,
        redeemable=False, mergeable=False, raw={},
    )
    defaults.update(kwargs)
    return PositionRow(**defaults)


def test_detect_overlap_same_row_in_two_statuses():
    open_rows = [_make_row(status="OPEN", condition_id="0xA", asset_token_id="111")]
    redeemable_rows = [_make_row(status="REDEEMABLE", condition_id="0xA", asset_token_id="111")]
    overlaps = detect_status_overlap(open_rows, redeemable_rows, [])
    assert len(overlaps) == 1
    assert overlaps[0]["condition_id"] == "0xA"


def test_detect_no_overlap_for_different_conditions():
    open_rows = [_make_row(status="OPEN", condition_id="0xA")]
    closed_rows = [_make_row(status="CLOSED", condition_id="0xB")]
    assert detect_status_overlap(open_rows, [], closed_rows) == []


@pytest.mark.asyncio
async def test_read_only_produces_report_without_db_writes():
    with patch("src.workers.v2_positions_sweep.V2Adapter") as MockAdapter:
        instance = MockAdapter.return_value.__aenter__.return_value
        instance.fetch_positions = AsyncMock(return_value=[
            _make_row(status="OPEN", source_total_pnl=500.0),
        ])
        report = await sweep_wallet_read_only("0xabc")

    assert report["address"] == "0xabc"
    assert report["open_rows"] == 1
    assert report["position_pnl"] == 500.0
    assert report["complete"] is True
    # No DB connection used
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/workers/test_v2_sweep_read_only.py -v
```

- [ ] **Step 3: Rewrite `src/workers/v2_positions_sweep.py`**

```python
"""Tier 1: v2 positions sweep worker.

Modes:
  --read-only   Print a report; do not write to the database.
  --shadow      Fetch + stage raw; do not update canonical tables.
  (default)     Full upsert with watermark update.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any

import asyncpg
from dotenv import load_dotenv

from src.pnl.v2_adapter import V2Adapter, PositionRow
from src.workers.positions_open_backfill import upsert_position_with_quarantine

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
logger = logging.getLogger("v2_positions_sweep")

ALL_STATUSES = ("OPEN", "REDEEMABLE", "CLOSED")


def detect_status_overlap(
    open_rows: list[PositionRow],
    redeemable_rows: list[PositionRow],
    closed_rows: list[PositionRow],
) -> list[dict[str, Any]]:
    """Return rows appearing in more than one status bucket by (condition_id, asset_token_id)."""
    def key(r: PositionRow) -> tuple:
        return (r.condition_id, r.asset_token_id or r.outcome_index)

    seen: dict[tuple, str] = {}
    overlaps: list[dict] = []
    for status, rows in [("OPEN", open_rows), ("REDEEMABLE", redeemable_rows),
                          ("CLOSED", closed_rows)]:
        for row in rows:
            k = key(row)
            if k in seen:
                overlaps.append({
                    "condition_id": row.condition_id,
                    "asset_token_id": row.asset_token_id,
                    "status_a": seen[k],
                    "status_b": status,
                })
            else:
                seen[k] = status
    return overlaps


async def sweep_wallet_read_only(address: str) -> dict[str, Any]:
    """Fetch v2 positions for one wallet, return a report dict. No DB writes."""
    async with V2Adapter() as adapter:
        open_rows = await adapter.fetch_positions(address, status="OPEN")
        redeemable_rows = await adapter.fetch_positions(address, status="REDEEMABLE")
        closed_rows = await adapter.fetch_positions(address, status="CLOSED")

    overlaps = detect_status_overlap(open_rows, redeemable_rows, closed_rows)

    invalid_rows = [
        r for r in open_rows + redeemable_rows + closed_rows
        if not r.source_total_pnl_valid
    ]

    # Canonical sum: OPEN + REDEEMABLE + CLOSED, deduplicating overlaps
    # Precedence for overlap: CLOSED > REDEEMABLE > OPEN
    seen_keys: set = set()
    position_pnl = 0.0
    for status, rows in [("CLOSED", closed_rows), ("REDEEMABLE", redeemable_rows),
                          ("OPEN", open_rows)]:
        for row in rows:
            k = (row.condition_id, row.asset_token_id or row.outcome_index)
            if k not in seen_keys:
                seen_keys.add(k)
                if row.source_total_pnl_valid and row.source_total_pnl is not None:
                    position_pnl += row.source_total_pnl

    return {
        "address": address,
        "open_rows": len(open_rows),
        "redeemable_rows": len(redeemable_rows),
        "closed_rows": len(closed_rows),
        "total_rows": len(open_rows) + len(redeemable_rows) + len(closed_rows),
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "invalid_rows": len(invalid_rows),
        "position_pnl": round(position_pnl, 2),
        "complete": len(invalid_rows) == 0 and len(overlaps) == 0,
    }


async def sweep_wallet(
    conn: asyncpg.Connection,
    address: str,
    read_only: bool = False,
) -> dict[str, Any]:
    """Full sweep: read-only report or persistent upsert + watermark."""
    if read_only:
        return await sweep_wallet_read_only(address)

    report = await sweep_wallet_read_only(address)
    ok = quarantined = 0

    async with V2Adapter() as adapter:
        for status in ALL_STATUSES:
            rows = await adapter.fetch_positions(address, status=status)
            for row in rows:
                d = {
                    "address": address, "status": status,
                    "condition_id": row.condition_id,
                    "outcome": row.outcome,
                    "outcome_index": row.outcome_index,
                    "asset_token_id": row.asset_token_id,
                    "event_id": row.event_id,
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
        INSERT INTO wallet_v2_sweep_watermarks
            (address, last_swept_at, rows_ok, rows_quarantined)
        VALUES ($1, NOW(), $2, $3)
        ON CONFLICT (address) DO UPDATE SET
            last_swept_at = NOW(),
            rows_ok = $2,
            rows_quarantined = $3
    """, address, ok, quarantined)

    return {**report, "rows_ok": ok, "rows_quarantined": quarantined}


async def run_fleet_sweep(
    concurrency: int = 10,   # start low, benchmark before increasing
    limit: int | None = None,
) -> None:
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=min(concurrency, 20))
    try:
        async with pool.acquire() as conn:
            q = ("SELECT address FROM wallets_v2 WHERE is_dormant=FALSE "
                 "ORDER BY last_active_at DESC NULLS LAST")
            if limit:
                q += f" LIMIT {int(limit)}"
            rows = await conn.fetch(q)
        wallets = [r["address"] for r in rows]
        sem = asyncio.Semaphore(concurrency)

        async def _do(addr: str) -> None:
            async with sem:
                async with pool.acquire() as conn:
                    try:
                        result = await sweep_wallet(conn, addr)
                        logger.info("sweep %s ok=%s quarantined=%s pnl=%s",
                                    addr[:12], result.get("rows_ok"),
                                    result.get("rows_quarantined"),
                                    result.get("position_pnl"))
                    except Exception:
                        logger.exception("Sweep failed: %s", addr)

        await asyncio.gather(*(_do(a) for a in wallets))
    finally:
        await pool.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true",
                        help="Report only — no DB writes")
    parser.add_argument("--deep-history", action="store_true",
                        help="Fetch pre-2026-09-07 data. EXPLICIT OPT-IN ONLY.")
    parser.add_argument("--wallet", help="Single wallet address")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if args.deep_history:
        logger.warning("DEEP HISTORY MODE — fetching pre-Sept-7 data")

    if args.wallet:
        if args.read_only:
            report = await sweep_wallet_read_only(args.wallet)
        else:
            pool = await asyncpg.create_pool(DB_URL)
            async with pool.acquire() as conn:
                report = await sweep_wallet(conn, args.wallet)
            await pool.close()
        import json
        print(json.dumps(report, indent=2))
    else:
        await run_fleet_sweep(concurrency=args.concurrency, limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/workers/test_v2_sweep_read_only.py -v
```

- [ ] **Step 5: Run Phase A smoke test (single wallet, read-only)**

```bash
python -m src.workers.v2_positions_sweep --wallet <actual-esennt-proxy-address> --read-only
```
Expected output:
```json
{
  "address": "0x...",
  "open_rows": N,
  "redeemable_rows": N,
  "closed_rows": N,
  "overlap_count": 0,
  "invalid_rows": 0,
  "position_pnl": 1754036.82,
  "complete": true
}
```

- [ ] **Step 6: Commit**

```bash
git add src/workers/v2_positions_sweep.py tests/workers/test_v2_sweep_read_only.py
git commit -m "feat(sweep): add --read-only mode, REDEEMABLE status, overlap detection, status deduplication"
```

---

### Phase A Exit Gate

- [ ] **Run full test suite**

```bash
pytest tests/ -v
```
Expected: all green, no regressions.

- [ ] **Single-wallet read-only smoke test passes for esennt**

```bash
python -m src.workers.v2_positions_sweep \
  --wallet <esennt-proxy-address> \
  --read-only
```
Expected: `position_pnl = 1754036.82`, `complete = true`

---

## Phase B — Fix before fleet rollout

These can be done after Phase A passes, in any order.

---

### Task B1: Fix REDEEM aggregation in `wallet_trade_history.py`

**Files:**
- Modify: `src/workers/wallet_trade_history.py`
- Test: `tests/workers/test_redeem_aggregation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/workers/test_redeem_aggregation.py
from src.workers.wallet_trade_history import aggregate_redeem_events

def test_two_row_redeem_sums_usdc():
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00",
         "conditionId": "0x1", "outcome": "YES"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00",
         "conditionId": "0x1", "outcome": "NO"},
    ]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 50.0

def test_single_row_unchanged():
    events = [{"type": "REDEEM", "transactionHash": "0xbbb", "usdcSize": "100.00"}]
    result = aggregate_redeem_events(events)
    assert len(result) == 1 and float(result[0]["usdcSize"]) == 100.0

def test_raw_rows_also_preserved_separately():
    """Raw per-outcome events are returned alongside the aggregated list."""
    from src.workers.wallet_trade_history import aggregate_redeem_events_with_raw
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00", "outcome": "YES"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00", "outcome": "NO"},
    ]
    aggregated, raw = aggregate_redeem_events_with_raw(events)
    assert len(aggregated) == 1     # for cash reconciliation
    assert len(raw) == 2            # for position provenance
```

- [ ] **Step 2: Implement both functions in `wallet_trade_history.py`**

```python
def aggregate_redeem_events(events: list[dict]) -> list[dict]:
    """Transaction-level cash aggregate: one row per transactionHash, usdcSize summed.
    Use only for account-level cash reconciliation, NOT for position provenance.
    """
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


def aggregate_redeem_events_with_raw(
    events: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Return (aggregated_for_cash, raw_for_provenance).
    Never use the aggregated list for per-outcome position tracking.
    """
    return aggregate_redeem_events(events), list(events)
```

- [ ] **Step 3: Wire into the existing REDEEM branch (~line 122)**

```python
elif ev_type in ("REDEEM", "REDEMPTION"):
    aggregated, raw_events = aggregate_redeem_events_with_raw(type_events)
    # Use `aggregated` for cash accounting
    # Use `raw_events` for per-position provenance tracking
```

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/workers/test_redeem_aggregation.py -v
git add src/workers/wallet_trade_history.py tests/workers/test_redeem_aggregation.py
git commit -m "fix(redeem): aggregate by transactionHash for cash; preserve raw per-outcome events for provenance"
```

---

### Task B2: Add missing fields to `PositionRow` → already done in Task A1

`asset_token_id`, `outcome`, `redeemable`, validity flags — all added in the A1 rewrite. No separate task needed.

---

### Phase B Verification

```bash
# Full suite
pytest tests/ -v

# 20-wallet cohort shadow run (after Phase A gate passes)
python -m src.workers.v2_positions_sweep \
  --wallet-file cohort_20.txt \
  --read-only \
  --concurrency 3
```

---

## Files touched summary

| File | Change |
|---|---|
| `src/pnl/v2_adapter.py` | Full rewrite — strict sentinel parsing, validity flags, cursor loop guard, `asset_token_id`, `outcome`, `redeemable` |
| `src/utils/polymarket_rate_limit.py` | Add `respect_retry_after()` |
| `src/pnl/invariants.py` | Distinguish None from 0; hard/soft split; fix `_f()` |
| `src/workers/positions_open_backfill.py` | Implement actual upsert in `upsert_position_with_quarantine`; update caller signature |
| `src/workers/positions_closed_backfill.py` | Same — implement upsert; update caller signature |
| `src/workers/v2_positions_sweep.py` | `--read-only` mode; REDEEMABLE status; overlap detection; dedup before sum; default concurrency 10 |
| `src/workers/wallet_trade_history.py` | Add `aggregate_redeem_events`, `aggregate_redeem_events_with_raw` |
| `tests/pnl/test_v2_adapter.py` | Zero-value, missing-field, outcome_index=0, malformed cases |
| `tests/pnl/test_invariants.py` | Missing-field, hard/soft split cases |
| `tests/utils/test_rate_limit_retry_after.py` | New |
| `tests/workers/test_upsert_with_quarantine.py` | New — valid/invalid/soft rows |
| `tests/workers/test_v2_sweep_read_only.py` | New — read-only, overlap detection |
| `tests/workers/test_redeem_aggregation.py` | New |
