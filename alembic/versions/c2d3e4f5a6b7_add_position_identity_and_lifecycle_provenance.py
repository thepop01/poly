"""Add token-aware identity evidence and lifecycle provenance schema.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-09

This is an expand migration.  It unblocks Task 4 without changing the published
canonical metric grain: ``wallet_positions_v2`` and
``wallet_closed_positions_v2`` keep their ``(address, condition_id, outcome)``
primary keys.

Design rules enforced here:

* The ancestor's ``wallet_source_snapshots_v2`` is reused.  A second snapshot
  table is never created.  If the ancestor table is absent (a database that was
  built from a partial fixture) it is created once, with the ancestor's exact
  shape, and recorded as owned by this revision.
* Every pre-existing evidence/decision table is validated fail-closed against
  its exact catalog contract (columns, types, nullability, defaults, primary
  key, foreign keys, checks and indexes) before anything else happens.  An
  incompatible table aborts the upgrade instead of being silently adopted.
* Exact token identity is TEXT.  A NUMERIC/float token column can never recover
  leading zeros, so it is rejected rather than migrated.
* Every table, column, constraint, index, sequence, trigger, function and
  metadata row created here is recorded in ``ledger_schema_objects_v2``.
  ``downgrade()`` removes only objects this revision actually created and fails
  closed when ownership cannot be proven.

Trigger semantics on both canonical position tables (executable PostgreSQL, not
documentation): legacy all-null provenance accepts unrelated updates; exactly
one atomic all-null -> complete initialization is allowed; partial provenance is
rejected on INSERT and UPDATE; initialized provenance can neither be cleared nor
rewritten; lifecycle transitions require complete provenance and a complete
referenced snapshot; terminal states cannot transition.  Identity evidence and
identity decisions are append-only.

No production backfill behaviour is invented: all new position columns are
nullable with no default and no row is rewritten.
"""
from __future__ import annotations

import re
from typing import Final

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: str = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


OWNERSHIP_TABLE: Final[str] = "ledger_schema_objects_v2"
OWNERSHIP_REVISION: Final[str] = revision

SNAPSHOT_TABLE: Final[str] = "wallet_source_snapshots_v2"
SNAPSHOT_INDEX: Final[str] = "idx_wallet_source_snapshots_address_v2"
EVIDENCE_TABLE: Final[str] = "wallet_position_identity_evidence_v2"
DECISION_TABLE: Final[str] = "wallet_position_identity_decisions_v2"

POSITION_TABLES: Final[tuple[str, ...]] = (
    "wallet_positions_v2",
    "wallet_closed_positions_v2",
)

# Provenance columns that must be initialized together.  ``provenance_event_hash``
# and ``provenance_reason`` are optional annotations, tracked separately below.
REQUIRED_PROVENANCE_COLUMNS: Final[tuple[str, ...]] = (
    "provenance_kind",
    "lifecycle_state",
    "provenance_snapshot_id",
    "first_seen_at",
    "last_seen_at",
)
OPTIONAL_PROVENANCE_COLUMNS: Final[tuple[str, ...]] = (
    "provenance_event_hash",
    "provenance_reason",
)
PROVENANCE_COLUMNS: Final[tuple[str, ...]] = (
    REQUIRED_PROVENANCE_COLUMNS + OPTIONAL_PROVENANCE_COLUMNS
)
# Immutable once provenance is initialized.
IMMUTABLE_PROVENANCE_COLUMNS: Final[tuple[str, ...]] = (
    "provenance_kind",
    "first_seen_at",
)

PROVENANCE_KINDS: Final[tuple[str, ...]] = ("ordinary", "redeemable", "synthetic")
LIFECYCLE_STATES: Final[tuple[str, ...]] = (
    "ordinary",
    "redeemable",
    "redeemed",
    "expired",
    "superseded",
)
TERMINAL_LIFECYCLE_STATES: Final[tuple[str, ...]] = (
    "redeemed",
    "expired",
    "superseded",
)
# Monotonic, idempotent lifecycle transitions.  Anything else is rejected.
LIFECYCLE_TRANSITIONS: Final[tuple[tuple[str, str], ...]] = (
    ("ordinary", "redeemable"),
    ("ordinary", "superseded"),
    ("redeemable", "redeemed"),
    ("redeemable", "expired"),
    ("redeemable", "superseded"),
)

DECISION_STATUSES: Final[tuple[str, ...]] = (
    "eligible",
    "review_required",
    "excluded_proven",
)
# Synthetic provenance is only ever justified by explicit ledger events, never
# by a price or quantity heuristic.
EVIDENCE_TYPES: Final[tuple[str, ...]] = (
    "positions_snapshot",
    "activity_event",
    "redemption",
    "mint",
    "split",
    "merge",
    "transfer",
)

PROVENANCE_COLUMN_DEFINITIONS: Final[dict[str, str]] = {
    "provenance_kind": "TEXT",
    "lifecycle_state": "TEXT",
    "provenance_snapshot_id": "BIGINT",
    "provenance_event_hash": "TEXT",
    "provenance_reason": "TEXT",
    "first_seen_at": "TIMESTAMPTZ",
    "last_seen_at": "TIMESTAMPTZ",
}
EXTRA_POSITION_COLUMNS: Final[dict[str, dict[str, str]]] = {
    # Open rows need a resolution timestamp; the closed table already has one.
    "wallet_positions_v2": {"resolved_at": "TIMESTAMPTZ"},
    # Closed rows need an explicit redemption timestamp.
    "wallet_closed_positions_v2": {"redeemed_at": "TIMESTAMPTZ"},
}

