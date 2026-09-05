# Evidence-Backed Wallet Ledger Implementation Plan

> For agentic workers: required sub-skill: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax.

Goal: Make wallet position statistics evidence-backed: recover capped histories, retain but exclude proven false rows, and derive displayed PnL, win rate, and categories only from eligible rows.

Architecture: Keep wallet_closed_positions_v2 as the historical record. Add provenance and eligibility state; accounting snapshots establish complete current inventory, market-partitioned positions enrich it, and timestamp-windowed Activity supplies historical proof only for flagged wallets. A PostgreSQL-backed limiter coordinates every local worker before it calls Polymarket.

Tech Stack: Python 3.12, asyncio/aiohttp, asyncpg, PostgreSQL, Alembic, pytest.

---

## Decisions and safety invariants

- Ledger grain stays (address, condition_id, outcome); multiple genuine outcomes in one market are allowed.
- Existing rows stay metrics_eligible=TRUE until source evidence proves otherwise. A complementary price/quantity pattern is a review candidate, never a deletion rule.
- A proven false row becomes metrics_eligible=FALSE; it remains stored with reason, evidence, and timestamp. Normal position APIs and all derived metrics omit it.
- Positions cap: 10,500 direct rows. Use accounting snapshot (conditionId, asset) inventory then bounded positions market partitions.
- Closed positions cap: 100,050 direct rows. A capped fetch is incomplete. Recover by obtaining historical condition IDs from Activity and querying closed positions by small market CSV batches.
- pm_pnl is the official account-PnL comparison only; it never scales or overwrites the position ledger.
- Shared endpoint budgets: positions 15 rps, closed positions 15 rps, trades 20 rps, general Data API 90 rps. These per-IP budgets are shared across workers.

## File map

| File | Change |
|---|---|
| alembic/versions/<revision>_add_wallet_evidence_and_eligibility.py | Add row eligibility, source snapshot/evidence tables, shared rate-limit bucket. |
| src/utils/polymarket_rate_limit.py | PostgreSQL token bucket and 429 retry policy. |
| src/workers/wallet_trade_history.py | Use limiter; persist completeness; add closed-market partition recovery. |
| src/workers/wallet_provenance_audit.py | Complete Activity fetch, normalization, classification, and evidence persistence. |
| src/scripts/run_wallet_integrity_scan.py | Read-only all-wallet scan and priority roster. |
| src/scripts/run_wallet_provenance_audit.py | Explicit no-write targeted Activity audit CLI. |
| src/scripts/apply_position_eligibility.py | Explicit audited, transactional eligibility toggle. |
| src/workers/compute_core_metrics.py, compute_category_stats.py, compute_historical_windows.py | Apply shared eligibility predicate. |
| src/workers/positions_metrics_compute.py, win_rate_compute.py | Compatibility wrappers; no competing metric writer. |
| src/api/routers/wallets_v2.py | Hide ineligible rows from normal responses. |
| tests/test_polymarket_rate_limit.py, tests/test_wallet_provenance_audit.py, tests/test_position_eligibility_metrics.py | New focused coverage. |
| docs/CHANGELOG.md, docs/CORE_LOGIC.md, docs/learner.md | Required implementation documentation. |

### Task 1: Schema for provenance, audit decisions, and eligibility

Files:
- Create: alembic/versions/<revision>_add_wallet_evidence_and_eligibility.py
- Create: tests/test_position_eligibility_metrics.py

- [ ] Step 1: Write the failing schema test

    async def test_ineligible_row_is_retained(conn, seeded_wallet):
        await conn.execute(
            "UPDATE wallet_closed_positions_v2 SET metrics_eligible=FALSE, "
            "exclusion_reason='activity_proven_unpurchased_leg' "
            "WHERE address=$1 AND condition_id=$2 AND outcome='No'",
            seeded_wallet, CONDITION_ID,
        )
        row = await conn.fetchrow(
            "SELECT metrics_eligible, exclusion_reason FROM wallet_closed_positions_v2 "
            "WHERE address=$1 AND condition_id=$2 AND outcome='No'",
            seeded_wallet, CONDITION_ID,
        )
        assert row["metrics_eligible"] is False
        assert row["exclusion_reason"] == "activity_proven_unpurchased_leg"

- [ ] Step 2: Verify failure

Run: pytest tests/test_position_eligibility_metrics.py::test_ineligible_row_is_retained -v
Expected: FAIL because the columns do not exist.

- [ ] Step 3: Implement migration

Add columns to wallet_closed_positions_v2:
- metrics_eligible BOOLEAN NOT NULL DEFAULT TRUE
- exclusion_reason TEXT
- excluded_at TIMESTAMPTZ
- source_asset TEXT

