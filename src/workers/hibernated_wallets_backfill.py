"""Retired dormant-wallet metrics backfill.

Dormant wallets are now selected from source evidence and processed by the
canonical source/coordinator pipeline.  This legacy loop must not fabricate a
``computed_at`` timestamp after failures.
"""

from __future__ import annotations

RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: hibernated_wallets_backfill is retired; "
        "use the source backfills and canonical coordinator"
    )


if __name__ == "__main__":
    raise SystemExit(main())
