"""Add replayable, provenance-aware ledger analytics schema.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-09-07

This is an expand migration.  It is deliberately safe to replay against a
clean database and against a database that was changed by the historical
``migrate_add_league.py`` helper.  Closed-position provenance columns are
nullable so this migration never rewrites the large closed-position table.
"""
from __future__ import annotations

import re
from typing import Final

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: str = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None

OWNERSHIP_TABLE = "ledger_schema_objects_v2"
OWNERSHIP_REVISION = revision


# This is also consumed by the contract tests.  Keep it limited to columns
# written or read by the supported v2 API/workers; legacy writer-only fields do
# not belong in this migration.
REQUIRED_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "markets_v2": (
        "category", "subcategory", "league", "event_slug",
    ),
    "category_stats_v2": (
        "subcategory", "league", "window_size", "pnl", "volume", "win_rate",
        "roi_pct", "resolved_count", "winning_count", "last_active", "computed_at",
    ),
    "wallet_positions_v2": (
        "is_parlay", "is_resolved", "asset_token_id",
    ),
    "wallet_closed_positions_v2": (
        "is_parlay", "is_redeemable", "resolved_at", "data_quality_flag",
        "metrics_eligible", "exclusion_reason", "excluded_at", "source_asset",
        "asset_token_id", "source_realized_pnl", "ledger_cost_basis",
        "ledger_volume_usd", "ledger_settlement_value", "ledger_pnl",
        "ledger_formula_version", "ledger_provenance_version", "settlement_included",
        "ledger_computed_at", "normalized_parlay_key",
    ),
    "wallet_metrics_v2": (
        "total_pnl", "total_volume", "roi_pct", "win_rate", "resolved_count",
        "winning_count", "avg_buy_price", "data_completeness_pct", "parlay_pnl",
        "parlay_volume", "parlay_win_rate", "parlay_resolved_count",
        "parlay_winning_count", "pnl_100", "pnl_200", "pnl_300", "pnl_500",
        "pnl_750", "pnl_1000", "pnl_1500", "pnl_2000", "pnl_3500", "pnl_5000",
        "pnl_all", "position_value", "parlay_open_count", "parlay_open_value",
        "redeemable_count", "redeemable_winning_count", "computed_at",
        "categories_computed_at", "open_synced_at", "closed_synced_at",
        "capital_synced_at", "pm_pnl", "pm_volume", "pm_rank", "pm_synced_at",
        "balance", "deposits", "withdrawals", "buys_below_15c", "wins_below_15c",
        "losses_below_15c", "avg_sell_below_15c", "buys_15_30c", "wins_15_30c",
        "losses_15_30c", "avg_sell_15_30c", "buys_30_45c", "wins_30_45c",
        "losses_30_45c", "avg_sell_30_45c", "buys_45_60c", "wins_45_60c",
        "losses_45_60c", "avg_sell_45_60c", "buys_60_75c", "wins_60_75c",
        "losses_60_75c", "avg_sell_60_75c", "buys_above_75c", "wins_above_75c",
        "losses_above_75c", "avg_sell_above_75c",
    ),
}


