"""Conservative provenance helpers for wallet position audits.

These functions intentionally never decide that a row is false from numeric
shape alone.  They classify row/source comparisons so an explicit review or a
future evidence-backed exclusion can act on the result.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class AuditDecision:
    status: str
    reason: str


def normalize_outcome(value: object) -> str:
    """Normalize display-only outcome spelling without treating labels as IDs."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def classify_row(
    position: Mapping[str, object],
    sibling_rows: Iterable[Mapping[str, object]],
    activity: Iterable[Mapping[str, object]],
) -> AuditDecision:
    """Classify a row without making an unsupported deletion decision.

    A matching Activity BUY on the same normalized outcome is direct evidence
    of a CLOB purchase.  Matching non-trade activity can be evidence of a
    legitimate mint/merge/redemption lifecycle.  Complementary sibling rows
    with no match are only review candidates: a real split can look identical.
    """
    condition_id = str(position.get("condition_id") or position.get("conditionId") or "")
    outcome = normalize_outcome(position.get("outcome"))
    source_asset = str(position.get("source_asset") or position.get("asset") or "")
    same_market = [e for e in activity if str(e.get("conditionId") or "") == condition_id]
    same_leg = [
        e for e in same_market
        if normalize_outcome(e.get("outcome")) == outcome
        and (not source_asset or not e.get("asset") or str(e.get("asset")) == source_asset)
    ]
    if any(str(e.get("type") or "").upper() == "TRADE" and str(e.get("side") or "").upper() == "BUY" for e in same_leg):
        return AuditDecision("eligible", "activity_matching_buy")
    if same_leg:
        return AuditDecision("eligible", "activity_matching_nontrade_event")

    bought = float(position.get("total_bought") or position.get("totalBought") or 0)
    price = float(position.get("avg_buy_price") or position.get("avgPrice") or 0)
    for sibling in sibling_rows:
        # Callers commonly supply every row in the market, including
        # `position` itself. A 50-cent row is its own numeric complement, but
        # it is never evidence of an opposite leg.
        sibling_outcome = normalize_outcome(sibling.get("outcome"))
        sibling_asset = str(sibling.get("source_asset") or sibling.get("asset") or "")
        if sibling_outcome == outcome and sibling_asset == source_asset:
            continue
        sibling_bought = float(sibling.get("total_bought") or sibling.get("totalBought") or 0)
        sibling_price = float(sibling.get("avg_buy_price") or sibling.get("avgPrice") or 0)
        if abs(bought - sibling_bought) < 0.001 and abs((price + sibling_price) - 1.0) < 0.001:
            return AuditDecision("review_required", "complementary_unproven_signature")
    if same_market:
        return AuditDecision("review_required", "same_market_different_outcome")
    return AuditDecision("review_required", "absent_from_activity_requires_source_check")
