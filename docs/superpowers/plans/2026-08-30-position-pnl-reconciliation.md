# Position-Only PnL Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `wallet_metrics_v2.total_pnl` a trustworthy, position-derived PnL that reconciles with Polymarket's `pm_pnl` for directional traders, and explicitly flags the wallet archetypes where position math provably cannot converge.

**Architecture:** Redefine `total_pnl = cleaned_realized(closed) + cleaned_unrealized(open)`. Today the phantom-loss cleaning is applied only to closed rows, leaving the open/redeemable side to inject synthetic losses — this is the single largest defect. Cost basis is capped at actual CLOB cash spent, and complete-set mint cost is attributed once per set (by pairing complementary outcomes on the same `condition_id`) instead of being either double-counted or deleted. Wallets whose data cannot support the reconstruction (complete-set minters, truncated multi-year accounts) are flagged and fall back to `pm_pnl` with an explicit provenance marker rather than being force-matched.

**Tech Stack:** Python 3.12, asyncio, aiohttp, asyncpg, PostgreSQL 16 (Docker container `poly-postgres-1`), pytest + pytest-asyncio. Data source: Polymarket Data API (`https://data-api.polymarket.com`) only — no on-chain/Alchemy dependency.

---

## Measured Baseline (established 2026-08-30, do not re-derive)

Live DB state, `wallet_metrics_v2` where `pm_pnl IS NOT NULL AND pm_pnl <> 0` (331,383 wallets):

| Defect | Count | Share |
|---|---:|---:|
| `position_value` is NULL or 0 | 182,850 | 55.2% |
| `balance` == `position_value` exactly (duplication) | 90,014 | 27.2% |
| `total_pnl` == `pm_pnl` exactly (override contamination) | 38,769 | 11.7% |
| `position_value = 0` AND `|pm_pnl| >= $10k` | 8,632 | — |
| `position_value = 0` AND `|pm_pnl| >= $100k` | 1,623 | — |
| `position_value = 0` but rows exist in `wallet_positions_v2` (SQL-recoverable, $15,454,198) | 1,358 | — |
| Unflagged `is_redeemable` rows in `wallet_closed_positions_v2` holding `-$858,924,558` | 15,021,709 | — |
| `markets_v2.winning_outcome` populated | 0 of 1,248,241 | 0% |

API-side prototype results (10 wallets, rules applied to closed **and** open rows):

| Variant | Median relative error | Within 20% |
|---|---:|---:|
| Current DB `total_pnl` | 135.1% | 2/15 |
| Closed-side cleaning only | >288% (diverges) | — |
| Closed + open cleaning (prototype) | **63.7%** | **4/10** |

Best prototype cases prove convergence is real: `tdrhrhhd` 0.1%, `gmpm` 2.5%, `sainttroplay` 2.6%, `Supah9ga` 19.3%.
Residual is a systematic **over-credit** on the closed side (`Siziriv` +$3.65M, `XAE12Archangel` +$2.15M, `BreakTheBank` +$3.29M) caused by zeroing the cost of a minted leg while still crediting the paired winning leg at $1.00. Task 4 fixes exactly this.

**Acceptance target:** median relative error `<= 20%` and `>= 60%` of the 20-wallet cohort within 20%, measured only over wallets not flagged as non-reconcilable.

---

## Key Code Facts (verified — trust these, do not re-investigate)

| Fact | Location |
|---|---|
| `balance` is assigned the **portfolio value**, not cash — root of the duplication bug | `src/workers/positions_open_backfill.py:262` |
| `position_value` is correctly `sum(currentValue)` | `src/workers/positions_open_backfill.py:264` |
| `/value` endpoint feeds both `balance` and portfolio value | `src/workers/wallet_trade_history.py:430-432`, `src/workers/stats_refresher.py:36` |
| `total_pnl = website_pnl` override (still live) | `src/workers/leaderboard_stats.py:1063`, UPSERT at `:1077-1086` |
| Metrics compute reads `position_value` back from its own row (so 0 stays 0) | `src/workers/positions_metrics_compute.py:265-266`, writes at `:278` |
| `parlay_volume` sums raw shares, not USD | `src/workers/positions_metrics_compute.py:222` |
| Win detection: `winning_outcome` join (dead — column empty) then `sell_p >= 0.95` fallback | `src/workers/positions_metrics_compute.py:148-155` |
| Open-position store: `size, avg_price, current_value, unrealized_pnl, is_resolved, is_parlay` | table `wallet_positions_v2` |
| Closed store: `avg_buy_price, avg_sell_price, total_bought, total_sold, realized_pnl, is_redeemable, data_quality_flag` | table `wallet_closed_positions_v2` |
| Metrics store has `unrealised_pnl` (British spelling) already | table `wallet_metrics_v2` |
| Existing SQL-only aggregator for `position_value` | `src/scripts/backfill_position_value.py` |
| Tests: pytest-asyncio, session-scoped `test_pool` asyncpg fixture, real DB | `tests/conftest.py:15-26` |

**API paging limits (verified):** `/positions` page size 500 and wraps around (repeats pages) past the end — dedupe by `(conditionId, outcome, asset)` and stop when a page yields zero new keys. `/closed-positions` page size 50, returns `[]` at the true end, hard ceiling at offset 30,000.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/pnl/__init__.py` | Package marker. |
| `src/pnl/rules.py` | Pure functions: cost-basis rules, complete-set pairing, archetype classification. Zero I/O, zero DB, zero network — this is the only file with the accounting logic, so it is the only file that needs exhaustive unit tests. |
| `src/pnl/reconcile.py` | Applies `rules.py` to fetched rows and returns a `WalletPnl` result. Takes plain lists of dicts — no network calls, so it is testable with fixtures. |
| `src/scripts/reconcile_report.py` | CLI harness: fetch a cohort from the API, run `reconcile.py`, print/save the convergence report. This is the measurement instrument used as the acceptance gate. |
| `src/scripts/repair_phantom_losses_v2.py` | One-shot DB repair extending the original to the 15.0M unflagged redeemable rows. |
| `tests/test_pnl_rules.py` | Unit tests for `rules.py`. |
| `tests/test_pnl_reconcile.py` | Unit tests for `reconcile.py` using inline fixtures. |
| `tests/test_position_value_integrity.py` | DB integrity assertions (duplication, override, zero-value counts). |

**Modified files:**

| Path | Change |
|---|---|
| `src/workers/positions_open_backfill.py:262` | Stop assigning portfolio value to `balance`. |
| `src/workers/positions_open_backfill.py:316-332` | Also persist `unrealised_pnl`. |
| `src/workers/positions_metrics_compute.py:222` | `parlay_volume` in USD. |
| `src/workers/positions_metrics_compute.py:148-155` | Replace dead `winning_outcome` join with resolved-value win detection. |
| `src/workers/positions_metrics_compute.py:265-278` | `total_pnl` = cleaned realized + unrealised; recompute `position_value` from `wallet_positions_v2` instead of echoing itself. |
| `src/workers/leaderboard_stats.py:1063-1086` | Remove the `total_pnl = website_pnl` override. |
| `docs/problem.md`, `docs/learner.md` | Correct the false-resolved claims listed in Task 10. |

**Database migration:** add `wallet_metrics_v2.pnl_source TEXT` and `wallet_metrics_v2.pnl_residual NUMERIC` so every wallet records how its `total_pnl` was derived and how far it sits from `pm_pnl`.

---

## Task 1: Cost-basis rules module

**Files:**
- Create: `src/pnl/__init__.py`
- Create: `src/pnl/rules.py`
- Test: `tests/test_pnl_rules.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pnl_rules.py`:

```python
from src.pnl.rules import parse_num, cost_basis, CostRule


def test_parse_num_handles_none_and_strings():
    assert parse_num(None) == 0.0
    assert parse_num("") == 0.0
    assert parse_num("1.5") == 1.5
    assert parse_num(3) == 3.0
    assert parse_num("garbage") == 0.0


