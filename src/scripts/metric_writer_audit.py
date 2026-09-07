"""Read-only metric ownership audit and baseline snapshot tool.

The static audit intentionally has no database dependency.  The optional
baseline command opens an explicit PostgreSQL connection in a READ ONLY
transaction and writes JSON outside production tables.

Usage::

    python -m src.scripts.metric_writer_audit audit
    python -m src.scripts.metric_writer_audit baseline \
        --database-url "$DATABASE_URL" --output artifacts/metric-baseline.json

No database URL is embedded here.  ``--database-url`` is required for a
baseline (``DATABASE_URL`` may be used as an explicit environment setting).
"""

from __future__ import annotations

import argparse
import ast
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"

# These are the fields whose values are accounting outputs, rather than raw
# source evidence or capital/official snapshots.  The coordinator is the only
# live writer allowed to update them.
INTERNAL_METRIC_FIELDS = frozenset({
    "total_pnl", "total_volume", "roi_pct", "win_rate",
    "resolved_count", "winning_count", "avg_buy_price", "avg_position_size",
    "avg_hold_time_hours", "biggest_win", "biggest_loss", "active_days",
    "trades_2x", "trades_1_5x", "data_completeness_pct",
    "parlay_pnl", "parlay_volume", "parlay_win_rate",
    "parlay_resolved_count", "parlay_winning_count",
    "pnl_all", "pnl_100", "pnl_200", "pnl_300", "pnl_500", "pnl_750",
    "pnl_1000", "pnl_1500", "pnl_2000", "pnl_2500", "pnl_3500", "pnl_5000",
    "wins_below_15c", "losses_below_15c", "buys_below_15c", "avg_sell_below_15c",
    "wins_15_30c", "losses_15_30c", "buys_15_30c", "avg_sell_15_30c",
    "wins_30_45c", "losses_30_45c", "buys_30_45c", "avg_sell_30_45c",
    "wins_45_60c", "losses_45_60c", "buys_45_60c", "avg_sell_45_60c",
    "wins_60_75c", "losses_60_75c", "buys_60_75c", "avg_sell_60_75c",
    "wins_above_75c", "losses_above_75c", "buys_above_75c", "avg_sell_above_75c",
    "win_rate_100", "win_rate_300", "win_rate_800", "win_rate_1500",
    "win_rate_2500", "tl_win_rate", "tl_roi_pct", "tl_resolved_count",
    "tl_winning_count", "sb_win_rate", "sb_roi_pct", "sb_resolved_count",
    "sb_winning_count",
})

CATEGORY_METRIC_FIELDS = frozenset({
    "pnl", "total_pnl", "volume", "total_volume", "win_rate", "roi_pct",
    "resolved_count", "winning_count", "last_active", "computed_at",
})

OFFICIAL_FIELDS = frozenset({"pm_pnl", "pm_volume", "pm_rank", "pm_synced_at"})
CAPITAL_FIELDS = frozenset({
    "balance", "deposits", "withdrawals", "peak_capital", "net_capital",
    "capital_synced_at",
})
SOURCE_FRESHNESS_FIELDS = frozenset({"open_synced_at", "closed_synced_at"})
KEY_FIELDS = frozenset({"address"})
CATEGORY_KEY_FIELDS = frozenset({
    "address", "category", "subcategory", "league", "window_size",
})
OPERATIONAL_FIELDS = frozenset({"onchain_verify_pending", "onchain_verified_at"})

# A legacy writer is safer when it cannot be accidentally invoked during the
# ownership transition.  Disabled files remain visible to the audit; they are
# valid only when they contain a verifiable retired entry point.
DISABLED_WRITERS = frozenset({
    "src/workers/leaderboard_stats.py",
    "src/scripts/audit_and_recalc_metrics.py",
    "src/scripts/fix_redundant_subcategories.py",
    "src/scripts/global_market_backfill.py",
    "src/scripts/fix_wallet_markets.py",
    "src/scripts/recompute_all_category_stats.py",
    "src/scripts/resolve_wallet_markets.py",
    "src/scripts/backfill_missing_wins.py",
    "src/scripts/backfill_position_value.py",
    "src/scripts/backfill_zero_pnl_balance.py",
    "src/scripts/backfill_window_stats.py",
    "src/scripts/repair_and_sync_wallet.py",
    "src/workers/hibernated_wallets_backfill.py",
})

