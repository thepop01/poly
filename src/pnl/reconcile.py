"""Combine cleaned closed and open contributions into one wallet PnL."""
from dataclasses import dataclass

from src.pnl.rules import (
    closed_contribution,
    is_synthetic_mint,
    open_contribution,
)


@dataclass
class WalletPnl:
    realized: float
    unrealized: float
    total_pnl: float
    pm_pnl: float
    residual: float
    relative_error: float
    source: str
    n_closed: int
    n_open: int
    dropped_synthetic_legs: int


def _key(row: dict) -> tuple[str, str]:
    return (row.get("conditionId") or "", row.get("outcome") or "")


def reconcile_wallet(closed_rows: list[dict], open_rows: list[dict],
                     pm_pnl: float) -> WalletPnl:
    """Compute position-derived PnL and its distance from the leaderboard.

    Every (conditionId, outcome) row remains independent. Complete-set mint
    collateral cannot be reconstructed by inventing, dropping, or pairing
    outcome rows; account-level reconciliation must use actual activity or
    the official leaderboard PnL instead.
    """
    realized = sum(closed_contribution(row) for row in closed_rows)
    unrealized = sum(open_contribution(row) for row in open_rows)

    total = realized + unrealized
    residual = total - pm_pnl
    relative_error = (abs(residual) / abs(pm_pnl) * 100.0) if pm_pnl else 0.0
    source = classify_wallet(closed_rows, open_rows, pm_pnl)

    return WalletPnl(
        realized=realized,
        unrealized=unrealized,
        total_pnl=total,
        pm_pnl=pm_pnl,
        residual=residual,
        relative_error=relative_error,
        source=source,
        n_closed=len(closed_rows),
        n_open=len(open_rows),
        dropped_synthetic_legs=0,
    )


CLOSED_POSITIONS_CEILING = 30_000
MINTER_SYNTHETIC_SHARE = 0.20


def classify_wallet(closed_rows: list[dict], open_rows: list[dict],
                    pm_pnl: float) -> str:
    """Label the wallet archetype to decide whether positions can be trusted.

    - no_position_data:    nothing to sum; positions cannot produce a number
    - complete_set_minter: mint cost is not attributable per row
    - truncated_history:   we hold a sample, not a lifetime
    - directional:         reconstructable
    """
    rows = list(closed_rows) + list(open_rows)
    if not rows:
        return "no_position_data"

    synthetic = sum(1 for row in rows if is_synthetic_mint(row))
    if synthetic / len(rows) >= MINTER_SYNTHETIC_SHARE:
        return "complete_set_minter"

    if len(closed_rows) >= CLOSED_POSITIONS_CEILING:
        return "truncated_history"

    return "directional"
