"""Read-only provenance audit between closed-position rows and Polymarket activity.

The Data API caps `/activity` pagination at offset 5,000.  This script avoids
that cap by recursively splitting a requested time range whenever a window is
full, then compares activity to the database at (conditionId, outcome).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import asyncpg
from dotenv import load_dotenv

from src.scripts.archive_activity_parquet import archive_events
from src.workers.wallet_provenance_audit import classify_row, normalize_outcome

load_dotenv()

DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
).replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
ACTIVITY_URL = "https://data-api.polymarket.com/activity"
PAGE_SIZE = 500
MAX_OFFSET = 5000
ACTIVITY_HTTP_CONCURRENCY = max(1, int(os.getenv("ACTIVITY_HTTP_CONCURRENCY", "50")))
_activity_request_semaphore: asyncio.Semaphore | None = None
_activity_request_loop: asyncio.AbstractEventLoop | None = None
logger = logging.getLogger(__name__)


def _get_activity_request_semaphore() -> asyncio.Semaphore:
    """Return one process-wide semaphore bound to the current event loop."""
    global _activity_request_semaphore, _activity_request_loop
    loop = asyncio.get_running_loop()
    if _activity_request_semaphore is None or _activity_request_loop is not loop:
        _activity_request_semaphore = asyncio.Semaphore(ACTIVITY_HTTP_CONCURRENCY)
        _activity_request_loop = loop
    return _activity_request_semaphore


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _activity_key(row: dict) -> tuple:
    return (
        row.get("transactionHash"), row.get("type"), row.get("conditionId"),
        row.get("asset"), row.get("outcome"), row.get("timestamp"),
        row.get("side"), row.get("size"), row.get("usdcSize"),
    )


def _activity_event_digest(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def _restore_activity_event(row: Mapping[str, object]) -> dict:
    """Restore one stored event to the original Data API field shape."""
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    event = dict(payload)
    event_timestamp = row.get("event_timestamp")
    event.setdefault("conditionId", row.get("condition_id"))
    event.setdefault("asset", row.get("asset"))
    event.setdefault("outcome", row.get("outcome"))
    event.setdefault("type", row.get("event_type"))
    event.setdefault("side", row.get("side"))
    event.setdefault(
        "timestamp",
        event_timestamp.timestamp() if isinstance(event_timestamp, datetime) else event_timestamp,
    )
    event.setdefault("size", _number(row.get("size")))
    event.setdefault("usdcSize", _number(row.get("usdc_size")))
    event.setdefault("price", _number(row.get("price")))
    event.setdefault("transactionHash", row.get("transaction_hash"))
    return event


def _activity_buy_summary(events: list[dict]) -> tuple[float, float, float | None]:
    """Return shares, USD cost, and weighted price for same-leg Activity BUYs."""
    buys = [
        event for event in events
        if str(event.get("type") or "").upper() == "TRADE"
        and str(event.get("side") or "").upper() == "BUY"
    ]
    shares = sum(_number(event.get("size")) for event in buys)
    usdc = sum(_number(event.get("usdcSize")) for event in buys)
    return shares, usdc, (usdc / shares if shares else None)


def _activity_lifecycle_summary(events: list[dict]) -> dict[str, object]:
    """Compact lifecycle accounting at (condition_id, outcome) grain.

    This intentionally keeps event-level provenance out of the position table.
    Values are aggregated from the supplied event list and never inferred from
    the DB position.  A mismatch row may pass all market events so its
    Activity outcome remains visible beside the DB outcome.
    """
    buckets = {
        "buy": [0.0, 0.0], "sell": [0.0, 0.0], "redeem": [0.0, 0.0],
        "split": [0.0, 0.0], "merge": [0.0, 0.0], "conversion": [0.0, 0.0],
        "reward": [0.0, 0.0], "rebate": [0.0, 0.0], "yield": [0.0, 0.0],
    }
    first_ts: float | None = None
    last_ts: float | None = None
    hashes: set[str] = set()
    for event in events:
        kind = str(event.get("type") or "").upper()
        side = str(event.get("side") or "").upper()
        key: str | None = None
        if kind == "TRADE" and side == "BUY":
            key = "buy"
        elif kind == "TRADE" and side == "SELL":
            key = "sell"
        elif kind in {"REDEEM", "SPLIT", "MERGE", "CONVERSION", "REWARD", "YIELD"}:
            key = kind.lower()
        elif kind in {"MAKER_REBATE", "TAKER_REBATE", "REBATE"}:
            key = "rebate"
        if key:
            buckets[key][0] += _number(event.get("size"))
            buckets[key][1] += _number(event.get("usdcSize"))
        digest = _activity_event_digest(event)
        hashes.add(digest)
        timestamp = _number(event.get("timestamp"))
        if timestamp:
            first_ts = timestamp if first_ts is None else min(first_ts, timestamp)
            last_ts = timestamp if last_ts is None else max(last_ts, timestamp)
    buy_shares, buy_usdc = buckets["buy"]
    sell_shares, sell_usdc = buckets["sell"]
    redeem_shares, redeem_usdc = buckets["redeem"]
    split_shares, split_usdc = buckets["split"]
    merge_shares, merge_usdc = buckets["merge"]
    conversion_shares, conversion_usdc = buckets["conversion"]
    return {
        "activity_buy_shares": buy_shares,
        "activity_buy_usdc": buy_usdc,
        "activity_avg_buy_price": buy_usdc / buy_shares if buy_shares else None,
        "activity_sell_shares": sell_shares,
        "activity_sell_usdc": sell_usdc,
        "activity_avg_sell_price": sell_usdc / sell_shares if sell_shares else None,
        "activity_redeem_shares": redeem_shares,
        "activity_redeem_usdc": redeem_usdc,
        "activity_split_shares": split_shares,
        "activity_split_usdc": split_usdc,
        "activity_merge_shares": merge_shares,
        "activity_merge_usdc": merge_usdc,
        "activity_conversion_shares": conversion_shares,
        "activity_conversion_usdc": conversion_usdc,
        "activity_reward_usdc": buckets["reward"][1],
        "activity_rebate_usdc": buckets["rebate"][1],
        "activity_yield_usdc": buckets["yield"][1],
        "activity_net_shares": buy_shares + split_shares + conversion_shares - sell_shares - merge_shares - redeem_shares,
        "activity_event_count": len(events),
        "activity_distinct_event_count": len(hashes),
        "activity_first_event_at": datetime.fromtimestamp(first_ts, timezone.utc) if first_ts else None,
        "activity_last_event_at": datetime.fromtimestamp(last_ts, timezone.utc) if last_ts else None,
    }


async def _fetch_page(
    session: aiohttp.ClientSession, address: str, start: int, end: int, offset: int,
    request_semaphore: asyncio.Semaphore,
) -> list[dict]:
    params = {
        "user": address,
        "start": start,
        "end": end,
        "sortBy": "TIMESTAMP",
        "sortDirection": "ASC",
        "limit": PAGE_SIZE,
        "offset": offset,
    }
    for attempt in range(4):
        try:
            async with request_semaphore:
                async with session.get(ACTIVITY_URL, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else []
                    if response.status not in (429, 500, 502, 503, 504):
                        raise RuntimeError(f"activity HTTP {response.status} for {start}-{end}")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt == 3:
                raise
        await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"activity retries exhausted for {start}-{end}")


async def fetch_complete_activity(address: str, start: int, end: int) -> list[dict]:
    """Fetch complete activity by recursively bisecting windows at the offset cap."""
    timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=45)
    seen: dict[tuple, dict] = {}
    completed = 0
    request_semaphore = _get_activity_request_semaphore()

    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
        earliest_page = await _fetch_page(session, address, start, end, 0, request_semaphore)
        timestamps = [int(row.get("timestamp") or 0) for row in earliest_page if row.get("timestamp")]
        if not timestamps:
            return []
        # Avoid recursively probing decades before the wallet's first event.
        windows = [(min(timestamps), end)]
        while windows:
            window_start, window_end = windows.pop()
            pages = await asyncio.gather(*[
                _fetch_page(session, address, window_start, window_end, offset, request_semaphore)
                for offset in range(0, MAX_OFFSET + 1, PAGE_SIZE)
            ])
            if len(pages[-1]) == PAGE_SIZE:
                if window_end <= window_start:
                    raise RuntimeError(
                        f"more than {MAX_OFFSET + PAGE_SIZE} activity rows at second {window_start}; "
                        "cannot prove completeness without an additional API partition"
                    )
                midpoint = (window_start + window_end) // 2
                windows.append((window_start, midpoint))
                windows.append((midpoint + 1, window_end))
                continue
            for page in pages:
                for row in page:
                    if isinstance(row, dict):
                        seen[_activity_key(row)] = row
            completed += 1
            if completed % 10 == 0:
                print(f"windows={completed:,} pending={len(windows):,} activity={len(seen):,}", flush=True)
    return list(seen.values())


async def _persist_audit(
    conn: asyncpg.Connection, address: str, activity: list[dict], decisions: list[dict],
    reconciliations: list[dict], activity_only_markets: list[dict], report: dict,
    canonical_markets: set[str] | None = None,
    redeemable_markets: set[str] | None = None,
    source_snapshot_id: int | None = None,
) -> str:
    """Persist immutable source proof and conservative decisions.

    This deliberately stores only `eligible` and `review_required` decisions.
    An Activity mismatch is not proof that a position row is false, so this
    writer never creates an `excluded_proven` decision.
    """
    activity_digest = hashlib.sha256(
        json.dumps([_activity_key(row) for row in activity], sort_keys=True, default=str).encode()
    ).hexdigest()
    audit_id = uuid.uuid4()
    archive_info = None
    # A legacy one-shot audit owns its source fetch and archives it here. The
    # split analyzer receives the exact snapshot staged by Worker 3; archiving
    # that complete fetch happens before Worker 4 applies hot-cache retention.
    if source_snapshot_id is None:
        divergence = await conn.fetchrow(
            "SELECT total_pnl, pm_pnl FROM wallet_metrics_v2 WHERE address=$1", address
        )
        if divergence and divergence["total_pnl"] is not None and divergence["pm_pnl"] is not None:
            if abs(float(divergence["total_pnl"]) - float(divergence["pm_pnl"])) >= 100000:
                try:
                    archive_info = archive_events(
                        activity, address, os.getenv("ACTIVITY_ARCHIVE_DIR", "backtest_cache/activity_archives")
                    )
                except RuntimeError as exc:
                    logger.error("Activity archive unavailable for %s: %s", address, exc)
    async with conn.transaction():
        snapshot_id = source_snapshot_id
        if snapshot_id is None:
            snapshot_id = await conn.fetchval("""
                INSERT INTO wallet_source_snapshots_v2 (address, source, complete, payload_sha256, metadata)
                VALUES ($1, 'activity', TRUE, $2, $3::jsonb)
                RETURNING id
            """, address, activity_digest, json.dumps(report["activity"]))
            await conn.executemany("""
                INSERT INTO wallet_activity_events_v2 (
                    snapshot_id, address, event_sha256, condition_id, asset, outcome,
                    event_type, side, event_timestamp, size, usdc_size, price,
                    transaction_hash, payload
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,to_timestamp($9),$10,$11,$12,$13,$14::jsonb
                ) ON CONFLICT (snapshot_id, event_sha256) DO NOTHING
            """, [
                (
                    snapshot_id, address, _activity_event_digest(event), event.get("conditionId"),
                    event.get("asset"), event.get("outcome"), event.get("type"), event.get("side"),
                    _number(event.get("timestamp")) or None, _number(event.get("size")),
                    _number(event.get("usdcSize")), _number(event.get("price")),
                    event.get("transactionHash"), json.dumps(event),
                ) for event in activity
            ])
        evidence_ids: dict[tuple[str, str], int] = {}
        for decision in decisions:
            event = decision.get("evidence_event")
            transfer = decision.get("lineage_transfer")
            if not event and not transfer:
                continue
            key = (decision["condition_id"], decision["outcome"])
            evidence_ids[key] = await conn.fetchval("""
                INSERT INTO wallet_position_evidence_v2 (
                    address, condition_id, asset, outcome, evidence_type, transaction_hash, snapshot_id
                ) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id
            """, address, decision["condition_id"],
                event.get("asset") if event else transfer["token_id"], decision["outcome"],
                decision["reason"] if event else "lineage_transfer_in",
                event.get("transactionHash") if event else transfer["tx_hash"], snapshot_id)
        await conn.executemany("""
            INSERT INTO wallet_position_audit_decisions_v2
                (audit_id, address, condition_id, outcome, status, reason, evidence_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """, [
            (audit_id, address, d["condition_id"], d["outcome"], d["status"], d["reason"],
             evidence_ids.get((d["condition_id"], d["outcome"])))
            for d in decisions
        ])
        await conn.executemany("""
            INSERT INTO wallet_position_activity_reconciliations_v2 (
                audit_id, snapshot_id, address, condition_id, outcome, classification,
                comparison_quality,
                db_total_bought, db_avg_buy_price, db_cost_basis, db_realized_pnl,
                activity_buy_shares, activity_buy_usdc, activity_avg_buy_price,
                shares_delta, cost_basis_delta, activity_outcomes,
                lineage_transfer_in_shares, lineage_transfer_in_count, lineage_first_transfer_at,
                activity_sell_shares, activity_sell_usdc, activity_avg_sell_price,
                activity_redeem_shares, activity_redeem_usdc,
                activity_split_shares, activity_split_usdc,
                activity_merge_shares, activity_merge_usdc,
                activity_conversion_shares, activity_conversion_usdc,
                activity_reward_usdc, activity_rebate_usdc, activity_yield_usdc,
                activity_net_shares, activity_event_count, activity_distinct_event_count,
                activity_first_event_at, activity_last_event_at,
                acquisition_status, position_recommendation, baseline_complete
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb,
                      $18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,$37,$38,$39,$40,$41,$42)
        """, [
            (
                audit_id, snapshot_id, address, row["condition_id"], row["outcome"],
                row["classification"], row["comparison_quality"], row["db_total_bought"], row["db_avg_buy_price"],
                row["db_cost_basis"], row["db_realized_pnl"], row["activity_buy_shares"],
                row["activity_buy_usdc"], row["activity_avg_buy_price"], row["shares_delta"],
                row["cost_basis_delta"], json.dumps(row["activity_outcomes"]),
                row["lineage_transfer_in_shares"], row["lineage_transfer_in_count"], row["lineage_first_transfer_at"],
                row["activity_sell_shares"], row["activity_sell_usdc"], row["activity_avg_sell_price"],
                row["activity_redeem_shares"], row["activity_redeem_usdc"],
                row["activity_split_shares"], row["activity_split_usdc"],
                row["activity_merge_shares"], row["activity_merge_usdc"],
                row["activity_conversion_shares"], row["activity_conversion_usdc"],
                row["activity_reward_usdc"], row["activity_rebate_usdc"], row["activity_yield_usdc"],
                row["activity_net_shares"], row["activity_event_count"], row["activity_distinct_event_count"],
                row["activity_first_event_at"], row["activity_last_event_at"],
                row["acquisition_status"], row["position_recommendation"], row["baseline_complete"],
            ) for row in reconciliations
        ])
        await conn.executemany("""
            INSERT INTO wallet_activity_only_markets_v2 (
                audit_id, snapshot_id, address, condition_id, event_count, outcomes,
                has_open_position, activity_status, net_shares, buy_cost,
                average_buy_price, current_position_verified, is_redeemable,
                canonical_position_created, last_checked_at
            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13,$14,NOW())
        """, [
            (audit_id, snapshot_id, address, row["condition_id"], row["event_count"],
             json.dumps(row["outcomes"]), row["has_open_position"], row["activity_status"],
             row["net_shares"], row["buy_cost"], row["average_buy_price"],
             row["current_position_verified"], row["is_redeemable"], False)
            for row in activity_only_markets
        ])
        # Keep raw provenance for only contradictory/lifecycle markets.  The
        # hot Activity table is bounded below; exception evidence is retained
        # in its own deduplicated table for later review/archive.
        exception_pairs = {
            (row["condition_id"], row["outcome"]): row["comparison_quality"]
            for row in reconciliations
            if row["comparison_quality"] != "exact_activity_buy"
        }
        exception_events = []
        for event in activity:
            cid = str(event.get("conditionId") or "")
            if not cid:
                continue
            matching = [quality for (pair_cid, _), quality in exception_pairs.items() if pair_cid == cid]
            if not matching:
                continue
            outcome = str(event.get("outcome") or "")
            quality = next((q for (pair_cid, pair_outcome), q in exception_pairs.items()
                            if pair_cid == cid and pair_outcome.lower() == outcome.lower()), matching[0])
            exception_events.append((
                address, cid, event.get("asset"), event.get("outcome"), event.get("type"),
                event.get("side"), _number(event.get("timestamp")) or None,
                _number(event.get("size")), _number(event.get("usdcSize")),
                _number(event.get("price")), event.get("transactionHash"),
                _activity_event_digest(event), snapshot_id, quality, json.dumps(event),
            ))
        if exception_events:
            await conn.executemany("""
                INSERT INTO wallet_activity_exception_events_v2 (
                    address, condition_id, asset, outcome, event_type, side,
                    event_timestamp, size, usdc_size, price, transaction_hash,
                    event_sha256, snapshot_id, classification, payload
                ) VALUES ($1,$2,$3,$4,$5,$6,to_timestamp($7),$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
                ON CONFLICT (address, event_sha256) DO NOTHING
            """, exception_events)
        # Raw events are a hot cache.  Aggregates and exception evidence above
        # remain available after this bounded retention pass.
        await conn.execute("""
            DELETE FROM wallet_activity_events_v2
            WHERE address = $1 AND id NOT IN (
                SELECT id FROM (
                    SELECT DISTINCT ON (event_sha256)
                        id, event_timestamp
                    FROM wallet_activity_events_v2
                    WHERE address = $1
                    ORDER BY event_sha256, event_timestamp DESC NULLS LAST, id DESC
                ) distinct_events
                ORDER BY event_timestamp DESC NULLS LAST, id DESC
                LIMIT 500
            )
        """, address)
        latest = max(activity, key=lambda e: (_number(e.get("timestamp")), _activity_event_digest(e)), default=None)
        await conn.execute("""
            INSERT INTO wallet_activity_scan_state_v2 (
                address, baseline_complete, baseline_start_at, baseline_end_at,
                last_confirmed_timestamp, last_confirmed_event_hash,
                last_scan_at, last_audit_id, last_error, updated_at
            ) VALUES ($1, TRUE, $2, $3, $4, $5, NOW(), $6, NULL, NOW())
            ON CONFLICT (address) DO UPDATE SET
                baseline_complete = TRUE,
                baseline_start_at = COALESCE(wallet_activity_scan_state_v2.baseline_start_at, EXCLUDED.baseline_start_at),
                baseline_end_at = EXCLUDED.baseline_end_at,
                last_confirmed_timestamp = COALESCE(EXCLUDED.last_confirmed_timestamp, wallet_activity_scan_state_v2.last_confirmed_timestamp),
                last_confirmed_event_hash = COALESCE(EXCLUDED.last_confirmed_event_hash, wallet_activity_scan_state_v2.last_confirmed_event_hash),
                last_scan_at = NOW(), last_audit_id = EXCLUDED.last_audit_id,
                pending_snapshot_id = NULL, last_error = NULL, updated_at = NOW()
        """, address, datetime.fromisoformat(report["activity_window"]["start"]),
            datetime.fromisoformat(report["activity_window"]["end"]),
            datetime.fromtimestamp(_number(latest.get("timestamp")), timezone.utc) if latest else None,
            _activity_event_digest(latest) if latest else None, audit_id)
        if archive_info:
            archive_min = datetime.fromtimestamp(archive_info["minimum_timestamp"], timezone.utc) if archive_info["minimum_timestamp"] else None
            archive_max = datetime.fromtimestamp(archive_info["maximum_timestamp"], timezone.utc) if archive_info["maximum_timestamp"] else None
            await conn.execute("""
                INSERT INTO wallet_activity_archives_v2 (
                    address, file_path, sha256, row_count, minimum_timestamp,
                    maximum_timestamp, schema_version, compression, baseline_complete, verified_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            """, address, archive_info["file_path"], archive_info["sha256"], archive_info["row_count"],
                archive_min, archive_max, archive_info["schema_version"], archive_info["compression"],
                bool(report["activity_window"].get("incremental") is False))
        if canonical_markets:
            await conn.execute("""
                UPDATE wallet_activity_only_markets_v2
                SET activity_status='canonical_position_found',
                    current_position_verified=TRUE,
                    canonical_position_created=TRUE,
                    last_checked_at=NOW()
                WHERE address=$1 AND condition_id = ANY($2::text[])
                  AND NOT (condition_id = ANY($3::text[]))
            """, address, list(canonical_markets), [row["condition_id"] for row in activity_only_markets])
    return str(audit_id)


async def audit(address: str, start: int, end: int, persist: bool = False) -> dict:
    requested_start = start
    if persist and start <= 1:
        state_conn = await asyncpg.connect(DB_URL)
        try:
            state = await state_conn.fetchrow(
                "SELECT baseline_complete, last_confirmed_timestamp FROM wallet_activity_scan_state_v2 WHERE address=$1",
                address,
            )
        finally:
            await state_conn.close()
        # Incremental scans overlap the last day to catch late/reordered events.
        if state and state["baseline_complete"] and state["last_confirmed_timestamp"]:
            start = max(1, int(state["last_confirmed_timestamp"].timestamp()) - 86400)
    activity = await fetch_complete_activity(address, start, end)
    conn = await asyncpg.connect(DB_URL)
    try:
        positions = await conn.fetch("""
            SELECT condition_id, outcome, total_bought, avg_buy_price, realized_pnl,
                   closed_at, is_redeemable, data_quality_flag, source_asset
            FROM wallet_closed_positions_v2
            WHERE address = $1
        """, address)
        open_position_rows = await conn.fetch("""
            SELECT DISTINCT condition_id, COALESCE(is_resolved, FALSE) AS is_resolved
            FROM wallet_positions_v2 WHERE address = $1
        """, address)
        open_position_markets = {row["condition_id"] for row in open_position_rows}
        redeemable_markets = {row["condition_id"] for row in open_position_rows if row["is_resolved"]}
        # A P2P transfer is position-grain evidence only when the exact CTF
        # token ID matches the source asset of this stored row.  Wallet-level
        # funding is intentionally not loaded here: cash funding never proves
        # acquisition of a particular market outcome.
        transfer_rows = await conn.fetch("""
            SELECT token_id, amount, tx_hash, transferred_at
            FROM wallet_position_transfers_v2
            WHERE to_address = $1
        """, address)
    finally:
        await conn.close()

    activity_by_leg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    activity_by_market: dict[str, list[dict]] = defaultdict(list)
    for event in activity:
        condition_id = str(event.get("conditionId") or "")
        outcome = str(event.get("outcome") or "")
        if condition_id:
            activity_by_market[condition_id].append(event)
            activity_by_leg[(condition_id, outcome)].append(event)

    rows_by_market: dict[str, list[asyncpg.Record]] = defaultdict(list)
    for position in positions:
        rows_by_market[position["condition_id"]].append(position)

    matched = missing_leg = market_only = nontrade_only = 0
    matched_pnl = missing_pnl = market_only_pnl = nontrade_only_pnl = 0.0
    buy_basis_delta = 0.0
    examples: list[dict] = []
    decisions: list[dict] = []
    reconciliations: list[dict] = []
    for position in positions:
        condition_id, outcome = position["condition_id"], position["outcome"]
        pnl = _number(position["realized_pnl"])
        events = [
            event for event in activity_by_market.get(condition_id, [])
            if normalize_outcome(event.get("outcome")) == normalize_outcome(outcome)
        ]
        market_events = activity_by_market.get(condition_id, [])
        buy_shares, buy_usdc, activity_avg_price = _activity_buy_summary(events)
        buys = [event for event in events if str(event.get("type") or "").upper() == "TRADE" and str(event.get("side") or "").upper() == "BUY"]
        decision = classify_row(position, rows_by_market[condition_id], market_events)
        evidence_event = buys[0] if buys else (events[0] if events else None)
        if decision.status == "eligible" and buys:
            classification = "direct_activity_buy"
        elif decision.status == "eligible":
            classification = "activity_same_leg_nontrade"
        elif market_events:
            classification = "activity_outcome_differs"
        else:
            classification = "activity_absent"
        db_total_bought = _number(position["total_bought"])
        db_avg_buy_price = _number(position["avg_buy_price"])
        db_cost_basis = db_total_bought * db_avg_buy_price
        if classification == "direct_activity_buy":
            comparison_quality = (
                "exact_activity_buy"
                if abs(db_total_bought - buy_shares) < 0.001 and abs(db_cost_basis - buy_usdc) < 0.01
                else "activity_buy_values_differ"
            )
        elif classification == "activity_same_leg_nontrade":
            comparison_quality = "nontrade_no_buy"
        elif classification == "activity_outcome_differs":
            comparison_quality = "outcome_mismatch"
        else:
            comparison_quality = "activity_absent"
        decisions.append({
            "condition_id": condition_id, "outcome": outcome, "status": decision.status,
            "reason": classification, "evidence_event": evidence_event,
        })
        lifecycle_events = events if events else market_events
        lifecycle = _activity_lifecycle_summary(lifecycle_events)
        reconciliations.append({
            "condition_id": condition_id, "outcome": outcome, "classification": classification,
            "comparison_quality": comparison_quality,
            "db_total_bought": db_total_bought, "db_avg_buy_price": db_avg_buy_price,
            "db_cost_basis": db_cost_basis, "db_realized_pnl": pnl,
            "activity_buy_shares": buy_shares if buys else None,
            "activity_buy_usdc": buy_usdc if buys else None,
            "activity_avg_buy_price": activity_avg_price,
            "shares_delta": (db_total_bought - buy_shares) if buys else None,
            "cost_basis_delta": (db_cost_basis - buy_usdc) if buys else None,
            "activity_outcomes": sorted({str(event.get("outcome") or "") for event in market_events}),
            **lifecycle,
            "acquisition_status": "verified_buy" if buys else "unknown",
            "position_recommendation": "eligible" if buys else "review_required",
            "baseline_complete": True,
        })
        if decision.status == "eligible" and buys:
            matched += 1
            matched_pnl += pnl
            buy_basis_delta += abs(_number(position["total_bought"]) - sum(_number(e.get("size")) for e in buys))
            continue
        if decision.status == "eligible":
            nontrade_only += 1
            nontrade_only_pnl += pnl
            bucket = "same_leg_nontrade"
        elif market_events:
            market_only += 1
            market_only_pnl += pnl
            bucket = "same_market_other_outcome"
        else:
            missing_leg += 1
            missing_pnl += pnl
            bucket = "absent_from_activity"
        if len(examples) < 100:
            examples.append({
                "bucket": bucket, "condition_id": condition_id, "outcome": outcome,
                "realized_pnl": pnl, "total_bought": _number(position["total_bought"]),
                "closed_at": position["closed_at"].isoformat() if position["closed_at"] else None,
                "is_redeemable": bool(position["is_redeemable"]),
                "quality_flag": position["data_quality_flag"],
            })

    report = {
        "address": address,
        "activity_window": {
            "start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end, timezone.utc).isoformat(),
            "requested_start": datetime.fromtimestamp(requested_start, timezone.utc).isoformat(),
            "incremental": start != requested_start,
        },
        "activity": {
            "events": len(activity), "markets": len(activity_by_market),
            "legs": len(activity_by_leg),
            "types": dict(sorted((kind, sum(1 for e in activity if e.get("type") == kind)) for kind in {e.get("type") for e in activity})),
        },
        "positions": {
            "rows": len(positions), "markets": len({p["condition_id"] for p in positions}),
            "matched_buy_leg_rows": matched, "matched_buy_leg_pnl": matched_pnl,
            "same_leg_nontrade_rows": nontrade_only, "same_leg_nontrade_pnl": nontrade_only_pnl,
            "same_market_other_outcome_rows": market_only, "same_market_other_outcome_pnl": market_only_pnl,
            "absent_from_activity_rows": missing_leg, "absent_from_activity_pnl": missing_pnl,
            "sum_abs_buy_quantity_delta": buy_basis_delta,
        },
        "activity_only_markets": {
            "not_in_closed_positions": len(set(activity_by_market) - set(rows_by_market)),
            "represented_by_open_position": len((set(activity_by_market) - set(rows_by_market)) & open_position_markets),
            "absent_from_both_position_tables": len((set(activity_by_market) - set(rows_by_market)) - open_position_markets),
            "condition_ids": sorted(set(activity_by_market) - set(rows_by_market)),
        },
        "examples": examples,
    }
    if persist:
        conn = await asyncpg.connect(DB_URL)
        try:
            activity_only_markets = [
                {
                    "condition_id": condition_id,
                    "event_count": len(activity_by_market[condition_id]),
                    "outcomes": sorted({str(event.get("outcome") or "") for event in activity_by_market[condition_id]}),
                    "has_open_position": condition_id in open_position_markets,
                    "activity_status": (
                        "redeemable_confirmed" if condition_id in redeemable_markets
                        else "open_confirmed" if condition_id in open_position_markets
                        else "provisional_open" if _activity_lifecycle_summary(activity_by_market[condition_id])["activity_net_shares"] > 0.001
                        else "lifecycle_only"
                    ),
                    "net_shares": _activity_lifecycle_summary(activity_by_market[condition_id])["activity_net_shares"],
                    "buy_cost": _activity_lifecycle_summary(activity_by_market[condition_id])["activity_buy_usdc"],
                    "average_buy_price": (
                        _activity_lifecycle_summary(activity_by_market[condition_id])["activity_buy_usdc"]
                        / _activity_lifecycle_summary(activity_by_market[condition_id])["activity_buy_shares"]
                        if _activity_lifecycle_summary(activity_by_market[condition_id])["activity_buy_shares"] else None
                    ),
                    "current_position_verified": condition_id in open_position_markets,
                    "is_redeemable": condition_id in redeemable_markets,
                }
                for condition_id in sorted(set(activity_by_market) - set(rows_by_market))
            ]
            report["audit_id"] = await _persist_audit(
                conn, address, activity, decisions, reconciliations, activity_only_markets, report,
                set(rows_by_market) | open_position_markets,
                redeemable_markets,
            )
        finally:
            await conn.close()
    return report


async def backfill_activity(address: str, start: int, end: int, persist: bool = False) -> dict:
    """Fetch complete activity from API and store raw events.

    This is the slow part: recursive bisection to avoid the 5000 offset cap.
    Stores a complete pending snapshot in wallet_activity_events_v2 and updates
    scan state. The snapshot is deliberately not pruned here: Worker 4 must
    compare the full source before retaining only the 500-event hot cache.
    """
    requested_start = start
    if persist and start <= 1:
        state_conn = await asyncpg.connect(DB_URL)
        try:
            state = await state_conn.fetchrow(
                "SELECT baseline_complete, last_confirmed_timestamp FROM wallet_activity_scan_state_v2 WHERE address=$1",
                address,
            )
        finally:
            await state_conn.close()
        if state and state["baseline_complete"] and state["last_confirmed_timestamp"]:
            start = max(1, int(state["last_confirmed_timestamp"].timestamp()) - 86400)
    activity = await fetch_complete_activity(address, start, end)
    report = {
        "address": address,
        "activity_window": {
            "start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end, timezone.utc).isoformat(),
            "requested_start": datetime.fromtimestamp(requested_start, timezone.utc).isoformat(),
            "incremental": start != requested_start,
        },
        "activity": {
            "events": len(activity),
            "markets": len({e.get("conditionId") for e in activity if e.get("conditionId")}),
            "legs": len({(e.get("conditionId"), e.get("outcome")) for e in activity if e.get("conditionId")}),
        },
    }
    if not persist:
        return report
    activity_digest = hashlib.sha256(
        json.dumps([_activity_key(row) for row in activity], sort_keys=True, default=str).encode()
    ).hexdigest()
    archive_info = None
    divergence_conn = await asyncpg.connect(DB_URL)
    try:
        divergence = await divergence_conn.fetchrow(
            "SELECT total_pnl, pm_pnl FROM wallet_metrics_v2 WHERE address=$1", address
        )
    finally:
        await divergence_conn.close()
    if divergence and divergence["total_pnl"] is not None and divergence["pm_pnl"] is not None:
        if abs(float(divergence["total_pnl"]) - float(divergence["pm_pnl"])) >= 100000:
            try:
                archive_info = archive_events(
                    activity, address, os.getenv("ACTIVITY_ARCHIVE_DIR", "backtest_cache/activity_archives")
                )
            except RuntimeError as exc:
                logger.error("Activity archive unavailable for %s: %s", address, exc)
    conn = await asyncpg.connect(DB_URL)
    try:
        async with conn.transaction():
            snapshot_id = await conn.fetchval("""
                INSERT INTO wallet_source_snapshots_v2 (address, source, complete, payload_sha256, metadata)
                VALUES ($1, 'activity', TRUE, $2, $3::jsonb)
                RETURNING id
            """, address, activity_digest, json.dumps(report["activity"]))
            await conn.executemany("""
                INSERT INTO wallet_activity_events_v2 (
                    snapshot_id, address, event_sha256, condition_id, asset, outcome,
                    event_type, side, event_timestamp, size, usdc_size, price,
                    transaction_hash, payload
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,to_timestamp($9),$10,$11,$12,$13,$14::jsonb
                ) ON CONFLICT (snapshot_id, event_sha256) DO NOTHING
            """, [
                (
                    snapshot_id, address, _activity_event_digest(event), event.get("conditionId"),
                    event.get("asset"), event.get("outcome"), event.get("type"), event.get("side"),
                    _number(event.get("timestamp")) or None, _number(event.get("size")),
                    _number(event.get("usdcSize")), _number(event.get("price")),
                    event.get("transactionHash"), json.dumps(event),
                ) for event in activity
            ])
            # Update scan state watermark.
            latest = max(activity, key=lambda e: (_number(e.get("timestamp")), _activity_event_digest(e)), default=None)
            await conn.execute("""
                INSERT INTO wallet_activity_scan_state_v2 (
                    address, baseline_complete, baseline_start_at, baseline_end_at,
                    last_confirmed_timestamp, last_confirmed_event_hash,
                    last_scan_at, last_audit_id, last_error, pending_snapshot_id, updated_at
                ) VALUES ($1, FALSE, $2, $3, $4, $5, NOW(), NULL, NULL, $6, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    baseline_complete = FALSE,
                    baseline_start_at = COALESCE(wallet_activity_scan_state_v2.baseline_start_at, EXCLUDED.baseline_start_at),
                    baseline_end_at = EXCLUDED.baseline_end_at,
                    last_confirmed_timestamp = COALESCE(EXCLUDED.last_confirmed_timestamp, wallet_activity_scan_state_v2.last_confirmed_timestamp),
                    last_confirmed_event_hash = COALESCE(EXCLUDED.last_confirmed_event_hash, wallet_activity_scan_state_v2.last_confirmed_event_hash),
                    last_scan_at = NOW(), last_error = NULL,
                    pending_snapshot_id = EXCLUDED.pending_snapshot_id, updated_at = NOW()
            """, address, datetime.fromisoformat(report["activity_window"]["start"]),
                datetime.fromisoformat(report["activity_window"]["end"]),
                datetime.fromtimestamp(_number(latest.get("timestamp")), timezone.utc) if latest else None,
                _activity_event_digest(latest) if latest else None, snapshot_id)
            if archive_info:
                archive_min = datetime.fromtimestamp(archive_info["minimum_timestamp"], timezone.utc) if archive_info["minimum_timestamp"] else None
                archive_max = datetime.fromtimestamp(archive_info["maximum_timestamp"], timezone.utc) if archive_info["maximum_timestamp"] else None
                await conn.execute("""
                    INSERT INTO wallet_activity_archives_v2 (
                        address, file_path, sha256, row_count, minimum_timestamp,
                        maximum_timestamp, schema_version, compression, baseline_complete, verified_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
                """, address, archive_info["file_path"], archive_info["sha256"], archive_info["row_count"],
                    archive_min, archive_max, archive_info["schema_version"], archive_info["compression"],
                    not report["activity_window"]["incremental"])
    finally:
        await conn.close()
    return report


async def analyze_activity(address: str, persist: bool = False) -> dict:
    """Read stored activity events and reconcile against positions.

    This is the fast part: reads from wallet_activity_events_v2 (already
    stored by backfill_activity), compares to positions, and persists
    audit decisions and reconciliation rows.
    """
    conn = await asyncpg.connect(DB_URL)
    try:
        state = await conn.fetchrow("""
            SELECT pending_snapshot_id, baseline_start_at, baseline_end_at
            FROM wallet_activity_scan_state_v2 WHERE address=$1
        """, address)
        if not state or not state["pending_snapshot_id"]:
            return {
                "address": address, "activity_events": 0, "positions": 0,
                "status": "no_pending_snapshot",
            }
        snapshot_id = state["pending_snapshot_id"]
        # Read exactly the complete source snapshot staged by Worker 3. Old
        # hot-cache rows and prior snapshots must not enter this audit.
        event_rows = await conn.fetch("""
            SELECT condition_id, asset, outcome, event_type, side,
                   event_timestamp, size, usdc_size, price, transaction_hash, payload
            FROM wallet_activity_events_v2
            WHERE address = $1 AND snapshot_id = $2
            ORDER BY event_timestamp ASC NULLS LAST
        """, address, snapshot_id)
        # Restore the source API field shape. The reconciliation helpers use
        # conditionId/type/usdcSize/transactionHash, not the DB column names.
        activity = [_restore_activity_event(row) for row in event_rows]
        # Load positions.
        positions = await conn.fetch("""
            SELECT condition_id, outcome, total_bought, avg_buy_price, realized_pnl,
                   closed_at, is_redeemable, data_quality_flag, source_asset
            FROM wallet_closed_positions_v2
            WHERE address = $1
        """, address)
        open_position_rows = await conn.fetch("""
            SELECT DISTINCT condition_id, COALESCE(is_resolved, FALSE) AS is_resolved
            FROM wallet_positions_v2 WHERE address = $1
        """, address)
        open_position_markets = {row["condition_id"] for row in open_position_rows}
        redeemable_markets = {row["condition_id"] for row in open_position_rows if row["is_resolved"]}
        transfer_rows = await conn.fetch("""
            SELECT token_id, amount, tx_hash, transferred_at
            FROM wallet_position_transfers_v2
            WHERE to_address = $1
        """, address)
    finally:
        await conn.close()

    # Index activity by (condition_id, outcome) and by condition_id.
    activity_by_leg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    activity_by_market: dict[str, list[dict]] = defaultdict(list)
    for event in activity:
        condition_id = str(event.get("condition_id") or event.get("conditionId") or "")
        outcome = str(event.get("outcome") or "")
        if condition_id:
            activity_by_market[condition_id].append(event)
            activity_by_leg[(condition_id, outcome)].append(event)

    rows_by_market: dict[str, list] = defaultdict(list)
    for position in positions:
        rows_by_market[position["condition_id"]].append(position)
    transfers_by_token: dict[str, list] = defaultdict(list)
    for transfer in transfer_rows:
        transfers_by_token[str(transfer["token_id"])].append(transfer)

    matched = missing_leg = market_only = nontrade_only = 0
    matched_pnl = missing_pnl = market_only_pnl = nontrade_only_pnl = 0.0
    buy_basis_delta = 0.0
    lineage_supported = 0
    lineage_supported_pnl = 0.0
    examples: list[dict] = []
    decisions: list[dict] = []
    reconciliations: list[dict] = []
    for position in positions:
        condition_id, outcome = position["condition_id"], position["outcome"]
        pnl = _number(position["realized_pnl"])
        events = [
            event for event in activity_by_market.get(condition_id, [])
            if normalize_outcome(event.get("outcome")) == normalize_outcome(outcome)
        ]
        market_events = activity_by_market.get(condition_id, [])
        lineage_transfers = transfers_by_token.get(str(position["source_asset"] or ""), [])
        lineage_shares = sum(_number(transfer["amount"]) for transfer in lineage_transfers)
        buy_shares, buy_usdc, activity_avg_price = _activity_buy_summary(events)
        buys = [event for event in events if str(event.get("event_type") or event.get("type") or "").upper() == "TRADE" and str(event.get("side") or "").upper() == "BUY"]
        decision = classify_row(position, rows_by_market[condition_id], market_events)
        evidence_event = buys[0] if buys else (events[0] if events else None)
        if decision.status == "eligible" and buys:
            classification = "direct_activity_buy"
        elif decision.status == "eligible":
            classification = "activity_same_leg_nontrade"
        elif market_events:
            classification = "activity_outcome_differs"
        else:
            classification = "activity_absent"
        db_total_bought = _number(position["total_bought"])
        db_avg_buy_price = _number(position["avg_buy_price"])
        db_cost_basis = db_total_bought * db_avg_buy_price
        if classification == "direct_activity_buy":
            comparison_quality = (
                "exact_activity_buy"
                if abs(db_total_bought - buy_shares) < 0.001 and abs(db_cost_basis - buy_usdc) < 0.01
                else "activity_buy_values_differ"
            )
        elif classification == "activity_same_leg_nontrade":
            comparison_quality = "nontrade_no_buy"
        elif classification == "activity_outcome_differs":
            comparison_quality = "outcome_mismatch"
        else:
            comparison_quality = "activity_absent"
        lineage_supported_row = not buys and bool(lineage_transfers)
        if lineage_supported_row:
            # Do not reclassify the Activity comparison itself: Activity is
            # still absent/non-trade.  Record the independently proven share
            # origin instead, without asserting a cost basis.
            comparison_quality = "lineage_transfer_in"
            lineage_supported += 1
            lineage_supported_pnl += pnl
        decisions.append({
            "condition_id": condition_id, "outcome": outcome, "status": decision.status,
            "reason": classification, "evidence_event": evidence_event,
            "lineage_transfer": lineage_transfers[0] if lineage_transfers else None,
        })
        lifecycle_events = events if events else market_events
        lifecycle = _activity_lifecycle_summary(lifecycle_events)
        reconciliations.append({
            "condition_id": condition_id, "outcome": outcome, "classification": classification,
            "comparison_quality": comparison_quality,
            "db_total_bought": db_total_bought, "db_avg_buy_price": db_avg_buy_price,
            "db_cost_basis": db_cost_basis, "db_realized_pnl": pnl,
            "activity_buy_shares": buy_shares if buys else None,
            "activity_buy_usdc": buy_usdc if buys else None,
            "activity_avg_buy_price": activity_avg_price,
            "shares_delta": (db_total_bought - buy_shares) if buys else None,
            "cost_basis_delta": (db_cost_basis - buy_usdc) if buys else None,
            "activity_outcomes": sorted({str(event.get("outcome") or "") for event in market_events}),
            "lineage_transfer_in_shares": lineage_shares,
            "lineage_transfer_in_count": len(lineage_transfers),
            "lineage_first_transfer_at": min((transfer["transferred_at"] for transfer in lineage_transfers), default=None),
            **lifecycle,
            "acquisition_status": (
                "verified_buy" if buys else "verified_transfer_in" if lineage_transfers else "unknown"
            ),
            "position_recommendation": "eligible" if buys else "review_required",
            "baseline_complete": True,
        })
        if decision.status == "eligible" and buys:
            matched += 1
            matched_pnl += pnl
            buy_basis_delta += abs(_number(position["total_bought"]) - sum(_number(e.get("size")) for e in buys))
            continue
        if decision.status == "eligible":
            nontrade_only += 1
            nontrade_only_pnl += pnl
        elif market_events:
            market_only += 1
            market_only_pnl += pnl
        else:
            missing_leg += 1
            missing_pnl += pnl
        if len(examples) < 100:
            examples.append({
                "condition_id": condition_id, "outcome": outcome,
                "realized_pnl": pnl, "total_bought": _number(position["total_bought"]),
                "closed_at": position["closed_at"].isoformat() if position["closed_at"] else None,
                "is_redeemable": bool(position["is_redeemable"]),
                "quality_flag": position["data_quality_flag"],
            })

    report = {
        "address": address,
        "activity_events": len(activity),
        "positions": len(positions),
        "matched_buy_leg_rows": matched, "matched_buy_leg_pnl": matched_pnl,
        "same_leg_nontrade_rows": nontrade_only, "same_leg_nontrade_pnl": nontrade_only_pnl,
        "same_market_other_outcome_rows": market_only, "same_market_other_outcome_pnl": market_only_pnl,
        "absent_from_activity_rows": missing_leg, "absent_from_activity_pnl": missing_pnl,
        "lineage_transfer_supported_rows": lineage_supported,
        "lineage_transfer_supported_pnl": lineage_supported_pnl,
        "examples": examples,
    }

    if persist:
        conn = await asyncpg.connect(DB_URL)
        try:
            activity_only_markets = [
                {
                    "condition_id": cid,
                    "event_count": len(activity_by_market[cid]),
                    "outcomes": sorted({str(e.get("outcome") or e.get("outcome") or "") for e in activity_by_market[cid]}),
                    "has_open_position": cid in open_position_markets,
                    "activity_status": (
                        "redeemable_confirmed" if cid in redeemable_markets
                        else "open_confirmed" if cid in open_position_markets
                        else "provisional_open" if _activity_lifecycle_summary(activity_by_market[cid])["activity_net_shares"] > 0.001
                        else "lifecycle_only"
                    ),
                    "net_shares": _activity_lifecycle_summary(activity_by_market[cid])["activity_net_shares"],
                    "buy_cost": _activity_lifecycle_summary(activity_by_market[cid])["activity_buy_usdc"],
                    "average_buy_price": (
                        _activity_lifecycle_summary(activity_by_market[cid])["activity_buy_usdc"]
                        / _activity_lifecycle_summary(activity_by_market[cid])["activity_buy_shares"]
                        if _activity_lifecycle_summary(activity_by_market[cid])["activity_buy_shares"] else None
                    ),
                    "current_position_verified": cid in open_position_markets,
                    "is_redeemable": cid in redeemable_markets,
                }
                for cid in sorted(set(activity_by_market) - set(rows_by_market))
            ]
            # Persist audit decisions, evidence, reconciliations, exception events.
            activity_window = {
                "start": (
                    state["baseline_start_at"].isoformat()
                    if state["baseline_start_at"]
                    else datetime.fromtimestamp(1, timezone.utc).isoformat()
                ),
                "end": (
                    state["baseline_end_at"].isoformat()
                    if state["baseline_end_at"]
                    else datetime.now(timezone.utc).isoformat()
                ),
                "incremental": bool(
                    state["baseline_start_at"] and state["baseline_start_at"].timestamp() > 1
                ),
            }
            await _persist_audit(
                conn, address, activity, decisions, reconciliations, activity_only_markets,
                {"activity": report, "activity_window": activity_window},
                set(rows_by_market) | open_position_markets, redeemable_markets,
                source_snapshot_id=snapshot_id,
            )
        finally:
            await conn.close()
    return report


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("--start", type=int, default=1, help="Epoch seconds; 1 requests full activity history")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persist", action="store_true", help="Store immutable audit proof and conservative decisions")
    args = parser.parse_args()
    report = await audit(args.address.lower(), args.start, int(time.time()), persist=args.persist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["activity"], indent=2))
    print(json.dumps(report["positions"], indent=2))
    print(f"report={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
