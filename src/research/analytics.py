"""Deterministic analytical queries for the AI Research Hub.

All SQL is parameterized and set-based: wallet collections are resolved
through ``research_result_members`` joined to ``research_chats`` for
ownership, never by issuing one query per wallet. Analytical meaning follows
the product contract:

- "More than 70% win rate" means ``win_rate > 70``, not ``>= 70``.
- Category scope uses ``category_stats_v2`` with ``window_size = 0`` unless a
  historical window is explicitly requested.
- A wallet is in an open position only when
  ``wallet_positions_v2.current_value > 0`` and the row is not resolved.
- Historical analysis uses only ``wallet_closed_positions_v2.metrics_eligible``.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from src.research.contracts import (
    FindWalletsArgs,
    MarketParticipantsArgs,
    MarketsTradedArgs,
    OutcomeConsensusArgs,
    PositionOverlapArgs,
    SameOutcomeHistoryArgs,
)

SORT_COLUMNS = {
    "win_rate": "win_rate",
    "pnl": "pnl",
    "volume": "volume",
    "resolved_count": "resolved_count",
}

GLOBAL_SORT_COLUMNS = {
    "win_rate": "m.win_rate",
    "pnl": "m.total_pnl",
    "volume": "m.total_volume",
    "resolved_count": "m.resolved_count",
}


class ResultSetAccessError(PermissionError):
    """Raised when a referenced result set is missing or owned by another user."""


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _clean_rows(rows: Any) -> list[dict[str, Any]]:
    return [{k: _clean(v) for k, v in dict(r).items()} for r in rows]


# Scope values are stored as canonical uppercase taxonomy labels
# (SPORTS, Cricket, IPL), but users write them in any case. Equality stays
# exact in meaning; the UPPER() arm only absorbs case differences. The plain
# `col = $n` arm is kept first so existing indexes remain usable.
def _scope_equals(column: str, param: str) -> str:
    return (
        f"({param}::text IS NULL OR {column} = {param} "
        f"OR UPPER({column}) = UPPER({param}))"
    )


# Exact (case-insensitive) taxonomy match for a scope level that the user
# explicitly requested. Unlike _scope_equals, a NULL param never matches.
def _scope_exact(column: str, param: str) -> str:
    return f"({column} = {param} OR UPPER({column}) = UPPER({param}))"


def _stats_slice_filter(
    subcategory: str | None,
    league: str | None,
    sub_param: str = "$3",
    league_param: str = "$4",
) -> str:
    """Row filter matching the pipeline's rollup grain.

    compute_category_stats writes (category,'','') category totals plus one
    row per (subcategory, league) slice; there are no subcategory totals.
    So a category-only scope must read the total row (never SUM slices with
    it), while a subcategory scope SUMs every league slice within it.
    """
    parts = []
    if subcategory is not None:
        parts.append(_scope_exact("c.subcategory", sub_param))
    elif league is None:
        # Category total row. The IS NULL anchors keep unused params typed.
        parts.append(
            f"c.subcategory = '' AND c.league = '' "
            f"AND {sub_param}::text IS NULL AND {league_param}::text IS NULL"
        )
    if league is not None:
        parts.append(_scope_exact("c.league", league_param))
        if subcategory is None:
            parts.append(f"{sub_param}::text IS NULL")
    elif subcategory is not None:
        parts.append(f"{league_param}::text IS NULL")
    return "AND " + " AND ".join(parts)


# Ownership guard shared by every set-based method. Runs before any
# analytical SQL and raises before touching position tables.
_INPUT_WALLETS_CTE = """
input AS (
    SELECT DISTINCT m.entity_key AS address
    FROM research_result_members m
    JOIN research_result_sets s ON s.result_set_id = m.result_set_id
    JOIN research_chats c ON s.chat_id = c.chat_id
    WHERE m.result_set_id = $1 AND c.owner_id = $2::uuid AND m.entity_type = 'wallet'
),
input_count AS (SELECT COUNT(*) AS n FROM input)
"""

_INPUT_MARKETS_CTE = """
input_markets AS (
    SELECT DISTINCT m.entity_key AS condition_id
    FROM research_result_members m
    JOIN research_result_sets s ON s.result_set_id = m.result_set_id
    JOIN research_chats c ON s.chat_id = c.chat_id
    WHERE m.result_set_id = $%d AND c.owner_id = $2::uuid
      AND m.entity_type IN ('market', 'market_outcome', 'position_overlap', 'consensus')
)
"""


def _overlap_markets_sql(
    result_set_id: UUID, owner_id: str, min_wallet_count: int, limit: int
) -> tuple[str, tuple]:
    sql = f"""WITH {_INPUT_WALLETS_CTE}
                SELECT p.condition_id, MIN(mk.title) AS title,
                       COUNT(DISTINCT p.address)::int AS wallet_count,
                       SUM(p.current_value) AS current_value,
                       SUM(p.size) AS shares
                FROM wallet_positions_v2 p
                JOIN input i ON i.address = p.address
                LEFT JOIN markets_v2 mk ON mk.condition_id = p.condition_id
                WHERE COALESCE(p.current_value, 0) > 0
                  AND COALESCE(p.is_resolved, FALSE) = FALSE
                GROUP BY p.condition_id
                HAVING COUNT(DISTINCT p.address) >= $3
                ORDER BY wallet_count DESC, p.condition_id ASC
                LIMIT $4"""
    return sql, (result_set_id, owner_id, min_wallet_count, limit)


def _history_sql(
    result_set_id: UUID,
    owner_id: str,
    min_wallet_count: int,
    category: str | None,
    subcategory: str | None,
    league: str | None,
    include_open: bool,
    limit: int,
) -> tuple[str, tuple]:
    branches = [
        """SELECT p.address, p.condition_id, p.outcome, 'closed' AS source
           FROM wallet_closed_positions_v2 p JOIN input i ON i.address = p.address
           WHERE COALESCE(p.metrics_eligible, TRUE)"""
    ]
    if include_open:
        branches.append(
            """SELECT p.address, p.condition_id, p.outcome, 'open' AS source
               FROM wallet_positions_v2 p JOIN input i ON i.address = p.address
               WHERE COALESCE(p.current_value, 0) > 0
                 AND COALESCE(p.is_resolved, FALSE) = FALSE"""
        )
    union_sql = " UNION ALL ".join(branches)
    sql = f"""WITH {_INPUT_WALLETS_CTE},
                pos AS ({union_sql})
                SELECT p.condition_id, MIN(mk.title) AS title, p.outcome,
                       COUNT(DISTINCT p.address)::int AS wallet_count,
                       COALESCE(array_agg(DISTINCT p.source)
                                FILTER (WHERE p.source IS NOT NULL), '{{}}') AS sources
                FROM pos p
                LEFT JOIN markets_v2 mk ON mk.condition_id = p.condition_id
                WHERE {_scope_equals('mk.category', '$4')}
                  AND {_scope_equals('mk.subcategory', '$5')}
                  AND {_scope_equals('mk.league', '$6')}
                GROUP BY p.condition_id, p.outcome
                HAVING COUNT(DISTINCT p.address) >= $3
                ORDER BY wallet_count DESC, p.condition_id ASC, p.outcome ASC
                LIMIT $7"""
    return sql, (result_set_id, owner_id, min_wallet_count,
                 category, subcategory, league, limit)


class ResearchAnalytics:
    def __init__(self, pool: Any):
        self.pool = pool

    async def explain_query(
        self,
        owner_id: str,
        result_set_id: UUID,
        query: Literal["open_overlap", "same_outcome_history"],
        min_wallet_count: int = 2,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the parsed ``EXPLAIN (FORMAT JSON)`` plan for a set-based query."""
        async with self.pool.acquire() as conn:
            await self._require_result_set(conn, owner_id, result_set_id)
            if query == "open_overlap":
                sql, params = _overlap_markets_sql(
                    result_set_id, owner_id, min_wallet_count, limit)
            elif query == "same_outcome_history":
                sql, params = _history_sql(
                    result_set_id, owner_id, min_wallet_count, None, None, None, False, limit)
            else:
                raise ValueError(f"unknown explainable query: {query}")
            raw = await conn.fetchval("EXPLAIN (FORMAT JSON) " + sql, *params)
        return json.loads(raw) if isinstance(raw, str) else raw

    async def _require_result_set(
        self, conn: Any, owner_id: str, result_set_id: UUID
    ) -> None:
        owns = await conn.fetchval(
            """SELECT 1 FROM research_result_sets s
               JOIN research_chats c ON s.chat_id = c.chat_id
               WHERE s.result_set_id = $1 AND c.owner_id = $2::uuid""",
            result_set_id, owner_id,
        )
        if not owns:
            raise ResultSetAccessError("result set not found")

    async def _input_wallet_count(
        self, conn: Any, owner_id: str, result_set_id: UUID
    ) -> int:
        await self._require_result_set(conn, owner_id, result_set_id)
        return await conn.fetchval(
            """SELECT COUNT(*) FROM (
                   SELECT DISTINCT m.entity_key FROM research_result_members m
                   WHERE m.result_set_id = $1 AND m.entity_type = 'wallet'
               ) t""",
            result_set_id,
        ) or 0

    # -- wallet discovery --------------------------------------------

    async def find_wallets(self, args: FindWalletsArgs) -> list[dict]:
        comparison_sql = ">" if args.comparison == "gt" else ">="
        scope = {
            "category": args.category, "subcategory": args.subcategory,
            "league": args.league, "window_size": args.window_size,
        }
        async with self.pool.acquire() as conn:
            if args.category is not None:
                # One row per wallet at the requested rollup grain (category
                # total row, or SUM of league slices for a subcategory scope).
                # SUMming total rows together with slices would double-count.
                sort_col = SORT_COLUMNS[args.sort_by]
                slice_filter = _stats_slice_filter(
                    args.subcategory, args.league,
                    sub_param="$3", league_param="$4")
                rows = await conn.fetch(
                    f"""SELECT address, username, last_trade_at,
                               win_rate, pnl, volume,
                               resolved_count, winning_count,
                               balance, position_value
                        FROM (
                            SELECT w.address AS address,
                                   MAX(w.username) AS username,
                                   MAX(w.last_trade_at) AS last_trade_at,
                                   CASE WHEN SUM(c.resolved_count) > 0
                                        THEN 100.0 * SUM(c.winning_count)
                                             / SUM(c.resolved_count)
                                        ELSE 0 END AS win_rate,
                                   SUM(c.pnl) AS pnl,
                                   SUM(c.volume) AS volume,
                                   SUM(c.resolved_count) AS resolved_count,
                                   SUM(c.winning_count) AS winning_count,
                                   MAX(m.balance) AS balance,
                                   MAX(m.position_value) AS position_value
                            FROM category_stats_v2 c
                            JOIN wallets_v2 w ON w.address = c.address
                            LEFT JOIN wallet_metrics_v2 m ON m.address = w.address
                            WHERE c.window_size = $1
                              AND {_scope_equals('c.category', '$2')}
                              {slice_filter}
                            GROUP BY w.address
                        ) agg
                        WHERE win_rate {comparison_sql} $5
                          AND resolved_count >= $6
                        ORDER BY {sort_col} DESC, resolved_count DESC, address ASC
                        LIMIT $7""",
                    args.window_size, args.category, args.subcategory, args.league,
                    args.min_win_rate, args.min_resolved_count, args.limit,
                )
            else:
                sort_col = GLOBAL_SORT_COLUMNS[args.sort_by]
                rows = await conn.fetch(
                    f"""SELECT w.address, w.username, w.last_trade_at,
                               m.win_rate, m.total_pnl AS pnl, m.total_volume AS volume,
                               m.resolved_count, m.winning_count,
                               m.balance, m.position_value
                        FROM wallet_metrics_v2 m
                        JOIN wallets_v2 w ON w.address = m.address
                        WHERE m.win_rate {comparison_sql} $1
                          AND m.resolved_count >= $2
                        ORDER BY {sort_col} DESC, m.resolved_count DESC, w.address ASC
                        LIMIT $3""",
                    args.min_win_rate, args.min_resolved_count, args.limit,
                )
        cleaned = _clean_rows(rows)
        for row in cleaned:
            row["scope"] = dict(scope)
        return cleaned

    async def scope_hint(self, args: FindWalletsArgs) -> list[dict]:
        """Nearest real scopes when discovery returns nothing.

        Lists stored (subcategory, league) pairs under the requested
        category — narrowed to the requested subcategory when one is given —
        with wallet counts, so the model suggests an existing scope instead
        of speculating about market size.
        """
        if args.category is None:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.subcategory AS subcategory, c.league AS league,
                          COUNT(*)::int AS wallets
                   FROM category_stats_v2 c
                   WHERE c.window_size = $1 AND UPPER(c.category) = UPPER($2)
                     AND ($3::text IS NULL OR UPPER(c.subcategory) = UPPER($3))
                   GROUP BY c.subcategory, c.league
                   ORDER BY wallets DESC LIMIT 10""",
                args.window_size, args.category, args.subcategory,
            )
        return _clean_rows(rows)

    # -- market participants -----------------------------------------

    async def market_participants(self, args: MarketParticipantsArgs) -> list[dict]:
        scope = args.scope
        scope_echo = {
            "category": scope.category, "subcategory": scope.subcategory,
            "league": scope.league, "window_size": scope.window_size,
        }
        async with self.pool.acquire() as conn:
            if scope.category is not None:
                slice_filter = _stats_slice_filter(
                    scope.subcategory, scope.league,
                    sub_param="$4", league_param="$5")
                rows = await conn.fetch(
                    f"""WITH scoped AS (
                            SELECT c.address AS address,
                                   CASE WHEN SUM(c.resolved_count) > 0
                                        THEN 100.0 * SUM(c.winning_count)
                                             / SUM(c.resolved_count)
                                        ELSE 0 END AS win_rate,
                                   SUM(c.resolved_count) AS resolved_count,
                                   SUM(c.winning_count) AS winning_count,
                                   SUM(c.pnl) AS pnl,
                                   SUM(c.volume) AS volume
                            FROM category_stats_v2 c
                            WHERE c.window_size = $2
                              AND {_scope_equals('c.category', '$3')}
                              {slice_filter}
                            GROUP BY c.address
                        )
                        SELECT p.address, w.username, p.outcome, p.size, p.avg_price,
                               p.current_value, s.win_rate, s.resolved_count, s.winning_count,
                               s.pnl, s.volume, m.balance, m.position_value, w.last_trade_at
                        FROM wallet_positions_v2 p
                        JOIN wallets_v2 w ON w.address = p.address
                        JOIN scoped s ON s.address = p.address
                        LEFT JOIN wallet_metrics_v2 m ON m.address = p.address
                        WHERE p.condition_id = $1
                          AND COALESCE(p.current_value, 0) > 0
                          AND COALESCE(p.is_resolved, FALSE) = FALSE
                          AND ($6::numeric IS NULL OR s.win_rate > $6)
                          AND s.resolved_count >= $7
                        ORDER BY s.win_rate DESC, s.resolved_count DESC,
                                 p.address ASC, p.outcome ASC
                        LIMIT $8""",
                    args.condition_id, scope.window_size, scope.category,
                    scope.subcategory, scope.league, args.min_win_rate,
                    args.min_resolved_count, args.limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT p.address, w.username, p.outcome, p.size, p.avg_price,
                               p.current_value, m.win_rate, m.resolved_count,
                               m.winning_count, m.total_pnl AS pnl, m.total_volume AS volume,
                               m.balance, m.position_value, w.last_trade_at
                        FROM wallet_positions_v2 p
                        JOIN wallets_v2 w ON w.address = p.address
                        JOIN wallet_metrics_v2 m ON m.address = p.address
                        WHERE p.condition_id = $1
                          AND COALESCE(p.current_value, 0) > 0
                          AND COALESCE(p.is_resolved, FALSE) = FALSE
                          AND ($2::numeric IS NULL OR m.win_rate > $2)
                          AND m.resolved_count >= $3
                        ORDER BY m.win_rate DESC, m.resolved_count DESC,
                                 p.address ASC, p.outcome ASC
                        LIMIT $4""",
                    args.condition_id, args.min_win_rate,
                    args.min_resolved_count, args.limit,
                )
        cleaned = _clean_rows(rows)
        for row in cleaned:
            row["scope"] = dict(scope_echo)
        return cleaned

    # -- markets traded ----------------------------------------------

    async def markets_traded(self, owner_id: str, args: MarketsTradedArgs) -> list[dict]:
        branches: list[str] = []
        if args.state in ("open", "all"):
            branches.append(
                """SELECT p.address, p.condition_id, p.outcome,
                          p.current_value, p.size, 'open' AS source
                   FROM wallet_positions_v2 p JOIN input i ON i.address = p.address
                   WHERE COALESCE(p.current_value, 0) > 0
                     AND COALESCE(p.is_resolved, FALSE) = FALSE"""
            )
        if args.state in ("closed", "all"):
            branches.append(
                """SELECT p.address, p.condition_id, p.outcome,
                          NULL::numeric AS current_value, NULL::numeric AS size,
                          'closed' AS source
                   FROM wallet_closed_positions_v2 p JOIN input i ON i.address = p.address
                   WHERE COALESCE(p.metrics_eligible, TRUE)"""
            )
        union_sql = " UNION ALL ".join(branches)
        async with self.pool.acquire() as conn:
            await self._require_result_set(conn, owner_id, args.wallet_result_set_id)
            rows = await conn.fetch(
                f"""WITH {_INPUT_WALLETS_CTE},
                    pos AS ({union_sql})
                    SELECT mk.condition_id, mk.title, mk.category, mk.subcategory,
                           mk.league, mk.status,
                           COUNT(DISTINCT p.address)::int AS wallet_count,
                           COUNT(DISTINCT CASE WHEN p.source = 'open' THEN p.address END)::int AS open_wallets,
                           COUNT(DISTINCT CASE WHEN p.source = 'closed' THEN p.address END)::int AS closed_wallets,
                           ROUND(100.0 * COUNT(DISTINCT p.address)
                                 / NULLIF((SELECT n FROM input_count), 0), 2) AS coverage_pct,
                            COALESCE(array_agg(DISTINCT p.outcome)
                                     FILTER (WHERE p.outcome IS NOT NULL), '{{}}') AS outcomes,
                            COALESCE(SUM(p.current_value), 0) AS total_value
                    FROM pos p
                    JOIN markets_v2 mk ON mk.condition_id = p.condition_id
                    WHERE {_scope_equals('mk.category', '$3')}
                      AND {_scope_equals('mk.subcategory', '$4')}
                      AND {_scope_equals('mk.league', '$5')}
                    GROUP BY mk.condition_id, mk.title, mk.category, mk.subcategory,
                             mk.league, mk.status
                    ORDER BY wallet_count DESC, coverage_pct DESC, mk.condition_id ASC
                    LIMIT $6""",
                args.wallet_result_set_id, owner_id,
                args.category, args.subcategory, args.league, args.limit,
            )
        return _clean_rows(rows)

    # -- open position overlap ----------------------------------------

    async def open_position_overlap(
        self, owner_id: str, args: PositionOverlapArgs
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            input_count = await self._input_wallet_count(
                conn, owner_id, args.wallet_result_set_id
            )
            if input_count == 0:
                return []
            overlap_sql, overlap_params = _overlap_markets_sql(
                args.wallet_result_set_id, owner_id,
                args.min_wallet_count, args.limit)
            markets = await conn.fetch(overlap_sql, *overlap_params)
            if not markets:
                return []
            breakdown = await conn.fetch(
                f"""WITH {_INPUT_WALLETS_CTE}
                    SELECT p.condition_id, p.outcome,
                           COUNT(DISTINCT p.address)::int AS wallets
                    FROM wallet_positions_v2 p
                    JOIN input i ON i.address = p.address
                    WHERE COALESCE(p.current_value, 0) > 0
                      AND COALESCE(p.is_resolved, FALSE) = FALSE
                      AND p.condition_id = ANY($3)
                    GROUP BY p.condition_id, p.outcome""",
                args.wallet_result_set_id, owner_id,
                [m["condition_id"] for m in markets],
            )
        by_market: dict[str, dict[str, int]] = {}
        for row in breakdown:
            by_market.setdefault(row["condition_id"], {})[row["outcome"]] = row["wallets"]
        results = []
        for m in markets:
            wallet_count = m["wallet_count"]
            results.append({
                "condition_id": m["condition_id"],
                "title": m["title"],
                "wallet_count": wallet_count,
                "coverage_pct": round(100.0 * wallet_count / input_count, 2),
                "outcomes": by_market.get(m["condition_id"], {}),
                "current_value": _clean(m["current_value"]),
                "shares": _clean(m["shares"]),
                "input_wallet_count": input_count,
            })
        return results

    # -- outcome consensus --------------------------------------------

    async def outcome_consensus(
        self, owner_id: str, args: OutcomeConsensusArgs
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            input_count = await self._input_wallet_count(
                conn, owner_id, args.wallet_result_set_id
            )
            if input_count == 0:
                return []
            market_ids: list[str] | None = None
            if args.market_result_set_id is not None:
                await self._require_result_set(conn, owner_id, args.market_result_set_id)
                market_rows = await conn.fetch(
                    """SELECT DISTINCT entity_key FROM research_result_members
                       WHERE result_set_id = $1""",
                    args.market_result_set_id,
                )
                market_ids = [r["entity_key"] for r in market_rows]
                if not market_ids:
                    return []
            if args.condition_id is not None:
                market_filter = "AND p.condition_id = $4"
                extra: tuple = (args.condition_id,)
            elif market_ids is not None:
                market_filter = "AND p.condition_id = ANY($4)"
                extra = (market_ids,)
            else:
                market_filter = ""
                extra = ()
            per_market = await conn.fetch(
                f"""WITH {_INPUT_WALLETS_CTE}
                    SELECT p.condition_id, MIN(mk.title) AS title,
                           COUNT(DISTINCT p.address)::int AS wallet_count
                    FROM wallet_positions_v2 p
                    JOIN input i ON i.address = p.address
                    LEFT JOIN markets_v2 mk ON mk.condition_id = p.condition_id
                    WHERE COALESCE(p.current_value, 0) > 0
                      AND COALESCE(p.is_resolved, FALSE) = FALSE
                      {market_filter}
                    GROUP BY p.condition_id
                    ORDER BY wallet_count DESC, p.condition_id ASC
                    LIMIT $3""",
                args.wallet_result_set_id, owner_id, args.limit, *extra,
            )
            if not per_market:
                return []
            per_outcome = await conn.fetch(
                f"""WITH {_INPUT_WALLETS_CTE}
                    SELECT p.condition_id, p.outcome,
                           COUNT(DISTINCT p.address)::int AS wallet_count,
                           SUM(p.current_value) AS current_value,
                           SUM(p.size) AS shares
                    FROM wallet_positions_v2 p
                    JOIN input i ON i.address = p.address
                    WHERE COALESCE(p.current_value, 0) > 0
                      AND COALESCE(p.is_resolved, FALSE) = FALSE
                      AND p.condition_id = ANY($3)
                    GROUP BY p.condition_id, p.outcome
                    ORDER BY p.condition_id ASC, wallet_count DESC""",
                args.wallet_result_set_id, owner_id,
                [m["condition_id"] for m in per_market],
            )
        totals = {m["condition_id"]: m["wallet_count"] for m in per_market}
        titles = {m["condition_id"]: m["title"] for m in per_market}
        results = []
        for row in per_outcome:
            wallet_count = row["wallet_count"]
            results.append({
                "condition_id": row["condition_id"],
                "title": titles.get(row["condition_id"]),
                "outcome": row["outcome"],
                "wallet_count": wallet_count,
                "wallet_pct": round(100.0 * wallet_count / input_count, 2),
                "market_wallet_count": totals.get(row["condition_id"], 0),
                "current_value": _clean(row["current_value"]),
                "shares": _clean(row["shares"]),
                "input_wallet_count": input_count,
            })
        return results

    # -- historical same-outcome overlap -------------------------------

    async def same_outcome_history(
        self, owner_id: str, args: SameOutcomeHistoryArgs
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            input_count = await self._input_wallet_count(
                conn, owner_id, args.wallet_result_set_id
            )
            if input_count == 0:
                return []
            history_sql, history_params = _history_sql(
                args.wallet_result_set_id, owner_id, args.min_wallet_count,
                args.category, args.subcategory, args.league,
                args.include_open, args.limit)
            rows = await conn.fetch(history_sql, *history_params)
        results = []
        for r in _clean_rows(rows):
            r["coverage_pct"] = round(100.0 * r["wallet_count"] / input_count, 2)
            r["input_wallet_count"] = input_count
            results.append(r)
        return results

    # -- chat-scoped positions -----------------------------------------

    async def list_positions(
        self,
        owner_id: str,
        chat_id: UUID | str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return owner- and chat-scoped open positions for wallets discovered in the chat."""
        sql = """
        WITH chat_wallets AS (
            SELECT DISTINCT m.entity_key AS address
            FROM research_result_members m
            JOIN research_result_sets rs ON rs.result_set_id = m.result_set_id
            JOIN research_chats c ON c.chat_id = rs.chat_id
            WHERE c.owner_id = $1::uuid
              AND c.chat_id = $2::uuid
              AND m.entity_type = 'wallet'
        )
        SELECT p.address, p.condition_id, mk.title AS market_title,
               p.outcome, p.size, p.avg_price, p.current_value,
               p.unrealized_pnl, p.entry_at, p.computed_at
        FROM wallet_positions_v2 p
        JOIN chat_wallets cw ON cw.address = p.address
        LEFT JOIN markets_v2 mk ON mk.condition_id = p.condition_id
        WHERE COALESCE(p.current_value, 0) > 0
          AND COALESCE(p.is_resolved, FALSE) = FALSE
        ORDER BY p.current_value DESC NULLS LAST, p.condition_id, p.outcome, p.address
        OFFSET $3 LIMIT $4
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, str(owner_id), str(chat_id), offset, limit)
        return _clean_rows(rows)

