# Task 3 migration contract report

## Status

Implemented the ledger analytics migration follow-up in the isolated worktree. The revision now attaches to the actual parent Alembic head and remains a single-head graph.

## Changes

- Rebuilt the additive Task 3 change directly on parent `5f590f0`; all existing parent migrations are preserved. Revision `b1c2d3e4f5a6` follows the actual parent head `a0b1c2d3e4f5`. Replay fixtures stamp at that head before running the target upgrade and downgrade.
- Reordered upgrade convergence so the historical four-column `category_stats_v2` key is safely converted to the league-aware five-column key before base-contract validation; unknown uniqueness constraints/indexes still fail closed.
- Exact token identity accepts PostgreSQL `TEXT` and bounded `VARCHAR(n)` / `character varying(n)` catalog forms, while rejecting numeric and unbounded character-varying storage. Nullable/no-default requirements remain enforced.
- Added focused validator tests for accepted/rejected catalog types and nullability/default violations.
- The opt-in PostgreSQL replay test already executes the real Alembic graph for clean and historical league-modified fixtures, checks upgrade/downgrade catalog contracts, ownership, retained base objects, removed owned objects, and leading-zero/long-token round trips. Its downgrade target now follows the actual parent head.

## Verification

- `python -m pytest tests/test_migration_contract.py -q` — 10 passed, 1 opt-in PostgreSQL replay test skipped because `MIGRATION_TEST_DATABASE_URL` is not configured.
- `python -m compileall -q alembic/versions/b1c2d3e4f5a6_add_ledger_analytics_schema.py src/scripts/migrate_add_league.py` — passed.
- Alembic graph inspection — `b1c2d3e4f5a6` is the sole head after `a0b1c2d3e4f5`; parent migration inventory is unchanged.
- No production database migration was run.

## Concerns

The PostgreSQL replay remains opt-in and was not executable without a disposable PostgreSQL URL. The parent graph files are intentionally included because the target revision references `a0b1c2d3e4f5`; omitting them would leave an unusable revision graph when cherry-picked.

## Commit

Follow-up fixes verified and committed with the required co-author trailer. PostgreSQL replay remains skipped because `MIGRATION_TEST_DATABASE_URL` is not configured.