GUARD_FUNCTION: Final[str] = "ledger_position_provenance_guard_v2"
SNAPSHOT_CHECK_FUNCTION: Final[str] = "ledger_require_complete_snapshot_v2"
APPEND_ONLY_FUNCTION: Final[str] = "ledger_append_only_guard_v2"

PROVENANCE_TRIGGERS: Final[dict[str, str]] = {
    "wallet_positions_v2": "trg_wallet_positions_v2_provenance",
    "wallet_closed_positions_v2": "trg_wallet_closed_positions_v2_provenance",
}
APPEND_ONLY_TRIGGERS: Final[dict[str, str]] = {
    EVIDENCE_TABLE: "trg_wallet_position_identity_evidence_v2_append_only",
    DECISION_TABLE: "trg_wallet_position_identity_decisions_v2_append_only",
}

CREATED_INDEXES: Final[tuple[str, ...]] = (
    "idx_wallet_position_identity_evidence_lookup_v2",
    "idx_wallet_position_identity_evidence_snapshot_v2",
    "uq_wallet_position_identity_evidence_v2",
    "uq_wallet_position_identity_decisions_v2",
)
CREATED_SEQUENCES: Final[tuple[str, ...]] = (
    f"{EVIDENCE_TABLE}_id_seq",
    f"{DECISION_TABLE}_id_seq",
)

METADATA_OBJECT: Final[str] = f"{OWNERSHIP_TABLE}:{revision}"


# --------------------------------------------------------------------------
# Catalog helpers
# --------------------------------------------------------------------------

_ANY_DEFAULT = object()


def _bind():
    return op.get_bind()


def _normalize_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_catalog_type(value: str) -> str:
    value = _normalize_sql(value)
    value = value.replace("varchar", "character varying")
    value = value.replace("timestamp with time zone", "timestamptz")
    value = value.replace("timestamp without time zone", "timestamp")
    return value


def _table_exists(table: str) -> bool:
    return bool(
        _bind()
        .execute(
            sa.text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"public.{table}"},
        )
        .scalar()
    )


def _relation_exists(name: str) -> bool:
    return bool(
        _bind()
        .execute(
            sa.text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"public.{name}"},
        )
        .scalar()
    )