Create:
- wallet_source_snapshots_v2(id BIGSERIAL PK, address TEXT, source TEXT, complete BOOLEAN, fetched_at TIMESTAMPTZ, payload_sha256 TEXT, metadata JSONB)
- wallet_position_evidence_v2(id BIGSERIAL PK, address TEXT, condition_id TEXT, asset TEXT, outcome TEXT, evidence_type TEXT, transaction_hash TEXT, snapshot_id BIGINT FK), indexed by address, condition_id, asset
- wallet_position_audit_decisions_v2(id BIGSERIAL PK, audit_id UUID, address TEXT, condition_id TEXT, outcome TEXT, status TEXT constrained to eligible/review_required/excluded_proven, reason TEXT, evidence_id BIGINT, created_at TIMESTAMPTZ)
- data_api_rate_limit_buckets(endpoint TEXT PK, tokens NUMERIC, updated_at TIMESTAMPTZ)

Include equivalent downgrade statements.

- [ ] Step 4: Apply and pass test

Run: alembic upgrade head; pytest tests/test_position_eligibility_metrics.py::test_ineligible_row_is_retained -v
Expected: PASS.

- [ ] Step 5: Commit

Run:
    git add alembic/versions/<revision>_add_wallet_evidence_and_eligibility.py tests/test_position_eligibility_metrics.py
    git commit -m "feat: add position evidence and eligibility schema"

### Task 2: Shared rate limiting and reliable incomplete handling

Files:
- Create: src/utils/polymarket_rate_limit.py
- Modify: src/workers/wallet_trade_history.py
- Modify: src/workers/polymarket_trade_backfiller.py
- Create: tests/test_polymarket_rate_limit.py

- [ ] Step 1: Write failing tests

    async def test_shared_bucket_waits_after_token_is_spent(pool):
        limiter = PostgresRateLimiter(pool, {"positions": (1.0, 1.0)})
        await limiter.acquire("positions")
        started = time.monotonic()
        await limiter.acquire("positions")
        assert time.monotonic() - started >= 0.9

    async def test_429_retries_before_marking_fetch_incomplete(monkeypatch):
        result = await fetch_positions(fake_session(statuses=[429, 200]), ADDRESS)
        assert result.complete is True

- [ ] Step 2: Verify failure

Run: pytest tests/test_polymarket_rate_limit.py -v
Expected: FAIL because the shared limiter does not exist.

- [ ] Step 3: Implement

Define PostgresRateLimiter.acquire(endpoint). In a transaction, select the endpoint bucket row FOR UPDATE, refill based on elapsed time, consume one token, commit, then sleep/retry if no token is available. Pass it to every source fetch. On 429 use Retry-After or 2/4/8-second retry; after final failure return complete=False. Never advance a sync timestamp from incomplete data.

- [ ] Step 4: Verify

Run: pytest tests/test_polymarket_rate_limit.py tests/test_closed_position_pagination.py -v
Expected: PASS.

- [ ] Step 5: Commit

Run:
    git add src/utils/polymarket_rate_limit.py src/workers/wallet_trade_history.py src/workers/polymarket_trade_backfiller.py tests/test_polymarket_rate_limit.py
    git commit -m "fix: coordinate Polymarket API rate limits"

### Task 3: Capped source recovery

Files:
- Modify: src/workers/wallet_trade_history.py
- Create: src/workers/wallet_provenance_audit.py
- Modify: tests/test_closed_position_pagination.py
- Create: tests/test_wallet_provenance_audit.py

- [ ] Step 1: Write failing tests

    async def test_closed_offset_ceiling_is_incomplete():
        rows, complete = await fetch_closed_positions(fake_full_pages_to_100000(), ADDRESS)
        assert complete is False
        assert len(rows) == 100050

    async def test_activity_condition_ids_drive_market_partition_recovery():
        activity = [{"conditionId": CID_A}, {"conditionId": CID_B}, {"conditionId": CID_C}]
        result = await recover_closed_by_activity_markets(fake_session(), ADDRESS, activity, batch_size=2)
        assert result.complete is True
        assert {row["conditionId"] for row in result.rows} == {CID_A, CID_B, CID_C}

- [ ] Step 2: Verify failure

Run: pytest tests/test_closed_position_pagination.py tests/test_wallet_provenance_audit.py -v
Expected: FAIL because recovery is absent.

- [ ] Step 3: Implement bounded recovery

Define SourceResult with rows, complete, source, and metadata. recover_closed_by_activity_markets obtains unique condition IDs from Activity, requests each CSV market batch at limit 50 until a short page, and returns complete=False for any failed partition, repeat, or its own offset cap.

Insert a source snapshot hash/completeness record for every accounting snapshot, positions response, closed positions response, and market partition recovery. Retain immutable raw ZIP/JSON in backtest_cache/source_snapshots/<address>/<timestamp>/.

- [ ] Step 4: Verify