# These files retain compatibility helpers or historical SQL for imports, so
# a module-level marker alone is insufficient.  Every executable write helper
# must fail before its first query.
RETIRED_ENTRY_GUARDS: dict[str, tuple[str, ...]] = {
    "src/workers/leaderboard_stats.py": (
        "leaderboard_stats.process_wallet is retired",
        "leaderboard_stats runner is retired",
    ),
}

CANONICAL_WRITERS = frozenset({
    "src/workers/compute_core_metrics.py",
    "src/workers/compute_category_stats.py",
    "src/workers/compute_historical_windows.py",
    "src/workers/positions_metrics_compute.py",
})

# Each policy has an explicit table-specific allow-list.  Key columns are
# included deliberately: an upsert must be able to establish the row identity,
# but no writer may silently publish another owner's field.
OFFICIAL_WRITERS = frozenset({
    "src/workers/poly_leaderboard_sync.py",
    "src/workers/pnl_balance_refetch.py",
    "src/workers/wallet_trade_history.py",
})
CAPITAL_WRITERS = frozenset({
    "src/workers/capital_metrics_backfill.py",
    "src/workers/stats_refresher.py",
})
SOURCE_WRITERS = frozenset({
    "src/workers/positions_open_backfill.py",
    "src/workers/positions_closed_backfill.py",
    "src/workers/positions_winrate_backfill.py",
    "src/scripts/backfill_deep_closed_history.py",
})
AUXILIARY_WRITERS = frozenset({"src/workers/onchain_verifier.py"})

POLICY_ALLOWED_WALLET_FIELDS: dict[str, frozenset[str]] = {
    "canonical": KEY_FIELDS | INTERNAL_METRIC_FIELDS | frozenset({
        "computed_at", "categories_computed_at",
    }),
    "official": KEY_FIELDS | OFFICIAL_FIELDS,
    "capital": KEY_FIELDS | CAPITAL_FIELDS,
    "source": KEY_FIELDS | SOURCE_FRESHNESS_FIELDS | frozenset({
        "position_value", "parlay_open_count", "parlay_open_value",
        "redeemable_count", "redeemable_winning_count",
    }),
    "auxiliary": KEY_FIELDS | OPERATIONAL_FIELDS,
    "disabled": frozenset(),
}
POLICY_ALLOWED_CATEGORY_FIELDS: dict[str, frozenset[str]] = {
    "canonical": CATEGORY_KEY_FIELDS | CATEGORY_METRIC_FIELDS,
    "official": frozenset(),
    "capital": frozenset(),
    "source": frozenset(),
    "auxiliary": frozenset(),
    "disabled": frozenset(),
}