def _function_exists(name: str) -> bool:
    return bool(
        _bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public' AND p.proname = :name
                )
                """
            ),
            {"name": name},
        )
        .scalar()
    )


def _trigger_exists(table: str, name: str) -> bool:
    return bool(
        _bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger tg
                    JOIN pg_class t ON t.oid = tg.tgrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'public'
                      AND t.relname = :table
                      AND tg.tgname = :name
                      AND NOT tg.tgisinternal
                )
                """
            ),
            {"table": table, "name": name},
        )
        .scalar()
    )


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        _bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'public'
                      AND t.relname = :table
                      AND c.conname = :name
                )
                """
            ),
            {"table": table, "name": name},
        )
        .scalar()
    )


def _column_exists(table: str, column: str) -> bool:
    return column in _catalog_columns(table)


def _catalog_columns(table: str) -> dict[str, tuple[str, bool, str | None]]:
    rows = (
        _bind()
        .execute(
            sa.text(
                """
                SELECT a.attname,
                       format_type(a.atttypid, a.atttypmod),
                       a.attnotnull,
                       pg_get_expr(d.adbin, d.adrelid)
                FROM pg_attribute a
                JOIN pg_class t ON t.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                LEFT JOIN pg_attrdef d
                       ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE n.nspname = 'public' AND t.relname = :table
                  AND a.attnum > 0 AND NOT a.attisdropped
                """
            ),
            {"table": table},
        )
        .all()
    )
    return {
        str(name): (_normalize_catalog_type(str(type_name)), bool(notnull), default)
        for name, type_name, notnull, default in rows
    }


def _primary_key_columns(table: str) -> tuple[str, ...] | None:
    row = (
        _bind()
        .execute(
            sa.text(
                """
                SELECT array_agg(a.attname ORDER BY keys.ordinality)
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY
                    AS keys(attnum, ordinality)
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = keys.attnum
                WHERE n.nspname = 'public' AND t.relname = :table AND i.indisprimary
                GROUP BY i.indexrelid
                """
            ),
            {"table": table},
        )
        .first()
    )
    if not row or row[0] is None:
        return None
    return tuple(row[0])


def _constraint_definitions(table: str, constraint_type: str) -> list[str]:
    rows = (
        _bind()
        .execute(
            sa.text(
                """
                SELECT lower(regexp_replace(pg_get_constraintdef(c.oid),
                                            '[[:space:]]+', ' ', 'g'))
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = :table
                  -- ``contype`` is ``"char"``; compare as text so the driver
                  -- binds a plain string parameter.
                  AND c.contype::text = :constraint_type
                """
            ),
            {"table": table, "constraint_type": constraint_type},
        )
        .all()
    )
    return [str(row[0]) for row in rows]


def _index_definitions(table: str) -> dict[str, str]:
    rows = (
        _bind()
        .execute(
            sa.text(
                """
                SELECT i.indexrelid::regclass::text,
                       regexp_replace(lower(pg_get_indexdef(i.indexrelid)),
                                      '[[:space:]]+', ' ', 'g'),
                       i.indisvalid
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public' AND t.relname = :table
                """
            ),
            {"table": table},
        )
        .all()
    )
    definitions: dict[str, str] = {}
    for name, definition, valid in rows:
        short = str(name).split(".")[-1].strip('"')
        if not bool(valid):
            raise RuntimeError(
                f"{table} index {short} is invalid; a concurrent build did not "
                "complete.  Repair the index before upgrading."
            )
        definitions[short] = str(definition)
    return definitions


def _assert_column_contract(
    table: str, contracts: dict[str, tuple[str, bool, object]]
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
        actual_normalized = (
            None if actual_default is None else _normalize_sql(str(actual_default))
        )
        expected_normalized = (
            None
            if expected_default is None
            else _normalize_sql(str(expected_default))
        )
        if actual_normalized != expected_normalized:
            raise RuntimeError(
                f"{table}.{column} has incompatible default {actual_default!r}; "
                f"expected {expected_default!r}"
            )


def _assert_primary_key(table: str, expected: tuple[str, ...]) -> None:
    actual = _primary_key_columns(table)
    if actual != expected:
        raise RuntimeError(
            f"{table} has incompatible primary key {actual!r}; expected {expected!r}"
        )


def _assert_constraint_fragments(
    table: str, constraint_type: str, fragments: tuple[str, ...]
) -> None:
    definitions = _constraint_definitions(table, constraint_type)
    kind = {"c": "check", "f": "foreign key"}[constraint_type]
    for fragment in fragments:
        needle = _normalize_sql(fragment)
        if not any(needle in definition for definition in definitions):
            raise RuntimeError(
                f"{table} is missing a required {kind} constraint containing "
                f"{fragment!r}; found {definitions!r}"
            )


def _assert_index_definitions(
    table: str, expected: dict[str, str]
) -> None:
    definitions = _index_definitions(table)
    for name, expected_definition in expected.items():
        actual = definitions.get(name)
        if actual is None:
            raise RuntimeError(
                f"{table} is missing required index {name}; found "
                f"{sorted(definitions)!r}"
            )
        if actual != _normalize_sql(expected_definition):
            raise RuntimeError(
                f"{name} has incompatible definition {actual!r}; expected "
                f"{_normalize_sql(expected_definition)!r}"
            )


def _assert_exact_token_identity(table: str, column: str) -> None:
    """Reject any token column that cannot round-trip an exact string."""
    actual = _catalog_columns(table).get(column)
    if actual is None:
        raise RuntimeError(f"{table}.{column} is missing")
    actual_type, actual_notnull, actual_default = actual
    if actual_type != "text" and not re.fullmatch(
        r"character varying\(\d+\)", actual_type
    ):
        raise RuntimeError(
            f"{table}.{column} has incompatible exact-identity type "
            f"{actual_type!r}; numeric legacy values cannot recover leading "
            "zeros; repair the source-backed schema before upgrading"
        )
    if actual_notnull or actual_default is not None:
        raise RuntimeError(
            f"{table}.{column} must remain nullable with no default so legacy "
            "rows are not fabricated"
        )


# --------------------------------------------------------------------------
# Ownership
# --------------------------------------------------------------------------


def _require_ownership_table() -> None:
    if not _table_exists(OWNERSHIP_TABLE):
        raise RuntimeError(
            f"{OWNERSHIP_TABLE} is missing; the ledger analytics revision "
            "b1c2d3e4f5a6 must run before identity/lifecycle provenance can be "
            "recorded safely"
        )


def _record_object(name: str, kind: str, preexisting: bool) -> None:
    _bind().execute(
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


def _ownership_row(name: str) -> tuple[str, str, bool] | None:
    row = (
        _bind()
        .execute(
            sa.text(
                f"""
                SELECT object_kind, created_by_revision, preexisting
                FROM {OWNERSHIP_TABLE}
                WHERE object_name = :name
                """
            ),
            {"name": name},
        )
        .first()
    )
    if row is None:
        return None
    return (str(row[0]), str(row[1]), bool(row[2]))


def _is_droppable(name: str, kind: str, exists: bool) -> bool:
    """Fail closed unless this revision provably created ``name``."""
    if not exists:
        return False
    row = _ownership_row(name)
    if row is None:
        raise RuntimeError(
            f"refusing to drop {kind} {name}: no ownership record exists, so "
            "this revision cannot prove it created the object"
        )
    recorded_kind, recorded_revision, preexisting = row
    if recorded_revision != OWNERSHIP_REVISION:
        # Owned by another revision; preserve it and let that revision decide.
        return False
    if recorded_kind != kind:
        raise RuntimeError(
            f"refusing to drop {name}: ownership records kind {recorded_kind!r} "
            f"but the object is a {kind}"
        )
    return not preexisting


# --------------------------------------------------------------------------
# Ancestor validation (fail-closed)
# --------------------------------------------------------------------------

_SNAPSHOT_CONTRACT: Final[dict[str, tuple[str, bool, object]]] = {
    "id": ("BIGINT", True, _ANY_DEFAULT),
    "address": ("VARCHAR(42)", True, None),
    "source": ("TEXT", True, None),
    "complete": ("BOOLEAN", True, None),
    "fetched_at": ("TIMESTAMPTZ", True, "now()"),
    "payload_sha256": ("TEXT", True, None),
    "metadata": ("JSONB", True, "'{}'::jsonb"),
}

_LEGACY_EVIDENCE_CONTRACT: Final[dict[str, tuple[str, bool, object]]] = {
    "id": ("BIGINT", True, _ANY_DEFAULT),
    "address": ("VARCHAR(42)", True, None),
    "condition_id": ("VARCHAR(255)", True, None),
    "asset": ("TEXT", False, None),
    "outcome": ("TEXT", False, None),
    "evidence_type": ("TEXT", True, None),
    "transaction_hash": ("VARCHAR(66)", False, None),
    "snapshot_id": ("BIGINT", True, None),
    "created_at": ("TIMESTAMPTZ", True, "now()"),
}

_LEGACY_DECISION_CONTRACT: Final[dict[str, tuple[str, bool, object]]] = {
    "id": ("BIGINT", True, _ANY_DEFAULT),
    "audit_id": ("UUID", True, None),
    "address": ("VARCHAR(42)", True, None),
    "condition_id": ("VARCHAR(255)", True, None),
    "outcome": ("TEXT", True, None),
    "status": ("TEXT", True, None),
    "reason": ("TEXT", True, None),
    "evidence_id": ("BIGINT", False, None),
    "created_at": ("TIMESTAMPTZ", True, "now()"),
}


def _validate_preexisting_evidence_tables() -> None:
    """Validate every pre-existing evidence/decision table, fail-closed.

    These tables are produced by revision ``m6n7o8p9q0r1``.  They are never
    rewritten here; an incompatible shape aborts the upgrade so that Task 4 can
    never consume ambiguous identity evidence.
    """
    if _table_exists(SNAPSHOT_TABLE):
        _assert_column_contract(SNAPSHOT_TABLE, _SNAPSHOT_CONTRACT)
        _assert_primary_key(SNAPSHOT_TABLE, ("id",))
        _assert_index_definitions(
            SNAPSHOT_TABLE,
            {
                SNAPSHOT_INDEX: (
                    f"create index {SNAPSHOT_INDEX} on public.{SNAPSHOT_TABLE} "
                    "using btree (address, fetched_at desc)"
                )
            },
        )

    if _table_exists("wallet_position_evidence_v2"):
        # ``asset`` carries an exact source token identity; check it first so a
        # lost-identity column produces the identity-specific failure.
        _assert_exact_token_identity("wallet_position_evidence_v2", "asset")
        _assert_column_contract(
            "wallet_position_evidence_v2", _LEGACY_EVIDENCE_CONTRACT
        )
        _assert_primary_key("wallet_position_evidence_v2", ("id",))
        _assert_constraint_fragments(
            "wallet_position_evidence_v2",
            "f",
            (f"foreign key (snapshot_id) references {SNAPSHOT_TABLE}(id)",),
        )
        _assert_index_definitions(
            "wallet_position_evidence_v2",
            {
                "idx_wallet_position_evidence_lookup_v2": (
                    "create index idx_wallet_position_evidence_lookup_v2 on "
                    "public.wallet_position_evidence_v2 using btree "
                    "(address, condition_id, asset)"
                )
            },
        )
        # ``asset`` carries an exact source token identity.
        _assert_exact_token_identity("wallet_position_evidence_v2", "asset")

    if _table_exists("wallet_position_audit_decisions_v2"):
        _assert_column_contract(
            "wallet_position_audit_decisions_v2", _LEGACY_DECISION_CONTRACT
        )
        _assert_primary_key("wallet_position_audit_decisions_v2", ("id",))
        _assert_constraint_fragments(
            "wallet_position_audit_decisions_v2",
            "f",
            ("foreign key (evidence_id) references wallet_position_evidence_v2(id)",),
        )
        _assert_constraint_fragments(
            "wallet_position_audit_decisions_v2",
            "c",
            ("status = any",),
        )
        _assert_index_definitions(
            "wallet_position_audit_decisions_v2",
            {
                "idx_wallet_position_audit_decisions_audit_v2": (
                    "create index idx_wallet_position_audit_decisions_audit_v2 on "
                    "public.wallet_position_audit_decisions_v2 using btree "
                    "(audit_id, address)"
                )
            },
        )


def _ensure_source_snapshot_table() -> None:
    """Reuse the ancestor snapshot table; create it only when truly absent."""
    existed = _table_exists(SNAPSHOT_TABLE)
    index_existed = _relation_exists(SNAPSHOT_INDEX)
    sequence_existed = _relation_exists(f"{SNAPSHOT_TABLE}_id_seq")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SNAPSHOT_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            source TEXT NOT NULL,
            complete BOOLEAN NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payload_sha256 TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {SNAPSHOT_INDEX} "
        f"ON {SNAPSHOT_TABLE} (address, fetched_at DESC)"
    )
    _record_object(SNAPSHOT_TABLE, "table", existed)
    _record_object(SNAPSHOT_INDEX, "index", index_existed)
    _record_object(f"{SNAPSHOT_TABLE}_id_seq", "sequence", sequence_existed)


# --------------------------------------------------------------------------
# New identity tables
# --------------------------------------------------------------------------


def _sql_string_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _create_identity_tables() -> None:
    evidence_existed = _table_exists(EVIDENCE_TABLE)
    evidence_seq_existed = _relation_exists(f"{EVIDENCE_TABLE}_id_seq")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EVIDENCE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            asset_token_id TEXT,
            source_asset TEXT,
            outcome TEXT,
            evidence_type VARCHAR(32) NOT NULL,
            transaction_hash VARCHAR(66),
            event_sha256 TEXT,
            snapshot_id BIGINT NOT NULL REFERENCES {SNAPSHOT_TABLE}(id),
            observed_at TIMESTAMPTZ,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_{EVIDENCE_TABLE}_identity_present
                CHECK (asset_token_id IS NOT NULL OR source_asset IS NOT NULL),
            CONSTRAINT ck_{EVIDENCE_TABLE}_evidence_type
                CHECK (evidence_type IN ({_sql_string_list(EVIDENCE_TYPES)}))
        )
        """
    )
    _record_object(EVIDENCE_TABLE, "table", evidence_existed)
    _record_object(f"{EVIDENCE_TABLE}_id_seq", "sequence", evidence_seq_existed)
    for constraint in (
        f"ck_{EVIDENCE_TABLE}_identity_present",
        f"ck_{EVIDENCE_TABLE}_evidence_type",
        f"{EVIDENCE_TABLE}_snapshot_id_fkey",
        f"{EVIDENCE_TABLE}_pkey",
    ):
        _record_object(
            f"{EVIDENCE_TABLE}.{constraint}", "constraint", evidence_existed
        )

    decision_existed = _table_exists(DECISION_TABLE)
    decision_seq_existed = _relation_exists(f"{DECISION_TABLE}_id_seq")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DECISION_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            audit_id UUID NOT NULL,
            address VARCHAR(42) NOT NULL,
            condition_id VARCHAR(255) NOT NULL,
            outcome TEXT NOT NULL,
            asset_token_id TEXT,
            source_asset TEXT,
            evidence_id BIGINT REFERENCES {EVIDENCE_TABLE}(id),
            snapshot_id BIGINT REFERENCES {SNAPSHOT_TABLE}(id),
            status TEXT NOT NULL
                CHECK (status IN ({_sql_string_list(DECISION_STATUSES)})),
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    _record_object(DECISION_TABLE, "table", decision_existed)
    _record_object(f"{DECISION_TABLE}_id_seq", "sequence", decision_seq_existed)
    for constraint in (
        f"{DECISION_TABLE}_status_check",
        f"{DECISION_TABLE}_evidence_id_fkey",
        f"{DECISION_TABLE}_snapshot_id_fkey",
        f"{DECISION_TABLE}_pkey",
    ):
        _record_object(
            f"{DECISION_TABLE}.{constraint}", "constraint", decision_existed
        )


