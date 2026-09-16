"""Retired legacy wallet metrics repair command.

Metric repair used to mutate canonical accounting values and could overwrite
eligible-row counts, ROI, and freshness fields.  The canonical coordinator in
``src.workers.positions_metrics_compute`` is now the only supported publisher.
Use ``python -m src.scripts.metric_writer_audit audit`` for a read-only static
ownership audit and its ``baseline`` command for a read-only database snapshot.
"""

from __future__ import annotations


RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"


def main() -> int:
    """Fail closed before importing a database driver or opening a connection."""
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: use the canonical metrics coordinator; "
        "this legacy command performs no database access"
    )


if __name__ == "__main__":
    raise SystemExit(main())
