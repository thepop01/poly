"""Retired legacy official-PnL fallback backfill."""
from __future__ import annotations

RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: official PnL remains pm_pnl; canonical totals use the position ledger"
    )


if __name__ == "__main__":
    raise SystemExit(main())
