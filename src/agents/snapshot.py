"""Build a flat metric snapshot (dict[str, float]) from a markets row for the
condition DSL. Price-change fields are placeholders (0.0) in Phase 1."""
from datetime import datetime, timezone
from typing import Any, Mapping

_FAR_FUTURE_HOURS = 10.0 ** 9


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    return float(v)


def build_snapshot(row: Mapping[str, Any]) -> dict[str, float]:
    resolution = row.get("resolution_date")
    if resolution is None:
        hours = _FAR_FUTURE_HOURS
    else:
        if resolution.tzinfo is None:
            resolution = resolution.replace(tzinfo=timezone.utc)
        delta = resolution - datetime.now(timezone.utc)
        hours = delta.total_seconds() / 3600.0
    return {
        "current_price": _f(row.get("current_price")),
        "total_volume": _f(row.get("total_volume")),
        "liquidity": _f(row.get("liquidity")),
        "price_change_1h_pct": 0.0,   # Phase 1 placeholder; wire history later
        "price_change_24h_pct": 0.0,  # Phase 1 placeholder
        "hours_to_resolution": hours,
    }
