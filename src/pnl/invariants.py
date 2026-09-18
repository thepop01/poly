"""Hard identity checks for v2 position rows. Failing rows are quarantined."""
from __future__ import annotations
from dataclasses import dataclass

_TOL = 0.01  # 1-cent tolerance


@dataclass
class InvariantFailure:
    rule: str
    expected: str
    actual: str


def _f(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def check_row_invariants(row: dict) -> list[InvariantFailure]:
    failures: list[InvariantFailure] = []

    tc = _f(row.get("total_cost_usdc"))
    ec = _f(row.get("entry_cost_usdc"))
    ef = _f(row.get("entry_fees_usdc"))
    if tc > 0 and abs(tc - (ec + ef)) > _TOL:
        failures.append(InvariantFailure("cost_decomposition", f"total={tc}", f"net+fees={ec+ef}"))

    tp = _f(row.get("source_total_pnl"))
    rp = _f(row.get("realized_pnl"))
    up = _f(row.get("unrealized_pnl"))
    if tp != 0.0 and abs(tp - (rp + up)) > _TOL:
        failures.append(InvariantFailure("pnl_decomposition", f"total={tp}", f"realized+unrealized={rp+up}"))

    cs = _f(row.get("current_size"))
    ts = _f(row.get("total_size"))
    if ts > 0 and cs > ts + _TOL:
        failures.append(InvariantFailure("size_sanity", f"current<={ts}", f"current={cs}"))

    return failures


def compute_cost_basis_confidence(row: dict) -> str:
    """Return 'high' or 'low'. Low when any shares have no acquisition price."""
    if _f(row.get("transfer_in_size")) > 0 or _f(row.get("unattributed_size")) > 0:
        return "low"
    return "high"
