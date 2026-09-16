"""Retired legacy window-statistics writer.

This command delegated to the retired ``leaderboard_stats.process_wallet``
worker, which could publish canonical metric fields.  Window and category
metrics are now owned by the canonical coordinator.
"""

from __future__ import annotations

RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: backfill_window_stats is retired; "
        "use positions_metrics_compute"
    )


if __name__ == "__main__":
    raise SystemExit(main())
