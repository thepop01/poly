"""Typed contracts for the AI Research Hub.

The language model may select only registered tools with validated arguments;
it never receives database credentials or executes generated SQL.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ResultKind(StrEnum):
    WALLET_SET = "wallet_set"
    MARKET_SET = "market_set"
    POSITION_OVERLAP = "position_overlap"
    MARKET_PARTICIPANTS = "market_participants"
    OUTCOME_CONSENSUS = "outcome_consensus"
    SAME_OUTCOME_HISTORY = "same_outcome_history"


class PanelType(StrEnum):
    WALLET_TABLE = "wallet_table"
    MARKET_TABLE = "market_table"
    OVERLAP_TABLE = "overlap_table"
    CONSENSUS = "consensus"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PanelState(StrEnum):
    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    CLOSED = "closed"


class StreamEventType(StrEnum):
    RUN_STARTED = "run.started"
    TOOL_STARTED = "tool.started"
    RESULT_CREATED = "result.created"
    PANEL_UPSERTED = "panel.upserted"
    ASSISTANT_DELTA = "assistant.delta"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class Scope(BaseModel):
    category: str | None = Field(
        default=None,
        description="Top-level category, e.g. 'Sports'. Case-sensitive exact match.",
    )
    subcategory: str | None = Field(
        default=None,
        description="Second level, e.g. 'Cricket' in Sports -> Cricket -> T20. "
        "This is NOT the league; never put league names here.",
    )
    league: str | None = Field(
        default=None,
        description="Third level, e.g. 'T20' in Sports -> Cricket -> T20. "
        "This is NOT the subcategory; never put subcategory names here.",
    )
    window_size: int = Field(
        default=0, ge=0, le=5000,
        description="Historical position window. Always 0 unless the user explicitly "
        "requests a historical window.",
    )


class FindWalletsArgs(Scope):
    min_win_rate: float = Field(
        default=70, ge=0, le=100,
        description="Strict lower bound when comparison='gt': 'more than 70%' means "
        "win_rate > 70.",
    )
    comparison: Literal["gt", "gte"] = Field(
        default="gt",
        description="Use 'gt' for 'more than X%'. Only use 'gte' when the user says "
        "'at least' or '70% or more'. Never emit symbols like '>' or '>='. ",
    )
    min_resolved_count: int = Field(
        default=20, ge=1, le=100_000,
        description="Evidence floor: minimum resolved positions. Default 20; use the "
        "user's number when they state one.",
    )
    sort_by: Literal["win_rate", "pnl", "volume", "resolved_count"] = "win_rate"
    limit: int = Field(default=100, ge=1, le=1000)


class PositionOverlapArgs(BaseModel):
    wallet_result_set_id: UUID
    min_wallet_count: int = Field(default=2, ge=2, le=1000)
    limit: int = Field(default=100, ge=1, le=500)


class MarketsTradedArgs(Scope):
    wallet_result_set_id: UUID
    state: Literal["open", "closed", "all"] = "all"
    limit: int = Field(default=100, ge=1, le=500)


class MarketParticipantsArgs(BaseModel):
    condition_id: str = Field(min_length=3, max_length=255)
    min_win_rate: float | None = Field(default=None, ge=0, le=100)
    min_resolved_count: int = Field(default=20, ge=1, le=100_000)
    scope: Scope = Field(default_factory=Scope)
    limit: int = Field(default=100, ge=1, le=500)


class OutcomeConsensusArgs(BaseModel):
    wallet_result_set_id: UUID
    market_result_set_id: UUID | None = None
    condition_id: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=100, ge=1, le=500)


class SameOutcomeHistoryArgs(Scope):
    wallet_result_set_id: UUID
    min_wallet_count: int = Field(default=2, ge=2, le=1000)
    include_open: bool = False
    limit: int = Field(default=100, ge=1, le=500)


class ResearchChat(BaseModel):
    chat_id: UUID
    title: str
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


class ResearchMessage(BaseModel):
    message_id: int
    chat_id: UUID
    run_id: UUID | None = None
    role: Literal["user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ResearchRun(BaseModel):
    run_id: UUID
    chat_id: UUID
    status: RunStatus
    prompt: str
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ResultSetSummary(BaseModel):
    result_set_id: UUID
    chat_id: UUID
    run_id: UUID | None = None
    kind: str
    label: str
    definition: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    row_count: int = 0
    snapshot_at: datetime
    created_at: datetime


class PanelLayout(BaseModel):
    col_span: Literal[4, 6, 8, 12] = 12
    min_height: int = Field(default=420, ge=100, le=2000)
    order: int = Field(default=0, ge=0)


class ResearchPanel(BaseModel):
    panel_id: UUID
    chat_id: UUID
    result_set_id: UUID | None = None
    panel_type: str
    panel_key: str
    title: str
    state: PanelState = PanelState.NORMAL
    layout: PanelLayout
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StreamEvent(BaseModel):
    type: str
    run_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class PageResultSetArgs(BaseModel):
    result_set_id: UUID
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=100, ge=1, le=200)