def test_zero_bought_has_no_cost_basis():
    # Minted via splitPosition: CLOB recorded no purchase, so no cash was spent.
    row = {"totalBought": 0, "avgPrice": 0.5, "initialValue": 1_010_133.42}
    cost, rule = cost_basis(row)
    assert cost == 0.0
    assert rule is CostRule.ZERO_BOUGHT


def test_normal_buy_uses_shares_times_price():
    row = {"totalBought": 1000, "avgPrice": 0.25, "initialValue": 250.0}
    cost, rule = cost_basis(row)
    assert cost == 250.0
    assert rule is CostRule.CASH_SPENT


def test_cost_is_capped_by_initial_value_when_lower():
    # Guards against inflated totalBought * avgPrice products.
    row = {"totalBought": 1000, "avgPrice": 0.90, "initialValue": 400.0}
    cost, rule = cost_basis(row)
    assert cost == 400.0
    assert rule is CostRule.CASH_SPENT


def test_initial_value_of_zero_does_not_cap():
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 0}
    cost, rule = cost_basis(row)
    assert cost == 300.0
    assert rule is CostRule.CASH_SPENT


def test_synthetic_mint_price_is_detected_but_cost_retained_by_default():
    # avgPrice exactly 0.50 with nothing ever sold is Polymarket's synthetic
    # mint estimate. It is only safe to drop when the paired leg is absent,
    # which is decided later by the pairing pass -- not here.
    row = {"totalBought": 2_020_266, "avgPrice": 0.5, "totalSold": 0,
           "initialValue": 1_010_133.0}
    cost, rule = cost_basis(row)
    assert rule is CostRule.SYNTHETIC_MINT
    assert cost == 1_010_133.0


def test_synthetic_detection_requires_nothing_sold():
    row = {"totalBought": 1000, "avgPrice": 0.5, "totalSold": 400,
           "initialValue": 500.0}
    _, rule = cost_basis(row)
    assert rule is CostRule.CASH_SPENT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pnl'`

- [ ] **Step 3: Write minimal implementation**

Create `src/pnl/__init__.py` as an empty file (package marker).

Create `src/pnl/rules.py`:

```python
"""Pure position-accounting rules. No I/O, no DB, no network.

Every rule here exists because Polymarket's position payloads mix two
incompatible sources: the CLOB orderbook (which knows what was actually
bought) and the on-chain token balance (which does not). Cost basis must
never exceed the cash the CLOB actually recorded.
"""
from enum import Enum

SYNTHETIC_MINT_LOW = 0.4995
SYNTHETIC_MINT_HIGH = 0.5005
ZERO_BOUGHT_EPSILON = 0.01


class CostRule(str, Enum):
    ZERO_BOUGHT = "zero_bought"
    SYNTHETIC_MINT = "synthetic_mint"
    CASH_SPENT = "cash_spent"


def parse_num(value) -> float:
    """Coerce an API field to float. Missing/garbage becomes 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def is_synthetic_mint(row: dict) -> bool:
    """True when avgPrice is Polymarket's 0.50 mint estimate and nothing sold."""
    avg_price = parse_num(row.get("avgPrice"))
    if not (SYNTHETIC_MINT_LOW <= avg_price <= SYNTHETIC_MINT_HIGH):
        return False
    return parse_num(row.get("totalSold")) == 0.0


def cost_basis(row: dict) -> tuple[float, CostRule]:
    """Return (cost_basis_usd, rule_applied) for one position row."""
    total_bought = parse_num(row.get("totalBought"))
    avg_price = parse_num(row.get("avgPrice"))
    initial_value = parse_num(row.get("initialValue"))

    if total_bought <= ZERO_BOUGHT_EPSILON:
        return 0.0, CostRule.ZERO_BOUGHT

    cost = total_bought * avg_price
    if initial_value > 0:
        cost = min(cost, initial_value)

    if is_synthetic_mint(row):
        return cost, CostRule.SYNTHETIC_MINT

    return cost, CostRule.CASH_SPENT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pnl/__init__.py src/pnl/rules.py tests/test_pnl_rules.py
git commit -m "feat(pnl): add cost-basis rules capped at actual CLOB cash spent"
```

---

## Task 2: Per-row PnL contribution

**Files:**
- Modify: `src/pnl/rules.py`
- Test: `tests/test_pnl_rules.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pnl_rules.py`:

```python
from src.pnl.rules import closed_contribution, open_contribution


def test_closed_winner_keeps_its_realized_pnl():
    row = {"totalBought": 1000, "avgPrice": 0.40, "initialValue": 400.0,
           "realizedPnl": 600.0}
    assert closed_contribution(row) == 600.0


def test_closed_loss_is_floored_at_cash_spent():
    # Polymarket reports -1,010,133 on a position that cost 400 in cash.
    row = {"totalBought": 1000, "avgPrice": 0.40, "initialValue": 400.0,
           "realizedPnl": -1_010_133.42}
    assert closed_contribution(row) == -400.0


def test_closed_minted_loss_becomes_zero():
    row = {"totalBought": 0, "avgPrice": 0.50, "initialValue": 1_010_133.42,
           "realizedPnl": -1_010_133.42}
    assert closed_contribution(row) == 0.0


def test_open_position_marks_to_market_against_cost():
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 300.0,
           "currentValue": 500.0}
    assert open_contribution(row) == 200.0


def test_unredeemed_winner_credits_full_payout_minus_cost():
    # Market resolved in our favour; currentValue is size * 1.00, unclaimed.
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 300.0,
           "currentValue": 1000.0, "redeemable": True}
    assert open_contribution(row) == 700.0


def test_open_minted_loser_contributes_zero_not_a_phantom_loss():
    # This single rule is what previously injected tens of millions in
    # fake losses on the open side.
    row = {"totalBought": 0, "avgPrice": 0.50, "initialValue": 1_010_133.42,
           "currentValue": 0.0, "redeemable": True}
    assert open_contribution(row) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'closed_contribution'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/pnl/rules.py`:

```python
def closed_contribution(row: dict) -> float:
    """PnL for a settled position: reported realized PnL, floored at cash spent.

    A position cannot lose more than the cash that entered it. Polymarket's
    realizedPnl on minted residuals violates this, which is the phantom loss.
    """
    cost, _rule = cost_basis(row)
    realized = parse_num(row.get("realizedPnl"))
    return max(realized, -cost)


def open_contribution(row: dict) -> float:
    """PnL for a live or resolved-but-unclaimed position.

    currentValue already carries the $1.00-per-share payout for unredeemed
    winners, so the same expression covers both cases.
    """
    cost, _rule = cost_basis(row)
    return parse_num(row.get("currentValue")) - cost
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/pnl/rules.py tests/test_pnl_rules.py
git commit -m "feat(pnl): add closed/open contribution with loss floored at cash spent"
```

---

## Task 3: Complete-set pairing

The prototype over-credited `Siziriv` by $3.65M and `BreakTheBank` by $3.29M. Cause: a complete-set minter pays $1.00 once and receives two legs. Polymarket labels each leg `avgPrice = 0.50`. Those two halves correctly sum to the $1.00 mint cost — so dropping them is wrong when both legs are present, and keeping them is wrong when only one leg survives in the data (the other was truncated or never returned). This task decides per market.

**Files:**
- Modify: `src/pnl/rules.py`
- Test: `tests/test_pnl_rules.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pnl_rules.py`:

```python
from src.pnl.rules import synthetic_legs_to_drop


def test_paired_synthetic_legs_are_retained():
    # Both halves present: 0.50 + 0.50 == the true $1.00 mint cost. Keep both.
    rows = [
        {"conditionId": "0xaa", "outcome": "Yes", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
        {"conditionId": "0xaa", "outcome": "No", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
    ]
    assert synthetic_legs_to_drop(rows) == set()


def test_orphan_synthetic_leg_is_dropped():
    # Only one half present: its 0.50 basis is an unbacked guess.
    rows = [
        {"conditionId": "0xbb", "outcome": "No", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
    ]
    assert synthetic_legs_to_drop(rows) == {("0xbb", "No")}


def test_non_synthetic_rows_are_never_dropped():
    rows = [
        {"conditionId": "0xcc", "outcome": "Yes", "avgPrice": 0.31,
         "totalSold": 0, "totalBought": 100},
    ]
    assert synthetic_legs_to_drop(rows) == set()


def test_pairing_spans_closed_and_open_rows_together():
    # The winning leg settles into /closed-positions while the losing leg
    # stays in /positions. Both must be considered one market.
    rows = [
        {"conditionId": "0xdd", "outcome": "Yes", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100, "_src": "closed"},
        {"conditionId": "0xdd", "outcome": "No", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100, "_src": "open"},
    ]
    assert synthetic_legs_to_drop(rows) == set()


def test_multiple_markets_are_scored_independently():
    rows = [
        {"conditionId": "0xee", "outcome": "Yes", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
        {"conditionId": "0xee", "outcome": "No", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
        {"conditionId": "0xff", "outcome": "No", "avgPrice": 0.5,
         "totalSold": 0, "totalBought": 100},
    ]
    assert synthetic_legs_to_drop(rows) == {("0xff", "No")}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: FAIL — `ImportError: cannot import name 'synthetic_legs_to_drop'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/pnl/rules.py`:

```python
def synthetic_legs_to_drop(rows: list[dict]) -> set[tuple[str, str]]:
    """Identify synthetic-mint legs whose cost basis must be discarded.

    Pass the closed and open rows together: a minter's winning leg settles
    into /closed-positions while the losing leg remains in /positions, and
    they only make sense as one market.

    A synthetic 0.50 basis is trustworthy only when the complementary leg is
    also present, because the two halves then sum to the real $1.00 mint
    cost. A lone synthetic leg is an unbacked guess and is dropped.

    Returns the set of (conditionId, outcome) keys to zero out.
    """
    synthetic_by_market: dict[str, set[str]] = {}
    for row in rows:
        if not is_synthetic_mint(row):
            continue
        condition_id = row.get("conditionId") or ""
        outcome = row.get("outcome") or ""
        synthetic_by_market.setdefault(condition_id, set()).add(outcome)

    orphans: set[tuple[str, str]] = set()
    for condition_id, outcomes in synthetic_by_market.items():
        if len(outcomes) < 2:
            for outcome in outcomes:
                orphans.add((condition_id, outcome))
    return orphans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pnl_rules.py -v`
Expected: PASS — 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/pnl/rules.py tests/test_pnl_rules.py
git commit -m "feat(pnl): drop orphan synthetic mint legs, retain paired complete sets"
```

---

## Task 4: Wallet reconciliation

**Files:**
- Create: `src/pnl/reconcile.py`
- Test: `tests/test_pnl_reconcile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pnl_reconcile.py`:

```python
from src.pnl.reconcile import reconcile_wallet


def test_simple_directional_trader_reconciles():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 1000,
               "avgPrice": 0.40, "initialValue": 400.0, "realizedPnl": 600.0}]
    open_rows = [{"conditionId": "0x2", "outcome": "Yes", "totalBought": 500,
                  "avgPrice": 0.20, "initialValue": 100.0,
                  "currentValue": 150.0}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=650.0)
    assert result.realized == 600.0
    assert result.unrealized == 50.0
    assert result.total_pnl == 650.0
    assert result.residual == 0.0


def test_phantom_loss_on_open_side_is_neutralised():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 1000,
               "avgPrice": 0.52, "initialValue": 520.0, "realizedPnl": 480.0}]
    # Minted residual reported as a million-dollar drawdown on zero cash.
    open_rows = [{"conditionId": "0x1", "outcome": "No", "totalBought": 0,
                  "avgPrice": 0.50, "initialValue": 1_010_133.42,
                  "currentValue": 0.0, "redeemable": True}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=480.0)
    assert result.unrealized == 0.0
    assert result.total_pnl == 480.0


def test_orphan_synthetic_leg_cost_is_dropped():
    closed = []
    open_rows = [{"conditionId": "0x9", "outcome": "No", "totalBought": 100,
                  "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
                  "currentValue": 0.0, "redeemable": True}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=0.0)
    assert result.unrealized == 0.0
    assert result.dropped_synthetic_legs == 1


def test_paired_synthetic_legs_keep_their_cost():
    closed = []
    open_rows = [
        {"conditionId": "0x9", "outcome": "Yes", "totalBought": 100,
         "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
         "currentValue": 100.0},
        {"conditionId": "0x9", "outcome": "No", "totalBought": 100,
         "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
         "currentValue": 0.0},
    ]
    result = reconcile_wallet(closed, open_rows, pm_pnl=0.0)
    # Paid 100 for the set, holding 100 of value: net zero.
    assert result.unrealized == 0.0
    assert result.dropped_synthetic_legs == 0


def test_residual_and_relative_error_are_reported():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
               "avgPrice": 0.50, "initialValue": 50.0, "realizedPnl": 50.0}]
    result = reconcile_wallet(closed, [], pm_pnl=100.0)
    assert result.total_pnl == 50.0
    assert result.residual == -50.0
    assert result.relative_error == 50.0


def test_relative_error_is_zero_when_pm_pnl_is_zero():
    result = reconcile_wallet([], [], pm_pnl=0.0)
    assert result.total_pnl == 0.0
    assert result.relative_error == 0.0


def test_empty_wallet_is_flagged_as_no_data():
    result = reconcile_wallet([], [], pm_pnl=8_052_184.54)
    assert result.source == "no_position_data"


def test_populated_wallet_is_flagged_as_positions():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
               "avgPrice": 0.50, "initialValue": 50.0, "realizedPnl": 50.0}]
    result = reconcile_wallet(closed, [], pm_pnl=50.0)
    assert result.source == "positions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pnl_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pnl.reconcile'`

- [ ] **Step 3: Write minimal implementation**

Create `src/pnl/reconcile.py`:

```python
"""Combine cleaned closed and open contributions into one wallet PnL."""
from dataclasses import dataclass

from src.pnl.rules import (
    closed_contribution,
    open_contribution,
    parse_num,
    synthetic_legs_to_drop,
)


@dataclass
class WalletPnl:
    realized: float
    unrealized: float
    total_pnl: float
    pm_pnl: float
    residual: float
    relative_error: float
    source: str
    n_closed: int
    n_open: int
    dropped_synthetic_legs: int


def _key(row: dict) -> tuple[str, str]:
    return (row.get("conditionId") or "", row.get("outcome") or "")


def reconcile_wallet(closed_rows: list[dict], open_rows: list[dict],
                     pm_pnl: float) -> WalletPnl:
    """Compute position-derived PnL and its distance from the leaderboard.

    Closed and open rows are paired as one population so a minter's split
    legs are recognised even when they live in different endpoints.
    """
    drop = synthetic_legs_to_drop(list(closed_rows) + list(open_rows))

    realized = 0.0
    for row in closed_rows:
        if _key(row) in drop:
            realized += max(parse_num(row.get("realizedPnl")), 0.0)
        else:
            realized += closed_contribution(row)

    unrealized = 0.0
    for row in open_rows:
        if _key(row) in drop:
            unrealized += parse_num(row.get("currentValue"))
        else:
            unrealized += open_contribution(row)

    total = realized + unrealized
    residual = total - pm_pnl
    relative_error = (abs(residual) / abs(pm_pnl) * 100.0) if pm_pnl else 0.0
    source = "positions" if (closed_rows or open_rows) else "no_position_data"

    return WalletPnl(
        realized=realized,
        unrealized=unrealized,
        total_pnl=total,
        pm_pnl=pm_pnl,
        residual=residual,
        relative_error=relative_error,
        source=source,
        n_closed=len(closed_rows),
        n_open=len(open_rows),
        dropped_synthetic_legs=len(drop),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pnl_reconcile.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/pnl/reconcile.py tests/test_pnl_reconcile.py
git commit -m "feat(pnl): reconcile closed and open contributions into wallet PnL"
```