_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([a-zA-Z_][\w]*)\s*\((.*?)\)", re.IGNORECASE | re.DOTALL
)
_UPDATE_RE = re.compile(
    r"UPDATE\s+([a-zA-Z_][\w]*)\s+SET\s+(.*?)(?=\bWHERE\b|\bFROM\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_ASSIGN_RE = re.compile(r"\b([a-zA-Z_][\w]*)\s*=", re.IGNORECASE)


def _fields(text: str) -> set[str]:
    return {part.strip().strip('"').lower() for part in text.split(",") if part.strip()}


def extract_sql_writes(source: str) -> list[dict[str, Any]]:
    """Extract likely INSERT/UPDATE field writes from Python SQL strings.

    This is deliberately conservative: it is a static guardrail, not a SQL
    parser.  A reviewer can inspect the reported statement and add a focused
    policy when a query uses dynamic SQL.
    """
    writes: list[dict[str, Any]] = []
    for match in _INSERT_RE.finditer(source):
        table = match.group(1).lower()
        fields = _fields(match.group(2))
        tail = source[match.start(): source.find("\"\"\"", match.end()) if source.find("\"\"\"", match.end()) >= 0 else len(source)]
        conflict = re.search(r"ON\s+CONFLICT.*?DO\s+UPDATE\s+SET\s+(.*?)(?=\bWHERE\b|\"\"\"|'''|$)", tail, re.IGNORECASE | re.DOTALL)
        if conflict:
            fields.update(_ASSIGN_RE.findall(conflict.group(1)))
        writes.append({"table": table, "fields": fields, "kind": "insert", "offset": match.start()})
    for match in _UPDATE_RE.finditer(source):
        fields = set(_ASSIGN_RE.findall(match.group(2)))
        writes.append({"table": match.group(1).lower(), "fields": fields, "kind": "update", "offset": match.start()})
    return writes


def _policy_for(path: Path, root: Path = ROOT) -> str:
    relative = path.relative_to(root).as_posix()
    if relative in DISABLED_WRITERS:
        return "disabled"
    if relative in CANONICAL_WRITERS:
        return "canonical"
    if relative in OFFICIAL_WRITERS:
        return "official"
    if relative in CAPITAL_WRITERS:
        return "capital"
    if relative in SOURCE_WRITERS:
        return "source"
    if relative in AUXILIARY_WRITERS:
        return "auxiliary"
    return "unknown"


def _retired_entry_point(source: str, relative: str) -> bool:
    """Recognize a source-level fail-closed retirement contract.

    A marker in ``main`` is not enough when a module exposes callable writer
    helpers.  Known compatibility modules therefore require guards at every
    retained executable write entry point.
    """
    marker = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS" in source or (
        "is retired" in source.lower() and "raise RuntimeError" in source
    )
    required_guards = RETIRED_ENTRY_GUARDS.get(relative, ())
    return marker and all(guard in source for guard in required_guards)


def audit_writers(root: Path = ROOT) -> dict[str, Any]:
    """Return a deterministic ownership report and violations."""
    violations: list[dict[str, Any]] = []
    writers: list[dict[str, Any]] = []
    for path in sorted((root / "src").rglob("*.py")):
        if path.name == "metric_writer_audit.py":
            continue
        source = path.read_text(encoding="utf-8")
        policy = _policy_for(path, root)
        statements = extract_sql_writes(source)
        relative = path.relative_to(root).as_posix()
        entry = {"path": relative, "policy": policy, "writes": []}
        if policy == "disabled" and not _retired_entry_point(source, relative):
            violations.append({
                "path": relative,
                "table": "*",
                "fields": ["active_writer_without_retirement_marker"],
                "kind": "retirement",
            })
        for statement in statements:
            table = statement["table"]
            fields = sorted(statement["fields"])
            if table not in {"wallet_metrics_v2", "category_stats_v2"}:
                continue
            entry["writes"].append({"table": table, "fields": fields, "kind": statement["kind"]})
            allowed = (
                POLICY_ALLOWED_WALLET_FIELDS.get(policy, frozenset())
                if table == "wallet_metrics_v2"
                else POLICY_ALLOWED_CATEGORY_FIELDS.get(policy, frozenset())
            )
            forbidden = sorted(set(fields) - allowed)
            # A disabled module is intentionally retained for historical
            # imports, but its entry point must fail closed before any query;
            # the retirement check above is the guard that makes this safe.
            if policy == "disabled" and _retired_entry_point(source, relative):
                forbidden = []
            if policy == "unknown":
                forbidden = fields
            if forbidden:
                violations.append({"path": relative, "table": table, "fields": forbidden, "kind": statement["kind"]})
        if entry["writes"] or policy == "disabled":
            writers.append(entry)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ownership": {
            "source": "raw positions/evidence/eligibility and source freshness",
            "canonical": "internal totals/ROI/counts/buckets/parlays/categories/windows",
            "capital": "capital/deposit/withdrawal fields and capital freshness",
            "official": "pm_* fields and pm freshness only",
        },
        "disabled_writers": sorted(DISABLED_WRITERS),
        "writers": writers,
        "violations": violations,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


