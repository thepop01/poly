"""Contract and behavioural tests for revision ``c2d3e4f5a6b7``.

Two layers:

* database-free contract tests that pin the declared schema/ownership contract
  and the pure catalog helpers;
* PostgreSQL replay tests that execute the real Alembic revision against a real
  server and exercise the trigger semantics.  Trigger behaviour is never
  asserted by reading the migration source; it is asserted by running SQL.

Set ``MIGRATION_TEST_DATABASE_URL`` to a disposable PostgreSQL database to run
the replay layer.  The ``public`` schema of that database is dropped and
recreated repeatedly, so it must never point at production.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Iterable

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    ROOT
    / "alembic"
    / "versions"
    / "c2d3e4f5a6b7_add_position_identity_and_lifecycle_provenance.py"
)
FIXTURES = ROOT / "tests" / "fixtures"

BASE_FIXTURE = "migration_identity_base_schema.sql"
PREREQ_FIXTURE = "migration_identity_prereq_schema.sql"
MALFORMED_FIXTURE = "migration_identity_malformed_schema.sql"

DATABASE_URL = os.environ.get("MIGRATION_TEST_DATABASE_URL")
requires_postgres = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set MIGRATION_TEST_DATABASE_URL to run the PostgreSQL replay layer",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "identity_provenance_migration", MIGRATION_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Database-free contract tests
# ---------------------------------------------------------------------------


def test_revision_follows_the_analytics_schema_and_graph_has_one_head():
    module = _load_migration()
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))

    assert module.revision == "c2d3e4f5a6b7"
    assert module.down_revision == "b1c2d3e4f5a6"
    # The whole graph the replay tests execute must be present and unambiguous.
    assert list(scripts.get_heads()) == [module.revision]
    assert scripts.get_current_head() == module.revision
    ancestors = {script.revision for script in scripts.walk_revisions()}
    # wallet_source_snapshots_v2 is reused from this ancestor, never recreated
    # under a second name.
    assert "m6n7o8p9q0r1" in ancestors
    assert "b1c2d3e4f5a6" in ancestors


def test_snapshot_table_is_reused_and_never_duplicated():
    module = _load_migration()
    assert module.SNAPSHOT_TABLE == "wallet_source_snapshots_v2"
    created_tables = {module.EVIDENCE_TABLE, module.DECISION_TABLE}
    assert module.SNAPSHOT_TABLE not in created_tables
    # No second snapshot-shaped table is introduced by this revision.
    assert not any("source_snapshot" in name for name in created_tables)


def test_declared_lifecycle_contract_is_explicit_and_minimal():
    module = _load_migration()

    assert module.PROVENANCE_KINDS == ("ordinary", "redeemable", "synthetic")
    assert module.LIFECYCLE_STATES == (
        "ordinary",
        "redeemable",
        "redeemed",
        "expired",
        "superseded",
    )
    assert module.TERMINAL_LIFECYCLE_STATES == ("redeemed", "expired", "superseded")
    assert module.DECISION_STATUSES == (
        "eligible",
        "review_required",
        "excluded_proven",
    )

    transitions = set(module.LIFECYCLE_TRANSITIONS)
    assert transitions == {
        ("ordinary", "redeemable"),
        ("ordinary", "superseded"),
        ("redeemable", "redeemed"),
        ("redeemable", "expired"),
        ("redeemable", "superseded"),
    }
    # Monotonic: no transition may leave a terminal state and none is a self
    # loop, so a replayed transition is idempotent rather than cyclic.
    for source, target in transitions:
        assert source not in module.TERMINAL_LIFECYCLE_STATES
        assert source != target
        assert source in module.LIFECYCLE_STATES
        assert target in module.LIFECYCLE_STATES

    # Synthetic provenance must be justified by explicit ledger events only.
    assert {"mint", "split", "merge", "transfer"} <= set(module.EVIDENCE_TYPES)


def test_provenance_columns_are_nullable_with_no_backfill_default():
    module = _load_migration()

    assert set(module.REQUIRED_PROVENANCE_COLUMNS) == {
        "provenance_kind",
        "lifecycle_state",
        "provenance_snapshot_id",
        "first_seen_at",
        "last_seen_at",
    }
    assert set(module.OPTIONAL_PROVENANCE_COLUMNS) == {
        "provenance_event_hash",
        "provenance_reason",
    }
    assert set(module.PROVENANCE_COLUMNS) == set(
        module.REQUIRED_PROVENANCE_COLUMNS
    ) | set(module.OPTIONAL_PROVENANCE_COLUMNS)
    assert set(module.IMMUTABLE_PROVENANCE_COLUMNS) == {
        "provenance_kind",
        "first_seen_at",
    }
    # No DEFAULT and no NOT NULL anywhere: the large position tables are never
    # rewritten and no production backfill behaviour is invented here.
    for definition in module.PROVENANCE_COLUMN_DEFINITIONS.values():
        assert "DEFAULT" not in definition.upper()
        assert "NOT NULL" not in definition.upper()
    assert module.EXTRA_POSITION_COLUMNS["wallet_positions_v2"] == {
        "resolved_at": "TIMESTAMPTZ"
    }
    assert module.EXTRA_POSITION_COLUMNS["wallet_closed_positions_v2"] == {
        "redeemed_at": "TIMESTAMPTZ"
    }
    assert module.POSITION_TABLES == (
        "wallet_positions_v2",
        "wallet_closed_positions_v2",
    )


def test_every_created_object_kind_is_tracked_for_ownership():
    module = _load_migration()
    tracked_kinds = {
        "table",
        "column",
        "constraint",
        "index",
        "sequence",
        "trigger",
        "function",
        "metadata",
    }
    recorded: list[tuple[str, str]] = []

    def capture(name: str, kind: str, preexisting: bool) -> None:
        recorded.append((name, kind))

    # Drive the recording paths with stubbed catalog access so the full
    # inventory is observable without a database.
    module._record_object = capture  # type: ignore[assignment]
    module._table_exists = lambda _table: True  # type: ignore[assignment]
    module._relation_exists = lambda _name: True  # type: ignore[assignment]
    module._function_exists = lambda _name: True  # type: ignore[assignment]
    module._trigger_exists = lambda _table, _name: True  # type: ignore[assignment]
    module._constraint_exists = lambda _table, _name: True  # type: ignore[assignment]
    module._catalog_columns = lambda _table: {}  # type: ignore[assignment]

    import contextlib

    class _NoopContext:
        @staticmethod
        @contextlib.contextmanager
        def autocommit_block():
            yield

    class _NoopOp:
        @staticmethod
        def execute(_sql: str) -> None:
            return None

        @staticmethod
        def get_context():
            return _NoopContext

    module.op = _NoopOp  # type: ignore[assignment]
    module._assert_index_definitions = lambda *_a, **_k: None  # type: ignore[assignment]

    module._ensure_source_snapshot_table()
    module._create_identity_tables()
    module._add_provenance_columns()
    module._create_functions_and_triggers()
    module._record_object(module.METADATA_OBJECT, "metadata", False)
    module._create_identity_indexes()

    kinds = {kind for _name, kind in recorded}
    assert kinds == tracked_kinds

    names = {name for name, _kind in recorded}
    assert module.EVIDENCE_TABLE in names
    assert module.DECISION_TABLE in names
    assert module.SNAPSHOT_TABLE in names
    assert set(module.CREATED_INDEXES) <= names
    assert set(module.CREATED_SEQUENCES) <= names
    for table in module.POSITION_TABLES:
        for column in module.PROVENANCE_COLUMNS:
            assert f"{table}.{column}" in names
        assert f"{table}.ck_{table}_provenance_kind" in names
        assert f"{table}.ck_{table}_lifecycle_state" in names
        assert f"{table}.fk_{table}_provenance_snapshot" in names
    for table, trigger in {
        **module.PROVENANCE_TRIGGERS,
        **module.APPEND_ONLY_TRIGGERS,
    }.items():
        assert f"{table}.{trigger}" in names
    for function in (
        module.GUARD_FUNCTION,
        module.APPEND_ONLY_FUNCTION,
        module.SNAPSHOT_CHECK_FUNCTION,
    ):
        assert f"{function}()" in names
    assert module.METADATA_OBJECT in names


def test_exact_token_identity_accepts_text_and_bounded_varchar_only(monkeypatch):
    module = _load_migration()
    for type_name in ("text", "character varying(255)", "varchar(255)"):
        monkeypatch.setattr(
            module,
            "_catalog_columns",
            lambda _table, type_name=type_name: {
                "asset_token_id": (
                    module._normalize_catalog_type(type_name),
                    False,
                    None,
                )
            },
        )
        module._assert_exact_token_identity("wallet_positions_v2", "asset_token_id")

    for type_name in ("numeric", "double precision", "bigint", "character varying"):
        monkeypatch.setattr(
            module,
            "_catalog_columns",
            lambda _table, type_name=type_name: {
                "asset_token_id": (
                    module._normalize_catalog_type(type_name),
                    False,
                    None,
                )
            },
        )
        with pytest.raises(RuntimeError, match="exact-identity type"):
            module._assert_exact_token_identity(
                "wallet_positions_v2", "asset_token_id"
            )


def test_exact_token_identity_requires_nullable_without_default(monkeypatch):
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
            module._assert_exact_token_identity(
                "wallet_positions_v2", "asset_token_id"
            )


def test_index_contract_rejects_an_invalid_concurrent_build(monkeypatch):
    module = _load_migration()

    class _Bind:
        @staticmethod
        def execute(*_args: Any, **_kwargs: Any):
            class _Result:
                @staticmethod
                def all():
                    return [("public.idx", "create index idx on public.t (x)", False)]

            return _Result()

    monkeypatch.setattr(module, "_bind", lambda: _Bind())
    with pytest.raises(RuntimeError, match="invalid"):
        module._index_definitions("t")


def test_ownership_helper_fails_closed_on_missing_or_mismatched_records(monkeypatch):
    module = _load_migration()

    monkeypatch.setattr(module, "_ownership_row", lambda _name: None)
    with pytest.raises(RuntimeError, match="no ownership record"):
        module._is_droppable("some_object", "table", True)

    monkeypatch.setattr(
        module, "_ownership_row", lambda _name: ("index", module.revision, False)
    )
    with pytest.raises(RuntimeError, match="ownership records kind"):
        module._is_droppable("some_object", "table", True)

    # Pre-existing objects and objects owned by other revisions are preserved.
    monkeypatch.setattr(
        module, "_ownership_row", lambda _name: ("table", module.revision, True)
    )
    assert module._is_droppable("some_object", "table", True) is False
    monkeypatch.setattr(
        module, "_ownership_row", lambda _name: ("table", "b1c2d3e4f5a6", False)
    )
    assert module._is_droppable("some_object", "table", True) is False
    monkeypatch.setattr(
        module, "_ownership_row", lambda _name: ("table", module.revision, False)
    )
    assert module._is_droppable("some_object", "table", True) is True
    # A non-existent object is never a drop candidate and never ambiguous.
    assert module._is_droppable("some_object", "table", False) is False


def test_replay_fixtures_are_present_and_distinct():
    base = (FIXTURES / BASE_FIXTURE).read_text(encoding="utf-8")
    prereq = (FIXTURES / PREREQ_FIXTURE).read_text(encoding="utf-8")
    malformed = (FIXTURES / MALFORMED_FIXTURE).read_text(encoding="utf-8")

    assert "CREATE TABLE ledger_schema_objects_v2" in base
    assert "asset_token_id TEXT" in base
    assert "PRIMARY KEY (address, condition_id, outcome)" in base
    assert "CREATE TABLE wallet_source_snapshots_v2" in prereq
    assert "asset TEXT" in prereq
    assert "asset NUMERIC" in malformed
    assert "asset NUMERIC" not in prereq
    assert prereq != malformed


# ---------------------------------------------------------------------------
# PostgreSQL replay layer
# ---------------------------------------------------------------------------


def _alembic(*args: str, expect_success: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL or ""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
    )
    if expect_success:
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _run(coro):
    return asyncio.run(coro)


async def _apply_fixtures(fixtures: Iterable[str]) -> None:
    import asyncpg

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for name in fixtures:
            await conn.execute((FIXTURES / name).read_text(encoding="utf-8"))
    finally:
        await conn.close()


def _prepare(fixtures: Iterable[str], upgrade: bool = True) -> None:
    _run(_apply_fixtures(fixtures))
    # The fixtures reproduce the schema immediately after b1c2d3e4f5a6, so the
    # graph is stamped at that point and the real revision under test is then
    # executed by the real Alembic runner.
    _alembic("stamp", "b1c2d3e4f5a6")
    if upgrade:
        _alembic("upgrade", "head")


async def _connect():
    import asyncpg

    return await asyncpg.connect(DATABASE_URL)


async def _seed_snapshot(conn, address: str, complete: bool = True) -> int:
    return await conn.fetchval(
        """
        INSERT INTO wallet_source_snapshots_v2
            (address, source, complete, payload_sha256)
        VALUES ($1, 'positions', $2, 'sha')
        RETURNING id
        """,
        address,
        complete,
    )


async def _seed_open_position(conn, address: str) -> None:
    await conn.execute(
        """
        INSERT INTO wallet_positions_v2 (address, condition_id, outcome, size)
        VALUES ($1, 'condition-1', 'YES', 10)
        """,
        address,
    )


async def _initialize_provenance(
    conn,
    address: str,
    snapshot_id: int,
    state: str = "ordinary",
    kind: str = "ordinary",
) -> None:
    await conn.execute(
        """
        UPDATE wallet_positions_v2
        SET provenance_kind = $2,
            lifecycle_state = $3,
            provenance_snapshot_id = $4,
            provenance_event_hash = 'hash-1',
            provenance_reason = 'initial snapshot',
            first_seen_at = NOW(),
            last_seen_at = NOW()
        WHERE address = $1
        """,
        address,
        kind,
        state,
        snapshot_id,
    )


def _pg_error() -> type[BaseException]:
    import asyncpg

    return asyncpg.PostgresError


async def _assert_rejects(coro_factory: Callable[[], Any], message: str) -> None:
    with pytest.raises(_pg_error()) as excinfo:
        await coro_factory()
    assert message in str(excinfo.value), str(excinfo.value)


@pytest.fixture
def prepared_db():
    """A disposable database upgraded through the revision under test."""
    _prepare([BASE_FIXTURE, PREREQ_FIXTURE])
    return DATABASE_URL


@requires_postgres
def test_clean_upgrade_matches_the_declared_catalog_contract(prepared_db):
    module = _load_migration()

    async def run():
        conn = await _connect()
        try:
            for table in (module.EVIDENCE_TABLE, module.DECISION_TABLE):
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )

            # Exact TEXT token identity on every identity-bearing column.
            for table, column in (
                (module.EVIDENCE_TABLE, "asset_token_id"),
                (module.EVIDENCE_TABLE, "source_asset"),
                (module.DECISION_TABLE, "asset_token_id"),
                (module.DECISION_TABLE, "source_asset"),
                ("wallet_positions_v2", "asset_token_id"),
                ("wallet_closed_positions_v2", "asset_token_id"),
            ):
                row = await conn.fetchrow(
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
                      AND a.attname = $2
                    """,
                    table,
                    column,
                )
                assert row["type_name"] == "text", (table, column)
                assert row["attnotnull"] is False
                assert row["default_expr"] is None

            # Nullable, defaultless provenance columns on both canonical tables,
            # and an unchanged published metric grain.
            for table in module.POSITION_TABLES:
                expected = dict(module.PROVENANCE_COLUMN_DEFINITIONS)
                expected.update(module.EXTRA_POSITION_COLUMNS[table])
                for column in expected:
                    row = await conn.fetchrow(
                        """
                        SELECT a.attnotnull,
                               pg_get_expr(d.adbin, d.adrelid) AS default_expr
                        FROM pg_attribute a
                        JOIN pg_class t ON t.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = t.relnamespace
                        LEFT JOIN pg_attrdef d
                               ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                        WHERE n.nspname = 'public' AND t.relname = $1
                          AND a.attname = $2
                        """,
                        table,
                        column,
                    )
                    assert row is not None, (table, column)
                    assert row["attnotnull"] is False
                    assert row["default_expr"] is None
                pk = await conn.fetchval(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = $1::regclass AND contype = 'p'
                    """,
                    table,
                )
                assert pk == "PRIMARY KEY (address, condition_id, outcome)"
                fk = await conn.fetchval(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = $1::regclass AND conname = $2
                    """,
                    table,
                    f"fk_{table}_provenance_snapshot",
                )
                assert fk == (
                    "FOREIGN KEY (provenance_snapshot_id) "
                    "REFERENCES wallet_source_snapshots_v2(id)"
                )

            # Exact index definitions, all valid.
            for name, (
                table,
                expected,
            ) in module._EXPECTED_INDEX_DEFINITIONS.items():
                row = await conn.fetchrow(
                    """
                    SELECT pg_get_indexdef(indexrelid) AS def, indisvalid,
                           indrelid::regclass::text AS rel
                    FROM pg_index WHERE indexrelid = $1::regclass
                    """,
                    name,
                )
                assert row["indisvalid"] is True
                assert row["rel"] == table
                assert " ".join(row["def"].lower().split()) == " ".join(
                    expected.lower().split()
                )

            # Ownership: everything created here is recorded, and the ancestor
            # snapshot table is recorded as pre-existing so it survives.
            owned = {
                row["object_name"]: row
                for row in await conn.fetch(
                    """
                    SELECT object_name, object_kind, preexisting
                    FROM ledger_schema_objects_v2
                    WHERE created_by_revision = 'c2d3e4f5a6b7'
                    """
                )
            }
            assert owned[module.SNAPSHOT_TABLE]["preexisting"] is True
            assert owned[module.EVIDENCE_TABLE]["preexisting"] is False
            assert owned[module.DECISION_TABLE]["preexisting"] is False
            assert owned[module.METADATA_OBJECT]["object_kind"] == "metadata"
            for name in module.CREATED_INDEXES:
                assert owned[name]["object_kind"] == "index"
            for name in module.CREATED_SEQUENCES:
                assert owned[name]["object_kind"] == "sequence"
            for table in module.POSITION_TABLES:
                for column in module.PROVENANCE_COLUMNS:
                    assert owned[f"{table}.{column}"]["object_kind"] == "column"
            for table, trigger in {
                **module.PROVENANCE_TRIGGERS,
                **module.APPEND_ONLY_TRIGGERS,
            }.items():
                assert owned[f"{table}.{trigger}"]["object_kind"] == "trigger"
            for function in (
                module.GUARD_FUNCTION,
                module.APPEND_ONLY_FUNCTION,
                module.SNAPSHOT_CHECK_FUNCTION,
            ):
                assert owned[f"{function}()"]["object_kind"] == "function"

            # The ancestor evidence/decision tables are untouched.
            for table in (
                "wallet_position_evidence_v2",
                "wallet_position_audit_decisions_v2",
            ):
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_exact_token_identity_round_trips_through_the_evidence_tables(prepared_db):
    long_token = "000" + "9" * 140

    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xtoken")
            await conn.execute(
                """
                INSERT INTO wallet_position_identity_evidence_v2
                    (address, condition_id, asset_token_id, evidence_type,
                     snapshot_id)
                VALUES ('0xtoken', 'condition-1', $1, 'positions_snapshot', $2)
                """,
                long_token,
                snapshot_id,
            )
            assert (
                await conn.fetchval(
                    "SELECT asset_token_id FROM wallet_position_identity_evidence_v2"
                )
                == long_token
            )
            await conn.execute(
                """
                INSERT INTO wallet_position_identity_decisions_v2
                    (audit_id, address, condition_id, outcome, asset_token_id,
                     status, reason)
                VALUES (gen_random_uuid(), '0xtoken', 'condition-1', 'YES', $1,
                        'review_required', 'conflicting token identity')
                """,
                long_token,
            )
            assert (
                await conn.fetchval(
                    "SELECT asset_token_id FROM wallet_position_identity_decisions_v2"
                )
                == long_token
            )
            # Identity evidence must carry at least one exact identity.
            await _assert_rejects(
                lambda: conn.execute(
                    """
                    INSERT INTO wallet_position_identity_evidence_v2
                        (address, condition_id, evidence_type, snapshot_id)
                    VALUES ('0xtoken', 'condition-2', 'positions_snapshot', $1)
                    """,
                    snapshot_id,
                ),
                "ck_wallet_position_identity_evidence_v2_identity_present",
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_identity_evidence_and_decisions_are_append_only(prepared_db):
    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xappend")
            await conn.execute(
                """
                INSERT INTO wallet_position_identity_evidence_v2
                    (address, condition_id, asset_token_id, evidence_type,
                     snapshot_id)
                VALUES ('0xappend', 'condition-1', '0123', 'activity_event', $1)
                """,
                snapshot_id,
            )
            await conn.execute(
                """
                INSERT INTO wallet_position_identity_decisions_v2
                    (audit_id, address, condition_id, outcome, asset_token_id,
                     status, reason)
                VALUES ('11111111-1111-1111-1111-111111111111', '0xappend',
                        'condition-1', 'YES', '0123', 'eligible', 'single token')
                """
            )

            for table in (
                "wallet_position_identity_evidence_v2",
                "wallet_position_identity_decisions_v2",
            ):
                await _assert_rejects(
                    lambda table=table: conn.execute(
                        f"UPDATE {table} SET address = '0xrewrite'"
                    ),
                    "append-only",
                )
                await _assert_rejects(
                    lambda table=table: conn.execute(f"DELETE FROM {table}"),
                    "append-only",
                )
                assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 1

            # A duplicate decision for the same audit/address/condition/outcome/
            # token identity is refused by the unique expression index.
            await _assert_rejects(
                lambda: conn.execute(
                    """
                    INSERT INTO wallet_position_identity_decisions_v2
                        (audit_id, address, condition_id, outcome,
                         asset_token_id, status, reason)
                    VALUES ('11111111-1111-1111-1111-111111111111', '0xappend',
                            'condition-1', 'YES', '0123', 'excluded_proven',
                            'duplicate')
                    """
                ),
                "uq_wallet_position_identity_decisions_v2",
            )
            # A different exact token is a different identity and is accepted.
            await conn.execute(
                """
                INSERT INTO wallet_position_identity_decisions_v2
                    (audit_id, address, condition_id, outcome, asset_token_id,
                     status, reason)
                VALUES ('11111111-1111-1111-1111-111111111111', '0xappend',
                        'condition-1', 'YES', '00123', 'review_required',
                        'conflicting token identity')
                """
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM wallet_position_identity_decisions_v2"
                )
                == 2
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_legacy_all_null_provenance_accepts_unrelated_updates(prepared_db):
    async def run():
        conn = await _connect()
        try:
            await _seed_open_position(conn, "0xlegacy")
            await conn.execute(
                "UPDATE wallet_positions_v2 SET size = 42, current_value = 7 "
                "WHERE address = '0xlegacy'"
            )
            assert (
                await conn.fetchval(
                    "SELECT size FROM wallet_positions_v2 WHERE address = '0xlegacy'"
                )
                == 42
            )
            assert (
                await conn.fetchval(
                    "SELECT provenance_kind FROM wallet_positions_v2 "
                    "WHERE address = '0xlegacy'"
                )
                is None
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_partial_provenance_is_rejected_on_insert_and_update(prepared_db):
    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xpartial")
            await _assert_rejects(
                lambda: conn.execute(
                    """
                    INSERT INTO wallet_positions_v2
                        (address, condition_id, outcome, provenance_kind)
                    VALUES ('0xpartial', 'condition-1', 'YES', 'ordinary')
                    """
                ),
                "partial lifecycle provenance",
            )
            await _seed_open_position(conn, "0xpartial")
            await _assert_rejects(
                lambda: conn.execute(
                    """
                    UPDATE wallet_positions_v2
                    SET provenance_kind = 'ordinary',
                        lifecycle_state = 'ordinary',
                        provenance_snapshot_id = $1
                    WHERE address = '0xpartial'
                    """,
                    snapshot_id,
                ),
                "partial lifecycle provenance initialization",
            )
            assert (
                await conn.fetchval(
                    "SELECT provenance_kind FROM wallet_positions_v2 "
                    "WHERE address = '0xpartial'"
                )
                is None
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_complete_initialization_requires_a_complete_snapshot(prepared_db):
    async def run():
        conn = await _connect()
        try:
            incomplete = await _seed_snapshot(conn, "0xinit", complete=False)
            complete = await _seed_snapshot(conn, "0xinit", complete=True)
            await _seed_open_position(conn, "0xinit")

            await _assert_rejects(
                lambda: _initialize_provenance(conn, "0xinit", incomplete),
                "is incomplete",
            )
            await _assert_rejects(
                lambda: _initialize_provenance(conn, "0xinit", complete + 10_000),
                "does not exist",
            )

            await _initialize_provenance(conn, "0xinit", complete)
            row = await conn.fetchrow(
                "SELECT provenance_kind, lifecycle_state, provenance_snapshot_id "
                "FROM wallet_positions_v2 WHERE address = '0xinit'"
            )
            assert row["provenance_kind"] == "ordinary"
            assert row["lifecycle_state"] == "ordinary"
            assert row["provenance_snapshot_id"] == complete

            # An insert may also arrive already initialized, atomically.
            await conn.execute(
                """
                INSERT INTO wallet_closed_positions_v2
                    (address, condition_id, outcome, provenance_kind,
                     lifecycle_state, provenance_snapshot_id, first_seen_at,
                     last_seen_at)
                VALUES ('0xinit', 'condition-2', 'NO', 'redeemable',
                        'redeemable', $1, NOW(), NOW())
                """,
                complete,
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_initialized_provenance_cannot_be_cleared_or_rewritten(prepared_db):
    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xfrozen")
            other = await _seed_snapshot(conn, "0xfrozen")
            await _seed_open_position(conn, "0xfrozen")
            await _initialize_provenance(conn, "0xfrozen", snapshot_id)

            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET provenance_kind = NULL, "
                    "lifecycle_state = NULL, provenance_snapshot_id = NULL, "
                    "first_seen_at = NULL, last_seen_at = NULL "
                    "WHERE address = '0xfrozen'"
                ),
                "cannot be cleared",
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET provenance_reason = NULL "
                    "WHERE address = '0xfrozen'"
                ),
                "cannot be cleared",
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET provenance_kind = 'synthetic' "
                    "WHERE address = '0xfrozen'"
                ),
                "cannot be rewritten",
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET first_seen_at = NOW() "
                    "WHERE address = '0xfrozen'"
                ),
                "cannot be rewritten",
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET provenance_snapshot_id = $1 "
                    "WHERE address = '0xfrozen'",
                    other,
                ),
                "without a lifecycle transition",
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 "
                    "SET last_seen_at = first_seen_at - INTERVAL '1 day' "
                    "WHERE address = '0xfrozen'"
                ),
                "cannot move backwards",
            )

            # Unrelated columns and a forward last_seen_at heartbeat stay legal.
            await conn.execute(
                "UPDATE wallet_positions_v2 SET size = 5, last_seen_at = NOW() "
                "WHERE address = '0xfrozen'"
            )
            assert (
                await conn.fetchval(
                    "SELECT size FROM wallet_positions_v2 WHERE address = '0xfrozen'"
                )
                == 5
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_lifecycle_transitions_are_validated_and_terminal_states_are_frozen(
    prepared_db,
):
    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xlifecycle")
            incomplete = await _seed_snapshot(conn, "0xlifecycle", complete=False)
            transition_snapshot = await _seed_snapshot(conn, "0xlifecycle")
            await _seed_open_position(conn, "0xlifecycle")
            await _initialize_provenance(conn, "0xlifecycle", snapshot_id)

            # An unsupported transition is refused.
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET lifecycle_state = 'redeemed', "
                    "provenance_snapshot_id = $1 WHERE address = '0xlifecycle'",
                    transition_snapshot,
                ),
                "unsupported lifecycle transition ordinary -> redeemed",
            )
            # A transition may not rest on an incomplete snapshot.
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET lifecycle_state = 'redeemable', "
                    "provenance_snapshot_id = $1 WHERE address = '0xlifecycle'",
                    incomplete,
                ),
                "is incomplete",
            )
            # A transition may not clear provenance on the way.
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_positions_v2 SET lifecycle_state = 'redeemable', "
                    "provenance_snapshot_id = NULL WHERE address = '0xlifecycle'"
                ),
                "cannot be cleared",
            )

            await conn.execute(
                """
                UPDATE wallet_positions_v2
                SET lifecycle_state = 'redeemable',
                    provenance_snapshot_id = $1,
                    provenance_event_hash = 'hash-2',
                    provenance_reason = 'complete positions snapshot',
                    last_seen_at = NOW()
                WHERE address = '0xlifecycle'
                """,
                transition_snapshot,
            )
            assert (
                await conn.fetchval(
                    "SELECT lifecycle_state FROM wallet_positions_v2 "
                    "WHERE address = '0xlifecycle'"
                )
                == "redeemable"
            )

            await conn.execute(
                """
                UPDATE wallet_positions_v2
                SET lifecycle_state = 'redeemed',
                    provenance_snapshot_id = $1,
                    provenance_event_hash = 'hash-3',
                    provenance_reason = 'authoritative redemption',
                    last_seen_at = NOW()
                WHERE address = '0xlifecycle'
                """,
                snapshot_id,
            )

            # Terminal states cannot transition anywhere, including back.
            for target in ("redeemable", "expired", "ordinary"):
                await _assert_rejects(
                    lambda target=target: conn.execute(
                        "UPDATE wallet_positions_v2 SET lifecycle_state = $1, "
                        "provenance_snapshot_id = $2 WHERE address = '0xlifecycle'",
                        target,
                        transition_snapshot,
                    ),
                    "terminal lifecycle state redeemed",
                )
            # A repeated no-op write of the same terminal state is idempotent.
            await conn.execute(
                "UPDATE wallet_positions_v2 SET lifecycle_state = 'redeemed', "
                "last_seen_at = NOW() WHERE address = '0xlifecycle'"
            )
            assert (
                await conn.fetchval(
                    "SELECT lifecycle_state FROM wallet_positions_v2 "
                    "WHERE address = '0xlifecycle'"
                )
                == "redeemed"
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_closed_positions_enforce_the_same_provenance_semantics(prepared_db):
    async def run():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xclosed")
            await conn.execute(
                """
                INSERT INTO wallet_closed_positions_v2
                    (address, condition_id, outcome, realized_pnl)
                VALUES ('0xclosed', 'condition-1', 'YES', 12)
                """
            )
            # Legacy update on an all-null closed row.
            await conn.execute(
                "UPDATE wallet_closed_positions_v2 SET realized_pnl = 13 "
                "WHERE address = '0xclosed'"
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_closed_positions_v2 SET lifecycle_state = 'ordinary' "
                    "WHERE address = '0xclosed'"
                ),
                "partial lifecycle provenance initialization",
            )
            await conn.execute(
                """
                UPDATE wallet_closed_positions_v2
                SET provenance_kind = 'redeemable',
                    lifecycle_state = 'redeemable',
                    provenance_snapshot_id = $1,
                    first_seen_at = NOW(),
                    last_seen_at = NOW()
                WHERE address = '0xclosed'
                """,
                snapshot_id,
            )
            await conn.execute(
                """
                UPDATE wallet_closed_positions_v2
                SET lifecycle_state = 'redeemed',
                    redeemed_at = NOW(),
                    provenance_snapshot_id = $1,
                    last_seen_at = NOW()
                WHERE address = '0xclosed'
                """,
                snapshot_id,
            )
            await _assert_rejects(
                lambda: conn.execute(
                    "UPDATE wallet_closed_positions_v2 SET lifecycle_state = 'expired' "
                    "WHERE address = '0xclosed'"
                ),
                "terminal lifecycle state redeemed",
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_malformed_preexisting_evidence_table_fails_closed():
    _prepare([BASE_FIXTURE, MALFORMED_FIXTURE], upgrade=False)
    result = _alembic("upgrade", "head", expect_success=False)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "wallet_position_evidence_v2.asset" in combined
    assert "exact-identity type" in combined
    assert "numeric legacy values cannot recover leading zeros" in combined

    async def run():
        conn = await _connect()
        try:
            # Nothing was adopted or created by the aborted upgrade.
            for table in (
                "wallet_position_identity_evidence_v2",
                "wallet_position_identity_decisions_v2",
            ):
                assert not await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
            assert not await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM ledger_schema_objects_v2
                    WHERE created_by_revision = 'c2d3e4f5a6b7'
                )
                """
            )
        finally:
            await conn.close()

    _run(run())


@requires_postgres
def test_downgrade_removes_only_objects_this_revision_created(prepared_db):
    module = _load_migration()

    async def seed():
        conn = await _connect()
        try:
            snapshot_id = await _seed_snapshot(conn, "0xdowngrade")
            await conn.execute(
                """
                INSERT INTO wallet_position_evidence_v2
                    (address, condition_id, asset, evidence_type, snapshot_id)
                VALUES ('0xdowngrade', 'condition-1', '0123', 'legacy', $1)
                """,
                snapshot_id,
            )
            await _seed_open_position(conn, "0xdowngrade")
            await _initialize_provenance(conn, "0xdowngrade", snapshot_id)
        finally:
            await conn.close()

    _run(seed())
    _alembic("downgrade", "b1c2d3e4f5a6")

    async def verify():
        conn = await _connect()
        try:
            # Objects created by this revision are gone.
            for table in (module.EVIDENCE_TABLE, module.DECISION_TABLE):
                assert not await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
            for index in module.CREATED_INDEXES:
                assert not await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{index}"
                )
            for function in (
                module.GUARD_FUNCTION,
                module.APPEND_ONLY_FUNCTION,
                module.SNAPSHOT_CHECK_FUNCTION,
            ):
                assert not await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_proc p
                        JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'public' AND p.proname = $1
                    )
                    """,
                    function,
                )
            for table, trigger in {
                **module.PROVENANCE_TRIGGERS,
                **module.APPEND_ONLY_TRIGGERS,
            }.items():
                if await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                ):
                    assert not await conn.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM pg_trigger tg
                            JOIN pg_class t ON t.oid = tg.tgrelid
                            WHERE t.relname = $1 AND tg.tgname = $2
                        )
                        """,
                        table,
                        trigger,
                    )
            for table in module.POSITION_TABLES:
                columns = {
                    row["column_name"]
                    for row in await conn.fetch(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = $1",
                        table,
                    )
                }
                assert not (set(module.PROVENANCE_COLUMNS) & columns)
                assert "address" in columns

            # Pre-existing ancestor objects and their data are preserved.
            assert await conn.fetchval(
                "SELECT to_regclass('public.wallet_source_snapshots_v2') IS NOT NULL"
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM wallet_source_snapshots_v2"
                )
                == 1
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM wallet_position_evidence_v2"
                )
                == 1
            )
            assert await conn.fetchval(
                "SELECT to_regclass("
                "'public.wallet_position_audit_decisions_v2') IS NOT NULL"
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM wallet_positions_v2 "
                    "WHERE address = '0xdowngrade'"
                )
                == 1
            )

            # The ownership ledger itself belongs to b1c2d3e4f5a6 and survives,
            # with this revision's own-created rows removed.
            assert await conn.fetchval(
                "SELECT to_regclass('public.ledger_schema_objects_v2') IS NOT NULL"
            )
            assert await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM ledger_schema_objects_v2
                    WHERE created_by_revision = 'b1c2d3e4f5a6'
                )
                """
            )
            leftover = await conn.fetch(
                """
                SELECT object_name, preexisting FROM ledger_schema_objects_v2
                WHERE created_by_revision = 'c2d3e4f5a6b7'
                """
            )
            assert all(row["preexisting"] for row in leftover)
        finally:
            await conn.close()

    _run(verify())

    # The expand migration is replayable: upgrading again after an
    # ownership-safe downgrade rebuilds exactly the same objects.
    _alembic("upgrade", "head")

    async def verify_replay():
        conn = await _connect()
        try:
            for table in (module.EVIDENCE_TABLE, module.DECISION_TABLE):
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
            for index in module.CREATED_INDEXES:
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{index}"
                )
            # Pre-existing ancestor data survived both directions.
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM wallet_position_evidence_v2"
                )
                == 1
            )
        finally:
            await conn.close()

    _run(verify_replay())