def _validate_identity_tables() -> None:
    _assert_column_contract(
        EVIDENCE_TABLE,
        {
            "id": ("BIGINT", True, _ANY_DEFAULT),
            "address": ("VARCHAR(42)", True, None),
            "condition_id": ("VARCHAR(255)", True, None),
            "asset_token_id": ("TEXT", False, None),
            "source_asset": ("TEXT", False, None),
            "outcome": ("TEXT", False, None),
            "evidence_type": ("VARCHAR(32)", True, None),
            "transaction_hash": ("VARCHAR(66)", False, None),
            "event_sha256": ("TEXT", False, None),
            "snapshot_id": ("BIGINT", True, None),
            "observed_at": ("TIMESTAMPTZ", False, None),
            "payload": ("JSONB", True, "'{}'::jsonb"),
            "created_at": ("TIMESTAMPTZ", True, "now()"),
        },
    )
    _assert_primary_key(EVIDENCE_TABLE, ("id",))
    _assert_constraint_fragments(
        EVIDENCE_TABLE,
        "c",
        (
            "asset_token_id is not null",
            "evidence_type",
        ),
    )
    _assert_constraint_fragments(
        EVIDENCE_TABLE,
        "f",
        (f"foreign key (snapshot_id) references {SNAPSHOT_TABLE}(id)",),
    )
    _assert_exact_token_identity(EVIDENCE_TABLE, "asset_token_id")
    _assert_exact_token_identity(EVIDENCE_TABLE, "source_asset")

    _assert_column_contract(
        DECISION_TABLE,
        {
            "id": ("BIGINT", True, _ANY_DEFAULT),
            "audit_id": ("UUID", True, None),
            "address": ("VARCHAR(42)", True, None),
            "condition_id": ("VARCHAR(255)", True, None),
            "outcome": ("TEXT", True, None),
            "asset_token_id": ("TEXT", False, None),
            "source_asset": ("TEXT", False, None),
            "evidence_id": ("BIGINT", False, None),
            "snapshot_id": ("BIGINT", False, None),
            "status": ("TEXT", True, None),
            "reason": ("TEXT", True, None),
            "created_at": ("TIMESTAMPTZ", True, "now()"),
        },
    )
    _assert_primary_key(DECISION_TABLE, ("id",))
    _assert_constraint_fragments(DECISION_TABLE, "c", ("status = any",))
    _assert_constraint_fragments(
        DECISION_TABLE,
        "f",
        (
            f"foreign key (evidence_id) references {EVIDENCE_TABLE}(id)",
            f"foreign key (snapshot_id) references {SNAPSHOT_TABLE}(id)",
        ),
    )
    _assert_exact_token_identity(DECISION_TABLE, "asset_token_id")
    _assert_exact_token_identity(DECISION_TABLE, "source_asset")


