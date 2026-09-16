"""Retired legacy wins/count backfill."""
from __future__ import annotations

RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: eligible counts are owned by the canonical coordinator"
    )


if __name__ == "__main__":
    raise SystemExit(main())
