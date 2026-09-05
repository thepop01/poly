"""Write and verify compressed Activity snapshots for high-divergence wallets."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def archive_events(events: list[dict[str, Any]], address: str, directory: str | Path) -> dict[str, Any]:
    """Write a deterministic ZSTD Parquet snapshot and verify it can be read."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised in deployment
        raise RuntimeError("pyarrow is required for high-divergence Activity archives") from exc

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{address.lower()}_{stamp}.parquet"
    rows = []
    for event in events:
        rows.append({
            "event_sha256": hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest(),
            "condition_id": event.get("conditionId"),
            "asset": event.get("asset"),
            "outcome": event.get("outcome"),
            "event_type": event.get("type"),
            "side": event.get("side"),
            "timestamp": event.get("timestamp"),
            "size": event.get("size"),
            "usdc_size": event.get("usdcSize"),
            "price": event.get("price"),
            "transaction_hash": event.get("transactionHash"),
            "payload_json": json.dumps(event, sort_keys=True, default=str),
        })
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = pq.read_metadata(path)
    if metadata.num_rows != len(rows):
        raise RuntimeError(f"Parquet row-count verification failed: {metadata.num_rows} != {len(rows)}")
    timestamps = [float(event.get("timestamp")) for event in events if event.get("timestamp")]
    return {
        "file_path": str(path),
        "sha256": digest,
        "row_count": len(rows),
        "minimum_timestamp": min(timestamps) if timestamps else None,
        "maximum_timestamp": max(timestamps) if timestamps else None,
        "schema_version": "activity-v1",
        "compression": "zstd",
    }