# --------------------------------------------------------------------------
# Lifecycle provenance columns
# --------------------------------------------------------------------------


def _add_provenance_columns() -> None:
    for table in POSITION_TABLES:
        if not _table_exists(table):
            raise RuntimeError(
                f"{table} is missing; the canonical position tables must exist "
                "before lifecycle provenance can be added"
            )
        definitions = dict(PROVENANCE_COLUMN_DEFINITIONS)
        definitions.update(EXTRA_POSITION_COLUMNS[table])
        for column, sql_type in definitions.items():
            existed = _column_exists(table, column)
            # Nullable, no default: never rewrite a large position table.
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}"
            )
            _record_object(f"{table}.{column}", "column", existed)

        for name, definition in (
            (
                f"ck_{table}_provenance_kind",
                "provenance_kind IS NULL OR provenance_kind IN "
                f"({_sql_string_list(PROVENANCE_KINDS)})",
            ),
            (
                f"ck_{table}_lifecycle_state",
                "lifecycle_state IS NULL OR lifecycle_state IN "
                f"({_sql_string_list(LIFECYCLE_STATES)})",
            ),
        ):
            existed = _constraint_exists(table, name)
            if not existed:
                op.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({definition})"
                )
            _record_object(f"{table}.{name}", "constraint", existed)

        fk_name = f"fk_{table}_provenance_snapshot"
        fk_existed = _constraint_exists(table, fk_name)
        if not fk_existed:
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY (provenance_snapshot_id) "
                f"REFERENCES {SNAPSHOT_TABLE}(id)"
            )
        _record_object(f"{table}.{fk_name}", "constraint", fk_existed)


