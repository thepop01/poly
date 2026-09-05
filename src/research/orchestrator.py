"""Bounded orchestration loop and deterministic panel policy.

Flow per run: persist the user message, mark the run running, build compact
context, then alternate between provider actions and validated tool
executions. Tool results persist as immutable snapshots; panels are created
or updated by a deterministic key policy (same analysis updates, new analysis
creates). All failures surface as one terminal ``run.failed`` event with a
stable, client-safe error code.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic import BaseModel

from src.research.analytics import ResearchAnalytics, ResultSetAccessError
from src.research.context import (
    build_context,
    resolve_market_set_id,
    resolve_wallet_set_id,
)
from src.research.contracts import PanelType, ResultKind, StreamEvent
from src.research.llm import ProviderConfigError, ProviderError
from src.research.repository import ResearchRepository
from src.research.tools import (
    TOOL_DEFINITIONS,
    ToolNotFoundError,
    ToolValidationError,
    execute_tool,
    get_tool,
    tool_schemas,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


PANEL_FAMILY = {
    "find_wallets": "wallets",
    "market_participants": "wallets",
    "markets_traded": "markets",
    "open_position_overlap": "open-overlap",
    "outcome_consensus": "consensus",
    "same_outcome_history": "history-overlap",
}

PANEL_DEFAULTS: dict[str, dict[str, int]] = {
    PanelType.WALLET_TABLE.value: {"col_span": 12, "min_height": 420},
    PanelType.MARKET_TABLE.value: {"col_span": 12, "min_height": 420},
    PanelType.OVERLAP_TABLE.value: {"col_span": 8, "min_height": 380},
    PanelType.CONSENSUS.value: {"col_span": 4, "min_height": 380},
}


def panel_key(tool_name: str, args: BaseModel) -> str:
    stable = args.model_dump(mode="json", exclude={"limit"}, exclude_none=True)
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:12]
    family = PANEL_FAMILY[tool_name]
    return f"{family}:{digest}"


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentence_chunks(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    return parts or ([text] if text else [])


@dataclass
class ResearchOrchestrator:
    repo: ResearchRepository
    analytics: ResearchAnalytics
    provider: Any
    max_tool_calls: int = field(default_factory=lambda: _env_int("RESEARCH_MAX_TOOL_CALLS", 6))
    max_rows: int = field(default_factory=lambda: _env_int("RESEARCH_MAX_ROWS", 1000))
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RESEARCH_RUN_TIMEOUT_SECONDS", "90"))
    )

    def _event(self, run_id: UUID, type_: str, **data: Any) -> StreamEvent:
        return StreamEvent(type=type_, run_id=str(run_id), data=data)

    @staticmethod
    def _log_extra(owner_id: str, run_id: UUID, chat_id: UUID, **fields: Any) -> dict[str, Any]:
        # Never log prompts, addresses, API keys, or raw provider payloads.
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
        return {"run_id": str(run_id), "chat_id": str(chat_id),
                "owner_hash": owner_hash, **fields}

    async def _fail(
        self,
        owner_id: str,
        run_id: UUID,
        code: str,
        safe_message: str,
        out: list[StreamEvent],
        chat_id: UUID | None = None,
    ) -> None:
        await self.repo.set_run_status(owner_id, run_id, "failed", code, safe_message)
        out.append(self._event(run_id, "run.failed", error_code=code, error_message=safe_message))
        if chat_id is not None:
            logger.warning(
                "research run failed",
                extra=self._log_extra(owner_id, run_id, chat_id, error_code=code),
            )

    async def run_stream(
        self,
        *,
        owner_id: str,
        chat_id: UUID,
        prompt: str,
        request: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute one conversational run, yielding NDJSON-ready stream events."""
        events: list[StreamEvent] = []
        run = await self.repo.create_run(owner_id, chat_id, prompt)
        if run is None:
            # Chat missing or not owned; nothing to stream against.
            return
        run_id = run.run_id
        terminal_sent = False
        try:
            await self.repo.add_message(owner_id, chat_id, "user", prompt, run_id=run_id)
            await self.repo.set_run_status(owner_id, run_id, "running")
            events.append(self._event(run_id, "run.started", chat_id=str(chat_id)))
            async with asyncio.timeout(self.timeout_seconds):
                ctx = await build_context(self.repo, owner_id, chat_id)
                refs = list(ctx.result_refs)
                tools_used = 0
                short_circuits = 0
                executed_keys: dict[tuple[str, str], int] = {}
                while True:
                    if request is not None and await request.is_disconnected():
                        await self.repo.set_run_status(
                            owner_id, run_id, "cancelled", "CANCELLED", "Run cancelled."
                        )
                        events.append(self._event(
                            run_id, "run.failed",
                            error_code="CANCELLED", error_message="Run cancelled."))
                        logger.info(
                            "research run cancelled",
                            extra=self._log_extra(owner_id, run_id, chat_id),
                        )
                        terminal_sent = True
                        break
                    try:
                        action = await self.provider.next_action(ctx, tool_schemas())
                    except ProviderConfigError as exc:
                        logger.warning("research provider not configured")
                        await self._fail(owner_id, run_id, exc.code, str(exc),
                                         events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    except ProviderError as exc:
                        logger.warning(
                            "research provider error", extra={"run_id": str(run_id)})
                        await self._fail(owner_id, run_id, exc.code, "Analysis provider failed.",
                                         events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    if action.kind == "answer":
                        text = action.text or ""
                        message = await self.repo.add_message(
                            owner_id, chat_id, "assistant", text, run_id=run_id)
                        for chunk in _sentence_chunks(text):
                            events.append(self._event(run_id, "assistant.delta", text=chunk))
                        await self.repo.set_run_status(owner_id, run_id, "completed")
                        events.append(self._event(
                            run_id, "run.completed",
                            message_id=message.message_id if message else None))
                        logger.info(
                            "research run completed",
                            extra=self._log_extra(
                                owner_id, run_id, chat_id, tools_used=tools_used),
                        )
                        terminal_sent = True
                        break
                    # Tool call path.
                    try:
                        tool = get_tool(action.tool_name or "")
                    except ToolNotFoundError:
                        logger.warning("research unknown tool %r", action.tool_name)
                        await self._fail(owner_id, run_id, "UNKNOWN_TOOL",
                                         "Unknown analysis tool requested.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    if tools_used >= self.max_tool_calls:
                        await self._fail(owner_id, run_id, "MAX_TOOL_CALLS",
                                         "Analysis tool budget exhausted.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    arguments = dict(action.arguments or {})
                    if "wallet_result_set_id" in tool.args_model.model_fields and not arguments.get(
                        "wallet_result_set_id"
                    ):
                        filled = resolve_wallet_set_id(prompt, refs)
                        if filled:
                            arguments["wallet_result_set_id"] = filled
                    if "market_result_set_id" in tool.args_model.model_fields and not arguments.get(
                        "market_result_set_id"
                    ):
                        # Only narrow to a market set when the prompt actually
                        # references markets; otherwise consensus/history cover
                        # every open market of the wallet set.
                        if re.search(r"market", prompt, re.IGNORECASE):
                            filled_market = resolve_market_set_id(prompt, refs)
                            if filled_market:
                                arguments["market_result_set_id"] = filled_market
                    tool_start = time.perf_counter()
                    try:
                        validated_args = tool.args_model.model_validate(arguments)
                    except Exception:
                        logger.warning("research invalid tool args for %s", tool.name)
                        await self._fail(owner_id, run_id, "INVALID_TOOL_ARGS",
                                         "Invalid analysis parameters.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    call_key = (tool.name, panel_key(tool.name, validated_args))
                    if call_key in executed_keys:
                        # Identical analysis already ran: snapshots are immutable
                        # within a run, so re-executing adds nothing. Tell the
                        # model the earlier row count and let it answer.
                        short_circuits += 1
                        if short_circuits > 2:
                            await self._fail(owner_id, run_id, "MAX_TOOL_CALLS",
                                             "Analysis tool budget exhausted.",
                                             events, chat_id=chat_id)
                            terminal_sent = True
                            break
                        logger.info(
                            "research duplicate tool call short-circuited",
                            extra=self._log_extra(
                                owner_id, run_id, chat_id, tool=tool.name,
                                rows=executed_keys[call_key]),
                        )
                        ctx.messages.append({
                            "role": "system",
                            "content": (
                                f"Note: {tool.name} with identical arguments already ran "
                                f"in this run and returned {executed_keys[call_key]} rows. "
                                "Answer the user from the available results instead of "
                                "calling it again."
                            ),
                        })
                        continue
                    events.append(self._event(
                        run_id, "tool.started",
                        tool_name=tool.name, arguments=arguments))
                    try:
                        execution = await execute_tool(
                            self.repo, self.analytics, owner_id=owner_id, chat_id=chat_id,
                            tool_name=tool.name, arguments=arguments, run_id=run_id)
                    except ToolValidationError:
                        logger.warning("research invalid tool args for %s", tool.name)
                        await self._fail(owner_id, run_id, "INVALID_TOOL_ARGS",
                                         "Invalid analysis parameters.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    except ResultSetAccessError:
                        logger.warning("research result access denied")
                        await self._fail(owner_id, run_id, "RESULT_ACCESS_DENIED",
                                         "Referenced results are not available in this chat.",
                                         events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    except Exception:
                        logger.exception("research tool execution failed")
                        await self._fail(owner_id, run_id, "TOOL_ERROR",
                                         "Analysis step failed.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    tools_used += 1
                    result_set = execution.result_set
                    executed_keys[call_key] = result_set.row_count
                    logger.info(
                        "research tool executed",
                        extra=self._log_extra(
                            owner_id, run_id, chat_id, tool=tool.name,
                            duration_ms=round((time.perf_counter() - tool_start) * 1000, 1),
                            rows=result_set.row_count),
                    )
                    if result_set.row_count > self.max_rows:
                        await self._fail(owner_id, run_id, "ROW_LIMIT",
                                         "Analysis returned too many rows.", events, chat_id=chat_id)
                        terminal_sent = True
                        break
                    events.append(self._event(
                        run_id, "result.created",
                        result_set_id=str(result_set.result_set_id),
                        kind=result_set.kind, label=result_set.label,
                        row_count=result_set.row_count,
                        snapshot_at=result_set.snapshot_at.isoformat(),
                        summary=result_set.summary))
                    panel = await self._upsert_panel(
                        owner_id, chat_id, tool.name, validated_args,
                        execution.panel_type, result_set)
                    events.append(self._event(
                        run_id, "panel.upserted", panel=panel.model_dump(mode="json")))
                    refs = await self._refresh_refs(owner_id, chat_id)
                    ctx = await build_context(self.repo, owner_id, chat_id)
        except TimeoutError:
            logger.warning("research run timed out")
            if not terminal_sent:
                await self._fail(owner_id, run_id, "TIMEOUT",
                                 "Analysis timed out.", events, chat_id=chat_id)
                terminal_sent = True
        except Exception:
            logger.exception("research run failed unexpectedly")
            if not terminal_sent:
                await self._fail(owner_id, run_id, "RUN_ERROR",
                                 "Analysis run failed.", events, chat_id=chat_id)
                terminal_sent = True
        for event in events:
            yield event

    async def _refresh_refs(self, owner_id: str, chat_id: UUID) -> list[dict]:
        summaries = await self.repo.list_result_summaries(owner_id, chat_id, limit=20)
        return [{
            "result_set_id": str(r.result_set_id), "kind": r.kind,
            "label": r.label, "row_count": r.row_count,
            "definition": r.definition, "summary": r.summary,
        } for r in summaries]

    async def _upsert_panel(
        self,
        owner_id: str,
        chat_id: UUID,
        tool_name: str,
        args: BaseModel,
        panel_type: PanelType,
        result_set: Any,
    ) -> Any:
        key = panel_key(tool_name, args)
        defaults = PANEL_DEFAULTS[panel_type.value]
        existing = await self.repo.list_panels(owner_id, chat_id)
        order = len(existing)
        for panel in existing:
            if panel.panel_key == key:
                order = panel.layout.order if hasattr(panel.layout, "order") else order
                break
        layout = {
            "col_span": defaults["col_span"],
            "min_height": defaults["min_height"],
            "order": order,
        }
        config = {
            "result_kind": result_set.kind,
            "summary": result_set.summary,
            "row_count": result_set.row_count,
            "snapshot_at": result_set.snapshot_at.isoformat(),
        }
        panel = await self.repo.upsert_panel(
            owner_id, chat_id, key, panel_type.value, result_set.label,
            result_set.result_set_id, layout, config,
        )
        assert panel is not None
        return panel


def available_tool_names() -> list[str]:
    return [t.name for t in TOOL_DEFINITIONS]