# The base objects are created defensively because the actual repository head
# predates the v2 chain, while production may already have them.  Every object
# and every column below is therefore safe on either starting shape.
def _ensure_base_tables() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallets_v2 (
            address VARCHAR(42) PRIMARY KEY,
            username VARCHAR(255),
            tier VARCHAR(20),
            tier_reason VARCHAR(50),
            might_cook_type VARCHAR(20),
            is_dormant BOOLEAN,
            last_trade_at TIMESTAMPTZ,
            added_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS markets_v2 (
            condition_id VARCHAR(255) PRIMARY KEY,
            title TEXT,
            description TEXT,
            image_url TEXT,
            category VARCHAR(50),
            subcategory VARCHAR(100),
            status VARCHAR(20),
            winning_outcome VARCHAR(255),
            winning_index INTEGER,
            resolved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_metrics_v2 (
            address VARCHAR(42) PRIMARY KEY REFERENCES wallets_v2(address),
            total_pnl NUMERIC,
            total_volume NUMERIC,
            roi_pct NUMERIC,
            win_rate NUMERIC,
            resolved_count INTEGER,
            winning_count INTEGER,
            computed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS category_stats_v2 (
            address VARCHAR(42) NOT NULL REFERENCES wallets_v2(address),
            category VARCHAR(50) NOT NULL,
            subcategory VARCHAR(100) NOT NULL DEFAULT '',
            window_size INTEGER NOT NULL DEFAULT 0,
            pnl NUMERIC,
            volume NUMERIC,
            win_rate NUMERIC,
            roi_pct NUMERIC,
            resolved_count INTEGER,
            winning_count INTEGER,
            computed_at TIMESTAMPTZ,
            PRIMARY KEY (address, category, subcategory, window_size)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_positions_v2 (
            address VARCHAR(42) NOT NULL REFERENCES wallets_v2(address),
            condition_id VARCHAR(255) NOT NULL REFERENCES markets_v2(condition_id),
            outcome VARCHAR(255) NOT NULL,
            size NUMERIC,
            avg_price NUMERIC,
            current_value NUMERIC,
            unrealized_pnl NUMERIC,
            entry_at TIMESTAMPTZ,
            computed_at TIMESTAMPTZ,
            PRIMARY KEY (address, condition_id, outcome)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_closed_positions_v2 (
            address VARCHAR(42) NOT NULL REFERENCES wallets_v2(address),
            condition_id VARCHAR(255) NOT NULL REFERENCES markets_v2(condition_id),
            outcome VARCHAR(255) NOT NULL,
            avg_buy_price NUMERIC,
            avg_sell_price NUMERIC,
            total_bought NUMERIC,
            total_sold NUMERIC,
            realized_pnl NUMERIC,
            opened_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ,
            n_trades INTEGER,
            PRIMARY KEY (address, condition_id, outcome)
        )
        """
    )


def _add_columns(table: str, definitions: dict[str, str]) -> None:
    for column, sql_type in definitions.items():
        # Names are migration-owned constants, not user input.
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}")


def _table_exists(table: str) -> bool:
    return bool(
        op.get_bind().execute(
            sa.text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"public.{table}"},
        ).scalar()
    )


_DEFAULT_UNCHECKED = object()
_ANY_DEFAULT = object()


def _normalize_catalog_type(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    value = value.replace("varchar", "character varying")
    value = value.replace("timestamp with time zone", "timestamptz")
    value = value.replace("timestamp without time zone", "timestamp")
    return value


def _catalog_columns(table: str) -> dict[str, tuple[str, bool, str | None]]:
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT a.attname,
                   format_type(a.atttypid, a.atttypmod),
                   a.attnotnull,
                   pg_get_expr(d.adbin, d.adrelid)
            FROM pg_attribute a
            JOIN pg_class t ON t.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = 'public' AND t.relname = :table
              AND a.attnum > 0 AND NOT a.attisdropped
            """
        ),
        {"table": table},
    ).all()
    return {
        str(name): (_normalize_catalog_type(str(type_name)), bool(notnull), default)
        for name, type_name, notnull, default in rows
    }


def _assert_column_contract(
    table: str,
    contracts: dict[str, tuple[str, bool, object]],
) -> None:
    columns = _catalog_columns(table)
    for column, (expected_type, expected_notnull, expected_default) in contracts.items():
        actual = columns.get(column)
        if actual is None:
            raise RuntimeError(f"{table} is missing required column {column}")
        actual_type, actual_notnull, actual_default = actual
        if actual_type != _normalize_catalog_type(expected_type):
            raise RuntimeError(
                f"{table}.{column} has incompatible type {actual_type!r}; "
                f"expected {_normalize_catalog_type(expected_type)!r}"
            )
        if actual_notnull != expected_notnull:
            raise RuntimeError(
                f"{table}.{column} has incompatible nullability "
                f"(not-null={actual_notnull}); expected not-null={expected_notnull}"
            )
        if expected_default is _ANY_DEFAULT:
            continue
        if expected_default is not _DEFAULT_UNCHECKED:
            actual_normalized = None if actual_default is None else re.sub(
                r"\s+", " ", str(actual_default).strip().lower()
            )
            expected_normalized = (
                None
                if expected_default is None
                else re.sub(r"\s+", " ", str(expected_default).strip().lower())
            )
            if actual_normalized != expected_normalized:
                raise RuntimeError(
                    f"{table}.{column} has incompatible default {actual_default!r}; "
                    f"expected {expected_default!r}"
                )


def _assert_exact_token_identity(table: str) -> None:
    """Reject legacy numeric token columns before they can lose identity."""
    columns = _catalog_columns(table)
    actual = columns.get("asset_token_id")
    if actual is None:
        raise RuntimeError(f"{table}.asset_token_id was not created")
    actual_type, actual_notnull, actual_default = actual
    if actual_type != "text" and not re.fullmatch(r"character varying\(\d+\)", actual_type):
        raise RuntimeError(
            f"{table}.asset_token_id has incompatible exact-identity type "
            f"{actual_type!r}; numeric legacy values cannot recover leading zeros; "
            "repair the source-backed schema before upgrading"
        )
    if actual_notnull or actual_default is not None:
        raise RuntimeError(
            f"{table}.asset_token_id must remain nullable with no default so legacy "
            "rows are not fabricated"
        )


def _ensure_ownership_table() -> None:
    existed = _table_exists(OWNERSHIP_TABLE)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OWNERSHIP_TABLE} (
            object_name TEXT PRIMARY KEY,
            object_kind TEXT NOT NULL,
            created_by_revision TEXT NOT NULL,
            preexisting BOOLEAN NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    _assert_column_contract(
        OWNERSHIP_TABLE,
        {
            "object_name": ("TEXT", True, None),
            "object_kind": ("TEXT", True, None),
            "created_by_revision": ("TEXT", True, None),
            "preexisting": ("BOOLEAN", True, None),
            "recorded_at": ("TIMESTAMPTZ", True, "now()"),
        },
    )
    _assert_primary_key_contract(OWNERSHIP_TABLE, ("object_name",))
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {OWNERSHIP_TABLE}
                (object_name, object_kind, created_by_revision, preexisting)
            VALUES (:name, :kind, :revision, :preexisting)
            ON CONFLICT (object_name) DO NOTHING
            """
        ),
        {
            "name": OWNERSHIP_TABLE,
            "kind": "table",
            "revision": OWNERSHIP_REVISION,
            "preexisting": existed,
        },
    )


def _record_object(name: str, kind: str, preexisting: bool) -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {OWNERSHIP_TABLE}
                (object_name, object_kind, created_by_revision, preexisting)
            VALUES (:name, :kind, :revision, :preexisting)
            ON CONFLICT (object_name) DO NOTHING
            """
        ),
        {
            "name": name,
            "kind": kind,
            "revision": OWNERSHIP_REVISION,
            "preexisting": preexisting,
        },
    )


def _assert_index_contract(name: str, table: str, expected_definition: str) -> None:
    row = op.get_bind().execute(
        sa.text(
            """
            SELECT indexrelid::regclass::text, pg_get_indexdef(indexrelid), indisvalid
            FROM pg_index
            WHERE indexrelid = to_regclass(:qualified)
              AND indrelid = to_regclass(:table)
            """
        ),
        {"qualified": f"public.{name}", "table": f"public.{table}"},
    ).first()
    if not row:
        raise RuntimeError(f"{name} is missing or targets the wrong table")
    if not bool(row[2]):
        raise RuntimeError(f"{name} is invalid; concurrent index build did not complete")
    actual = re.sub(r"\s+", " ", str(row[1]).strip().lower())
    expected = re.sub(r"\s+", " ", expected_definition.strip().lower())
    if actual != expected:
        raise RuntimeError(
            f"{name} has incompatible definition {row[1]!r}; expected {expected_definition!r}"
        )


def _assert_primary_key_contract(table: str, expected: tuple[str, ...]) -> None:
    actual = _primary_key_columns(table)
    if actual != expected:
        raise RuntimeError(
            f"{table} has incompatible primary key {actual!r}; expected {expected!r}"
        )


def _primary_key_columns(table: str) -> tuple[str, ...] | None:
    row = op.get_bind().execute(
        sa.text(
            """
            SELECT array_agg(a.attname ORDER BY keys.ordinality)
            FROM pg_index i
            JOIN pg_class t ON t.oid = i.indrelid
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY
                AS keys(attnum, ordinality)
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = keys.attnum
            WHERE t.relname = :table AND i.indisprimary
            GROUP BY i.indexrelid
            """
        ),
        {"table": table},
    ).first()
    if not row or row[0] is None:
        return None
    return tuple(row[0])


def _constraint_definitions(table: str, constraint_type: str) -> list[str]:
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT lower(regexp_replace(pg_get_constraintdef(c.oid), '[[:space:]]+', ' ', 'g'))
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = :table AND c.contype = :constraint_type
            """
        ),
        {"table": table, "constraint_type": constraint_type},
    ).all()
    return [str(row[0]) for row in rows]


def _ensure_table_contract(
    table: str,
    required_columns: tuple[str, ...],
    primary_key: tuple[str, ...],
    checks: tuple[str, ...] = (),
    foreign_keys: tuple[str, ...] = (),
    column_contracts: dict[str, tuple[str, bool, object]] | None = None,
) -> None:
    columns = {
        str(row[0])
        for row in op.get_bind().execute(
            sa.text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
                """
            ),
            {"table": table},
        ).all()
    }
    missing = sorted(set(required_columns) - columns)
    if missing:
        raise RuntimeError(
            f"{table} exists but is missing required migration columns: {', '.join(missing)}"
        )
    if column_contracts:
        _assert_column_contract(table, column_contracts)
    actual_pk = _primary_key_columns(table)
    if actual_pk != primary_key:
        raise RuntimeError(
            f"{table} has incompatible primary key {actual_pk!r}; expected {primary_key!r}"
        )
    check_defs = _constraint_definitions(table, "c")
    for expected in checks:
        normalized = re.sub(r"\\s+", " ", expected.lower()).strip()
        def equivalent(definition: str) -> bool:
            if normalized in definition:
                return True
            # PostgreSQL deparses varchar CHECK ... IN (...) as a text cast
            # compared with an ANY(ARRAY[...]) expression.
            if normalized.startswith("status in (") and "status::text = any (array[" in definition:
                values = re.findall(r"'([^']+)'", definition)
                return set(values) == {"queued", "running", "completed", "failed"}
            return False
        if not any(equivalent(definition) for definition in check_defs):
            raise RuntimeError(
                f"{table} is missing required check constraint containing {expected!r}"
            )
    fk_defs = _constraint_definitions(table, "f")
    for expected in foreign_keys:
        normalized = expected.lower().replace("  ", " ")
        if not any(normalized in definition for definition in fk_defs):
            raise RuntimeError(
                f"{table} is missing required foreign key containing {expected!r}"
            )