---

## Task 5: Archetype classification

Some wallets provably cannot be reconciled from positions. They must be flagged, never force-matched. `problem.md` §10.C.3-4 forced two of them and called it a fix — this task replaces that practice.

**Files:**
- Modify: `src/pnl/reconcile.py`
- Test: `tests/test_pnl_reconcile.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pnl_reconcile.py`:

```python
from src.pnl.reconcile import classify_wallet


def _row(**kw):
    base = {"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
            "avgPrice": 0.30, "totalSold": 50, "initialValue": 30.0}
    base.update(kw)
    return base


def test_wallet_with_no_rows_is_no_position_data():
    assert classify_wallet([], [], pm_pnl=8_052_184.0) == "no_position_data"


def test_wallet_dominated_by_synthetic_mints_is_a_minter():
    rows = [_row(conditionId=f"0x{i}", avgPrice=0.5, totalSold=0)
            for i in range(30)]
    rows += [_row(conditionId="0xzz")]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "complete_set_minter"


def test_wallet_at_the_closed_positions_ceiling_is_truncated():
    rows = [_row(conditionId=f"0x{i}") for i in range(30_000)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "truncated_history"


def test_ordinary_wallet_is_directional():
    rows = [_row(conditionId=f"0x{i}") for i in range(50)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "directional"


def test_minter_check_precedes_truncation_check():
    # A minter that also hit the ceiling is still primarily a minter.
    rows = [_row(conditionId=f"0x{i}", avgPrice=0.5, totalSold=0)
            for i in range(30_000)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "complete_set_minter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pnl_reconcile.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_wallet'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/pnl/reconcile.py` — extend the import from `src.pnl.rules` to include `is_synthetic_mint`, then append:

```python
CLOSED_POSITIONS_CEILING = 30_000
MINTER_SYNTHETIC_SHARE = 0.20


def classify_wallet(closed_rows: list[dict], open_rows: list[dict],
                    pm_pnl: float) -> str:
    """Label the wallet archetype to decide whether positions can be trusted.

    - no_position_data:    nothing to sum; positions cannot produce a number
    - complete_set_minter: mint cost is not attributable per row
    - truncated_history:   we hold a sample, not a lifetime
    - directional:         reconstructable
    """
    rows = list(closed_rows) + list(open_rows)
    if not rows:
        return "no_position_data"

    synthetic = sum(1 for row in rows if is_synthetic_mint(row))
    if synthetic / len(rows) >= MINTER_SYNTHETIC_SHARE:
        return "complete_set_minter"

    if len(closed_rows) >= CLOSED_POSITIONS_CEILING:
        return "truncated_history"

    return "directional"
```

Then set the label inside `reconcile_wallet` by replacing the `source` assignment:

```python
    source = classify_wallet(closed_rows, open_rows, pm_pnl)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pnl_reconcile.py -v`
Expected: PASS — 13 passed. `test_populated_wallet_is_flagged_as_positions` now fails on the label; update its assertion to `assert result.source == "directional"` and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/pnl/reconcile.py tests/test_pnl_reconcile.py
git commit -m "feat(pnl): classify wallet archetype instead of forcing convergence"
```

---

## Task 6: Reconciliation report CLI

This is the acceptance gate for the whole plan. It must exist before any DB write happens.

**Files:**
- Create: `src/scripts/reconcile_report.py`

- [ ] **Step 1: Verify the API is reachable**

Run: `python -c "import requests; r=requests.get('https://data-api.polymarket.com/positions', params={'user':'0xf0318c32136c2db7fec88b84869aee6a1106c80c','limit':1}, timeout=30); print(r.status_code, len(r.json()))"`
Expected: `200 1`

If this fails with a connection timeout, stop and resolve network access before continuing — every later task depends on it.

- [ ] **Step 2: Write the script**

Create `src/scripts/reconcile_report.py`:

```python
"""Measure position-derived PnL against pm_pnl across a wallet cohort.

Usage:
    python -m src.scripts.reconcile_report --cohort baseline
    python -m src.scripts.reconcile_report --min-pnl 100000 --limit 200
"""
import argparse
import asyncio
import json
import os

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.pnl.reconcile import reconcile_wallet

load_dotenv()

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))
BASE = "https://data-api.polymarket.com"
OUT_PATH = "reconcile_report.json"

# The 20 wallets audited in docs/problem.md, used as the fixed regression cohort.
BASELINE = [
    ("sainttroplay", "0x9319a045cdd0c2180e5eb7ad44374383db9a6410"),
    ("Supah9ga", "0x57cd939930fd119067ca9dc42b22b3e15708a0fb"),
    ("BreakTheBank", "0xf0318c32136c2db7fec88b84869aee6a1106c80c"),
    ("gmpm", "0x14964aefa2cd7caff7878b3820a690a03c5aa429"),
    ("tdrhrhhd", "0xd7f85d0eb0fe0732ca38d9107ad0d4d01b1289e4"),
    ("afkpnlucl", "0x55eca3687ea7d69632ffe0f297ea3d5158bb8c7d"),
    ("XAE12Archangel", "0xfbfd14dd4bb607373119de95f1d4b21c3b6c0029"),
    ("wallet_2c33506", "0x2c335066fe58fe9237c3d3dc7b275c2a034a0563"),
    ("wallet_09b428f", "0x09b428f7c2b469786286214aa5c90dd9015f7320"),
    ("Gucky-45", "0xe613b515bd46b1585a8b137a4d291d9b80bd540e"),
    ("Siziriv", "0x8e9eedf20dfa70956d49f608a205e402d9df38e4"),
    ("AnonymousUsername", "0x9703676286b93c2eca71ca96e8757104519a69c2"),
    ("ImJustKen", "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"),
    ("Anjun", "0x43372356634781eea88d61bbdd7824cdce958882"),
    ("wokerjoesleeper", "0x63d43bbb87f85af03b8f2f9e2fad7b54334fa2f1"),
    ("Cannae", "0x7ea571c40408f340c1c8fc8eaacebab53c1bde7b"),
    ("ferrariChampions2026", "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"),
    ("alwayslatetotheparty", "0xb687f00464e33934f5d591f224e71c3559ecaee5"),
    ("swisstony", "0x204f72f35326db932158cba6adff0b9a1da95e14"),
    ("debased", "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1"),
]


