# src/workers/curated_positions_builder.py
"""Build curated_positions rows from Polymarket open+closed positions and
market resolution. Win/loss keys on the sign of realized_pnl."""
import logging
import aiohttp
import asyncpg

from src.utils.market_resolution import fetch_market_resolution
from src.workers.leaderboard_stats import fetch_positions, _parse

logger = logging.getLogger(__name__)

POSITION_CAP = 5000


def classify_position(pos: dict, resolution: dict) -> dict:
    """Pure: given a merged position and its market resolution, return the
    classified row fields."""
    total_bought = _parse(pos.get("total_bought"))
    total_sold = _parse(pos.get("total_sold"))
    net_tokens = _parse(pos.get("net_tokens"))
    resolved = bool(resolution.get("resolved"))
    won = resolved and resolution.get("winning_outcome") == pos.get("outcome")
    payout = net_tokens * 1.0 if won else 0.0
    realized_pnl = payout + total_sold - total_bought
    return {
        "total_bought": total_bought,
        "total_sold": total_sold,
        "net_tokens": net_tokens,
        "market_resolved": resolved,
        "won": won,
        "payout": payout,
        "realized_pnl": realized_pnl,
        "is_resolved": resolved,
        "is_win": resolved and realized_pnl > 0,
    }


async def build_wallet_positions(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    """Fetch a curated wallet's open positions, classify against market
    resolution, and upsert into curated_positions (capped)."""
    raw = await fetch_positions(session, address)
    positions = (raw or [])[:POSITION_CAP]
    for p in positions:
        cid = p.get("conditionId")
        if not cid:
            continue
        merged = {
            "outcome": p.get("outcome") or "",
            "total_bought": _parse(p.get("totalBought")),
            "total_sold": 0.0,  # open-position endpoint gives no sold leg
            "net_tokens": _parse(p.get("size")),
        }
        resolution = await fetch_market_resolution(session, cid)
        fields = classify_position(merged, resolution)
        await conn.execute(
            """
            INSERT INTO curated_positions
                (address, condition_id, outcome, total_bought, total_sold, net_tokens,
                 market_resolved, won, payout, realized_pnl, is_resolved, is_win,
                 category, subcategory, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW())
            ON CONFLICT (address, condition_id, outcome) DO UPDATE SET
                total_bought=EXCLUDED.total_bought, total_sold=EXCLUDED.total_sold,
                net_tokens=EXCLUDED.net_tokens, market_resolved=EXCLUDED.market_resolved,
                won=EXCLUDED.won, payout=EXCLUDED.payout, realized_pnl=EXCLUDED.realized_pnl,
                is_resolved=EXCLUDED.is_resolved, is_win=EXCLUDED.is_win, computed_at=NOW()
            """,
            address, cid, merged["outcome"], fields["total_bought"], fields["total_sold"],
            fields["net_tokens"], fields["market_resolved"], fields["won"], fields["payout"],
            fields["realized_pnl"], fields["is_resolved"], fields["is_win"],
            p.get("category"), p.get("subcategory"),
        )
