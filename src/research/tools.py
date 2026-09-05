"""Validated analytical tool registry for the AI Research Hub.

The model may select only these registered tools with JSON arguments. Tool
descriptions state defaults and definitions so the model does not guess them.
Every execution persists an immutable result-set snapshot plus members.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from src.research.analytics import ResearchAnalytics
from src.research.contracts import (
    FindWalletsArgs,
    MarketParticipantsArgs,
    MarketsTradedArgs,
    OutcomeConsensusArgs,
    PanelType,
    PositionOverlapArgs,
    ResultKind,
    ResultSetSummary,
    SameOutcomeHistoryArgs,
)
from src.research.repository import ResearchRepository


class ToolNotFoundError(LookupError):
    def __init__(self, tool_name: str):
        super().__init__(f"unknown research tool: {tool_name}")
        self.code = "UNKNOWN_TOOL"


class ToolValidationError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "INVALID_TOOL_ARGS"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    result_kind: ResultKind
    panel_type: PanelType
    handler_name: str


TOOL_DEFINITIONS = (
    ToolDefinition(
        "find_wallets",
        "Find wallets by scoped evidence-backed performance. "
        "Scope hierarchy is category -> subcategory -> league, e.g. "
        "category='Sports', subcategory='Cricket', league='T20'. Never swap "
        "subcategory and league. "
        "Defaults: win-rate comparison is strict 'gt' ('more than 70%' means win_rate > 70), "
        "evidence floor min_resolved_count=20, category scope uses category_stats_v2 "
        "with window_size=0, sort_by=win_rate, limit=100.",
        FindWalletsArgs, ResultKind.WALLET_SET, PanelType.WALLET_TABLE, "find_wallets",
    ),
    ToolDefinition(
        "markets_traded",
        "Aggregate markets traded by a saved wallet set. "
        "Requires wallet_result_set_id from an earlier wallet result in the same chat. "
        "state is open, closed, or all (default all).",
        MarketsTradedArgs, ResultKind.MARKET_SET, PanelType.MARKET_TABLE, "markets_traded",
    ),
    ToolDefinition(
        "open_position_overlap",
        "Find open markets shared by a saved wallet set. "
        "Requires wallet_result_set_id from an earlier wallet result in the same chat. "
        "'All of them' means coverage uses distinct_wallet_count equal to the input "
        "result-set row count; coverage_pct is exact.",
        PositionOverlapArgs, ResultKind.POSITION_OVERLAP, PanelType.OVERLAP_TABLE,
        "open_position_overlap",
    ),
    ToolDefinition(
        "market_participants",
        "Find and rank qualified wallets holding an open position in one market. "
        "Requires condition_id. Applies scoped category statistics (window_size=0, "
        "default evidence floor 20), not global win rate.",
        MarketParticipantsArgs, ResultKind.MARKET_PARTICIPANTS, PanelType.WALLET_TABLE,
        "market_participants",
    ),
    ToolDefinition(
        "outcome_consensus",
        "Measure outcome choice and capital by market for a saved wallet set. "
        "Grouped by the market's stored outcome label; multi-outcome markets keep "
        "their actual labels and are never forced into YES/NO.",
        OutcomeConsensusArgs, ResultKind.OUTCOME_CONSENSUS, PanelType.CONSENSUS,
        "outcome_consensus",
    ),
    ToolDefinition(
        "same_outcome_history",
        "Measure repeated historical market/outcome overlap for a saved wallet set. "
        "Uses only metrics-eligible closed positions unless include_open is true. "
        "Descriptive only: never label wallets coordinated, copied, or collusive.",
        SameOutcomeHistoryArgs, ResultKind.SAME_OUTCOME_HISTORY, PanelType.OVERLAP_TABLE,
        "same_outcome_history",
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}


@dataclass(frozen=True)
class ToolExecution:
    result_set: ResultSetSummary
    panel_type: PanelType


def get_tool(name: str) -> ToolDefinition:
    try:
        return _TOOLS_BY_NAME[name]
    except KeyError:
        raise ToolNotFoundError(name) from None


def tool_schemas() -> list[dict[str, Any]]:
    """JSON-schema tool specs handed to the language model."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.args_model.model_json_schema(),
            "result_kind": tool.result_kind.value,
        }
        for tool in TOOL_DEFINITIONS
    ]


