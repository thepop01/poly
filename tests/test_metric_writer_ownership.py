"""Task 1 ownership and safety guardrails."""

from pathlib import Path

import pytest

from src.scripts.metric_writer_audit import (
    CANONICAL_WRITERS,
    DISABLED_WRITERS,
    audit_writers,
    baseline,
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
    assert "src/scripts/backfill_window_stats.py" in DISABLED_WRITERS
    assert "src/scripts/recompute_all_category_stats.py" in DISABLED_WRITERS
    assert CANONICAL_WRITERS


def test_window_backfill_is_retired_without_indirect_leaderboard_import():
    source = (ROOT / "src/scripts/backfill_window_stats.py").read_text(encoding="utf-8")
    assert "from src.workers.leaderboard_stats" not in source
    assert "RETIRED_METRIC_REPAIR_NO_DB_ACCESS" in source
    import subprocess
    result = subprocess.run(
        ["python", "-m", "src.scripts.backfill_window_stats"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "RETIRED_METRIC_REPAIR_NO_DB_ACCESS" in result.stderr


def test_leaderboard_write_helpers_fail_closed_before_db_access(monkeypatch):
    import asyncio
    from src.workers import leaderboard_stats

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("database access occurred")

    monkeypatch.setattr(leaderboard_stats.asyncpg, "create_pool", fail_if_called)
    with pytest.raises(RuntimeError, match="retired"):
        asyncio.run(leaderboard_stats.process_wallet(object(), object(), "0xabc"))
    with pytest.raises(RuntimeError, match="retired"):
        asyncio.run(leaderboard_stats.run_leaderboard_stats("postgresql://unused"))


def test_sql_extractor_reports_upsert_update_columns():
    writes = extract_sql_writes(
        """INSERT INTO wallet_metrics_v2 (address, pm_pnl) VALUES ($1, $2)
        ON CONFLICT (address) DO UPDATE SET pm_pnl = EXCLUDED.pm_pnl;"""
    )
    assert writes[0]["table"] == "wallet_metrics_v2"
    assert "pm_pnl" in writes[0]["fields"]


def test_rogue_writer_is_rejected(tmp_path):
    path = tmp_path / "src" / "workers" / "rogue.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "async def write(conn):\n"
        "    await conn.execute('INSERT INTO wallet_metrics_v2 (address, total_pnl) VALUES ($1, $2)')\n",
        encoding="utf-8",
    )
    report = audit_writers(tmp_path)
    assert any(v["path"] == "src/workers/rogue.py" for v in report["violations"])


def test_disabled_writer_requires_retirement_marker(tmp_path):
    path = tmp_path / "src" / "scripts" / "audit_and_recalc_metrics.py"
    path.parent.mkdir(parents=True)
    path.write_text("UPDATE wallet_metrics_v2 SET total_pnl = 1", encoding="utf-8")
    report = audit_writers(tmp_path)
    assert any(v["kind"] == "retirement" for v in report["violations"])


class _FakeMetricConnection:
    def __init__(self, row=None):
        self.row = row or {"deposits": 1, "withdrawals": 2}
        self.executed = []

    async def fetchrow(self, query, *args):
        return self.row

    async def execute(self, query, *args):
        self.executed.append((query, args))



def test_capital_activity_pnl_is_ignored(monkeypatch):
    import asyncio
    import src.workers.capital_metrics_backfill as capital

    async def activity(_session, _address):
        return 10.0, 3.0, 999999.0

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(capital, "fetch_activity_deposits_withdrawals", activity)
    monkeypatch.setattr(capital.asyncio, "sleep", no_sleep)
    conn = _FakeMetricConnection()
    asyncio.run(capital.process_capital_metrics(conn, object(), "0xabc"))
    query, args = conn.executed[0]
    assert args == ("0xabc", 10.0, 3.0)
    assert "roi_pct" not in query and "total_pnl" not in query



def test_official_sync_only_publishes_pm_snapshot(monkeypatch):
    import asyncio
    import src.workers.pnl_balance_refetch as official

    async def leaderboard(_session, _address):
        return {"pnl": 12.0, "volume": 34.0, "rank": 5, "username": ""}

    monkeypatch.setattr(official, "fetch_leaderboard_stats", leaderboard)
    conn = _FakeMetricConnection()
    asyncio.run(official.process_wallet_pnl_balance(conn, object(), "0xabc"))
    query, args = conn.executed[0]
    assert args == ("0xabc", 12.0, 34.0, 5)
    assert "computed_at" not in query and "capital_synced_at" not in query


class _FakeBaselineConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append(("execute", query))

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query))
        if "to_regclass" in query:
            return True
        if "information_schema.columns" in query:
            return 0
        return 0

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query))
        if "information_schema.columns" in query:
            return []
        return []

    async def close(self):
        self.calls.append(("close",))


async def _fake_connect(_url):
    return _FakeBaselineConnection()


def test_baseline_uses_read_only_transaction_and_rolls_back(monkeypatch, tmp_path):
    import asyncpg
    fake = _FakeBaselineConnection()

    async def connect(_url):
        return fake

    monkeypatch.setattr(asyncpg, "connect", connect)
    import asyncio
    result = asyncio.run(baseline("postgresql://test", tmp_path / "baseline.json"))
    executed = [call[1] for call in fake.calls if call[0] == "execute"]
    assert "BEGIN TRANSACTION READ ONLY" in executed
    assert "ROLLBACK" in executed
    assert result["read_only"] is True
