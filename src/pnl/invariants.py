"""Hard and soft identity checks for v2 position rows.

Hard failures → quarantine (row is not persisted).
Soft warnings → logged, row is persisted with a warning flag.

Cost decomposition is SOFT until Polymarket confirms whether
avg_price is net or gross of entry_fees_usdc.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

_TOL = 0.01  # 1-cent tolerance for float arithmetic


@dataclass
class InvariantFailure:
    rule: str
    expected: str
    actual: str


@dataclass
class SoftInvariantWarning:
    rule: str
    expected: str
    actual: str


def _present(row: dict, key: str) -> bool:
    return key in row and row[key] is not None


def _f(val) -> float | None:
    """Return float or None (never silently zero for missing)."""
    if val is None:
        return None
    try:
        v = float(val)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def check_row_invariants(
    row: dict,
) -> tuple[list[InvariantFailure], list[SoftInvariantWarning]]:
    """Return (hard_failures, soft_warnings).

    hard_failures: non-empty → quarantine the row.
    soft_warnings: non-empty → persist with warning flag.
    """
    failures: list[InvariantFailure] = []
    warnings: list[SoftInvariantWarning] = []

    # ── Hard: PnL decomposition ───────────────────────────────────────────
    # Only check when all three fields are present and parseable.
    tp = _f(row.get("source_total_pnl"))
    rp = _f(row.get("realized_pnl"))
    up = _f(row.get("unrealized_pnl"))
    if tp is not None and rp is not None and up is not None:
        if abs(tp - (rp + up)) > _TOL:
            failures.append(InvariantFailure(
                "pnl_decomposition",
                f"total_pnl={tp:.4f}",
                f"realized+unrealized={rp+up:.4f}",
            ))

    # ── Hard: size sanity ─────────────────────────────────────────────────
    cs = _f(row.get("current_size"))
    ts = _f(row.get("total_size"))
    if cs is not None and cs < 0:
        failures.append(InvariantFailure("negative_current_size", ">=0", f"{cs}"))
    if ts is not None and ts < 0:
        failures.append(InvariantFailure("negative_total_size", ">=0", f"{ts}"))
    if cs is not None and ts is not None and ts > 0 and cs > ts + _TOL:
        failures.append(InvariantFailure(
            "size_sanity", f"current_size<={ts}", f"current_size={cs}"
        ))

    # ── Soft: cost decomposition ──────────────────────────────────────────
    # SOFT until Polymarket confirms whether avg_price is net or gross.
    tc = _f(row.get("total_cost_usdc"))
    ec = _f(row.get("entry_cost_usdc"))
    ef = _f(row.get("entry_fees_usdc"))
    if tc is not None and ec is not None and ef is not None and tc > 0:
        if abs(tc - (ec + ef)) > _TOL:
            warnings.append(SoftInvariantWarning(
                "cost_decomposition",
                f"total={tc:.4f}",
                f"entry+fees={ec+ef:.4f}",
            ))

    return failures, warnings


def compute_cost_basis_confidence(row: dict) -> str:
    """Return 'high' or 'low'. Low when any shares have no acquisition price."""
    def _pos(key: str) -> bool:
        v = _f(row.get(key))
        return v is not None and v > 0
    if _pos("transfer_in_size") or _pos("unattributed_size"):
        return "low"
    return "high"