async def _get(session, path, params, retries=6):
    for attempt in range(retries):
        try:
            async with session.get(BASE + path, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        await asyncio.sleep(1.0 * (attempt + 1))
    return None


async def _page_all(session, path, address, limit, extra, ceiling=30_000):
    """Page an endpoint, deduping because /positions wraps past the end."""
    rows, offset, seen = [], 0, set()
    while offset <= ceiling:
        params = {"user": address, "limit": limit, "offset": offset}
        params.update(extra)
        page = await _get(session, path, params)
        if not page:
            break
        fresh = 0
        for row in page:
            key = (row.get("conditionId"), row.get("outcome"), row.get("asset"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            fresh += 1
        if fresh == 0 or len(page) < limit:
            break
        offset += limit
    return rows


async def fetch_wallet(session, address):
    board = await _get(session, "/v1/leaderboard",
                       {"user": address, "category": "OVERALL",
                        "timePeriod": "ALL"})
    if isinstance(board, dict):
        pm_pnl = float(board.get("pnl") or 0)
    elif isinstance(board, list) and board:
        pm_pnl = float(board[0].get("pnl") or 0)
    else:
        pm_pnl = 0.0

    closed = await _page_all(session, "/closed-positions", address, 50,
                             {"sortBy": "TIMESTAMP", "sortDirection": "DESC"})
    open_rows = await _page_all(session, "/positions", address, 500,
                                {"sortBy": "CURRENT", "sortDirection": "DESC"})
    return pm_pnl, closed, open_rows


async def load_cohort(args):
    if args.cohort == "baseline":
        return BASELINE
    conn = await asyncpg.connect(DB_URL)
    rows = await conn.fetch("""
        SELECT m.address, COALESCE(w.username, m.address) AS username
        FROM wallet_metrics_v2 m
        LEFT JOIN wallets_v2 w ON w.address = m.address
        WHERE m.pm_pnl IS NOT NULL AND abs(m.pm_pnl) >= $1
        ORDER BY abs(m.pm_pnl) DESC
        LIMIT $2
    """, args.min_pnl, args.limit)
    await conn.close()
    return [(r["username"], r["address"]) for r in rows]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", default="baseline",
                        choices=["baseline", "db"])
    parser.add_argument("--min-pnl", type=float, default=100_000.0)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    cohort = await load_cohort(args)
    timeout = aiohttp.ClientTimeout(total=900, connect=30)
    results = []

    header = (f"{'wallet':<22}{'pm_pnl':>13}{'total_pnl':>13}"
              f"{'residual':>13}{'err%':>8}  archetype")
    print(header)
    print("-" * len(header))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, address in cohort:
            try:
                pm_pnl, closed, open_rows = await fetch_wallet(session, address)
            except Exception as exc:
                print(f"{name:<22}  ERROR {type(exc).__name__}: {exc}")
                continue
            result = reconcile_wallet(closed, open_rows, pm_pnl)
            payload = {"wallet": name, "address": address,
                       **result.__dict__}
            results.append(payload)
            print(f"{name:<22}{result.pm_pnl:>13,.0f}{result.total_pnl:>13,.0f}"
                  f"{result.residual:>13,.0f}{result.relative_error:>7.1f}%"
                  f"  {result.source}")
            with open(OUT_PATH, "w") as handle:
                json.dump(results, handle, indent=2)

    reconcilable = [r for r in results if r["source"] == "directional"]
    print("-" * len(header))
    print(f"cohort={len(results)}  directional={len(reconcilable)}")
    if reconcilable:
        errors = sorted(r["relative_error"] for r in reconcilable)
        median = errors[len(errors) // 2]
        within = sum(1 for e in errors if e <= 20)
        print(f"directional median error = {median:.1f}%   "
              f"within 20% = {within}/{len(errors)}")
        print(f"ACCEPTANCE: {'PASS' if median <= 20 else 'FAIL'} "
              f"(target median <= 20%)")
    for archetype in ("complete_set_minter", "truncated_history",
                      "no_position_data"):
        flagged = [r["wallet"] for r in results if r["source"] == archetype]
        if flagged:
            print(f"{archetype}: {flagged}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run the baseline cohort and record the result**

Run: `python -m src.scripts.reconcile_report --cohort baseline`
Expected: a 20-row table, an `ACCEPTANCE: PASS|FAIL` line, and `reconcile_report.json` written.

Record the printed median in the commit message. The prototype scored 63.7% median with per-row rules only; the pairing pass from Task 3 is expected to cut the over-credits on `Siziriv`, `XAE12Archangel`, `BreakTheBank` and `Anjun`.

- [ ] **Step 4: If ACCEPTANCE is FAIL, tune and re-measure**

Inspect the largest `residual` values in `reconcile_report.json`. Only two knobs may be adjusted, both in `src/pnl/rules.py`:
`MINTER_SYNTHETIC_SHARE` (currently `0.20`) and the `SYNTHETIC_MINT_LOW`/`HIGH` window.
Re-run Step 3 after each change. Do not add per-wallet special cases and do not overwrite `total_pnl` with `pm_pnl` to close a gap — that is the bug this plan removes.

- [ ] **Step 5: Commit**

```bash
git add src/scripts/reconcile_report.py reconcile_report.json
git commit -m "feat(pnl): add reconciliation report as the acceptance gate"
```

---

## Task 7: Stop assigning portfolio value to `balance`

`/value` returns the marked-to-market portfolio value, not cash. Assigning it to `balance` makes `balance` a duplicate of `position_value` for 90,014 wallets and double-counts open value in any equity formula.

**Files:**
- Modify: `src/workers/positions_open_backfill.py:259-262`
- Test: `tests/test_position_value_integrity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_position_value_integrity.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_balance_is_not_a_copy_of_position_value(test_pool):
    """balance is cash; position_value is marked-to-market holdings.

    Baseline on 2026-08-30 was 90,014 duplicated wallets. This test locks in
    improvement and fails if a regression pushes the count back up.
    """
    async with test_pool.acquire() as conn:
        duplicated = await conn.fetchval("""
            SELECT count(*) FROM wallet_metrics_v2
            WHERE balance IS NOT NULL AND position_value IS NOT NULL
              AND position_value <> 0
              AND abs(balance - position_value) < 0.01
        """)
    assert duplicated < 90_014, (
        f"{duplicated} wallets still have balance == position_value"
    )


@pytest.mark.asyncio
async def test_total_pnl_is_not_a_verbatim_copy_of_pm_pnl(test_pool):
    """Baseline was 38,769 wallets with total_pnl == pm_pnl exactly."""
    async with test_pool.acquire() as conn:
        overridden = await conn.fetchval("""
            SELECT count(*) FROM wallet_metrics_v2
            WHERE pm_pnl IS NOT NULL AND total_pnl IS NOT NULL
              AND pm_pnl <> 0
              AND abs(pm_pnl - total_pnl) < 0.01
        """)
    assert overridden < 38_769, (
        f"{overridden} wallets still mirror pm_pnl into total_pnl"
    )


@pytest.mark.asyncio
async def test_position_value_is_populated_where_open_rows_exist(test_pool):
    """No wallet should hold open rows yet report zero position_value."""
    async with test_pool.acquire() as conn:
        gap = await conn.fetchval("""
            SELECT count(*)
            FROM wallet_metrics_v2 m
            JOIN (
                SELECT address, SUM(current_value) AS total_val
                FROM wallet_positions_v2
                GROUP BY address
            ) p ON p.address = m.address
            WHERE (m.position_value IS NULL OR m.position_value = 0)
              AND p.total_val > 0
        """)
    assert gap == 0, f"{gap} wallets have open rows but position_value = 0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_position_value_integrity.py -v`
Expected: FAIL — the duplication test reports 90,014 and the population test reports 1,358.

- [ ] **Step 3: Fix the assignment**

In `src/workers/positions_open_backfill.py`, replace lines 259-262:

```python
    existing_balance = await conn.fetchval(
        "SELECT balance FROM wallet_metrics_v2 WHERE address = $1", address
    )
    balance = portfolio_val if portfolio_val > 0 else (float(existing_balance) if existing_balance is not None else 0.0)
```

with:

```python
    # /value returns marked-to-market PORTFOLIO value, not cash. Writing it to
    # `balance` made balance a duplicate of position_value for 90k wallets and
    # double-counted open value in every equity formula. Preserve whatever a
    # genuine cash source wrote; never synthesise it from portfolio value.
    existing_balance = await conn.fetchval(
        "SELECT balance FROM wallet_metrics_v2 WHERE address = $1", address
    )
    balance = float(existing_balance) if existing_balance is not None else 0.0
```

- [ ] **Step 4: Clear the duplicated values already in the table**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "UPDATE wallet_metrics_v2 SET balance = NULL WHERE balance IS NOT NULL AND position_value IS NOT NULL AND position_value <> 0 AND abs(balance - position_value) < 0.01;"
```

Expected: `UPDATE 90014`

- [ ] **Step 5: Re-run the duplication test**

Run: `python -m pytest tests/test_position_value_integrity.py::test_balance_is_not_a_copy_of_position_value -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/workers/positions_open_backfill.py tests/test_position_value_integrity.py
git commit -m "fix(metrics): stop writing portfolio value into balance"
```

---

## Task 8: Populate `position_value` and `unrealised_pnl`

**Files:**
- Modify: `src/scripts/backfill_position_value.py`
- Modify: `src/workers/positions_open_backfill.py:316-332`

- [ ] **Step 1: Extend the SQL aggregator to also write `unrealised_pnl`**

In `src/scripts/backfill_position_value.py`, replace the first UPDATE (lines 18-28) with:

```python
    res1 = await conn.execute("""
        UPDATE wallet_metrics_v2 m
        SET position_value = p.total_val,
            unrealised_pnl = p.total_unreal,
            computed_at = NOW()
        FROM (
            SELECT address,
                   COALESCE(SUM(current_value), 0)   AS total_val,
                   COALESCE(SUM(unrealized_pnl), 0)  AS total_unreal
            FROM wallet_positions_v2
            GROUP BY address
        ) p
        WHERE m.address = p.address;
    """)
```

and the second UPDATE (lines 32-38) with:

```python
    res2 = await conn.execute("""
        UPDATE wallet_metrics_v2
        SET position_value = 0,
            unrealised_pnl = 0,
            computed_at = NOW()
        WHERE address NOT IN (SELECT address FROM wallet_positions_v2)
          AND (position_value IS NULL OR position_value != 0);
    """)
```

- [ ] **Step 2: Run it**

Run: `python -m src.scripts.backfill_position_value`
Expected: two `UPDATE <n>` lines then `Done!`. The first should report at least 283,947 rows.

- [ ] **Step 3: Verify the population test now passes**

Run: `python -m pytest tests/test_position_value_integrity.py::test_position_value_is_populated_where_open_rows_exist -v`
Expected: PASS — the 1,358-wallet gap is closed.

- [ ] **Step 4: Persist `unrealised_pnl` from the worker too**

In `src/workers/positions_open_backfill.py`, add the unrealised total next to `pos_val` (after line 264):

```python
    pos_val = sum(_parse(p.get("currentValue", 0)) for p in positions)
    unrealised = sum(
        _parse(p.get("currentValue", 0)) - _parse(p.get("initialValue", 0))
        for p in positions
    )
```

Then in the UPSERT at lines 316-332, add the column, the placeholder, and the conflict clause. The statement becomes:

```python
    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, position_value, balance,
            parlay_open_count, parlay_open_value,
            redeemable_count, redeemable_winning_count,
            open_synced_at, unrealised_pnl
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $8 THEN NOW() ELSE NULL END, $9)
        ON CONFLICT (address) DO UPDATE SET
            position_value=EXCLUDED.position_value,
            balance=EXCLUDED.balance,
            parlay_open_count=EXCLUDED.parlay_open_count,
            parlay_open_value=EXCLUDED.parlay_open_value,
            redeemable_count=EXCLUDED.redeemable_count,
            redeemable_winning_count=EXCLUDED.redeemable_winning_count,
            unrealised_pnl=EXCLUDED.unrealised_pnl,
            open_synced_at=CASE WHEN $8 THEN NOW() ELSE wallet_metrics_v2.open_synced_at END
    """, address, pos_val, balance, parlay_open_count, parlay_open_value,
         redeemable_count, redeemable_winning_count, positions_complete, unrealised)
```

- [ ] **Step 5: Commit**

```bash
git add src/scripts/backfill_position_value.py src/workers/positions_open_backfill.py
git commit -m "feat(metrics): populate position_value and unrealised_pnl from open positions"
```

---

## Task 9: Extend the phantom-loss repair

The original repair tagged 4,542,645 rows. **15,021,709 unflagged `is_redeemable` rows still hold `-$858,924,558`.**

**Files:**
- Create: `src/scripts/repair_phantom_losses_v2.py`

- [ ] **Step 1: Measure before touching anything**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "SELECT count(*) AS rows, sum(realized_pnl)::numeric(16,0) AS pnl FROM wallet_closed_positions_v2 WHERE is_redeemable AND COALESCE(data_quality_flag,'') = '';"
```

Expected: `15021709 | -858924558`. Record both numbers.

- [ ] **Step 2: Write the repair script**

Create `src/scripts/repair_phantom_losses_v2.py`:

```python
"""Extend the phantom-loss repair to redeemable rows the first pass missed.

Applies the same principle as src/pnl/rules.py: a position cannot lose more
cash than entered it. Batched by address so a failure is resumable and the
table is never locked for long.
"""
import asyncio
import logging
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))

# Rule 1: no CLOB purchase recorded -> no cash was spent -> no loss possible.
ZERO_BOUGHT = """
UPDATE wallet_closed_positions_v2
SET realized_pnl = 0,
    data_quality_flag = 'synthetic_liquidation_artifact'
WHERE address = ANY($1::varchar[])
  AND is_redeemable
  AND COALESCE(data_quality_flag, '') = ''
  AND COALESCE(total_bought, 0) <= 0.01
  AND realized_pnl < 0
"""

# Rule 2: loss deeper than cash spent -> clamp to cash spent.
CAP_TO_CASH = """
UPDATE wallet_closed_positions_v2
SET realized_pnl = -(total_bought * avg_buy_price),
    data_quality_flag = 'mixed_minted_shares'
WHERE address = ANY($1::varchar[])
  AND is_redeemable
  AND COALESCE(data_quality_flag, '') = ''
  AND COALESCE(total_bought, 0) > 0.01
  AND realized_pnl < -(total_bought * avg_buy_price)
"""

# Rule 3: synthetic 0.50 mint price, never sold, no offsetting leg stored.
ORPHAN_SYNTHETIC_MINT = """
UPDATE wallet_closed_positions_v2 c
SET realized_pnl = 0,
    data_quality_flag = 'synthetic_mint_split'
WHERE c.address = ANY($1::varchar[])
  AND c.is_redeemable
  AND COALESCE(c.data_quality_flag, '') = ''
  AND c.avg_buy_price BETWEEN 0.4995 AND 0.5005
  AND COALESCE(c.total_sold, 0) = 0
  AND c.realized_pnl < 0
  AND NOT EXISTS (
      SELECT 1 FROM wallet_closed_positions_v2 s
      WHERE s.address = c.address
        AND s.condition_id = c.condition_id
        AND s.outcome <> c.outcome
        AND s.avg_buy_price BETWEEN 0.4995 AND 0.5005
  )
"""

BATCH = 500


def _count(tag: str) -> int:
    return int(tag.split()[-1]) if tag and tag.split()[-1].isdigit() else 0


async def main():
    conn = await asyncpg.connect(DB_URL)
    addresses = [r["address"] for r in await conn.fetch("""
        SELECT DISTINCT address FROM wallet_closed_positions_v2
        WHERE is_redeemable AND COALESCE(data_quality_flag, '') = ''
    """)]
    logger.info("wallets to repair: %d", len(addresses))

    totals = {"zero_bought": 0, "cap_to_cash": 0, "orphan_mint": 0}
    for start in range(0, len(addresses), BATCH):
        chunk = addresses[start:start + BATCH]
        async with conn.transaction():
            totals["zero_bought"] += _count(await conn.execute(ZERO_BOUGHT, chunk))
            totals["cap_to_cash"] += _count(await conn.execute(CAP_TO_CASH, chunk))
            totals["orphan_mint"] += _count(
                await conn.execute(ORPHAN_SYNTHETIC_MINT, chunk))
        logger.info("progress %d/%d  %s", min(start + BATCH, len(addresses)),
                    len(addresses), totals)

    remaining = await conn.fetchrow("""
        SELECT count(*) AS rows, COALESCE(sum(realized_pnl), 0)::numeric AS pnl
        FROM wallet_closed_positions_v2
        WHERE is_redeemable AND COALESCE(data_quality_flag, '') = ''
    """)
    logger.info("repaired: %s", totals)
    logger.info("still unflagged: %s rows holding %s",
                remaining["rows"], remaining["pnl"])
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Dry-run the row counts before writing**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "SELECT count(*) FILTER (WHERE COALESCE(total_bought,0) <= 0.01 AND realized_pnl < 0) AS rule1, count(*) FILTER (WHERE COALESCE(total_bought,0) > 0.01 AND realized_pnl < -(total_bought*avg_buy_price)) AS rule2, count(*) FILTER (WHERE avg_buy_price BETWEEN 0.4995 AND 0.5005 AND COALESCE(total_sold,0) = 0 AND realized_pnl < 0) AS rule3_candidates FROM wallet_closed_positions_v2 WHERE is_redeemable AND COALESCE(data_quality_flag,'') = '';"
```

Record the three counts. Their sum bounds how many rows the script may touch.

- [ ] **Step 4: Run the repair**

Run: `python -m src.scripts.repair_phantom_losses_v2`
Expected: progress lines, then a final `still unflagged:` line whose `pnl` magnitude is far below `-858924558`.

- [ ] **Step 5: Verify no row now loses more than it spent**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "SELECT count(*) AS violations FROM wallet_closed_positions_v2 WHERE realized_pnl < -(COALESCE(total_bought,0) * COALESCE(avg_buy_price,0)) - 0.01 AND COALESCE(total_bought,0) > 0.01 AND is_redeemable;"
```

Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add src/scripts/repair_phantom_losses_v2.py
git commit -m "fix(data): extend phantom-loss repair to 15M unflagged redeemable rows"
```

---

## Task 10: Remove the `pm_pnl` override and adopt the new definition

**Files:**
- Modify: `src/workers/leaderboard_stats.py:1062-1086`
- Modify: `src/workers/positions_metrics_compute.py:222`, `:148-155`, `:265-278`
- Migration: `wallet_metrics_v2.pnl_source`, `wallet_metrics_v2.pnl_residual`

- [ ] **Step 1: Add the provenance columns**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "ALTER TABLE wallet_metrics_v2 ADD COLUMN IF NOT EXISTS pnl_source TEXT, ADD COLUMN IF NOT EXISTS pnl_residual NUMERIC;"
```

Expected: `ALTER TABLE`

- [ ] **Step 2: Remove the override**

In `src/workers/leaderboard_stats.py`, replace lines 1062-1064:

```python
        # PnL from Polymarket leaderboard (website), NULL if not available
        total_pnl = website_pnl
        total_volume = website_volume
```

with:

```python
        # pm_pnl / pm_volume were already stored above. total_pnl is owned by
        # positions_metrics_compute and derived from position rows; mirroring
        # the leaderboard here is what produced 38,769 wallets whose total_pnl
        # was an untraceable copy of pm_pnl. Leave it alone.
        total_volume = website_volume
```

Then in the UPSERT at lines 1066-1086, drop `total_pnl` from the column list, remove its placeholder, delete `total_pnl=EXCLUDED.total_pnl` from the `DO UPDATE SET`, and renumber the remaining placeholders. Apply the same removal to the `wallets_v2` UPDATE at lines 1088-1096.

- [ ] **Step 3: Fix `parlay_volume` to be USD**

In `src/workers/positions_metrics_compute.py`, replace line 222:

```python
    parlay_volume = sum(_parse(cp.get("total_bought")) for cp in parlay_closed) ...
```

with:

```python
    # total_bought is a share count. Volume is dollars, so it must be priced.
    parlay_volume = sum(
        _parse(cp.get("total_bought")) * _parse(cp.get("avg_buy_price"))
        for cp in parlay_closed
    )
```

- [ ] **Step 4: Replace the dead win-detection join**

`markets_v2.winning_outcome` is empty in all 1,248,241 rows, so the `sell_p >= 0.95` fallback runs for every redeemable row — and an unredeemed winner always has `avg_sell_price = 0`. Replace lines 148-155:

```python
        winning_outcome = cp.get("winning_outcome")
        if winning_outcome:
            is_win = (cp.get("outcome") == winning_outcome)
        elif cp.get("is_redeemable"):
            is_win = realized_pnl > 0 or sell_p >= 0.95
```

with:

```python
        winning_outcome = cp.get("winning_outcome")
        if winning_outcome:
            is_win = (cp.get("outcome") == winning_outcome)
        elif cp.get("is_redeemable"):
            # An unredeemed position never sold, so avg_sell_price is always 0
            # and any sell-price threshold is unsatisfiable. Resolution value
            # is the real signal: a resolved position still carrying value won.
            is_win = (realized_pnl > 0
                      or _parse(cp.get("current_value")) > 0)
```

Extend the query that loads `cp` rows to select `wallet_positions_v2.current_value` for the same `(address, condition_id, outcome)`, so the field is present.

- [ ] **Step 5: Adopt the new `total_pnl` definition**

In `src/workers/positions_metrics_compute.py`, replace lines 265-266:

```python
    existing = await conn.fetchrow("SELECT position_value, parlay_open_count, parlay_open_value, redeemable_count, redeemable_winning_count, balance FROM wallet_metrics_v2 WHERE address = $1", address)
    pos_val = existing["position_value"] if existing else 0
```

with:

```python
    existing = await conn.fetchrow("SELECT parlay_open_count, parlay_open_value, redeemable_count, redeemable_winning_count, balance FROM wallet_metrics_v2 WHERE address = $1", address)
    # Recompute from the open-position table instead of echoing our own column;
    # reading it back is why 182,850 wallets stayed at position_value = 0.
    live = await conn.fetchrow("""
        SELECT COALESCE(SUM(current_value), 0)  AS pos_val,
               COALESCE(SUM(unrealized_pnl), 0) AS unrealised
        FROM wallet_positions_v2 WHERE address = $1
    """, address)
    pos_val = float(live["pos_val"]) if live else 0.0
    unrealised = float(live["unrealised"]) if live else 0.0
    # total_pnl = settled PnL + marked-to-market open PnL. This is the
    # position-space analogue of the leaderboard's equity delta.
    total_pnl = total_pnl + unrealised
```

Add `unrealised_pnl`, `pnl_source`, and `pnl_residual` to the UPSERT at line 278, setting `pnl_source = 'positions'` and `pnl_residual = total_pnl - pm_pnl` when `pm_pnl` is present.

- [ ] **Step 6: Run the affected worker on the baseline cohort and compare**

Run: `python -m src.scripts.reconcile_report --cohort baseline`
Expected: median directional error at or below the value recorded in Task 6 Step 3. If it regressed, revert Step 5 and investigate before proceeding.

- [ ] **Step 7: Run the integrity suite**

Run: `python -m pytest tests/test_position_value_integrity.py tests/test_pnl_rules.py tests/test_pnl_reconcile.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/workers/leaderboard_stats.py src/workers/positions_metrics_compute.py
git commit -m "fix(metrics): remove pm_pnl override, define total_pnl as realized + unrealised"
```

---

## Task 11: Backfill the wallets that have no position rows

8,632 wallets with `|pm_pnl| >= $10k` have `position_value = 0`; 1,623 of those are above `$100k`. These need an actual API fetch — no SQL can invent the rows.

**Files:**
- Create: `src/scripts/backfill_missing_positions.py`

- [ ] **Step 1: Write the backfill runner**

Create `src/scripts/backfill_missing_positions.py`:

```python
"""Re-fetch open positions for wallets whose position_value is missing.

Ordered by |pm_pnl| so the wallets that distort headline numbers most are
repaired first. Reuses the existing worker so there is one ingestion path.
"""
import argparse
import asyncio
import logging
import os

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.workers.positions_open_backfill import process_wallet_open_positions

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = (os.getenv("DATABASE_URL",
                    "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
          .replace("postgres://", "postgresql://"))

SELECT_TARGETS = """
SELECT address FROM wallet_metrics_v2
WHERE pm_pnl IS NOT NULL
  AND abs(pm_pnl) >= $1
  AND (position_value IS NULL OR position_value = 0)
ORDER BY abs(pm_pnl) DESC
LIMIT $2
"""


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pnl", type=float, default=10_000.0)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    conn = await asyncpg.connect(DB_URL)
    targets = [r["address"]
               for r in await conn.fetch(SELECT_TARGETS, args.min_pnl, args.limit)]
    await conn.close()
    logger.info("wallets to backfill: %d", len(targets))

    pool = await asyncpg.create_pool(DB_URL, min_size=2,
                                     max_size=args.concurrency + 2)
    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=300, connect=30)
    done = 0

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def run_one(address):
            nonlocal done
            async with semaphore:
                try:
                    async with pool.acquire() as conn_inner:
                        await process_wallet_open_positions(
                            conn_inner, session, address)
                except Exception as exc:
                    logger.warning("%s failed: %s", address[:12], exc)
                done += 1
                if done % 100 == 0:
                    logger.info("progress %d/%d", done, len(targets))

        await asyncio.gather(*(run_one(a) for a in targets))

    await pool.close()
    logger.info("backfill complete: %d wallets", done)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Confirm the worker entrypoint name**

Run: `python -c "import src.workers.positions_open_backfill as m; print([n for n in dir(m) if 'process' in n or 'wallet' in n])"`
Expected: a list containing the per-wallet coroutine. If it is not named `process_wallet_open_positions`, update the import and call in Step 1 to the actual name — do not add a wrapper.

- [ ] **Step 3: Smoke-test on the highest-value slice**

Run: `python -m src.scripts.backfill_missing_positions --min-pnl 100000 --limit 25 --concurrency 4`
Expected: `wallets to backfill: 25` then `backfill complete: 25`

- [ ] **Step 4: Verify the gap shrank**

Run:

```bash
docker exec poly-postgres-1 psql -U poly_user -d poly_db -c "SELECT count(*) FROM wallet_metrics_v2 WHERE pm_pnl IS NOT NULL AND abs(pm_pnl) >= 100000 AND (position_value IS NULL OR position_value = 0);"
```

Expected: below the 1,623 baseline.

- [ ] **Step 5: Run the full priority tier**

Run: `python -m src.scripts.backfill_missing_positions --min-pnl 10000 --limit 10000 --concurrency 8`
Expected: `backfill complete: 8632` (or fewer if earlier tasks already repaired some).

- [ ] **Step 6: Commit**

```bash
git add src/scripts/backfill_missing_positions.py
git commit -m "feat(backfill): re-fetch open positions for wallets missing position_value"
```

---

## Task 12: Final measurement and documentation correction

**Files:**
- Modify: `docs/problem.md`
- Modify: `docs/learner.md`
- Create: `docs/superpowers/plans/2026-08-30-position-pnl-reconciliation-results.md`

- [ ] **Step 1: Run the final acceptance measurement**

Run: `python -m src.scripts.reconcile_report --cohort baseline`
Expected: `ACCEPTANCE: PASS` with directional median error `<= 20%`.

- [ ] **Step 2: Run a wider cohort to confirm it generalises**

Run: `python -m src.scripts.reconcile_report --cohort db --min-pnl 100000 --limit 200`
Expected: directional median error `<= 20%` and at least 60% of directional wallets within 20%.

- [ ] **Step 3: Record the results**

Create `docs/superpowers/plans/2026-08-30-position-pnl-reconciliation-results.md` containing: the before/after table (baseline median 135.1% → measured), the per-archetype counts from both runs, and the residual list for every wallet still above 20% with its archetype. State plainly which wallets remain unreconciled and why.

- [ ] **Step 4: Correct the false claims in `docs/problem.md`**

Apply these edits — each is a statement currently contradicted by the database:

1. §3 "Redeemable Win Detection" — change `[SOLVED]` to `[SUPERSEDED]` and state that `markets_v2.winning_outcome` is empty in all 1,248,241 rows, so the documented join never executed; the working detection is resolution value (Task 10 Step 4).
2. §4 "Volume Aggregation" — note `parlay_volume` remained in share units at `positions_metrics_compute.py:222` until Task 10 Step 3.
3. §9.D — remove "exact mathematical sum of all ingested position rows". Replace with the Task 10 definition and note that `total_pnl` was previously overwritten by `pm_pnl` at `leaderboard_stats.py:1063`.
4. §10.A — replace the "+$261.07M eliminated" claim with both figures: 4,542,645 rows repaired by the first pass, and 15,021,709 rows holding `-$858,924,558` left untouched until Task 9.
5. §10.C.3 and §10.C.4 — BreakTheBank and debased had 0 closed rows; their "alignment" was the §10.B override, not the Option A cleaning. Say so.

- [ ] **Step 5: Reconcile `docs/learner.md`**

1. §3.4 vs report.md — both a 30,000 and a ~7,500 `/closed-positions` ceiling are documented. Record 30,000 as the probe-verified value, note where 7,500 appears, and mark the discrepancy resolved.
2. §14.1 — the `avg_buy_price = 0.50` root cause is now identified: Polymarket emits it as the mint-cost estimate (documented in problem.md §1.C's own JSON sample). Update the open question and point to `src/pnl/rules.py:is_synthetic_mint`.
3. §14.3 — keep the conclusion that position sums cannot equal leaderboard PnL to the cent, and add the measured residual from Step 1 as the empirical bound.
4. §8.2 vs §11.4 — trade retention is documented as both 30 and 15 days. Verify against the code and state one number.

- [ ] **Step 6: Commit**

```bash
git add docs/problem.md docs/learner.md docs/superpowers/plans/2026-08-30-position-pnl-reconciliation-results.md
git commit -m "docs: correct PnL claims contradicted by measured database state"
```

---

## Out of Scope

- On-chain / Alchemy reconstruction. Measured this session: the cash ledger cannot see unredeemed payouts (BreakTheBank had 237,484 token inflows against 41 USDC receipts), so it does not resolve the gap either. The 3.5 GB transfer cache in `backtest_cache/` and the scripts `backtest_full_ledger.py`, `diagnose.py`, `counterparties.py`, `token_flows.py`, `inspect_tx.py`, `check_addrs.py`, `validate_target*.py` are session artefacts. Delete them or move them under `scratch/`.
- Making complete-set minters reconcile. Their mint cost is not recoverable from position rows. Task 5 flags them; that is the correct outcome.
- Recovering truncated history beyond the 30,000-row API ceiling.
- Frontend changes. Once `pnl_source` exists, the UI should label any wallet not marked `positions`, but that is a separate plan.

---

## Self-Review

**Spec coverage.** Every defect established this session maps to a task: open-side phantom loss → Tasks 1-4; over-credit from orphan mint legs → Task 3; non-reconcilable archetypes → Task 5; measurement gate → Task 6; `balance` duplication (90,014) → Task 7; `position_value` = 0 (182,850) → Tasks 8 and 11; 15,021,709 unflagged rows / `-$858,924,558` → Task 9; `total_pnl = pm_pnl` override (38,769) → Task 10; `parlay_volume` share units → Task 10; dead `winning_outcome` join → Task 10; doc contradictions → Task 12.

**Placeholder scan.** No TBD/TODO markers. Every code step carries complete code. Every command has an expected result. Task 11 Step 2 verifies the worker's function name rather than assuming it — the one identifier this plan could not confirm without running the interpreter.

**Type consistency.** `parse_num`, `cost_basis`, `CostRule`, `is_synthetic_mint`, `closed_contribution`, `open_contribution`, `synthetic_legs_to_drop`, `reconcile_wallet`, `classify_wallet`, `WalletPnl` are defined once and referenced consistently. `WalletPnl.source` carries the `classify_wallet` labels, so Task 4's `test_populated_wallet_is_flagged_as_positions` is explicitly corrected in Task 5 Step 4 rather than left to fail. Column names `position_value`, `balance`, `unrealised_pnl` (British), `pnl_source`, `pnl_residual`, `data_quality_flag` match the live schema.

**Ordering.** The measurement gate (Task 6) precedes every mutation, so each later task is verifiable against a recorded baseline. Task 7 precedes Task 8 so the duplicate-clearing UPDATE is not immediately re-populated by the worker.