def _validate_provenance_columns() -> None:
    for table in POSITION_TABLES:
        contracts: dict[str, tuple[str, bool, object]] = {
            column: (sql_type, False, None)
            for column, sql_type in PROVENANCE_COLUMN_DEFINITIONS.items()
        }
        contracts.update(
            {
                column: (sql_type, False, None)
                for column, sql_type in EXTRA_POSITION_COLUMNS[table].items()
            }
        )
        _assert_column_contract(table, contracts)
        _assert_constraint_fragments(
            table, "c", ("provenance_kind", "lifecycle_state")
        )
        _assert_constraint_fragments(
            table,
            "f",
            (
                f"foreign key (provenance_snapshot_id) references "
                f"{SNAPSHOT_TABLE}(id)",
            ),
        )
        # The published metric grain must not change.
        _assert_primary_key(table, ("address", "condition_id", "outcome"))
        _assert_exact_token_identity(table, "asset_token_id")


# --------------------------------------------------------------------------
# Executable trigger semantics
# --------------------------------------------------------------------------


def _null_predicate(alias: str, columns: tuple[str, ...]) -> str:
    return "\n            AND ".join(f"{alias}.{column} IS NULL" for column in columns)


def _not_null_predicate(alias: str, columns: tuple[str, ...]) -> str:
    return "\n            AND ".join(
        f"{alias}.{column} IS NOT NULL" for column in columns
    )


def _transition_tuples() -> str:
    return ", ".join(
        f"('{source}', '{target}')" for source, target in LIFECYCLE_TRANSITIONS
    )