Run: pytest tests/test_closed_position_pagination.py tests/test_position_snapshot_fallback.py tests/test_wallet_provenance_audit.py -v
Expected: PASS.

- [ ] Step 5: Commit

Run:
    git add src/workers/wallet_trade_history.py src/workers/wallet_provenance_audit.py tests/test_closed_position_pagination.py tests/test_wallet_provenance_audit.py
    git commit -m "feat: recover capped closed history by market"

### Task 4: Read-only integrity scan and Activity provenance classifier

Files:
- Create: src/scripts/run_wallet_integrity_scan.py
- Create: src/scripts/run_wallet_provenance_audit.py
- Modify: src/scripts/audit_position_activity_coverage.py
- Modify: src/workers/wallet_provenance_audit.py
- Modify: tests/test_wallet_provenance_audit.py

- [ ] Step 1: Write failing classifier tests

    def test_complementary_signature_requires_review_not_exclusion():
        decision = classify_row(db_row("Yes", 10, .60), [db_row("Up", 10, .40)], [])
        assert decision.status == "review_required"
        assert decision.reason == "complementary_unproven_signature"

    def test_matching_activity_buy_asset_makes_position_eligible():
        decision = classify_row(db_row("Up", 10, .40, asset="42"), [], [
            {"conditionId": CID, "asset": "42", "outcome": "Up", "type": "TRADE", "side": "BUY"},
        ])
        assert decision.status == "eligible"

    def test_equivalent_labels_do_not_produce_mismatch():
        assert normalize_outcome("Anyone's Legend") == normalize_outcome("Anyones Legend")

- [ ] Step 2: Verify failure

Run: pytest tests/test_wallet_provenance_audit.py -v
Expected: FAIL because classifier functions do not exist.

- [ ] Step 3: Implement audit behavior

Activity retrieval recursively splits start/end time windows at the 5,000-offset budget and deduplicates by transactionHash, type, conditionId, asset, timestamp, side, size, usdcSize. Persist immutable Activity evidence.

The integrity scan emits one record per wallet with address, ledger_pnl, metric_pnl, metric_delta, root_category_pnl, root_delta, closed_rows, positions_capped, closed_capped, review_candidate_rows, and requires_activity_audit.

requires_activity_audit is true only for incomplete/capped sources, internal ledger-versus-metric mismatch, or evidence candidates; it is not triggered only because pm_pnl differs.

Return excluded_proven only when Activity is complete and shows no normalized matching asset/outcome purchase or mint evidence for the candidate while an incompatible source chain is recorded. Label-only variation or incomplete API data remains review_required.

- [ ] Step 4: Verify no-write behavior

Run: pytest tests/test_wallet_provenance_audit.py -v
Expected: PASS.

Run: python -m src.scripts.run_wallet_integrity_scan --output backtest_cache/integrity_scan.json
Expected: report created; no canonical position or metric writes.

Run: python -m src.scripts.run_wallet_provenance_audit 0x03c3b0236c5a01051381482e77f2210349073a1d --output backtest_cache/likebot_provenance.json
Expected: source evidence and decisions created; no eligibility changes.

- [ ] Step 5: Commit

Run:
    git add src/scripts/run_wallet_integrity_scan.py src/scripts/run_wallet_provenance_audit.py src/scripts/audit_position_activity_coverage.py src/workers/wallet_provenance_audit.py tests/test_wallet_provenance_audit.py
    git commit -m "feat: add read-only wallet provenance audits"

### Task 5: Derive all displayed statistics from eligible rows

Files:
- Modify: src/workers/compute_core_metrics.py
- Modify: src/workers/compute_category_stats.py
- Modify: src/workers/compute_historical_windows.py
- Modify: src/workers/positions_metrics_compute.py
- Modify: src/workers/win_rate_compute.py
- Modify: src/api/routers/wallets_v2.py
- Modify: tests/test_position_eligibility_metrics.py
- Modify: tests/test_modular_workers.py

- [ ] Step 1: Write failing tests

    async def test_all_derived_metrics_skip_ineligible_rows(conn, seeded_wallet):
        await mark_row_ineligible(conn, seeded_wallet, CONDITION_ID, "No")
        core = await compute_core_metrics_for_wallet(conn, seeded_wallet)
        await compute_category_stats_for_wallet(conn, seeded_wallet)
        windows = await compute_historical_windows_for_wallet(conn, seeded_wallet)
        assert core["resolved_count"] == 1
        assert core["total_pnl"] == 12.0
        assert windows["pnl_100"] == 12.0

    async def test_closed_positions_api_hides_ineligible_row(client, seeded_wallet):
        response = await client.get("/api/v2/wallets/" + seeded_wallet + "/closed-positions")
        assert INELIGIBLE_CONDITION not in {p["conditionId"] for p in response.json()["positions"]}

