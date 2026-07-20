# src/utils/market_resolution.py
"""Per-condition_id market-resolution lookup, cached in-process.

Resolution is immutable once set, so a simple dict cache is safe for the
lifetime of a worker pass. Source: CLOB /markets/{condition_id}, which returns
`closed` and a `tokens` array with a `winner` flag per outcome.
"""
import logging
import aiohttp

logger = logging.getLogger(__name__)

_resolution_cache: dict[str, dict] = {}


def classify_resolution(market: dict | None) -> dict:
    """Pure classifier over a CLOB market payload."""
    if not market or not market.get("closed"):
        return {"resolved": False, "winning_outcome": None}
    winner = None
    for tok in market.get("tokens", []) or []:
        if tok.get("winner"):
            winner = tok.get("outcome")
            break
    return {"resolved": True, "winning_outcome": winner}


async def fetch_market_resolution(session: aiohttp.ClientSession, condition_id: str) -> dict:
    """Return {"resolved": bool, "winning_outcome": str|None} for a condition_id.
    Cached; unresolved results are NOT cached (they can change)."""
    if not condition_id:
        return {"resolved": False, "winning_outcome": None}
    if condition_id in _resolution_cache:
        return _resolution_cache[condition_id]
    try:
        url = f"https://clob.polymarket.com/markets/{condition_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return {"resolved": False, "winning_outcome": None}
            market = await resp.json()
    except Exception as e:
        logger.warning(f"resolution fetch failed for {condition_id[:12]}: {e}")
        return {"resolved": False, "winning_outcome": None}
    result = classify_resolution(market)
    if result["resolved"]:
        _resolution_cache[condition_id] = result
    return result