@requires_postgres
def test_downgrade_drops_the_snapshot_table_only_when_it_created_it():
    module = _load_migration()
    # No ancestor evidence objects: this revision creates the snapshot table.
    _prepare([BASE_FIXTURE])

    async def check_owned():
        conn = await _connect()
        try:
            assert (
                await conn.fetchval(
                    "SELECT preexisting FROM ledger_schema_objects_v2 "
                    "WHERE object_name = $1",
                    module.SNAPSHOT_TABLE,
                )
                is False
            )
        finally:
            await conn.close()

    _run(check_owned())
    _alembic("downgrade", "b1c2d3e4f5a6")

    async def verify():
        conn = await _connect()
        try:
            assert not await conn.fetchval(
                "SELECT to_regclass('public.wallet_source_snapshots_v2') IS NOT NULL"
            )
            assert await conn.fetchval(
                "SELECT to_regclass('public.ledger_schema_objects_v2') IS NOT NULL"
            )
        finally:
            await conn.close()

    _run(verify())


@requires_postgres
def test_downgrade_fails_closed_when_ownership_is_ambiguous(prepared_db):
    module = _load_migration()

    async def forget_ownership():
        conn = await _connect()
        try:
            await conn.execute(
                "DELETE FROM ledger_schema_objects_v2 WHERE object_name = $1",
                module.EVIDENCE_TABLE,
            )
        finally:
            await conn.close()

    _run(forget_ownership())
    result = _alembic("downgrade", "b1c2d3e4f5a6", expect_success=False)
    assert result.returncode != 0
    assert "no ownership record exists" in result.stdout + result.stderr

    async def verify_nothing_was_removed():
        conn = await _connect()
        try:
            # The plan is resolved before any drop, so the schema is intact.
            for table in (module.EVIDENCE_TABLE, module.DECISION_TABLE):
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
                )
            for index in module.CREATED_INDEXES:
                assert await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"public.{index}"
                )
            for table in module.POSITION_TABLES:
                columns = {
                    row["column_name"]
                    for row in await conn.fetch(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = $1",
                        table,
                    )
                }
                assert set(module.PROVENANCE_COLUMNS) <= columns
        finally:
            await conn.close()

    _run(verify_nothing_was_removed())