def _create_functions_and_triggers() -> None:
    snapshot_fn_existed = _function_exists(SNAPSHOT_CHECK_FUNCTION)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SNAPSHOT_CHECK_FUNCTION}(p_snapshot_id BIGINT)
        RETURNS VOID
        LANGUAGE plpgsql
        SET search_path TO public, pg_temp
        AS $fn$
        DECLARE
            v_complete BOOLEAN;
        BEGIN
            SELECT complete INTO v_complete
            FROM {SNAPSHOT_TABLE}
            WHERE id = p_snapshot_id;
            IF v_complete IS NULL THEN
                RAISE EXCEPTION
                    'referenced source snapshot % does not exist', p_snapshot_id
                    USING ERRCODE = '23514';
            END IF;
            IF NOT v_complete THEN
                RAISE EXCEPTION
                    'referenced source snapshot % is incomplete; lifecycle '
                    'provenance requires a complete snapshot', p_snapshot_id
                    USING ERRCODE = '23514';
            END IF;
        END;
        $fn$
        """
    )
    _record_object(f"{SNAPSHOT_CHECK_FUNCTION}()", "function", snapshot_fn_existed)

    guard_fn_existed = _function_exists(GUARD_FUNCTION)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {GUARD_FUNCTION}()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path TO public, pg_temp
        AS $fn$
        DECLARE
            v_new_all_null BOOLEAN;
            v_new_complete BOOLEAN;
            v_old_all_null BOOLEAN;
            v_old_complete BOOLEAN;
        BEGIN
            v_new_all_null := {_null_predicate("NEW", PROVENANCE_COLUMNS)};
            v_new_complete := {_not_null_predicate("NEW", REQUIRED_PROVENANCE_COLUMNS)};

            IF TG_OP = 'INSERT' THEN
                IF v_new_all_null THEN
                    RETURN NEW;
                END IF;
                IF NOT v_new_complete THEN
                    RAISE EXCEPTION
                        'partial lifecycle provenance on %.% is rejected; '
                        'initialize all of {", ".join(REQUIRED_PROVENANCE_COLUMNS)} '
                        'in one atomic statement',
                        TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = '23514';
                END IF;
                PERFORM {SNAPSHOT_CHECK_FUNCTION}(NEW.provenance_snapshot_id);
                RETURN NEW;
            END IF;

            v_old_all_null := {_null_predicate("OLD", PROVENANCE_COLUMNS)};
            v_old_complete := {_not_null_predicate("OLD", REQUIRED_PROVENANCE_COLUMNS)};

            IF v_old_all_null THEN
                -- Legacy row: unrelated updates stay allowed.
                IF v_new_all_null THEN
                    RETURN NEW;
                END IF;
                -- Exactly one atomic all-null -> complete initialization.
                IF NOT v_new_complete THEN
                    RAISE EXCEPTION
                        'partial lifecycle provenance initialization on %.% is '
                        'rejected; initialize all of '
                        '{", ".join(REQUIRED_PROVENANCE_COLUMNS)} in one atomic '
                        'statement',
                        TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = '23514';
                END IF;
                PERFORM {SNAPSHOT_CHECK_FUNCTION}(NEW.provenance_snapshot_id);
                RETURN NEW;
            END IF;

            IF NOT v_old_complete THEN
                RAISE EXCEPTION
                    'lifecycle provenance on %.% is in an ambiguous partial '
                    'state; refusing to update',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;

            IF NOT v_new_complete THEN
                RAISE EXCEPTION
                    'initialized lifecycle provenance on %.% cannot be cleared',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;
            IF (NEW.provenance_event_hash IS NULL
                    AND OLD.provenance_event_hash IS NOT NULL)
               OR (NEW.provenance_reason IS NULL
                    AND OLD.provenance_reason IS NOT NULL) THEN
                RAISE EXCEPTION
                    'initialized lifecycle provenance on %.% cannot be cleared',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.provenance_kind IS DISTINCT FROM OLD.provenance_kind
               OR NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at THEN
                RAISE EXCEPTION
                    'initialized lifecycle provenance on %.% cannot be '
                    'rewritten (provenance_kind and first_seen_at are '
                    'immutable)',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.last_seen_at < OLD.last_seen_at THEN
                RAISE EXCEPTION
                    'lifecycle provenance last_seen_at on %.% cannot move '
                    'backwards',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.lifecycle_state = OLD.lifecycle_state THEN
                IF NEW.provenance_snapshot_id
                       IS DISTINCT FROM OLD.provenance_snapshot_id
                   OR NEW.provenance_event_hash
                       IS DISTINCT FROM OLD.provenance_event_hash
                   OR NEW.provenance_reason
                       IS DISTINCT FROM OLD.provenance_reason THEN
                    RAISE EXCEPTION
                        'initialized lifecycle provenance on %.% cannot be '
                        'rewritten without a lifecycle transition',
                        TG_TABLE_SCHEMA, TG_TABLE_NAME
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.lifecycle_state
                   IN ({_sql_string_list(TERMINAL_LIFECYCLE_STATES)}) THEN
                RAISE EXCEPTION
                    'terminal lifecycle state % on %.% cannot transition to %',
                    OLD.lifecycle_state, TG_TABLE_SCHEMA, TG_TABLE_NAME,
                    NEW.lifecycle_state
                    USING ERRCODE = '23514';
            END IF;
            IF (OLD.lifecycle_state, NEW.lifecycle_state)
                   NOT IN ({_transition_tuples()}) THEN
                RAISE EXCEPTION
                    'unsupported lifecycle transition % -> % on %.%',
                    OLD.lifecycle_state, NEW.lifecycle_state,
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;
            PERFORM {SNAPSHOT_CHECK_FUNCTION}(NEW.provenance_snapshot_id);
            RETURN NEW;
        END;
        $fn$
        """
    )
    _record_object(f"{GUARD_FUNCTION}()", "function", guard_fn_existed)

    append_fn_existed = _function_exists(APPEND_ONLY_FUNCTION)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {APPEND_ONLY_FUNCTION}()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path TO public, pg_temp
        AS $fn$
        BEGIN
            RAISE EXCEPTION
                '% on %.% is rejected; the table is append-only',
                TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = '23514';
        END;
        $fn$
        """
    )
    _record_object(f"{APPEND_ONLY_FUNCTION}()", "function", append_fn_existed)

    for table, trigger in PROVENANCE_TRIGGERS.items():
        existed = _trigger_exists(table, trigger)
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {GUARD_FUNCTION}()
            """
        )
        _record_object(f"{table}.{trigger}", "trigger", existed)

    for table, trigger in APPEND_ONLY_TRIGGERS.items():
        existed = _trigger_exists(table, trigger)
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {APPEND_ONLY_FUNCTION}()
            """
        )
        _record_object(f"{table}.{trigger}", "trigger", existed)


def _validate_functions_and_triggers() -> None:
    for function in (SNAPSHOT_CHECK_FUNCTION, GUARD_FUNCTION, APPEND_ONLY_FUNCTION):
        if not _function_exists(function):
            raise RuntimeError(f"{function} was not created")
    for table, trigger in {**PROVENANCE_TRIGGERS, **APPEND_ONLY_TRIGGERS}.items():
        if not _trigger_exists(table, trigger):
            raise RuntimeError(f"{trigger} on {table} was not created")


# --------------------------------------------------------------------------
# Indexes (concurrent, evidence/decision only)
# --------------------------------------------------------------------------

_EXPECTED_INDEX_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {
    "idx_wallet_position_identity_evidence_lookup_v2": (
        EVIDENCE_TABLE,
        f"create index idx_wallet_position_identity_evidence_lookup_v2 on "
        f"public.{EVIDENCE_TABLE} using btree "
        "(address, condition_id, asset_token_id)",
    ),
    "idx_wallet_position_identity_evidence_snapshot_v2": (
        EVIDENCE_TABLE,
        f"create index idx_wallet_position_identity_evidence_snapshot_v2 on "
        f"public.{EVIDENCE_TABLE} using btree (snapshot_id)",
    ),
    "uq_wallet_position_identity_evidence_v2": (
        EVIDENCE_TABLE,
        f"create unique index uq_wallet_position_identity_evidence_v2 on "
        f"public.{EVIDENCE_TABLE} using btree "
        "(address, condition_id, coalesce(outcome, ''::text), "
        "coalesce(asset_token_id, ''::text), coalesce(source_asset, ''::text), "
        "evidence_type, coalesce(event_sha256, ''::text))",
    ),
    "uq_wallet_position_identity_decisions_v2": (
        DECISION_TABLE,
        f"create unique index uq_wallet_position_identity_decisions_v2 on "
        f"public.{DECISION_TABLE} using btree "
        "(audit_id, address, condition_id, outcome, "
        "coalesce(asset_token_id, ''::text), coalesce(source_asset, ''::text))",
    ),
}

_INDEX_DDL: Final[dict[str, str]] = {
    "idx_wallet_position_identity_evidence_lookup_v2": (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_wallet_position_identity_evidence_lookup_v2 "
        f"ON {EVIDENCE_TABLE} (address, condition_id, asset_token_id)"
    ),
    "idx_wallet_position_identity_evidence_snapshot_v2": (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_wallet_position_identity_evidence_snapshot_v2 "
        f"ON {EVIDENCE_TABLE} (snapshot_id)"
    ),
    "uq_wallet_position_identity_evidence_v2": (
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
        "uq_wallet_position_identity_evidence_v2 "
        f"ON {EVIDENCE_TABLE} (address, condition_id, COALESCE(outcome, ''), "
        "COALESCE(asset_token_id, ''), COALESCE(source_asset, ''), "
        "evidence_type, COALESCE(event_sha256, ''))"
    ),
    "uq_wallet_position_identity_decisions_v2": (
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
        "uq_wallet_position_identity_decisions_v2 "
        f"ON {DECISION_TABLE} (audit_id, address, condition_id, outcome, "
        "COALESCE(asset_token_id, ''), COALESCE(source_asset, ''))"
    ),
}


def _create_identity_indexes() -> None:
    existed = {name: _relation_exists(name) for name in CREATED_INDEXES}
    # Migrations run inside a transaction; CREATE INDEX CONCURRENTLY may not.
    with op.get_context().autocommit_block():
        for name in CREATED_INDEXES:
            op.execute(_INDEX_DDL[name])
    for name in CREATED_INDEXES:
        _record_object(name, "index", existed[name])
    for table in (EVIDENCE_TABLE, DECISION_TABLE):
        _assert_index_definitions(
            table,
            {
                name: definition
                for name, (owner, definition) in _EXPECTED_INDEX_DEFINITIONS.items()
                if owner == table
            },
        )


# --------------------------------------------------------------------------
# upgrade / downgrade
# --------------------------------------------------------------------------


def upgrade() -> None:
    _require_ownership_table()
    # Fail closed on any incompatible pre-existing evidence/decision table
    # before creating or recording anything.
    _validate_preexisting_evidence_tables()
    _ensure_source_snapshot_table()
    _validate_preexisting_evidence_tables()
    _create_identity_tables()
    _validate_identity_tables()
    _add_provenance_columns()
    _validate_provenance_columns()
    _create_functions_and_triggers()
    _validate_functions_and_triggers()
    _record_object(METADATA_OBJECT, "metadata", False)
    _create_identity_indexes()


def _downgrade_plan() -> list[tuple[str, str]]:
    """Resolve every drop decision before mutating anything.

    ``_is_droppable`` raises when ownership cannot be proven, so building the
    whole plan first means an ambiguous object aborts the downgrade before a
    single object is removed.
    """
    plan: list[tuple[str, str]] = []

    # Triggers first so append-only/provenance guards cannot block cleanup.
    for table, trigger in {**PROVENANCE_TRIGGERS, **APPEND_ONLY_TRIGGERS}.items():
        exists = _table_exists(table) and _trigger_exists(table, trigger)
        if _is_droppable(f"{table}.{trigger}", "trigger", exists):
            plan.append(("trigger", f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))

    for name in CREATED_INDEXES:
        if _is_droppable(name, "index", _relation_exists(name)):
            plan.append(("index", f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))

    for table in POSITION_TABLES:
        if not _table_exists(table):
            continue
        for constraint in (
            f"fk_{table}_provenance_snapshot",
            f"ck_{table}_lifecycle_state",
            f"ck_{table}_provenance_kind",
        ):
            if _is_droppable(
                f"{table}.{constraint}",
                "constraint",
                _constraint_exists(table, constraint),
            ):
                plan.append(
                    (
                        "constraint",
                        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}",
                    )
                )
        for column in list(PROVENANCE_COLUMN_DEFINITIONS) + list(
            EXTRA_POSITION_COLUMNS[table]
        ):
            if _is_droppable(
                f"{table}.{column}", "column", _column_exists(table, column)
            ):
                plan.append(
                    ("column", f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
                )

    for table in (DECISION_TABLE, EVIDENCE_TABLE):
        if _is_droppable(table, "table", _table_exists(table)):
            plan.append(("table", f"DROP TABLE IF EXISTS {table}"))

    # Only drop the ancestor snapshot table when this revision created it.
    if _is_droppable(SNAPSHOT_TABLE, "table", _table_exists(SNAPSHOT_TABLE)):
        plan.append(("table", f"DROP TABLE IF EXISTS {SNAPSHOT_TABLE}"))

    for function, signature in (
        (GUARD_FUNCTION, ""),
        (APPEND_ONLY_FUNCTION, ""),
        (SNAPSHOT_CHECK_FUNCTION, "BIGINT"),
    ):
        if _is_droppable(f"{function}()", "function", _function_exists(function)):
            plan.append(
                ("function", f"DROP FUNCTION IF EXISTS {function}({signature})")
            )
    return plan


def downgrade() -> None:
    if not _table_exists(OWNERSHIP_TABLE):
        raise RuntimeError(
            "cannot safely downgrade the identity/lifecycle provenance schema "
            "without ownership records"
        )

    plan = _downgrade_plan()
    for kind, statement in plan:
        if kind == "index":
            with op.get_context().autocommit_block():
                op.execute(statement)
        else:
            op.execute(statement)

    # Finally remove this revision's ownership rows; the ownership table itself
    # belongs to b1c2d3e4f5a6 and is preserved.
    _bind().execute(
        sa.text(
            f"""
            DELETE FROM {OWNERSHIP_TABLE}
            WHERE created_by_revision = :revision AND NOT preexisting
            """
        ),
        {"revision": OWNERSHIP_REVISION},
    )
