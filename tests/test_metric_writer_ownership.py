"""Task 1 ownership and safety guardrails."""

from pathlib import Path

from src.scripts.metric_writer_audit import (
    CANONICAL_WRITERS,
    DISABLED_WRITERS,
    audit_writers,
    extract_sql_writes,
)


ROOT = Path(__file__).resolve().parents[1]


def test_static_writer_audit_has_no_noncanonical_internal_writers():
    report = audit_writers(ROOT)
    assert report["violations"] == []


def test_legacy_repair_is_not_present_as_an_active_resolved_count_repair():
    source = (ROOT / "src/scripts/audit_and_recalc_metrics.py").read_text(encoding="utf-8")
    assert "SET resolved_count = winning_count" not in source
    assert "SET resolved_count = GREATEST" not in source


def test_capital_worker_does_not_consume_official_or_activity_pnl_for_roi():
    source = (ROOT / "src/workers/capital_metrics_backfill.py").read_text(encoding="utf-8")
    assert "pm_pnl" not in source
    assert "effective_pnl" not in source
    assert "roi_pct" not in source.split("async def process_capital_metrics", 1)[1]
    assert "_activity_pnl" in source


def test_official_sync_does_not_touch_internal_freshness_or_category_rows():
    source = (ROOT / "src/workers/poly_leaderboard_sync.py").read_text(encoding="utf-8")
    assert "computed_at = NOW()" not in source
    assert "INSERT INTO category_stats_v2" not in source
    assert "pm_synced_at" in source


def test_legacy_category_and_leaderboard_writers_are_explicitly_disabled():
    assert "src/workers/leaderboard_stats.py" in DISABLED_WRITERS
    assert "src/scripts/recompute_all_category_stats.py" in DISABLED_WRITERS
    assert CANONICAL_WRITERS


def test_sql_extractor_reports_upsert_update_columns():
    writes = extract_sql_writes(
        """INSERT INTO wallet_metrics_v2 (address, pm_pnl) VALUES ($1, $2)
        ON CONFLICT (address) DO UPDATE SET pm_pnl = EXCLUDED.pm_pnl;"""
    )
    assert writes[0]["table"] == "wallet_metrics_v2"
    assert "pm_pnl" in writes[0]["fields"]