async def _table_exists(conn: Any, table: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table))


async def _columns(conn: Any, table: str) -> set[str]:
    rows = await conn.fetch(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = current_schema() AND table_name = $1""", table,
    )
    return {str(row["column_name"]) for row in rows}


async def _checksum(conn: Any, table: str, columns: list[str], where: str = "TRUE") -> str | None:
    if not columns or not await _table_exists(conn, table):
        return None
    # Identifiers come only from information_schema/constant lists above.
    selected = ", ".join(f'"{column}"' for column in columns)
    query = f"""SELECT md5(COALESCE(string_agg(md5(to_jsonb(row_data)::text), '' ORDER BY row_data::text), ''))
                  FROM (SELECT {selected} FROM "{table}" WHERE {where}) row_data"""
    return await conn.fetchval(query)


async def _count(conn: Any, query: str, *args: Any) -> int:
    """Run a required anomaly/count query without hiding schema failures."""
    value = await conn.fetchval(query, *args)
    if value is None:
        raise RuntimeError(f"baseline count returned NULL: {query.strip()}")
    return int(value)


async def baseline(database_url: str, output: Path) -> dict[str, Any]:
    """Take an aggregate/checksum baseline in a read-only transaction."""
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("BEGIN TRANSACTION READ ONLY")
        metrics_columns = await _columns(conn, "wallet_metrics_v2")
        category_columns = await _columns(conn, "category_stats_v2")
        closed_columns = await _columns(conn, "wallet_closed_positions_v2")
        positions_columns = await _columns(conn, "wallet_positions_v2")
        metrics_internal = [c for c in sorted(metrics_columns & INTERNAL_METRIC_FIELDS)]
        metrics_official = [c for c in sorted(metrics_columns & OFFICIAL_FIELDS)]
        category_identity = [c for c in ("address", "category", "subcategory", "league", "window_size") if c in category_columns]
        source_timestamp_columns = sorted(
            closed_columns & {"closed_at", "resolved_at", "opened_at", "created_at", "updated_at"}
        )
        category_timestamp_columns = sorted(
            category_columns & {"computed_at", "last_active", "created_at", "updated_at"}
        )
        result: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "tables": {},
            "anomalies": {},
        }
        if metrics_columns:
            result["tables"]["wallet_metrics_v2"] = {
                "row_count": await _count(conn, "SELECT count(*) FROM wallet_metrics_v2"),
                "internal_checksum": await _checksum(conn, "wallet_metrics_v2", ["address", *metrics_internal]),
                "official_checksum": await _checksum(conn, "wallet_metrics_v2", ["address", *metrics_official]),
                "null_freshness": {
                    c: await _count(conn, f"SELECT count(*) FROM wallet_metrics_v2 WHERE \"{c}\" IS NULL")
                    for c in sorted(metrics_columns & {"computed_at", "open_synced_at", "closed_synced_at", "capital_synced_at", "pm_synced_at"})
                },
            }
        if category_columns:
            result["tables"]["category_stats_v2"] = {
                "row_count": await _count(conn, "SELECT count(*) FROM category_stats_v2"),
                "checksum": await _checksum(conn, "category_stats_v2", [*category_identity, *sorted(category_columns & CATEGORY_METRIC_FIELDS)]),
                "window_sizes": [dict(row) for row in await conn.fetch("SELECT window_size, count(*) AS row_count FROM category_stats_v2 GROUP BY window_size ORDER BY window_size")],
                "null_timestamps": {
                    c: await _count(conn, f"SELECT count(*) FROM category_stats_v2 WHERE \"{c}\" IS NULL")
                    for c in category_timestamp_columns
                },
            }
        if closed_columns:
            identity = [c for c in ("address", "condition_id", "outcome") if c in closed_columns]
            result["tables"]["wallet_closed_positions_v2"] = {
                "row_count": await _count(conn, "SELECT count(*) FROM wallet_closed_positions_v2"),
                "checksum": await _checksum(conn, "wallet_closed_positions_v2", sorted(closed_columns)),
                "null_timestamps": {
                    c: await _count(conn, f"SELECT count(*) FROM wallet_closed_positions_v2 WHERE \"{c}\" IS NULL")
                    for c in source_timestamp_columns
                },
            }
            if len(identity) == 3:
                result["anomalies"]["duplicate_closed_identities"] = await _count(
                    conn, "SELECT count(*) FROM (SELECT address, condition_id, outcome FROM wallet_closed_positions_v2 GROUP BY 1,2,3 HAVING count(*) > 1) d",
                )
                eligible = "COALESCE(metrics_eligible, TRUE)" if "metrics_eligible" in closed_columns else "TRUE"
                flagged = "data_quality_flag IS NOT NULL" if "data_quality_flag" in closed_columns else "FALSE"
                result["anomalies"]["flagged_but_eligible_rows"] = await _count(
                    conn, f"SELECT count(*) FROM wallet_closed_positions_v2 WHERE {flagged} AND {eligible}",
                )
                result["anomalies"]["wallets_above_5000_closed_rows"] = await _count(
                    conn, "SELECT count(*) FROM (SELECT address FROM wallet_closed_positions_v2 GROUP BY address HAVING count(*) > 5000) d",
                )
        if category_columns and len(category_identity) == 5:
            result["anomalies"]["duplicate_category_identities"] = await _count(
                conn, "SELECT count(*) FROM (SELECT address, category, subcategory, league, window_size FROM category_stats_v2 GROUP BY 1,2,3,4,5 HAVING count(*) > 1) d",
            )
        if metrics_columns and closed_columns:
            if {"resolved_count", "winning_count"} <= metrics_columns:
                eligible = "COALESCE(c.metrics_eligible, TRUE)" if "metrics_eligible" in closed_columns else "TRUE"
                result["anomalies"]["stale_count_wallets"] = await _count(conn, f"""
                    SELECT count(*) FROM wallet_metrics_v2 m
                    JOIN (SELECT address, count(*) FILTER (WHERE {eligible}) AS resolved,
                                 count(*) FILTER (WHERE {eligible} AND realized_pnl > 0) AS wins
                          FROM wallet_closed_positions_v2 c GROUP BY address) s ON s.address = m.address
                    WHERE m.resolved_count IS DISTINCT FROM s.resolved OR m.winning_count IS DISTINCT FROM s.wins
                """)
        if metrics_columns and "closed_synced_at" in metrics_columns and "open_synced_at" in metrics_columns:
            result["anomalies"]["incomplete_histories"] = await _count(
                conn, "SELECT count(*) FROM wallet_metrics_v2 WHERE closed_synced_at IS NULL OR open_synced_at IS NULL",
            )
        await conn.execute("ROLLBACK")
    finally:
        await conn.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit metric writers or take a read-only baseline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit", help="run static ownership audit")
    baseline_parser = sub.add_parser("baseline", help="take a read-only database baseline")
    baseline_parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="explicit PostgreSQL URL (or DATABASE_URL)")
    baseline_parser.add_argument("--output", type=Path, required=True, help="JSON artifact path outside production tables")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        report = audit_writers()
        print(json.dumps(report, indent=2))
        return 1 if report["violations"] else 0
    if not args.database_url:
        raise SystemExit("baseline requires --database-url or DATABASE_URL; no credentials are embedded")
    report = asyncio.run(baseline(args.database_url, args.output))
    print(json.dumps({"output": str(args.output), "read_only": report["read_only"], "tables": list(report["tables"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
