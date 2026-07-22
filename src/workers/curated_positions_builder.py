# src/workers/curated_positions_builder.py
"""Build curated_positions rows from Polymarket open+closed positions and
market resolution. Win/loss keys on the sign of realized_pnl."""
import logging
import aiohttp
import asyncpg

from src.workers.leaderboard_stats import fetch_positions, fetch_closed_positions, _parse
from src.workers.window_stats import _parse_end

logger = logging.getLogger(__name__)

POSITION_CAP = 5000


def classify_position(pos: dict, is_closed_endpoint: bool = False) -> dict | None:
    """Classify a raw Polymarket position into curated_positions row fields.

    Win/loss is the SIGN of realized PnL, taken straight from the API — NOT
    which outcome the wallet held. A wallet that held a losing outcome but sold
    before resolution at a profit is a WIN (its realizedPnl is positive); the
    old outcome-matching logic scored those as losses.

    - Closed-positions endpoint: the wallet fully exited → always resolved;
      pnl = realizedPnl.
    - Open-positions endpoint: resolved only if `redeemable` (market settled);
      pnl = realizedPnl + cashPnl (booked + still-held legs).

    Returns None for an open, unresolved position (excluded from win rate)."""
    realized = _parse(pos.get("realizedPnl"))
    total_bought = _parse(pos.get("totalBought"))
    if is_closed_endpoint:
        resolved = True
        pnl = realized
    else:
        resolved = bool(pos.get("redeemable"))
        pnl = realized + _parse(pos.get("cashPnl"))
    if not resolved:
        return None
    return {
        "total_bought": total_bought,
        "total_sold": 0.0,
        "net_tokens": _parse(pos.get("size")),
        "market_resolved": True,
        "won": pnl > 0,
        "payout": _parse(pos.get("currentValue")),
        "realized_pnl": pnl,
        "is_resolved": True,
        "is_win": pnl > 0,
    }


async def _upsert(conn: asyncpg.Connection, address: str, pos: dict, fields: dict):
    await conn.execute(
        """
        INSERT INTO curated_positions
            (address, condition_id, outcome, total_bought, total_sold, net_tokens,
             market_resolved, won, payout, realized_pnl, is_resolved, is_win,
             category, subcategory, resolved_at, computed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NOW())
        ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
            total_bought=EXCLUDED.total_bought, total_sold=EXCLUDED.total_sold,
            net_tokens=EXCLUDED.net_tokens, market_resolved=EXCLUDED.market_resolved,
            won=EXCLUDED.won, payout=EXCLUDED.payout, realized_pnl=EXCLUDED.realized_pnl,
            is_resolved=EXCLUDED.is_resolved, is_win=EXCLUDED.is_win,
            resolved_at=EXCLUDED.resolved_at, computed_at=NOW()
        """,
        address, pos.get("conditionId"), pos.get("outcome") or "",
        fields["total_bought"], fields["total_sold"], fields["net_tokens"],
        fields["market_resolved"], fields["won"], fields["payout"],
        fields["realized_pnl"], fields["is_resolved"], fields["is_win"],
        pos.get("category"), pos.get("subcategory"), _parse_end(pos.get("endDate")),
    )


async def build_wallet_positions(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Rebuild a curated wallet's resolved positions from BOTH the open and
    closed Polymarket endpoints, then upsert into curated_positions (capped).

    Open endpoint contributes markets the wallet still holds a token in
    (resolved only when `redeemable`); closed endpoint contributes fully-exited
    markets. Together they form the complete resolved-position set the win rate
    is computed over. Win/loss = sign of realized PnL (see classify_position).

    Incremental: the closed fetch resumes from curated_position_sync's cursor —
    a wallet that left and re-entered the curated list only fetches the gap
    since its last complete fetch (latest 5000 of the gap if larger). The
    cursor advances ONLY after a complete pass, so interrupted runs re-fetch
    the same gap and self-heal. Positions are never deleted on demotion."""
    seen: set[tuple[str, str]] = set()
    count = 0

    cursor = await conn.fetchval(
        "SELECT last_closed_ts FROM curated_position_sync WHERE wallet_address = $1",
        address,
    )
    newer_than = cursor.timestamp() if cursor else None

    # Closed positions first — these are the realized wins/losses the wallet
    # already exited, which the open endpoint omits.
    try:
        closed, closed_complete = await fetch_closed_positions(session, address, newer_than_epoch=newer_than)
    except Exception as e:
        logger.warning(f"closed-positions fetch failed for {address[:10]}: {e}")
        closed, closed_complete = [], False
    if not closed_complete:
        logger.warning(f"closed fetch incomplete for {address[:10]} (deadline); cursor NOT advanced")
    max_ts = max((float(p["timestamp"]) for p in (closed or []) if p.get("timestamp") is not None), default=None)
    for p in (closed or []):
        cid = p.get("conditionId")
        if not cid or count >= POSITION_CAP:
            continue
        key = (cid, p.get("outcome") or "")
        if key in seen:
            continue
        fields = classify_position(p, is_closed_endpoint=True)
        if fields is None:
            continue
        seen.add(key)
        await _upsert(conn, address, p, fields)
        count += 1

    # Open positions — resolved ones (redeemable) the wallet hasn't exited yet.
    try:
        openp = await fetch_positions(session, address)
    except Exception as e:
        logger.warning(f"positions fetch failed for {address[:10]}: {e}")
        openp = []
    for p in (openp or []):
        cid = p.get("conditionId")
        if not cid or count >= POSITION_CAP:
            continue
        key = (cid, p.get("outcome") or "")
        if key in seen:
            continue
        fields = classify_position(p, is_closed_endpoint=False)
        if fields is None:
            continue
        seen.add(key)
        await _upsert(conn, address, p, fields)
        count += 1

    # Advance the incremental cursor ONLY after a complete closed fetch — a
    # failed, deadline-truncated, or interrupted pass leaves it untouched so
    # the unfetched tail of the gap re-fetches next run.
    if closed_complete and max_ts is not None:
        await conn.execute(
            """
            INSERT INTO curated_position_sync (wallet_address, last_closed_ts, updated_at)
            VALUES ($1, to_timestamp($2), NOW())
            ON CONFLICT (wallet_address) DO UPDATE SET
                last_closed_ts = GREATEST(COALESCE(curated_position_sync.last_closed_ts, to_timestamp(0)), EXCLUDED.last_closed_ts),
                updated_at = NOW()
            """,
            address, max_ts,
        )
