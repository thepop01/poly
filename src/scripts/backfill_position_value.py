"""Retired legacy open-position metrics backfill."""
from __future__ import annotations

RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: open metrics are owned by positions_open_backfill"
    )


if __name__ == "__main__":
    raise SystemExit(main())
