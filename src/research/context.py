"""Compact chat context and follow-up reference resolution.

The model receives compact summaries and opaque result-set IDs, never raw
member rows. Follow-ups such as "those wallets" resolve through the current
chat's result references only; another chat's results never resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

WALLET_KINDS = frozenset({"wallet_set", "market_participants"})
MARKET_KINDS = frozenset({
    "market_set", "position_overlap", "same_outcome_history", "outcome_consensus",
})


@dataclass(frozen=True)
class ResearchContext:
    messages: list[dict[str, str]]
    result_refs: list[dict[str, object]]


async def build_context(repo: Any, owner_id: str, chat_id: UUID) -> ResearchContext:
    messages = await repo.list_messages(owner_id, chat_id, limit=30)
    result_refs = await repo.list_result_summaries(owner_id, chat_id, limit=20)
    return ResearchContext(
        messages=[{"role": m.role, "content": m.content} for m in messages if m.role != "tool"],
        result_refs=[{
            "result_set_id": str(r.result_set_id), "kind": r.kind,
            "label": r.label, "row_count": r.row_count,
            "definition": r.definition, "summary": r.summary,
        } for r in result_refs],
    )


def resolve_reference(
    prompt: str, refs: list[dict[str, Any]], kinds: frozenset[str]
) -> dict[str, Any] | None:
    """Return the most recent compatible ref, preferring an explicit label match."""
    compat = [r for r in refs if r.get("kind") in kinds]
    if not compat:
        return None
    lowered = (prompt or "").lower()
    for ref in compat:
        label = str(ref.get("label") or "").lower().strip()
        if len(label) >= 4 and label in lowered:
            return ref
    return compat[0]


def resolve_wallet_set_id(
    prompt: str, refs: list[dict[str, Any]]
) -> str | None:
    ref = resolve_reference(prompt, refs, WALLET_KINDS)
    return str(ref["result_set_id"]) if ref else None


def resolve_market_set_id(
    prompt: str, refs: list[dict[str, Any]]
) -> str | None:
    ref = resolve_reference(prompt, refs, MARKET_KINDS)
    return str(ref["result_set_id"]) if ref else None