def _summarize(kind: ResultKind, args: BaseModel, rows: list[dict]) -> dict[str, Any]:
    summary: dict[str, Any] = {"tool_kind": kind.value, "row_count": len(rows)}
    dumped = args.model_dump(mode="json")
    if kind == ResultKind.WALLET_SET:
        summary.update({
            "min_win_rate": dumped.get("min_win_rate"),
            "comparison": dumped.get("comparison"),
            "evidence_floor": dumped.get("min_resolved_count"),
            "scope": {k: dumped.get(k) for k in ("category", "subcategory", "league", "window_size")},
        })
    elif kind == ResultKind.MARKET_PARTICIPANTS:
        summary.update({
            "condition_id": dumped.get("condition_id"),
            "evidence_floor": dumped.get("min_resolved_count"),
        })
    elif kind in (ResultKind.POSITION_OVERLAP, ResultKind.MARKET_SET,
                  ResultKind.OUTCOME_CONSENSUS, ResultKind.SAME_OUTCOME_HISTORY):
        summary.update({k: v for k, v in dumped.items() if k != "limit"})
    return summary


def _label(kind: ResultKind, rows: list[dict]) -> str:
    nouns = {
        ResultKind.WALLET_SET: "wallets",
        ResultKind.MARKET_SET: "markets",
        ResultKind.POSITION_OVERLAP: "shared markets",
        ResultKind.MARKET_PARTICIPANTS: "market participants",
        ResultKind.OUTCOME_CONSENSUS: "outcome rows",
        ResultKind.SAME_OUTCOME_HISTORY: "historical overlaps",
    }
    return f"{len(rows)} {nouns[kind]}"


def _members(kind: ResultKind, rows: list[dict]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for row in rows:
        if kind in (ResultKind.WALLET_SET, ResultKind.MARKET_PARTICIPANTS):
            members.append({
                "entity_type": "wallet", "entity_key": str(row["address"]), "payload": row,
            })
        elif kind in (ResultKind.MARKET_SET, ResultKind.POSITION_OVERLAP):
            members.append({
                "entity_type": "market", "entity_key": str(row["condition_id"]), "payload": row,
            })
        else:
            # Consensus/history rows stay keyed by condition_id (two outcomes
            # share one key) so any market-bearing set can filter later calls.
            members.append({
                "entity_type": "market_outcome",
                "entity_key": str(row["condition_id"]),
                "payload": row,
            })
    return members


async def execute_tool(
    repo: ResearchRepository,
    analytics: ResearchAnalytics,
    *,
    owner_id: str,
    chat_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    run_id: UUID | None = None,
) -> ToolExecution:
    """Validate arguments, run the analytical handler, persist the snapshot."""
    tool = get_tool(tool_name)
    try:
        args = tool.args_model.model_validate(arguments or {})
    except Exception as exc:
        raise ToolValidationError(f"invalid arguments for {tool_name}: {exc}") from exc

    handler = getattr(analytics, tool.handler_name, None)
    if handler is None:
        raise ToolNotFoundError(tool.handler_name)
    if tool.handler_name in ("find_wallets", "market_participants"):
        rows = await handler(args)
    else:
        rows = await handler(owner_id, args)

    summary = _summarize(tool.result_kind, args, rows)
    if tool.name == "find_wallets" and not rows and getattr(args, "category", None):
        # Empty discovery: hand the model the nearest real scopes so it can
        # suggest an existing taxonomy value instead of guessing.
        summary["available_scopes"] = await analytics.scope_hint(args)
    result_set = await repo.save_result_set(
        owner_id, chat_id, tool.result_kind.value, _label(tool.result_kind, rows),
        {"tool": tool.name, "arguments": args.model_dump(mode="json")},
        _members(tool.result_kind, rows),
        run_id=run_id, summary=summary,
    )
    if result_set is None:
        raise ToolValidationError("chat not found")
    return ToolExecution(result_set=result_set, panel_type=tool.panel_type)
