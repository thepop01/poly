# Position-Only PnL Reconciliation — Final Measurement Results

> Measured 2026-08-31 via `python -m src.scripts.reconcile_report --cohort baseline`

---

## 1. Before / After

| Metric | Before (old DB `total_pnl`) | After (reconciled API-side rules) |
|---|---:|---:|
| Median relative error | 135.1% | 106.9% |
| Within 20% | 2/15 | 5/12 |

The reconcile rules (cost-basis capping, synthetic-mint pairing, open-side contribution) were applied to live API data for the 20-wallet baseline cohort. The median error dropped from 135.1% to 106.9% but did not reach the ≤20% acceptance target.

---

## 2. Per-Archetype Counts

| Archetype | Count | Wallets |
|---|---:|---|
| directional | 12 | sainttroplay, Supah9ga, BreakTheBank, gmpm, tdrhrhhd, XAE12Archangel, wallet_2c33506, wallet_09b428f, AnonymousUsername, ImJustKen, Anjun, debased |
| complete_set_minter | 5 | afkpnlucl, Gucky-45, Siziriv, wokerjoesleeper, alwayslatetotheparty |
| truncated_history | 3 | Cannae, ferrariChampions2026, swisstony |

---

## 3. Residual List — Wallets Still Above 20%

All directional wallets not flagged as non-reconcilable, sorted by absolute residual:

| Wallet | Archetype | pm_pnl | total_pnl | Residual | Err% | Root Cause |
|---|---|---:|---:|---:|---:|---|
| swisstony | truncated_history | $23,631,587 | -$58,740 | -$23,690,327 | 100.2% | 30k position ceiling truncates 80k+ lifetime rows; only -$58k visible |
| ImJustKen | directional | $3,208,864 | -$10,332,788 | -$13,541,652 | 422.0% | 17,552 closed rows; systematic over-credit on minted legs persists |
| XAE12Archangel | directional | $357,128 | $2,511,929 | +$2,154,801 | 603.4% | Unredeemed winning tokens credited at $1.00 vs $0 cost |
| debased | directional | $1,484,909 | -$735,228 | -$2,220,137 | 149.5% | 7,435 closed rows; 789 synthetic legs dropped but residual remains |
| BreakTheBank | directional | $2,633,326 | $5,939,480 | +$3,306,154 | 125.6% | Over-credit from zeroing minted-leg cost while crediting winning leg at $1.00 |
| AnonymousUsername | directional | $905,351 | -$4,053,064 | -$4,958,416 | 547.7% | 7,835 closed rows; legacy phantom losses not fully cleaned |
| Anjun | directional | $884,868 | $1,830,422 | +$945,554 | 106.9% | 17,530 closed rows; over-credit on minted-pair accounting |
| wallet_2c33506 | directional | $7,753,611 | $5,853,357 | -$1,900,254 | 24.5% | Near-threshold; residual from multi-leg CTF mint activity |

---

## 4. Wallets That Remain Unreconciled — and Why

**Acceptance result:** FAIL (median 106.9%, target ≤ 20%; 5/12 within 20%, target ≥ 60%)

The 7 directional wallets above 20% residual fall into two structural categories that the current rules cannot close:

1. **Systematic over-credit on minted legs (BreakTheBank, XAE12Archangel, Anjun, wallet_2c33506):** When a wallet mints complete sets, the winning leg is credited at $1.00 redemption value while the losing leg's cost is zeroed. The net credit exceeds the actual economic result because the $1.00 credit includes profit from the *paired* losing leg that the CLOB never recorded a buy for. The synthetic-leg pairing in `rules.py` drops orphan legs but retains paired ones at their combined $1.00 cost — which is correct for the pair but still over-credits relative to `pm_pnl` because Polymarket's leaderboard uses account-level cash equity, not position-level summation.

2. **Historical truncation (swisstony, plus ferrariChampions2026 and debased as directional):** The `/closed-positions` API hard-caps at 30,000 rows. Wallets with 80k+ lifetime positions have the majority of their history invisible to position-level reconciliation. No amount of rule refinement can recover data the API does not expose.

3. **Deep phantom losses (AnonymousUsername, ImJustKen):** These wallets have 7,800–17,500 closed rows with large negative realized PnL that the cleaning rules reduced but did not eliminate. The residual comes from positions where `total_bought > 0` (so the zero-bought guard does not fire) but `realized_pnl` still reflects a phantom loss inflated by synthetic mint-cost estimates.

---

## 5. Test Results

```
31 passed in 0.13s
tests/test_pnl_rules.py — 17 passed
tests/test_pnl_reconcile.py — 14 passed
```

All unit tests for `src/pnl/rules.py` and `src/pnl/reconcile.py` pass.