- [ ] Step 2: Verify failure

Run: pytest tests/test_position_eligibility_metrics.py tests/test_modular_workers.py -v
Expected: FAIL because canonical queries include every row.

- [ ] Step 3: Implement one predicate and one writer path

Add AND COALESCE(c.metrics_eligible, TRUE) to every canonical core/category/window/API query. Make legacy metric modules call, in order: compute_core_metrics_for_wallet, compute_category_stats_for_wallet, then compute_historical_windows_for_wallet. They must not independently write wallet_metrics_v2. Public APIs must not expose an include_flagged option.

- [ ] Step 4: Verify

Run: pytest tests/test_position_eligibility_metrics.py tests/test_modular_workers.py tests/test_category_slug_classification.py -v
Expected: PASS.

- [ ] Step 5: Commit

Run:
    git add src/workers/compute_core_metrics.py src/workers/compute_category_stats.py src/workers/compute_historical_windows.py src/workers/positions_metrics_compute.py src/workers/win_rate_compute.py src/api/routers/wallets_v2.py tests/test_position_eligibility_metrics.py tests/test_modular_workers.py
    git commit -m "feat: compute wallet stats from eligible rows"

### Task 6: Reversible eligibility application and pilot rollout

Files:
- Create: src/scripts/apply_position_eligibility.py
- Modify: tests/test_position_eligibility_metrics.py
- Modify: docs/CHANGELOG.md
- Modify: docs/CORE_LOGIC.md
- Modify: docs/learner.md

- [ ] Step 1: Write failing apply tests

    async def test_apply_requires_proven_decision_and_recomputes(conn, seeded_wallet):
        audit_id = await create_decision(conn, seeded_wallet, CONDITION_ID, "No", "excluded_proven")
        await apply_eligibility(conn, audit_id, apply=True)
        assert await is_ineligible(conn, seeded_wallet, CONDITION_ID, "No")
        assert await metric_total_equals_eligible_ledger(conn, seeded_wallet)

    async def test_apply_rejects_review_required(conn, seeded_wallet):
        audit_id = await create_decision(conn, seeded_wallet, CONDITION_ID, "No", "review_required")
        with pytest.raises(ValueError, match="not proven"):
            await apply_eligibility(conn, audit_id, apply=True)

- [ ] Step 2: Verify failure

Run: pytest tests/test_position_eligibility_metrics.py -v
Expected: FAIL because application CLI does not exist.

- [ ] Step 3: Implement transactional application

The CLI defaults to dry-run and requires --apply and --audit-id. In one transaction: load only excluded_proven decisions, mark matching rows ineligible, recompute core/category/windows, and verify eligible-ledger PnL equals metric PnL and root category sum. Roll back on any failure. Print before/after eligible count, ledger PnL, win rate, category delta, and pm_pnl residual without modifying pm_pnl.

- [ ] Step 4: Pilot before fleet changes

Run the all-wallet integrity scan. Download accounting snapshots for the divergence roster and wallets at the 10,500 positions cap. Run Activity only for high-severity scan results, beginning with Likebot, BreakTheBank, and the next eight largest internal metric deltas. Review every excluded_proven decision. Apply only approved decisions in batches of ten wallets; stop on any nonzero post-apply ledger/metric or root-category delta.

- [ ] Step 5: Document and verify

Add required entries to the three documentation files: source caps, snapshot role, rate-limit coordination, evidence threshold, and retention/exclusion behavior.

Run:
    pytest tests/test_polymarket_rate_limit.py tests/test_closed_position_pagination.py tests/test_position_snapshot_fallback.py tests/test_wallet_provenance_audit.py tests/test_position_eligibility_metrics.py tests/test_modular_workers.py tests/test_safe_wallet_repair.py -v
    git diff --check

Expected: all focused tests PASS. Do not reformat unrelated existing dirty-worktree files.

- [ ] Step 6: Commit

Run:
    git add src/scripts/apply_position_eligibility.py tests/test_position_eligibility_metrics.py docs/CHANGELOG.md docs/CORE_LOGIC.md docs/learner.md
    git commit -m "feat: apply proven position exclusions safely"

## Plan self-review

- Coverage: Tasks 1/6 retain and quarantine bad rows; Task 2 addresses the API-limit report; Task 3 covers both 10,500-open and 100,050-closed caps; Task 4 keeps Activity targeted and proof-based; Task 5 repairs displayed statistics without forcing official PnL convergence.
- No forced PnL matching: pm_pnl is always diagnostic/account-level truth, never a scaling target.
- No destructive global action: every source audit is read-only; only explicitly proven rows can be excluded through a dry-run-first transactional CLI.
- Execution dependency: <revision> is generated by Alembic at implementation time; the Likebot audit ID is emitted by the pilot command.

