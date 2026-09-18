"""
Wallet Trade History Worker

Vets UNCLASSIFIED wallets_v2 rows (the v2 discovery queue, fed by
trade_tracker / deposit_tracker / manual adds) and assigns a tier:
  - Balance = 0                     → DEAD
  - 0 < balance < $1k               → LOW_BALANCE
  - Balance ≥ $1k, never traded     → NEW
  - Balance ≥ $1k, stale > 30d      → STANDARD + is_dormant
  - Balance ≥ $1k, recent trade     → STANDARD (global list)

Assigning the tier is what removes a wallet from the queue.
Runs on a schedule (every 60s recommended).
"""

import asyncio
import asyncpg
import aiohttp
import csv
import io
import os
import logging
import zipfile
from collections import deque
from typing import Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from src.utils.category_classifier import classify_tags, flatten_subcategory
from src.utils.polymarket_rate_limit import PostgresRateLimiter

load_dotenv()

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

BATCH_SIZE = 100       # wallets to process per run


def _parse(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def canonical_source(queue_source: str) -> str:
    """Map queue source strings ('trade_tracker', 'deposit_tracker',
    'Manual Queue', ...) to the canonical wallet_sources_v2 values."""
    s = (queue_source or "").lower()
    if "deposit" in s:
        return "deposit"
    if "trade" in s or "whale" in s:
        return "trade"
    if "leaderboard" in s:
        return "leaderboard"
    return "manual"


def aggregate_redeem_events(events: list[dict]) -> list[dict]:
    """Collapse multi-row redemptions sharing a transactionHash by summing usdcSize."""
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for ev in events:
        tx = str(ev.get("transactionHash") or "")
        if tx not in grouped:
            grouped[tx] = dict(ev)
            order.append(tx)
        else:
            try:
                grouped[tx]["usdcSize"] = str(
                    float(grouped[tx].get("usdcSize") or 0)
                    + float(ev.get("usdcSize") or 0)
                )
            except (TypeError, ValueError):
                pass
    return [grouped[tx] for tx in order]


def aggregate_redeem_events_with_raw(
    events: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Return (aggregated_for_cash, raw_for_provenance).
    Never use the aggregated list for per-outcome position tracking.
    """
    return aggregate_redeem_events(events), list(events)


async def fetch_combo_activity(
    session: aiohttp.ClientSession,
    address: str,
    min_ts: Optional[int] = None,
    max_pages: int = 1,
    rate_limiter: Optional[PostgresRateLimiter] = None,
) -> tuple[list[dict], list[dict]]:
    """Fetch open and closed combo parlay positions from Polymarket activity API with
    optional incremental timestamp filtering. Pages over the activity feed up to
    max_pages x 500 events (backfill callers use the default single page)."""
    open_combos = []
    closed_combos = []
    buy_events: dict[str, dict] = {}
    redeem_events_list: list[dict] = []
    offset = 0

    for _page in range(max_pages):
        ts_filter = f"&startTs={min_ts}" if min_ts else ""
        url = f"https://data-api.polymarket.com/activity?user={address}&limit=500&offset={offset}{ts_filter}"
        try:
            if rate_limiter:
                await rate_limiter.acquire("activity")
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not isinstance(data, list) or not data:
                    break

                for a in data:
                    cid = a.get("conditionId") or ""
                    if not cid:
                        continue
                    title = a.get("title") or ""
                    is_combo = a.get("isCombo") is True or "COMBO" in title.upper() or "PARLAY" in title.upper()
                    if not is_combo:
                        continue

                    ev_type = (a.get("type") or "").upper()
                    ev_ts = a.get("timestamp")
                    if ev_type in ("TRADE", "BUY"):
                        usdc_size = _parse(a.get("usdcSize"))
                        token_size = _parse(a.get("size"))
                        price = _parse(a.get("price"))
                        if cid not in buy_events:
                            buy_events[cid] = {
                                "title": title,
                                "asset": a.get("asset", ""),
                                "total_usdc": usdc_size,
                                "total_size": token_size,
                                "last_price": price,
                                "first_ts": ev_ts,
                            }
                        else:
                            buy_events[cid]["total_usdc"] += usdc_size
                            buy_events[cid]["total_size"] += token_size
                            # feed is newest-first: keep the earliest ts seen
                            if ev_ts and (not buy_events[cid].get("first_ts") or ev_ts < buy_events[cid]["first_ts"]):
                                buy_events[cid]["first_ts"] = ev_ts
                            if price > 0:
                                buy_events[cid]["last_price"] = price
                    elif ev_type in ("REDEEM", "REDEMPTION"):
                        redeem_events_list.append(a)

                if len(data) < 500:
                    break
                offset += 500
        except Exception as e:
            logger.debug(f"Combo activity fetch error for {address}: {e}")
            break

    # 1. Process closed/redeemed combos
    # NOTE: feed is newest-first; buy_events accumulate ALL buys per combo, so
    # the true average entry cost is total_usdc / total_size (volume-weighted),
    # NOT the most recent top-up price.

    # Aggregate REDEEM events by transactionHash to handle multi-row redemptions.
    # `aggregated_redeem_events` is the transaction-level cash view; the raw
    # per-outcome rows are kept for position-level provenance (share sizes).
    aggregated_redeem_events, raw_redeem_events = aggregate_redeem_events_with_raw(redeem_events_list)

    # Provenance: per-transactionHash sum of share sizes across the raw
    # per-outcome rows. Aggregation only sums usdcSize, so relying on the
    # first row's partial `size` would understate redeemed shares.
    raw_size_by_tx: dict[str, float] = {}
    for red in raw_redeem_events:
        tx = str(red.get("transactionHash") or "")
        try:
            raw_size_by_tx[tx] = raw_size_by_tx.get(tx, 0.0) + float(red.get("size") or 0)
        except (TypeError, ValueError):
            pass

    # Build a dict keyed by conditionId for processing
    redeem_events: dict[str, dict] = {}
    for red in aggregated_redeem_events:
        cid = red.get("conditionId") or ""
        if cid and cid not in redeem_events:
            redeem_events[cid] = red

    for cid, red in redeem_events.items():
        buy = buy_events.get(cid, {})
        title = buy.get("title") or red.get("title", "")

        if title:
            raw_c, raw_s = classify_tags([title])
            cat = raw_c.title()
            subcat = (flatten_subcategory(raw_c, raw_s) or raw_c).title()
        else:
            cat, subcat = "Sports", "Sports"

        # Position provenance: redeemed share size comes from the raw
        # per-outcome rows of this transaction (summed), falling back to the
        # accumulated buy size when the redemption rows carry no size.
        size = raw_size_by_tx.get(str(red.get("transactionHash") or ""), 0.0) or buy.get("total_size", 0.0)
        payout = _parse(red.get("usdcSize"))
        entry_cost = buy.get("total_usdc", 0.0)
        entry_price = (entry_cost / size) if (size > 0 and entry_cost > 0) else 0.0
        if entry_cost == 0 and entry_price > 0 and size > 0:
            entry_cost = entry_price * size

        realized_pnl = (payout - entry_cost) if entry_cost > 0 else payout

        def _ts_iso(ts_val):
            if not ts_val:
                return None
            try:
                from datetime import datetime, timezone
                return datetime.fromtimestamp(int(ts_val), tz=timezone.utc).isoformat()
            except Exception:
                return None

        closed_combos.append({
            "conditionId": cid,
            "asset": red.get("asset") or buy.get("asset", ""),
            "title": title,
            "size": size,
            "totalBought": size,
            "tokens": size,
            "avgPrice": entry_price,
            "entryCost": entry_cost,
            "payout": payout,
            "realizedPnl": realized_pnl,
            "closedAt": _ts_iso(red.get("timestamp")),
            "timestamp": red.get("timestamp"),
            "entryAt": _ts_iso(buy.get("first_ts")),
            "isCombo": True,
            "category": cat,
            "subcategory": subcat,
        })

    # 2. Process open combos
    for cid, buy in buy_events.items():
        if cid in redeem_events:
            continue
        title = buy.get("title", "")
        if title:
            raw_c, raw_s = classify_tags([title])
            cat = raw_c.title()
            subcat = (flatten_subcategory(raw_c, raw_s) or raw_c).title()
        else:
            cat, subcat = "Sports", "Sports"

        size = buy.get("total_size", 0.0)
        current_val = buy.get("total_usdc", 0.0)
        entry_price = (current_val / size) if (size > 0 and current_val > 0) else 0.0

        def _ts_iso(ts_val):
            if not ts_val:
                return None
            try:
                from datetime import datetime, timezone
                return datetime.fromtimestamp(int(ts_val), tz=timezone.utc).isoformat()
            except Exception:
                return None

        open_combos.append({
            "conditionId": cid,
            "asset": buy.get("asset", ""),
            "title": title,
            "size": size,
            "tokens": size,
            "avgPrice": entry_price,
            "currentValue": current_val,
            "invested": current_val,
            "realizedPnl": 0.0,
            "cashPnl": 0.0,
            "entryAt": _ts_iso(buy.get("first_ts")),
            "isCombo": True,
            "category": cat,
            "subcategory": subcat,
        })

    return open_combos, closed_combos



POSITIONS_MAX_OFFSET = 10000
SNAPSHOT_MARKET_BATCH_SIZE = 40
SNAPSHOT_REQUEST_SEMAPHORE = asyncio.Semaphore(8)


def _snapshot_position_keys(payload: bytes) -> set[tuple[str, str]]:
    """Return the exact (condition, asset) inventory from an accounting snapshot."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            with archive.open("positions.csv") as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
                return {
                    (str(row.get("conditionId") or ""), str(row.get("asset") or ""))
                    for row in reader
                    if row.get("conditionId") and row.get("asset")
                }
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, csv.Error):
        return set()


async def _fetch_positions_from_accounting_snapshot(
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
) -> tuple[list[dict], bool]:
    """Resolve a capped wallet's inventory in bounded market partitions.

    The snapshot supplies the complete condition/asset inventory. Its condition
    IDs are then used as selective `/positions?market=...` partitions so the
    returned rows retain Polymarket's cost-basis and PnL fields.
    """
    try:
        async with session.get(
            "https://data-api.polymarket.com/v1/accounting/snapshot",
            params={"user": address},
            timeout=aiohttp.ClientTimeout(total=120, connect=10, sock_read=110),
        ) as resp:
            if resp.status != 200:
                return [], False
            snapshot_keys = _snapshot_position_keys(await resp.read())
    except Exception as exc:
        logger.warning("Accounting snapshot failed for %s: %s", address, exc)
        return [], False

    # An empty or invalid archive is not enough evidence that a capped wallet is empty.
    if not snapshot_keys:
        return [], False

    condition_ids = sorted({condition_id for condition_id, _asset in snapshot_keys})
    async def fetch_batch(market_batch: list[str]) -> Optional[list[dict]]:
        for attempt in range(3):
            try:
                async with SNAPSHOT_REQUEST_SEMAPHORE:
                    if rate_limiter:
                        await rate_limiter.acquire("positions")
                    async with session.get(
                        "https://data-api.polymarket.com/positions",
                        params={
                            "user": address,
                            "market": ",".join(market_batch),
                            "limit": 500,
                            "offset": 0,
                        },
                        timeout=aiohttp.ClientTimeout(total=30, connect=10, sock_read=25),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if (
                                isinstance(data, list)
                                and len(data) < 500
                                and all(isinstance(row, dict) for row in data)
                            ):
                                return data
                        elif resp.status not in (429, 500, 502, 503, 504):
                            return None
            except Exception as exc:
                if attempt == 2:
                    logger.warning("Partitioned positions fetch failed for %s: %s", address, exc)
            await asyncio.sleep(0.5 * (attempt + 1))
        return None

    batches = [
        condition_ids[start:start + SNAPSHOT_MARKET_BATCH_SIZE]
        for start in range(0, len(condition_ids), SNAPSHOT_MARKET_BATCH_SIZE)
    ]
    batch_results = await asyncio.gather(*(fetch_batch(batch) for batch in batches))
    fetched: dict[tuple[str, str], dict] = {}
    for data in batch_results:
        if data is None:
            return list(fetched.values()), False
        for row in data:
            key = (str(row.get("conditionId") or ""), str(row.get("asset") or ""))
            if key in snapshot_keys:
                fetched[key] = row

    # Snapshot files can lag the live positions view by several hours. Retry any
    # gaps in smaller partitions, then accept a missing key only when the closed
    # endpoint proves that the snapshot position has since exited.
    for _attempt in range(2):
        missing_conditions = sorted({cid for cid, asset in snapshot_keys - set(fetched)})
        if not missing_conditions:
            break
        retry_batches = [
            missing_conditions[start:start + 10]
            for start in range(0, len(missing_conditions), 10)
        ]
        retry_results = await asyncio.gather(*(fetch_batch(batch) for batch in retry_batches))
        for data in retry_results:
            if data is None:
                continue
            for row in data:
                key = (str(row.get("conditionId") or ""), str(row.get("asset") or ""))
                if key in snapshot_keys:
                    fetched[key] = row

    missing_keys = snapshot_keys - set(fetched)
    if missing_keys:
        missing_conditions = sorted({condition_id for condition_id, _asset in missing_keys})

        async def fetch_closed_batch(market_batch: list[str]) -> Optional[list[dict]]:
            try:
                async with SNAPSHOT_REQUEST_SEMAPHORE:
                    if rate_limiter:
                        await rate_limiter.acquire("closed-positions")
                    async with session.get(
                        "https://data-api.polymarket.com/closed-positions",
                        params={
                            "user": address,
                            "market": ",".join(market_batch),
                            "limit": 50,
                            "offset": 0,
                        },
                        timeout=aiohttp.ClientTimeout(total=30, connect=10, sock_read=25),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, list) and all(isinstance(row, dict) for row in data):
                                return data
            except Exception:
                pass
            return None

        closed_batches = [
            missing_conditions[start:start + 10]
            for start in range(0, len(missing_conditions), 10)
        ]
        closed_results = await asyncio.gather(*(fetch_closed_batch(batch) for batch in closed_batches))
        exited_keys = {
            (str(row.get("conditionId") or ""), str(row.get("asset") or ""))
            for data in closed_results if data is not None
            for row in data
        }
        snapshot_keys -= missing_keys & exited_keys

    return list(fetched.values()), set(fetched) == snapshot_keys


async def fetch_positions(
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
) -> tuple[list[dict], bool]:
    """Fetch complete current positions, including capped wallets and combo parlays."""
    all_positions = []
    seen_keys = set()
    offset = 0
    limit = 500
    is_complete = False

    while offset <= POSITIONS_MAX_OFFSET:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            if rate_limiter:
                await rate_limiter.acquire("positions")
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data:
                        is_complete = True
                        break
                    if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                        is_complete = False
                        break
                    wrapped = all(
                        (p.get("conditionId"), p.get("asset", "")) in seen_keys
                        for p in data[:5]
                    )
                    if wrapped and len(all_positions) >= limit:
                        is_complete = offset < POSITIONS_MAX_OFFSET
                        break
                    for p in data:
                        cid = p.get("conditionId")
                        asset = p.get("asset", "")
                        if cid:
                            seen_keys.add((cid, asset))
                    all_positions.extend(data)
                    if len(data) < limit:
                        is_complete = True
                        break
                    if offset == POSITIONS_MAX_OFFSET:
                        snapshot_positions, snapshot_complete = await _fetch_positions_from_accounting_snapshot(
                            session, address, rate_limiter
                        )
                        if snapshot_complete:
                            all_positions = snapshot_positions
                            is_complete = True
                        else:
                            is_complete = False
                        break
                    offset += limit
                else:
                    is_complete = False
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch positions for {address} at offset {offset}: {e}")
            is_complete = False
            break

    # Merge Open Combo Parlay Positions
    open_combos, _ = await fetch_combo_activity(session, address, rate_limiter=rate_limiter)
    if open_combos:
        existing_cids = {p.get("conditionId") for p in all_positions if p.get("conditionId")}
        for combo in open_combos:
            if combo["conditionId"] not in existing_cids:
                all_positions.append(combo)

    return all_positions, is_complete


CLOSED_POSITIONS_MAX_OFFSET = 100000
ACTIVITY_PAGE_SIZE = 500
ACTIVITY_MAX_OFFSET = 5000


async def _activity_page(
    session: aiohttp.ClientSession,
    address: str,
    start: int | None,
    end: int,
    offset: int,
    rate_limiter: Optional[PostgresRateLimiter],
) -> Optional[list[dict]]:
    """Fetch one stable Activity page; `None` means it cannot be trusted."""
    params = {
        "user": address, "end": end, "limit": ACTIVITY_PAGE_SIZE, "offset": offset,
        "sortBy": "TIMESTAMP", "sortDirection": "ASC",
    }
    if start is not None:
        params["start"] = start
    for attempt in range(3):
        try:
            if rate_limiter:
                await rate_limiter.acquire("activity")
            async with session.get(
                "https://data-api.polymarket.com/activity", params=params,
                timeout=aiohttp.ClientTimeout(total=45, connect=10, sock_read=35),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) and all(isinstance(row, dict) for row in data) else None
                if response.status not in (429, 500, 502, 503, 504):
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(0.5 * (attempt + 1))
    return None


async def fetch_activity_market_ids(
    session: aiohttp.ClientSession,
    address: str,
    rate_limiter: Optional[PostgresRateLimiter] = None,
) -> tuple[set[str], bool]:
    """Return every Activity condition ID by splitting windows at its 5k offset cap.

    Activity is used only as a discovery index for deep closed-position
    recovery. It does not supply the position PnL or overwrite ledger rows.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    first_page = await _activity_page(session, address, None, now, 0, rate_limiter)
    if first_page is None:
        return set(), False
    timestamps = [int(row.get("timestamp") or 0) for row in first_page if row.get("timestamp")]
    if not timestamps:
        return set(), True

    market_ids: set[str] = set()
    windows: deque[tuple[int, int]] = deque([(min(timestamps), now)])
    while windows:
        start, end = windows.pop()
        pages: list[list[dict]] = []
        for offset in range(0, ACTIVITY_MAX_OFFSET + 1, ACTIVITY_PAGE_SIZE):
            page = await _activity_page(session, address, start, end, offset, rate_limiter)
            if page is None:
                return market_ids, False
            pages.append(page)
            if len(page) < ACTIVITY_PAGE_SIZE:
                break
        # A full page at offset 5,000 proves this time window exceeds the
        # endpoint budget. Split it; never silently discard its oldest rows.
        if len(pages) == (ACTIVITY_MAX_OFFSET // ACTIVITY_PAGE_SIZE) + 1 and len(pages[-1]) == ACTIVITY_PAGE_SIZE:
            if start >= end:
                logger.warning("Activity cannot be partitioned below one second for %s", address[:12])
                return market_ids, False
            midpoint = (start + end) // 2
            windows.append((start, midpoint))
            windows.append((midpoint + 1, end))
            continue
        for page in pages:
            market_ids.update(
                str(row.get("conditionId")) for row in page if row.get("conditionId")
            )
    return market_ids, True


async def recover_closed_positions_from_activity(
    session: aiohttp.ClientSession,
    address: str,
    known_keys: set[tuple[str, str]],
    rate_limiter: Optional[PostgresRateLimiter] = None,
) -> tuple[list[dict], bool]:
    """Recover closed rows past the address-wide endpoint ceiling.

    Each Activity-discovered market is queried individually because the closed
    endpoint returns at most 50 rows; batching markets could hide a full page
    from one market behind other markets. The caller must still treat `False`
    as no-sync/no-prune evidence.
    """
    market_ids, activity_complete = await fetch_activity_market_ids(session, address, rate_limiter)
    if not activity_complete:
        return [], False
    recovered: list[dict] = []
    for market_id in sorted(market_ids):
        offset = 0
        while offset <= CLOSED_POSITIONS_MAX_OFFSET:
            try:
                if rate_limiter:
                    await rate_limiter.acquire("closed-positions")
                async with session.get(
                    "https://data-api.polymarket.com/closed-positions",
                    params={"user": address, "market": market_id, "limit": 50, "offset": offset, "sortBy": "TIMESTAMP", "sortDirection": "DESC"},
                    timeout=aiohttp.ClientTimeout(total=30, connect=10, sock_read=25),
                ) as response:
                    if response.status != 200:
                        return recovered, False
                    page = await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                return recovered, False
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                return recovered, False
            for row in page:
                key = (str(row.get("conditionId") or ""), str(row.get("outcome") or row.get("asset") or ""))
                if key[0] and key not in known_keys:
                    known_keys.add(key)
                    recovered.append(row)
            if len(page) < 50:
                break
            offset += 50
        if offset > CLOSED_POSITIONS_MAX_OFFSET:
            return recovered, False
    return recovered, True


async def fetch_closed_positions(
    session: aiohttp.ClientSession,
    address: str,
    existing_keys: Optional[set[tuple[str, str]]] = None,
    rate_limiter: Optional[PostgresRateLimiter] = None,
    recover_deep_history: bool = False,
) -> tuple[list[dict], bool]:
    """Fetch resolved/closed positions for a wallet, including Closed Combo Parlays.
    If existing_keys is provided, stops fetching as soon as it hits already-known positions.

    Returns (positions, is_complete). is_complete=False means a batch of API
    requests failed and the result is truncated — callers MUST NOT mark
    closed_synced_at when is_complete=False, or missing positions become a
    permanent hole."""
    MAX_CLOSED = 200000
    all_closed = []
    seen_keys: set[tuple[str, str]] = set()
    limit = 50  # API caps closed-positions at 50/page

    # 1. Fetch Page 0 first (fast path for incremental sync)
    url0 = f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={0}&sortBy=TIMESTAMP&sortDirection=DESC"
    hit_end = False
    try:
        if rate_limiter:
            await rate_limiter.acquire("closed-positions")
        async with session.get(url0, timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)) as resp:
            if resp.status == 200:
                data0 = await resp.json()
                if isinstance(data0, list) and data0:
                    for p in data0:
                        cid = p.get("conditionId") or ""
                        outcome = p.get("outcome") or p.get("asset", "")
                        if existing_keys and cid and (cid, outcome) in existing_keys:
                            hit_end = True
                            break
                        key = (cid, outcome)
                        if cid and key not in seen_keys:
                            seen_keys.add(key)
                            all_closed.append(p)
                    if len(data0) < limit:
                        hit_end = True
                else:
                    hit_end = True
            else:
                return [], False
    except Exception as e:
        logger.debug(f"Page 0 fetch failed for {address[:12]}: {e}")
        return [], False

    # 2. If more pages needed (whale wallet or full backfill), paginate concurrently
    is_complete = True
    if not hit_end and len(all_closed) < MAX_CLOSED:
        offset = limit
        batch_size = 6
        MAX_RETRIES = 3
        while len(all_closed) < MAX_CLOSED:
            if offset > CLOSED_POSITIONS_MAX_OFFSET:
                logger.warning(
                    f"Closed-position API offset ceiling reached for {address[:12]}...; "
                    "history is truncated"
                )
                if recover_deep_history and not existing_keys:
                    recovered, recovered_complete = await recover_closed_positions_from_activity(
                        session, address, seen_keys, rate_limiter
                    )
                    all_closed.extend(recovered)
                    is_complete = recovered_complete
                else:
                    is_complete = False
                break
            remaining = MAX_CLOSED - len(all_closed)
            legal_pages = ((CLOSED_POSITIONS_MAX_OFFSET - offset) // limit) + 1
            pages_to_fetch = min(batch_size, (remaining + limit - 1) // limit, legal_pages)
            page_offsets = [offset + i * limit for i in range(pages_to_fetch)]
            urls = [
                f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={page_offset}&sortBy=TIMESTAMP&sortDirection=DESC"
                for page_offset in page_offsets
            ]
            batch_ok = False
            repeated_boundary = False
            for attempt in range(MAX_RETRIES):
                if rate_limiter:
                    await asyncio.gather(*(
                        rate_limiter.acquire("closed-positions") for _ in urls
                    ))
                results = await asyncio.gather(
                    *[session.get(url, timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)) for url in urls],
                    return_exceptions=True,
                )
                batch_ok = False
                repeated_boundary = False
                successful_pages = 0
                attempt_hit_end = False
                failed_page = False
                staged_rows = []
                staged_keys: set[tuple[str, str]] = set()
                for page_offset, resp in zip(page_offsets, results):
                    if isinstance(resp, Exception) or resp.status != 200:
                        failed_page = True
                        continue
                    data = await resp.json()
                    resp.release()
                    successful_pages += 1
                    if not data or not isinstance(data, list):
                        attempt_hit_end = True
                        break
                    page_keys = {
                        (p.get("conditionId") or "", p.get("outcome") or p.get("asset", ""))
                        for p in data
                        if p.get("conditionId")
                    }
                    # A repeated page is never a valid completion marker. It
                    # can be a transient cache/rate-limit response at shallow
                    # offsets, while at the documented ceiling it means older
                    # history is inaccessible. Retry it, then mark incomplete.
                    if page_keys and page_keys.issubset(seen_keys | staged_keys):
                        repeated_boundary = True
                        break
                    for p in data:
                        cid = p.get("conditionId") or ""
                        outcome = p.get("outcome") or p.get("asset", "")
                        if existing_keys and cid and (cid, outcome) in existing_keys:
                            attempt_hit_end = True
                            break
                        key = (cid, outcome)
                        if cid and key not in seen_keys and key not in staged_keys:
                            staged_keys.add(key)
                            staged_rows.append(p)
                    batch_ok = successful_pages == len(results)
                    if attempt_hit_end or len(data) < limit:
                        attempt_hit_end = True
                        break
                if (attempt_hit_end and not failed_page) or batch_ok:
                    seen_keys.update(staged_keys)
                    all_closed.extend(staged_rows)
                    hit_end = attempt_hit_end
                    break
                attempt_hit_end = False
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
            if hit_end:
                break
            if repeated_boundary:
                logger.warning(
                    f"Closed-position API repeated a boundary page for {address[:12]}... "
                    f"at offset {offset}; history is truncated"
                )
                is_complete = False
                break
            if not batch_ok:
                logger.warning(f"Batch failed after {MAX_RETRIES} retries for {address[:12]}... at offset {offset} — marking incomplete")
                is_complete = False
                break
            offset += pages_to_fetch * limit
            await asyncio.sleep(0.02)

    # Merge Closed Combo Parlay Positions
    _, closed_combos = await fetch_combo_activity(session, address, rate_limiter=rate_limiter)
    if closed_combos:
        existing_cids = {p.get("conditionId") for p in all_closed if p.get("conditionId")}
        if existing_keys:
            existing_cids.update({k[0] for k in existing_keys})
        for combo in closed_combos:
            if combo["conditionId"] not in existing_cids:
                all_closed.append(combo)

    return all_closed[:MAX_CLOSED], is_complete



async def _get_tiered(session: aiohttp.ClientSession, url: str) -> list | dict | None:
    """Helper to fetch from Polymarket with progressive tiered timeouts: 10s, 30s, 60s, 90s, 150s."""
    timeouts = [10, 30, 60, 90, 150]
    for i, t in enumerate(timeouts):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=t)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            if i < len(timeouts) - 1:
                logger.debug(f"Timeout {t}s failed for {url}. Retrying with {timeouts[i+1]}s...")
                await asyncio.sleep(1)
                continue
            logger.warning(f"All tiered timeouts failed for {url}: {e}")
            return None
    return None


async def fetch_website_pnl(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Fetch all-time PnL/volume/rank/username from Polymarket's public leaderboard."""
    url = f"https://data-api.polymarket.com/v1/leaderboard?user={address}&category=OVERALL&timePeriod=ALL"
    data = await _get_tiered(session, url)
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    raw_name = (item.get("userName") or "").strip()[:255]
    if raw_name.lower().startswith("0x") and len(raw_name) > 10:
        raw_name = ""
    return {
        "pnl": _parse(item.get("pnl")),
        "volume": _parse(item.get("vol")),
        "rank": int(item.get("rank") or 0),
        "username": raw_name,
    }


async def fetch_portfolio_value(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch total portfolio value/balance for a wallet from Polymarket Data API."""
    url = f"https://data-api.polymarket.com/value?user={address}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8, connect=3, sock_read=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and len(data) > 0:
                    return _parse(data[0].get("value", 0))
    except Exception:
        pass
    return 0.0


async def fetch_all_trades(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Lightweight 1-trade fetch to get recent trade metadata without heavy pagination."""
    url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
    data = await _get_tiered(session, url)
    if isinstance(data, list):
        return data
    return []


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch exact portfolio balance from Alchemy."""
    from src.utils.alchemy_client import alchemy_get_token_balances, PUSD_CONTRACT
    try:
        b = await alchemy_get_token_balances(session, address, [PUSD_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance for {address}: {e}")
    return 0.0


async def _fetch_last_trade_dt(session: aiohttp.ClientSession, address: str) -> datetime | None:
    """Fetch the most recent trade timestamp using the correct ?user= param."""
    url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
    data = await _get_tiered(session, url)
    if isinstance(data, list) and data:
        ts = data[0].get("timestamp")
        if ts:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return None


async def process_batch(conn: asyncpg.Connection, session: aiohttp.ClientSession, wallets: list[dict]):
    """Vet UNCLASSIFIED wallets: fetch balance + positions + website_pnl,
    assign a tier. leaderboard_stats picks up promoted wallets via next_check_at."""
    BALANCE_THRESHOLD = 1000.0

    for item in wallets:
        address = item["address"]
        queue_source = item["source"]

        is_leaderboard = queue_source and "leaderboard" in queue_source.lower()

        try:
            balance = await fetch_balance(session, address)
            website = await fetch_website_pnl(session, address)
            last_trade_dt = await _fetch_last_trade_dt(session, address)
            # Only fetch positions for non-leaderboard wallets
            if is_leaderboard:
                positions = []
            else:
                pos_res = await fetch_positions(session, address)
                positions = pos_res[0] if isinstance(pos_res, tuple) else pos_res
        except Exception as e:
            # Leave the wallet UNCLASSIFIED — it will be retried next run
            # instead of being misclassified as DEAD on a transient failure.
            logger.warning(f"Error fetching data for wallet {address[:10]}..., will retry: {e}")
            continue

        # Compute position_value from open positions
        position_value = 0.0
        for pos in (positions or []):
            curr_val = _parse(pos.get("currentValue"))
            if curr_val > 0:
                position_value += curr_val

        # Use website_pnl/volume if available, else fallback to 0
        website_pnl = website["pnl"] if website else 0.0
        website_volume = website["volume"] if website else 0.0
        website_rank = website["rank"] if website else None
        username = website["username"] if website else ""

        # Total Capital = cash balance + open position value
        total_cap = balance + position_value

        # ── decide promotion ──
        # Vetting gate: total_cap (balance + position_value) + last_trade_at determine global list entry
        now = datetime.now(timezone.utc)
        is_dormant_flag = (last_trade_dt is None or (now - last_trade_dt) >= timedelta(days=30))

        if total_cap < BALANCE_THRESHOLD:
            # total_cap < $1k (including 0 capital) → LOW_BALANCE tier
            # is_dormant = TRUE if inactive > 30 days or never traded; FALSE if active in last 30 days
            tier_reason_str = 'zero capital' if total_cap <= 0 else 'capital < $1k at vetting'
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'LOW_BALANCE', $5, $4, $3, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE WHEN wallets_v2.tier = 'CURATED' THEN 'CURATED' ELSE 'LOW_BALANCE' END,
                    tier_reason = CASE WHEN wallets_v2.tier = 'CURATED' THEN wallets_v2.tier_reason ELSE $5 END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                    is_dormant = $4,
                    updated_at = NOW()
            """, address, username, last_trade_dt, is_dormant_flag, tier_reason_str)
            logger.info(f"Low capital (<$1k, cap={total_cap:.0f}): {address[:10]}... marking LOW_BALANCE (dormant={is_dormant_flag})")
            continue

        # Balance > $1k — check last trade recency
        has_trades = last_trade_dt is not None
        now_utc = datetime.now(timezone.utc)

        if not has_trades:
            # Balance > $1k but no trades → New Wallets (Might Cook badge)
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'NEW', 'balance >= $1k, 0 trades', FALSE, NULL, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE WHEN wallets_v2.tier = 'CURATED' THEN 'CURATED' ELSE 'NEW' END,
                    tier_reason = CASE WHEN wallets_v2.tier = 'CURATED' THEN wallets_v2.tier_reason ELSE 'balance >= $1k, 0 trades' END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    is_dormant = FALSE,
                    updated_at = NOW()
            """, address, username)
            logger.info(f"New wallet no trades: {address[:10]}... balance={balance:.0f} → NEW (Might Cook)")
            continue

        is_stale = (now_utc - last_trade_dt) >= timedelta(days=30)

        if is_stale:
            # Stale → STANDARD or CURATED but dormant (hibernated)
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'STANDARD', 'hibernated: >30d inactive', TRUE, $3, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE
                        WHEN wallets_v2.tier = 'CURATED' THEN 'CURATED'
                        ELSE 'STANDARD'
                    END,
                    tier_reason = CASE WHEN wallets_v2.tier = 'CURATED' THEN wallets_v2.tier_reason ELSE 'hibernated: >30d inactive' END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                    is_dormant = TRUE,
                    updated_at = NOW()
            """, address, username, last_trade_dt)
            logger.info(f"Hibernating stale wallet: {address[:10]}... balance={balance:.0f} last_trade={last_trade_dt}")
            continue

        # ── Passed vetting: balance > $1k + recent trade → add to global list ──
        logger.info(f"Promoting {address[:10]}... balance={balance:.0f} pos_val={position_value:.0f} pnl=${website_pnl:.0f} vol=${website_volume:.0f}")

        await conn.execute("""
            INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
            VALUES ($1, $2, 'STANDARD', 'passed vetting', FALSE, $3, NOW(), NOW())
            ON CONFLICT (address) DO UPDATE SET
                tier = CASE WHEN wallets_v2.tier = 'CURATED' THEN 'CURATED' ELSE 'STANDARD' END,
                tier_reason = CASE WHEN wallets_v2.tier = 'CURATED' THEN wallets_v2.tier_reason ELSE 'passed vetting' END,
                username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                is_dormant = FALSE,
                updated_at = NOW()
        """, address, username, last_trade_dt)

        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address, canonical_source(queue_source), queue_source if queue_source else 'Unknown')

        # Discovery may establish the identity row, but it must not publish
        # metric ownership domains.  Official and capital snapshots are synced
        # by their dedicated workers; source/coordinator workers own the rest.
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address)
            VALUES ($1)
            ON CONFLICT (address) DO NOTHING
        """, address)


async def run_discovery(pool: asyncpg.Pool | None = None, db_url: str = DB_URL):
    """Main entry point for the discovery worker."""
    logger.info("Starting wallet discovery worker...")

    own_pool = False
    if pool is None:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        own_pool = True

    try:
        async with pool.acquire() as conn:
            # The v2 discovery queue: UNCLASSIFIED wallets awaiting vetting
            rows = await conn.fetch(
                """
                SELECT address, tier_reason AS source FROM wallets_v2
                WHERE tier = 'UNCLASSIFIED'
                  AND (next_check_at IS NULL OR next_check_at <= NOW())
                ORDER BY added_at ASC LIMIT $1
                """,
                BATCH_SIZE
            )
            wallets = [{"address": r["address"], "source": r["source"]} for r in rows]
            logger.info(f"Found {len(wallets)} wallets to evaluate.")

            if wallets:
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    await process_batch(conn, session, wallets)
    finally:
        if own_pool and pool:
            await pool.close()
    logger.info("Discovery worker finished.")


async def main():
    """Infinite loop for the orchestrator."""
    import signal
    shutdown = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    logger.info("Starting Wallet Queue Processor (interval=60s)")
    while not shutdown.is_set():
        try:
            await run_discovery()
        except Exception:
            logger.exception("Error in wallet discovery queue processor")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("Wallet Queue Processor shut down cleanly")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
