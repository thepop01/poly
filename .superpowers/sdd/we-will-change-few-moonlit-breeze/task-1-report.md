# Task 1 implementation report

## Files changed

- `src/scripts/metric_writer_audit.py` — durable static ownership audit and optional read-only baseline snapshot.
- `tests/test_metric_writer_ownership.py` — focused ownership, safety, and disabled-writer tests.
- `src/workers/capital_metrics_backfill.py` — capital/deposit/withdrawal-only writes; Activity API PnL is retained only as an ignored raw observation.
- `src/workers/compute_core_metrics.py` — internal totals are derived only from eligible closed position rows; no `pm_*` fallback.
- `src/workers/positions_open_backfill.py` — source worker no longer overwrites capital `balance` or internal unrealized PnL.
- `src/workers/stats_refresher.py` — capital refresh no longer overwrites open-position `position_value`.
- `src/workers/poly_leaderboard_sync.py` — official sync writes only `pm_*` and `pm_synced_at`; official category snapshots are skipped pending the Task 2 table.
- `src/scripts/audit_and_recalc_metrics.py` — count repairs are diagnostics only; removed the `resolved_count = winning_count` repair and equivalent category/subcategory repairs.
- `src/scripts/backfill_missing_wins.py`, `src/scripts/backfill_position_value.py`, `src/scripts/backfill_zero_pnl_balance.py` — hard-disabled overlapping legacy mutators with migration-path errors.

No production migration or database write was run.

## Ownership map

| Area | Owner | Fields / scope |
| --- | --- | --- |
| Source workers | `positions_open_backfill.py`, `positions_closed_backfill.py`, `positions_winrate_backfill.py` | Raw open/closed positions, source evidence, `metrics_eligible` and source freshness (`open_synced_at`, `closed_synced_at`); open source may maintain position-side evidence but not canonical totals. |
| Canonical coordinator | `positions_metrics_compute.py` via `compute_core_metrics.py`, `compute_category_stats.py`, and `compute_historical_windows.py` | Internal totals, ROI, win/resolved counts, price buckets, parlay metrics, categories, subcategories/leagues, and windows. Counts are reconstructed from eligible source rows. |
| Capital synchronization | `capital_metrics_backfill.py`, `stats_refresher.py` | `balance`, `deposits`, `withdrawals`, capital cursor; no `total_pnl`, `total_volume`, `roi_pct`, counts, or category fields. |
| Official synchronization | `poly_leaderboard_sync.py`, `pnl_balance_refetch.py` and official snapshot paths | `pm_pnl`, `pm_volume`, `pm_rank`, and `pm_synced_at` only. Official category rows are not written into canonical `category_stats_v2`; separate snapshots are deferred to Task 2. |

The static audit treats legacy category/recompute scripts and `leaderboard_stats.py` as disabled and exits nonzero if any enabled noncanonical writer updates canonical fields.

## Constrained writers and safety changes

- Removed Activity API/official PnL fallback from capital ROI logic; the capital worker no longer writes `roi_pct` at all.
- Removed the resolved-count repair in `audit_and_recalc_metrics.py`; category and subcategory repair statements are no-op diagnostic statements rather than count mutation.
- Disabled legacy `backfill_missing_wins`, `backfill_position_value`, and `backfill_zero_pnl_balance` entry points. Their error messages identify the canonical/source owner.
- Replaced official leaderboard `computed_at` updates with `pm_synced_at` and disabled writes to `category_stats_v2`.
- Prevented source open-position and capital refresher workers from clobbering capital or canonical internal fields.

## Baseline command and output

Static baseline/audit command:

```text
python -m src.scripts.metric_writer_audit audit
```

Output verification: `violations=0`, `writers=25` (JSON output was inspected and not committed as an artifact).

Read-only database baseline command:

```text
python -m src.scripts.metric_writer_audit baseline --database-url "$DATABASE_URL" --output artifacts/metric-baseline.json
```

Database access was unavailable in this worktree: no `DATABASE_URL` was configured, and the command refused to run (`baseline requires --database-url or DATABASE_URL; no credentials are embedded`). The baseline implementation requires an explicit URL, starts a `READ ONLY` transaction, rolls it back, and writes only an external JSON artifact. It captures internal and official checksums, category windows, duplicate identities, null freshness timestamps, stale count wallets, flagged-but-eligible rows, incomplete histories, and wallets above 5,000 closed rows when the corresponding tables/columns exist.

## Tests run

- `python -m pytest -q tests/test_metric_writer_ownership.py` — 6 passed.
- `python -m pytest -q tests/test_ledger_metrics.py tests/test_pnl_reconcile.py tests/test_pnl_rules.py tests/test_metric_writer_ownership.py` — 71 passed.
- `python -m compileall -q` on all changed Python modules — passed.
- `python -m src.scripts.metric_writer_audit audit` — passed with zero violations.
- `python -m pytest -q tests/test_safe_wallet_repair.py tests/test_audit_fixes.py tests/test_modular_workers.py` — 12 passed, 1 pre-existing unrelated failure in `tests/test_audit_fixes.py::test_is_parlay_heuristics` (`wallets_v2._is_parlay_position` classifies a title containing “AND” as parlay).

## Remaining concerns

1. The database baseline could not be populated without explicit operator database configuration; no production tables were touched.
2. Several historical scripts remain in the repository for auditability but are hard-disabled or listed as disabled by the static audit. They should be deleted or removed from deployment scheduling after the migration plan is complete.
3. `category_stats_v2` official snapshots are intentionally skipped until Task 2 supplies a separate table.
4. The unrelated existing parlay heuristic test failure remains outside Task 1 scope.
5. Dynamic SQL outside the static extractor's patterns requires manual review; the audit reports recognized SQL writes conservatively.
