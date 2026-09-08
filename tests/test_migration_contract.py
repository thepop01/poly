"""Contract tests for the replayable ledger analytics migration.

These checks are database-free by default.  The SQL fixtures document the two
supported starting shapes; an integration job can execute each fixture and run
Alembic upgrade/downgrade against PostgreSQL.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "b1c2d3e4f5a6_add_ledger_analytics_schema.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("ledger_schema_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_is_after_actual_current_head_and_graph_has_one_head():
    module = _load_migration()
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert module.down_revision == "a0b1c2d3e4f5"
    assert scripts.get_current_head() == module.revision
    assert list(scripts.get_heads()) == [module.revision]


def test_required_columns_cover_supported_v2_contract():
    module = _load_migration()
    required = module.REQUIRED_COLUMNS

    assert set(required["markets_v2"]) >= {"category", "subcategory", "league", "event_slug"}
    assert set(required["category_stats_v2"]) >= {
        "subcategory", "league", "window_size", "pnl", "volume", "win_rate",
        "roi_pct", "resolved_count", "winning_count", "last_active", "computed_at",
    }
    assert set(required["wallet_closed_positions_v2"]) >= {
        "is_parlay", "is_redeemable", "resolved_at", "data_quality_flag",
        "metrics_eligible", "source_realized_pnl", "ledger_cost_basis",
        "ledger_volume_usd", "ledger_settlement_value", "ledger_pnl",
        "ledger_formula_version", "ledger_provenance_version", "settlement_included",
        "ledger_computed_at", "normalized_parlay_key",
    }
    metric_columns = set(required["wallet_metrics_v2"])
    assert {f"pnl_{size}" for size in (100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000)} <= metric_columns
    assert {"computed_at", "categories_computed_at", "open_synced_at", "closed_synced_at", "capital_synced_at"} <= metric_columns
    for bucket in ("below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c"):
        assert {f"{kind}_{bucket}" for kind in ("buys", "wins", "losses", "avg_sell")} <= metric_columns


def test_migration_has_additive_guards_and_concurrent_index_autocommit():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '"asset_token_id": "TEXT"' in text
    assert "numeric legacy values cannot recover leading zeros" in text
    assert "ADD COLUMN IF NOT EXISTS" in text
    assert "CREATE TABLE IF NOT EXISTS wallet_metric_windows_v2" in text
    assert "CREATE TABLE IF NOT EXISTS official_category_stats_v2" in text
    assert "CREATE TABLE IF NOT EXISTS ledger_backfill_runs_v2" in text
    assert "CREATE TABLE IF NOT EXISTS ledger_backfill_checkpoints_v2" in text
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in text
    assert "op.get_context().autocommit_block()" in text
    assert "has duplicate canonical identities" in text
    assert "incompatible category_stats_v2 uniqueness constraint" in text


def test_fixture_shapes_are_present_and_distinct():
    clean = ROOT / "tests" / "fixtures" / "migration_clean_schema.sql"
    league = ROOT / "tests" / "fixtures" / "migration_league_modified_schema.sql"
    assert clean.is_file()
    assert league.is_file()
    clean_text = clean.read_text(encoding="utf-8")
    league_text = league.read_text(encoding="utf-8")
    assert "CREATE TABLE wallets_v2" in clean_text
    assert "tier VARCHAR(20) NOT NULL DEFAULT 'UNCLASSIFIED'" in clean_text
    assert "tier VARCHAR(20) NOT NULL DEFAULT 'UNCLASSIFIED'" in league_text
    assert "is_dormant BOOLEAN DEFAULT FALSE" in clean_text
    assert "status VARCHAR(20) DEFAULT 'ACTIVE'" in clean_text
    assert "total_pnl NUMERIC DEFAULT 0" in clean_text
    assert "total_volume NUMERIC DEFAULT 0" in clean_text
    assert "total_pnl NUMERIC DEFAULT 0" in league_text
    assert "total_volume NUMERIC DEFAULT 0" in league_text
    assert "pnl NUMERIC DEFAULT 0" in clean_text
    assert "league VARCHAR(100) DEFAULT ''" in league_text
    assert "PRIMARY KEY (address, category, subcategory, league, window_size)" in league_text
    assert "asset_token_id NUMERIC" not in clean_text
    assert "asset_token_id NUMERIC" not in league_text
    assert clean_text != league_text


def test_legacy_wrapper_only_validates_and_delegates(monkeypatch: pytest.MonkeyPatch):
    from src.scripts import migrate_add_league

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/poly_db")
    calls: list[tuple[list[str], dict]] = []

    def fake_call(command, **kwargs):
        calls.append((command, kwargs))
        return 0

    monkeypatch.setattr(subprocess, "call", fake_call)
    assert migrate_add_league.migrate() == 0
    assert calls
    command, kwargs = calls[0]
    assert command[-4:] == ["-m", "alembic", "upgrade", "head"]
    assert kwargs["cwd"] == migrate_add_league.ROOT
    assert kwargs["env"]["DATABASE_URL"].startswith("postgresql://")
    assert "asyncpg" not in migrate_add_league.__dict__
    assert "subprocess" in Path(migrate_add_league.__file__).read_text(encoding="utf-8")


def test_legacy_wrapper_rejects_non_postgres_url(monkeypatch: pytest.MonkeyPatch):
    from src.scripts import migrate_add_league

    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/not-production.db")
    with pytest.raises(SystemExit, match="PostgreSQL"):
        migrate_add_league.migrate()


def test_legacy_wrapper_rejects_unvalidated_extra_args(monkeypatch: pytest.MonkeyPatch):
    from src.scripts import migrate_add_league

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/poly_db")
    with pytest.raises(SystemExit, match="unsupported arguments"):
        migrate_add_league.migrate(["downgrade", "-1"])


def test_migration_tracks_preexisting_objects_for_safe_downgrade():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "ledger_schema_objects_v2" in text
    assert "preexisting" in text
    assert "cannot safely downgrade ledger analytics schema" in text
    assert "_owned_objects" in text


def test_exact_token_identity_accepts_text_and_bounded_varchar_but_not_numeric(monkeypatch):
    module = _load_migration()
    for type_name in ("text", "character varying(255)", "varchar(255)"):
        monkeypatch.setattr(
            module,
            "_catalog_columns",
            lambda _table, type_name=type_name: {
                "asset_token_id": (module._normalize_catalog_type(type_name), False, None)
            },
        )
        module._assert_exact_token_identity("wallet_positions_v2")

    for type_name in ("numeric", "character varying"):
        monkeypatch.setattr(
            module,
            "_catalog_columns",
            lambda _table, type_name=type_name: {
                "asset_token_id": (module._normalize_catalog_type(type_name), False, None)
            },
        )
        with pytest.raises(RuntimeError, match="exact-identity type"):
            module._assert_exact_token_identity("wallet_positions_v2")


def test_index_contract_rejects_invalid_index(monkeypatch):
    module = _load_migration()
    class Result:
        def first(self):
            return ("idx", "CREATE INDEX idx ON public.t (x)", False)
    class Bind:
        def execute(self, *_args, **_kwargs):
            return Result()
    monkeypatch.setattr(module.op, "get_bind", lambda: Bind())
    with pytest.raises(RuntimeError, match="invalid"):
        module._assert_index_contract("idx", "t", "CREATE INDEX idx ON public.t USING btree (x)")


def test_exact_token_identity_preserves_nullable_no_default_contract(monkeypatch):
    module = _load_migration()
    for notnull, default in ((True, None), (False, "'0'::text")):
        monkeypatch.setattr(
            module,
            "_catalog_columns",
            lambda _table, notnull=notnull, default=default: {
                "asset_token_id": ("text", notnull, default)
            },
        )
        with pytest.raises(RuntimeError, match="nullable with no default"):
            module._assert_exact_token_identity("wallet_positions_v2")


@pytest.mark.skipif(
    not os.environ.get("MIGRATION_TEST_DATABASE_URL"),
    reason="set MIGRATION_TEST_DATABASE_URL to run PostgreSQL migration replay",
)
def test_postgres_replay_and_downgrade():
    """Replay each isolated fixture through Alembic and verify the contract.

    The test intentionally uses one disposable database and resets ``public``
    between cases.  It executes the real graph rather than importing and
    calling the target revision, then downgrades only the target revision.
    """
    pytest.importorskip("asyncpg")
    import asyncio
    import asyncpg

    database_url = os.environ["MIGRATION_TEST_DATABASE_URL"]

    def alembic(*args: str) -> None:
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} failed\\nstdout:\\n{result.stdout}\\nstderr:\\n{result.stderr}"
        )

    async def run() -> None:
        conn = await asyncpg.connect(database_url)
        try:
            for fixture_name in (
                "migration_clean_schema.sql",
                "migration_league_modified_schema.sql",
            ):
                await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
                fixture = (ROOT / "tests" / "fixtures" / fixture_name).read_text(
                    encoding="utf-8"
                )
                await conn.execute(fixture)
                await conn.close()
                # Fixtures represent the schema immediately before this
                # revision. Stamp that intended starting point instead of
                # replaying unrelated historical/destructive revisions into
                # pre-created fixture tables, then execute the real target
                # upgrade and downgrade.
                alembic("stamp", "a0b1c2d3e4f5")
                alembic("upgrade", "head")
                conn = await asyncpg.connect(database_url)

                # Exact-string identity must preserve both leading zeros and a
                # token longer than NUMERIC precision without normalization.
                long_token = "000" + "9" * 140
                await conn.execute(
                    """
                    INSERT INTO wallet_positions_v2
                        (address, condition_id, outcome, asset_token_id)
                    VALUES ('0xidentity', 'condition-identity', 'YES', $1)
                    """,
                    long_token,
                )
                token = await conn.fetchval(
                    """
                    SELECT asset_token_id FROM wallet_positions_v2
                    WHERE address = '0xidentity'
                    """,
                )
                assert token == long_token

                for table in ("wallet_positions_v2", "wallet_closed_positions_v2"):
                    catalog = await conn.fetchrow(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod) AS type_name,
                               a.attnotnull,
                               pg_get_expr(d.adbin, d.adrelid) AS default_expr
                        FROM pg_attribute a
                        JOIN pg_class t ON t.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = t.relnamespace
                        LEFT JOIN pg_attrdef d
                          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                        WHERE n.nspname = 'public' AND t.relname = $1
                          AND a.attname = 'asset_token_id'
                        """,
                        table,
                    )
                    assert catalog["type_name"] == "text"
                    assert catalog["attnotnull"] is False
                    assert catalog["default_expr"] is None

                pk = await conn.fetchval(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'category_stats_v2'::regclass AND contype = 'p'
                    """
                )
                assert pk == "PRIMARY KEY (address, category, subcategory, league, window_size)"

                index_def = await conn.fetchval(
                    "SELECT pg_get_indexdef('idx_closed_ledger_backfill_v2'::regclass::oid)"
                )
                assert index_def == (
                    "CREATE INDEX idx_closed_ledger_backfill_v2 ON public.wallet_closed_positions_v2 "
                    "USING btree (address, closed_at DESC, condition_id, outcome)"
                )

                owned = await conn.fetch(
                    """
                    SELECT object_name, object_kind, created_by_revision, preexisting
                    FROM ledger_schema_objects_v2
                    WHERE created_by_revision = 'b1c2d3e4f5a6'
                    ORDER BY object_name
                    """
                )
                owned_by_name = {row["object_name"]: row for row in owned}
                for object_name, object_kind in (
                    ("wallet_metric_windows_v2", "table"),
                    ("official_category_stats_v2", "table"),
                    ("ledger_backfill_runs_v2", "table"),
                    ("ledger_backfill_checkpoints_v2", "table"),
                    ("idx_closed_ledger_backfill_v2", "index"),
                ):
                    assert owned_by_name[object_name]["object_kind"] == object_kind
                    assert owned_by_name[object_name]["preexisting"] is False

                alembic("downgrade", "a0b1c2d3e4f5")
                conn = await asyncpg.connect(database_url)
                for table in (
                    "wallets_v2",
                    "markets_v2",
                    "wallet_positions_v2",
                    "wallet_closed_positions_v2",
                    "ledger_schema_objects_v2",
                ):
                    assert await conn.fetchval(
                        "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                    )
                for table in (
                    "wallet_metric_windows_v2",
                    "official_category_stats_v2",
                    "ledger_backfill_runs_v2",
                    "ledger_backfill_checkpoints_v2",
                ):
                    assert not await conn.fetchval(
                        "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                    )
                assert not await conn.fetchval(
                    "SELECT to_regclass('public.idx_closed_ledger_backfill_v2') IS NOT NULL"
                )
        finally:
            await conn.close()

    asyncio.run(run())
