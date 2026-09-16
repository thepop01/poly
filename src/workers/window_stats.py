"""Pure, I/O-free helpers for windowed and headline stats.

Kept separate from leaderboard_stats.py so they can be unit-tested without a DB
or network. compute_category_window_stats groups closed positions by category and
slices the last N (by endDate desc) for each window.
"""
from datetime import datetime, timezone
from typing import Callable


def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _parse_end(val):
    if not val:
        return None
    try:
        s = str(val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _aggregate(positions: list[dict]) -> dict:
    pnl = 0.0
    volume = 0.0
    wins = 0
    last_active = None
    for cp in positions:
        rpnl = _parse(cp.get("realizedPnl"))
        pnl += rpnl
        volume += _parse(cp.get("totalBought"))
        if rpnl > 0:
            wins += 1
        end = _parse_end(cp.get("endDate"))
        if end and (last_active is None or end > last_active):
            last_active = end
    resolved = len(positions)
    return {
        "pnl": pnl,
        "volume": volume,
        "resolved_count": resolved,
        "winning_count": wins,
        "win_rate": (wins / resolved) if resolved else 0.0,
        "roi_pct": (pnl / volume * 100) if volume else 0.0,
        "last_active": last_active,
    }


def compute_category_window_stats(
    closed_positions: list[dict],
    windows: list[int],
    classify: Callable[[str], str],
) -> dict[tuple[str, int], dict]:
    """Return {(category, window): stats} plus ('OVERALL', window).

    `classify(title) -> CATEGORY` maps a position's market title to a category.
    Positions are sliced by endDate desc within each category (and overall).
    """
    if not closed_positions:
        return {}

    ordered = sorted(
        closed_positions,
        key=lambda cp: _parse_end(cp.get("endDate")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    by_cat: dict[str, list[dict]] = {}
    for cp in ordered:
        cat = (classify(cp.get("title") or "") or "OTHER").upper()
        by_cat.setdefault(cat, []).append(cp)

    result: dict[tuple[str, int], dict] = {}
    for window in windows:
        result[("OVERALL", window)] = _aggregate(ordered[:window])
        for cat, positions in by_cat.items():
            result[(cat, window)] = _aggregate(positions[:window])
    return result


def select_headline_pnl(website: dict | None, computed_pnl: float, computed_volume: float) -> dict:
    """Headline pnl/volume come from the leaderboard when the wallet appears on it
    (presence of the `website` object), else from our computed realized+unrealized.
    Presence — not `!= 0` — distinguishes a real break-even from a missing fetch."""
    if website is not None:
        return {"pnl": _parse(website.get("pnl")),
                "volume": _parse(website.get("volume")),
                "pnl_source": "leaderboard"}
    return {"pnl": computed_pnl, "volume": computed_volume, "pnl_source": "computed"}
