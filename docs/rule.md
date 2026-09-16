# Operations Runbook

*Last updated: 2026-09-02*

This is the operator guide for refreshing positions, collecting evidence, and publishing wallet metrics. The local database is the value displayed by the application; Polymarket data is the comparison source of truth. A mismatch is evidence to investigate, never a reason to force values to match.

## Pipeline and worker names

Run the phases in this order. Open and closed position refreshes may run in parallel; evidence analysis must wait for both the Activity snapshot and lineage baseline.

| Logical phase | Standalone worker | Orchestrator label |
|---|---|---|
| Open positions | `positions_open_backfill` | Worker 1 |
| Closed positions | `positions_closed_backfill` | Worker 2 |
| Activity snapshot (Worker 3) | `activity_backfiller_worker` | Worker 15 / 3 |
| Activity/position analysis (Worker 4) | `activity_analyzer_worker` | Worker 16 / 4 |
| Derived metrics | `positions_metrics_compute` | Worker 3 |
| Last-activity recovery | `last_trade_sweeper` | Worker 10 |
| Historical lineage scans | Paused — retained evidence only | Not supervised |

The logical “Worker 3/4” wording used in investigations means Activity source/analyzer; the orchestrator labels are shown above to avoid starting the wrong process.

## Standard start procedure (PowerShell)

Use one terminal per long-running worker, or run the orchestrator once. Do not start a standalone worker and the same orchestrator worker at the same time.

```powershell
cd D:\project\poly
alembic upgrade head
python -m src.workers.positions_open_backfill
python -m src.workers.positions_closed_backfill
python -m src.workers.activity_backfiller_worker --loop
python -m src.workers.activity_analyzer_worker --loop
python -m src.workers.last_trade_sweeper
```

For a complete deployment, use `python -m src.orchestrator` instead of duplicating these commands. Keep each process's stdout/stderr in `logs/`; never commit logs, `backtest_cache/`, or `backtest/_cache/`.

## Scheduling rules

- Open and closed sources are eligible when their source timestamp is missing or older than 48 hours, including hibernated wallets.
- Activity backfill (Worker 3A) considers only the approved divergence queue (at least $10,000, or at least $1,000 and 10%). It stages the snapshot and does not prune it before analysis.
- Historical lineage transfer scans are paused. Existing transfer evidence remains available as optional provenance but never blocks a wallet.
- Activity analysis (Worker 4) runs when `pending_snapshot_id` exists. It writes classifications, reconciliations, and exception evidence, then retains the newest 500 raw Activity events as a hot cache.
- The last-activity sweeper checks active and hibernated wallets every three hours. It wakes a wallet only from a real recent `/activity` timestamp; missing or old responses do not imply a trade.
- Lineage materialization is resumable and should remain uncapped. Normal CLOB trades retain only the newest 600 rows per wallet; this cap never applies to lineage transfers or funding evidence.

## Data-integrity rules

1. Apply migrations before workers. A source fetch that hits an API completeness boundary remains incomplete (`*_synced_at` is not advanced); retry or use the deep-history recovery path.
2. Do not delete or rewrite position rows solely because Activity differs. Preserve the row and evidence, classify it (`ok`, `non_trade`, `differs`, or `absent`), and review before changing metric eligibility.
3. Match transfer provenance by exact `source_asset` token ID plus transaction/log identity. A wallet-level USDC transfer does not prove acquisition of a market position and must not create cost basis.
4. Treat `/activity` as event evidence, not a replacement for the position ledger. Recursive pagination/bisection is required at the API boundary; the 500-event cache is not a complete history.
5. Do not combine opposite outcome legs merely to improve PnL. This changes win-rate denominators and can preserve fabricated complementary rows.
6. Metrics are computed from eligible canonical position/lineage data. Activity may explain a discrepancy, but it does not silently override PnL, ROI, or win rate.
7. Hibernation is metadata, not deletion. Position refreshes include dormant rows; Activity divergence work may wait until the sweeper finds fresh activity.

## Inspecting progress

```powershell
Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match 'positions_|activity_|sweeper|lineage_'} |
  Select-Object ProcessId,CommandLine
Get-Content logs\w3_activity_lineage.log -Tail 40
Get-Content logs\w4_activity_analyzer.log -Tail 40
```

Useful database checks are the 48-hour freshness counts for open/closed sources, three-hour sweeper progress, Activity scan state (`baseline_complete`, `pending_snapshot_id`), and lineage materialization cursor. A zero analyzer queue is normal when staged wallets are still waiting for lineage.

## Single-wallet analysis and recovery

Use the audit script for a read-only investigation (write an output under `scratch/evidence/`):

```powershell
python -m src.scripts.audit_position_activity_coverage 0xWALLET --output scratch\evidence\wallet.json
```

For production batches, use Workers 3/4 so the exact staged snapshot is paired with its analysis. Use deep closed-history recovery only for a capped/incomplete position source or a material divergence; never mark a partial API page complete. Review eligibility changes with the dry-run mode of `apply_position_eligibility` before applying them.

## Capacity and troubleshooting

Defaults are 100-way wallet concurrency for position and Activity snapshot workers, 20-way concurrency / 100-wallet batches for full-snapshot analysis, a 140+ database pool, Activity HTTP concurrency 50, and sweeper concurrency 30. Check PostgreSQL `max_connections`, active sessions, and API limiter capacity before increasing them. Connection timeouts mean reduce concurrency and retry; they are not proof that data is complete. If analysis is stuck, inspect snapshot size and database waits rather than retrying the historical lineage scan.

Before declaring a refresh complete, run `pytest -q`, verify `alembic current`, inspect worker error logs, and confirm ignored caches with `git status --ignored`. Keep investigations and generated reports in `scratch/`, not in maintained source directories.