def _owned_objects(kind: str) -> list[str]:
    return [
        str(row[0])
        for row in op.get_bind().execute(
            sa.text(
                f"""
                SELECT object_name FROM {OWNERSHIP_TABLE}
                WHERE object_kind = :kind
                  AND created_by_revision = :revision
                  AND NOT preexisting
                """
            ),
            {"kind": kind, "revision": OWNERSHIP_REVISION},
        ).all()
    ]


def _converge_category_identity() -> None:
    """Adopt the league-aware key, rejecting unknown uniqueness contracts."""
    # The old helper used an empty-string default.  Keep that identity stable
    # for old rows and make the column non-null before rebuilding the key.
    op.execute("ALTER TABLE category_stats_v2 ADD COLUMN IF NOT EXISTS league VARCHAR(100)")
    op.execute("UPDATE category_stats_v2 SET league = '' WHERE league IS NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM category_stats_v2
                GROUP BY address, category, subcategory, league, window_size
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'category_stats_v2 has duplicate canonical identities after league backfill';
            END IF;
        END $$
        """
    )
    # Drop only the known pre-league key.  An unrelated unique contract is a
    # schema error, not something this migration may silently weaken.
    op.execute(
        """
        DO $$
        DECLARE
            c RECORD;
            d TEXT;
        BEGIN
            FOR c IN
                SELECT conname,
                       regexp_replace(lower(pg_get_constraintdef(oid)),
                                      '[[:space:]]+', ' ', 'g') AS definition
                FROM pg_constraint
                WHERE conrelid = 'category_stats_v2'::regclass
                  AND contype IN ('p', 'u')
            LOOP
                d := c.definition;
                IF d = 'primary key (address, category, subcategory, league, window_size)'
                   OR d = 'unique (address, category, subcategory, league, window_size)' THEN
                    CONTINUE;
                ELSIF d = 'primary key (address, category, subcategory, window_size)'
                   OR d = 'unique (address, category, subcategory, window_size)' THEN
                    EXECUTE format('ALTER TABLE category_stats_v2 DROP CONSTRAINT %I', c.conname);
                ELSE
                    RAISE EXCEPTION
                        'incompatible category_stats_v2 uniqueness constraint %: %',
                        c.conname, d;
                END IF;
            END LOOP;
        END $$
        """
    )
    # A hand-created unique index is not represented by pg_constraint.  Accept
    # and remove only the historical four-column index; reject other indexes.
    op.execute(
        """
        DO $$
        DECLARE
            i RECORD;
            columns TEXT[];
        BEGIN
            FOR i IN
                SELECT indexrelid, indexrelid::regclass AS index_name
                FROM pg_index
                WHERE indrelid = 'category_stats_v2'::regclass
                  AND indisunique
                  AND NOT indisprimary
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_constraint c
                      WHERE c.conindid = pg_index.indexrelid
                  )
            LOOP
                SELECT array_agg(a.attname ORDER BY keys.ordinality)
                  INTO columns
                FROM pg_index x
                CROSS JOIN LATERAL unnest(x.indkey) WITH ORDINALITY
                    AS keys(attnum, ordinality)
                JOIN pg_attribute a
                  ON a.attrelid = x.indrelid AND a.attnum = keys.attnum
                WHERE x.indexrelid = i.indexrelid;

                IF columns = ARRAY['address', 'category', 'subcategory', 'league', 'window_size']
                   AND regexp_replace(lower(pg_get_indexdef(i.indexrelid)),
                                       '[[:space:]]+', ' ', 'g') =
                       'create unique index ' || lower(i.indexrelid::regclass::text) ||
                       ' on public.category_stats_v2 using btree (address, category, subcategory, league, window_size)' THEN
                    CONTINUE;
                ELSIF columns = ARRAY['address', 'category', 'subcategory', 'window_size']
                      AND position(' where ' IN lower(pg_get_indexdef(i.indexrelid))) = 0
                      AND position(' using btree ' IN lower(pg_get_indexdef(i.indexrelid))) > 0 THEN
                    EXECUTE format('DROP INDEX %s', i.index_name);
                ELSE
                    RAISE EXCEPTION
                        'incompatible category_stats_v2 unique index %: %',
                        i.index_name, columns;
                END IF;
            END LOOP;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'category_stats_v2'::regclass
                  AND contype = 'p'
                  AND regexp_replace(lower(pg_get_constraintdef(oid)),
                                     '[[:space:]]+', ' ', 'g') =
                      'primary key (address, category, subcategory, league, window_size)'
            ) THEN
                ALTER TABLE category_stats_v2
                    ALTER COLUMN league SET NOT NULL,
                    ADD CONSTRAINT category_stats_v2_pkey
                        PRIMARY KEY (address, category, subcategory, league, window_size);
            END IF;
        END $$
        """
    )


def _validate_base_contracts() -> None:
    contracts = {
        "wallets_v2": (
            ("address", "VARCHAR(42)", True, None),
            ("username", "VARCHAR(255)", False, None),
            ("tier", "VARCHAR(20)", True, "'UNCLASSIFIED'::character varying"),
            ("is_dormant", "BOOLEAN", False, "false"),
            ("last_trade_at", "TIMESTAMPTZ", False, None),
        ),
        "markets_v2": (
            ("condition_id", "VARCHAR(255)", True, None),
            ("title", "TEXT", False, None),
            ("category", "VARCHAR(50)", False, None),
            ("subcategory", "VARCHAR(100)", False, None),
            ("status", "VARCHAR(20)", False, "'ACTIVE'::character varying"),
        ),
        "wallet_metrics_v2": (
            ("address", "VARCHAR(42)", True, None),
            ("total_pnl", "NUMERIC", False, "0"),
            ("total_volume", "NUMERIC", False, "0"),
        ),
        "category_stats_v2": (
            ("address", "VARCHAR(42)", True, None),
            ("category", "VARCHAR(50)", True, None),
            ("subcategory", "VARCHAR(100)", True, "''::character varying"),
            ("window_size", "INTEGER", True, "0"),
            ("pnl", "NUMERIC", False, None),
            ("volume", "NUMERIC", False, None),
        ),
        "wallet_positions_v2": (
            ("address", "VARCHAR(42)", True, None),
            ("condition_id", "VARCHAR(255)", True, None),
            ("outcome", "VARCHAR(255)", True, None),
            ("size", "NUMERIC", False, None),
        ),
        "wallet_closed_positions_v2": (
            ("address", "VARCHAR(42)", True, None),
            ("condition_id", "VARCHAR(255)", True, None),
            ("outcome", "VARCHAR(255)", True, None),
            ("realized_pnl", "NUMERIC", False, None),
            ("closed_at", "TIMESTAMPTZ", False, None),
        ),
    }
    for table, columns in contracts.items():
        _assert_column_contract(
            table,
            {name: (type_name, notnull, default) for name, type_name, notnull, default in columns},
        )
    for table, expected_pk in (
        ("wallets_v2", ("address",)),
        ("markets_v2", ("condition_id",)),
        ("wallet_metrics_v2", ("address",)),
        ("wallet_positions_v2", ("address", "condition_id", "outcome")),
        ("wallet_closed_positions_v2", ("address", "condition_id", "outcome")),
    ):
        _assert_primary_key_contract(table, expected_pk)


def _validate_analytics_contracts() -> None:
    contracts = {
        "wallet_metric_windows_v2": {
            "address": ("VARCHAR(42)", True, None),
            "window_size": ("INTEGER", True, None),
            "pnl": ("NUMERIC", False, None),
            "volume": ("NUMERIC", False, None),
            "roi_pct": ("NUMERIC", False, None),
            "win_rate": ("NUMERIC", False, None),
            "resolved_count": ("INTEGER", False, None),
            "winning_count": ("INTEGER", False, None),
            "available_row_count": ("INTEGER", False, None),
            "completeness_pct": ("NUMERIC", False, None),
            "formula_version": ("VARCHAR(64)", False, None),
            "computed_at": ("TIMESTAMPTZ", False, None),
        },
        "official_category_stats_v2": {
            "snapshot_id": ("BIGINT", True, _ANY_DEFAULT),
            "address": ("VARCHAR(42)", True, None),
            "category": ("VARCHAR(50)", True, None),
            "subcategory": ("VARCHAR(100)", True, "''::character varying"),
            "league": ("VARCHAR(100)", True, "''::character varying"),
            "window_size": ("INTEGER", True, "0"),
            "source": ("VARCHAR(64)", True, None),
            "pnl": ("NUMERIC", False, None),
            "volume": ("NUMERIC", False, None),
            "roi_pct": ("NUMERIC", False, None),
            "win_rate": ("NUMERIC", False, None),
            "resolved_count": ("INTEGER", False, None),
            "winning_count": ("INTEGER", False, None),
            "snapshot_at": ("TIMESTAMPTZ", True, None),
            "created_at": ("TIMESTAMPTZ", True, "now()"),
        },
        "ledger_backfill_runs_v2": {
            "run_id": ("UUID", True, None),
            "job_name": ("VARCHAR(100)", True, None),
            "formula_version": ("VARCHAR(64)", False, None),
            "status": ("VARCHAR(20)", True, None),
            "started_at": ("TIMESTAMPTZ", False, None),
            "finished_at": ("TIMESTAMPTZ", False, None),
            "last_error": ("TEXT", False, None),
            "metadata": ("JSONB", True, "'{}'::jsonb"),
            "created_at": ("TIMESTAMPTZ", True, "now()"),
        },
        "ledger_backfill_checkpoints_v2": {
            "run_id": ("UUID", True, None),
            "address": ("VARCHAR(42)", True, None),
            "last_closed_at": ("TIMESTAMPTZ", False, None),
            "processed_rows": ("BIGINT", True, "0"),
            "available_rows": ("BIGINT", False, None),
            "updated_at": ("TIMESTAMPTZ", True, "now()"),
        },
    }
    primary_keys = {
        "wallet_metric_windows_v2": ("address", "window_size"),
        "official_category_stats_v2": ("snapshot_id",),
        "ledger_backfill_runs_v2": ("run_id",),
        "ledger_backfill_checkpoints_v2": ("run_id", "address"),
    }
    for table, contract in contracts.items():
        _assert_column_contract(table, contract)
        _assert_primary_key_contract(table, primary_keys[table])


def _create_analytics_tables() -> None:
    table_specs = (
        (
            "wallet_metric_windows_v2",
            """
            CREATE TABLE IF NOT EXISTS wallet_metric_windows_v2 (
                address VARCHAR(42) NOT NULL REFERENCES wallets_v2(address) ON DELETE CASCADE,
                window_size INTEGER NOT NULL CHECK (window_size >= 0),
                pnl NUMERIC, volume NUMERIC, roi_pct NUMERIC, win_rate NUMERIC,
                resolved_count INTEGER, winning_count INTEGER,
                available_row_count INTEGER, completeness_pct NUMERIC,
                formula_version VARCHAR(64), computed_at TIMESTAMPTZ,
                PRIMARY KEY (address, window_size)
            )
            """,
            ("address", "window_size", "pnl", "volume", "roi_pct", "win_rate",
             "resolved_count", "winning_count", "available_row_count",
             "completeness_pct", "formula_version", "computed_at"),
            ("address", "window_size"),
            ("window_size >= 0",),
            ("wallets_v2",),
        ),
        (
            "official_category_stats_v2",
            """
            CREATE TABLE IF NOT EXISTS official_category_stats_v2 (
                snapshot_id BIGSERIAL PRIMARY KEY,
                address VARCHAR(42) NOT NULL, category VARCHAR(50) NOT NULL,
                subcategory VARCHAR(100) NOT NULL DEFAULT '', league VARCHAR(100) NOT NULL DEFAULT '',
                window_size INTEGER NOT NULL DEFAULT 0, source VARCHAR(64) NOT NULL,
                pnl NUMERIC, volume NUMERIC, roi_pct NUMERIC, win_rate NUMERIC,
                resolved_count INTEGER, winning_count INTEGER,
                snapshot_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            ("snapshot_id", "address", "category", "subcategory", "league", "window_size",
             "source", "pnl", "volume", "roi_pct", "win_rate", "resolved_count",
             "winning_count", "snapshot_at", "created_at"),
            ("snapshot_id",),
            (),
            (),
        ),
        (
            "ledger_backfill_runs_v2",
            """
            CREATE TABLE IF NOT EXISTS ledger_backfill_runs_v2 (
                run_id UUID PRIMARY KEY, job_name VARCHAR(100) NOT NULL,
                formula_version VARCHAR(64), status VARCHAR(20) NOT NULL CHECK
                    (status IN ('queued', 'running', 'completed', 'failed')),
                started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, last_error TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            ("run_id", "job_name", "formula_version", "status", "started_at", "finished_at",
             "last_error", "metadata", "created_at"),
            ("run_id",),
            ("status IN ('queued', 'running', 'completed', 'failed')",),
            (),
        ),
        (
            "ledger_backfill_checkpoints_v2",
            """
            CREATE TABLE IF NOT EXISTS ledger_backfill_checkpoints_v2 (
                run_id UUID NOT NULL REFERENCES ledger_backfill_runs_v2(run_id) ON DELETE CASCADE,
                address VARCHAR(42) NOT NULL, last_closed_at TIMESTAMPTZ,
                processed_rows BIGINT NOT NULL DEFAULT 0, available_rows BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (run_id, address)
            )
            """,
            ("run_id", "address", "last_closed_at", "processed_rows", "available_rows", "updated_at"),
            ("run_id", "address"),
            (),
            ("ledger_backfill_runs_v2",),
        ),
    )
    for table, ddl, columns, primary_key, checks, foreign_keys in table_specs:
        existed = _table_exists(table)
        op.execute(ddl)
        _record_object(table, "table", existed)
        _ensure_table_contract(table, columns, primary_key, checks, foreign_keys)

    for name, table, ddl in (
        ("idx_official_category_stats_snapshot_v2", "official_category_stats_v2",
         "CREATE INDEX IF NOT EXISTS idx_official_category_stats_snapshot_v2 ON official_category_stats_v2 (address, snapshot_at DESC)"),
        ("idx_ledger_backfill_checkpoints_updated_v2", "ledger_backfill_checkpoints_v2",
         "CREATE INDEX IF NOT EXISTS idx_ledger_backfill_checkpoints_updated_v2 ON ledger_backfill_checkpoints_v2 (run_id, updated_at DESC)"),
    ):
        existed = bool(op.get_bind().execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{name}"}).scalar())
        op.execute(ddl)
        _record_object(name, "index", existed)
        expected_definition = {
            "idx_official_category_stats_snapshot_v2":
                "CREATE INDEX idx_official_category_stats_snapshot_v2 ON public.official_category_stats_v2 USING btree (address, snapshot_at DESC)",
            "idx_ledger_backfill_checkpoints_updated_v2":
                "CREATE INDEX idx_ledger_backfill_checkpoints_updated_v2 ON public.ledger_backfill_checkpoints_v2 USING btree (run_id, updated_at DESC)",
        }[name]
        _assert_index_contract(name, table, expected_definition)
    _validate_analytics_contracts()


def _create_closed_position_index() -> None:
    # wallet_closed_positions_v2 is intentionally large in production.  The
    # migration runner normally starts in a transaction, so this block is
    # required for PostgreSQL's CREATE INDEX CONCURRENTLY rule.
    exists = op.get_bind().execute(
        sa.text("SELECT to_regclass('public.wallet_closed_positions_v2') IS NOT NULL")
    ).scalar()
    if exists:
        index_exists = bool(
            op.get_bind().execute(
                sa.text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": "public.idx_closed_ledger_backfill_v2"},
            ).scalar()
        )
        with op.get_context().autocommit_block():
            op.execute(
                """
                CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_closed_ledger_backfill_v2
                    ON wallet_closed_positions_v2
                       (address, closed_at DESC, condition_id, outcome)
                """
            )
        _record_object("idx_closed_ledger_backfill_v2", "index", index_exists)
        _assert_index_contract(
            "idx_closed_ledger_backfill_v2",
            "wallet_closed_positions_v2",
            "CREATE INDEX idx_closed_ledger_backfill_v2 ON public.wallet_closed_positions_v2 USING btree (address, closed_at DESC, condition_id, outcome)",
        )


def upgrade() -> None:
    _ensure_ownership_table()
    _ensure_base_tables()
    _add_columns(
        "markets_v2",
        {
            "category": "VARCHAR(50)",
            "subcategory": "VARCHAR(100)",
            "league": "VARCHAR(100)",
            "event_slug": "VARCHAR(255)",
        },
    )
    op.execute("ALTER TABLE markets_v2 ALTER COLUMN league SET DEFAULT ''")
    op.execute("ALTER TABLE markets_v2 ALTER COLUMN event_slug SET DEFAULT ''")
    _add_columns(
        "category_stats_v2",
        {
            "subcategory": "VARCHAR(100)",
            "league": "VARCHAR(100)",
            "window_size": "INTEGER",
            "pnl": "NUMERIC",
            "volume": "NUMERIC",
            "win_rate": "NUMERIC",
            "roi_pct": "NUMERIC",
            "resolved_count": "INTEGER",
            "winning_count": "INTEGER",
            "last_active": "TIMESTAMPTZ",
            "computed_at": "TIMESTAMPTZ",
        },
    )
    _add_columns(
        "wallet_positions_v2",
        {
            "is_parlay": "BOOLEAN",
            "is_resolved": "BOOLEAN",
            "asset_token_id": "TEXT",
        },
    )
    _add_columns(
        "wallet_closed_positions_v2",
        {
            "is_parlay": "BOOLEAN",
            "is_redeemable": "BOOLEAN",
            "resolved_at": "TIMESTAMPTZ",
            "data_quality_flag": "TEXT",
            "metrics_eligible": "BOOLEAN",
            "exclusion_reason": "TEXT",
            "excluded_at": "TIMESTAMPTZ",
            "source_asset": "TEXT",
            "asset_token_id": "TEXT",
            # Nullable by design: do not rewrite the large closed table.
            "source_realized_pnl": "NUMERIC",
            "ledger_cost_basis": "NUMERIC",
            "ledger_volume_usd": "NUMERIC",
            "ledger_settlement_value": "NUMERIC",
            "ledger_pnl": "NUMERIC",
            "ledger_formula_version": "VARCHAR(64)",
            "ledger_provenance_version": "VARCHAR(64)",
            "settlement_included": "BOOLEAN",
            "ledger_computed_at": "TIMESTAMPTZ",
            "normalized_parlay_key": "TEXT",
        },
    )
    metric_defs: dict[str, str] = {
        "total_pnl": "NUMERIC",
        "total_volume": "NUMERIC",
        "roi_pct": "NUMERIC",
        "win_rate": "NUMERIC",
        "resolved_count": "INTEGER",
        "winning_count": "INTEGER",
        "avg_buy_price": "NUMERIC",
        "data_completeness_pct": "NUMERIC",
        "parlay_pnl": "NUMERIC",
        "parlay_volume": "NUMERIC",
        "parlay_win_rate": "NUMERIC",
        "parlay_resolved_count": "INTEGER",
        "parlay_winning_count": "INTEGER",
        **{f"pnl_{n}": "NUMERIC" for n in (100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000)},
        "pnl_all": "NUMERIC",
        "position_value": "NUMERIC",
        "parlay_open_count": "INTEGER",
        "parlay_open_value": "NUMERIC",
        "redeemable_count": "INTEGER",
        "redeemable_winning_count": "INTEGER",
        "computed_at": "TIMESTAMPTZ",
        "categories_computed_at": "TIMESTAMPTZ",
        "open_synced_at": "TIMESTAMPTZ",
        "closed_synced_at": "TIMESTAMPTZ",
        "capital_synced_at": "TIMESTAMPTZ",
        "pm_pnl": "NUMERIC",
        "pm_volume": "NUMERIC",
        "pm_rank": "INTEGER",
        "pm_synced_at": "TIMESTAMPTZ",
        "balance": "NUMERIC",
        "deposits": "NUMERIC",
        "withdrawals": "NUMERIC",
    }
    for bucket in ("below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c"):
        metric_defs.update(
            {
                f"buys_{bucket}": "INTEGER",
                f"wins_{bucket}": "INTEGER",
                f"losses_{bucket}": "INTEGER",
                f"avg_sell_{bucket}": "NUMERIC",
            }
        )
    _add_columns("wallet_metrics_v2", metric_defs)
    # Converge the historical four-column key before any contract validation;
    # validation must inspect the canonical league-aware identity, not reject
    # the supported legacy shape first.
    _converge_category_identity()
    _validate_base_contracts()
    _assert_exact_token_identity("wallet_positions_v2")
    _assert_exact_token_identity("wallet_closed_positions_v2")
    _create_analytics_tables()
    _create_closed_position_index()


def downgrade() -> None:
    # Keep additive columns on downgrade: a league column may have been
    # created by the historical helper before this revision, and dropping it
    # would destroy production data.  Only objects recorded as created by this
    # revision are eligible for removal; pre-existing objects are preserved.
    if not _table_exists(OWNERSHIP_TABLE):
        raise RuntimeError(
            "cannot safely downgrade ledger analytics schema without ownership records"
        )

    owned_indexes = set(_owned_objects("index"))
    if "idx_closed_ledger_backfill_v2" in owned_indexes:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_closed_ledger_backfill_v2")
    for index_name in (
        "idx_ledger_backfill_checkpoints_updated_v2",
        "idx_official_category_stats_snapshot_v2",
    ):
        if index_name in owned_indexes:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")

    for table_name in (
        "ledger_backfill_checkpoints_v2",
        "ledger_backfill_runs_v2",
        "official_category_stats_v2",
        "wallet_metric_windows_v2",
    ):
        if table_name in set(_owned_objects("table")):
            op.execute(f"DROP TABLE IF EXISTS {table_name}")
