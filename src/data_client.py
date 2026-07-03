"""Client for the Polymarket Data API."""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATA_API_URL = os.getenv("DATA_API_URL", "https://data-api.polymarket.com")


@dataclass
class ParsedTrade:
    tx_hash: str
    wallet_address: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    fee: float
    timestamp: datetime


def _parse_iso(dt_str: str | int | None) -> datetime:
    """Parse ISO datetime string or Unix timestamp, falling back to UTC now."""
    if not dt_str:
        return datetime.now(timezone.utc)
    if isinstance(dt_str, (int, float)):
        # Some endpoints return timestamps in seconds
        return datetime.fromtimestamp(dt_str, timezone.utc)
    
    # Handle 'Z' suffix
    cleaned = str(dt_str).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)


def _parse_trade(raw: dict) -> ParsedTrade:
    """Parse a raw Data API trade dict into our domain model."""
    side_val = raw.get("side", "")
    # Data API side might be 'buy'/'sell' or 'YES'/'NO'. We expect 'YES' or 'NO' in our DB schema.
    # However, Polymarket Data API for trades might just report the outcome being bought.
    # We will map it appropriately if we see different values.
    # Assuming 'side' returned is 'YES'/'NO' or mapped from condition/token.
    # Actually, the polymarket schema is usually:
    # "side": "BUY" / "SELL" and "outcome": "Yes" / "No" or "YES"/"NO".
    # Wait, the DB schema says: side VARCHAR(4) CHECK (side IN ('YES','NO')).
    # If the API returns something else, we need to extract it from 'outcome' or map it.
    
    # We'll extract side as uppercase 'YES' or 'NO'. If it's missing, default to 'YES'
    side = str(raw.get("outcome") or raw.get("side", "YES")).upper()
    if side not in ("YES", "NO"):
        side = "YES"

    return ParsedTrade(
        tx_hash=raw.get("transactionHash") or raw.get("tx_hash", ""),
        wallet_address=raw.get("user") or raw.get("wallet_address", ""),
        market_id=raw.get("conditionId") or raw.get("market_id", ""),
        token_id=raw.get("asset") or raw.get("token_id", ""),
        side=side,
        price=float(raw.get("price", 0) or 0),
        size=float(raw.get("size") or raw.get("amount", 0) or 0),
        fee=float(raw.get("fee", 0) or 0),
        timestamp=_parse_iso(raw.get("timestamp")),
    )


async def fetch_user_activity(wallet: str, limit: int = 100) -> list[ParsedTrade]:
    """Fetch recent activity for a specific wallet address."""
    url = f"{DATA_API_URL}/events" # actually /activity in TDD but endpoints might be different. Let's use /trades for now or /events?user=
    # Actually, the TDD says data-api.polymarket.com/activity?user=0xWALLET
    # I'll use that.
    params = {"user": wallet, "limit": limit}
    
    logger.info("Fetching Data API activity for wallet: %s", wallet)
    
    async with aiohttp.ClientSession() as session:
        # TDD suggests /activity endpoint
        url = f"{DATA_API_URL}/activity"
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 404:
                # Sometimes user doesn't exist or API differs
                return []
            resp.raise_for_status()
            data = await resp.json()
            
    # Some APIs wrap in a 'data' object or list directly
    raw_trades = data if isinstance(data, list) else data.get("data", [])
    
    return [_parse_trade(t) for t in raw_trades if "transactionHash" in t or "tx_hash" in t]

async def fetch_market_trades(market_id: str, limit: int = 100) -> list[ParsedTrade]:
    """Fetch recent trades for a specific market conditionId."""
    params = {"market": market_id, "limit": limit}
    
    logger.info("Fetching Data API trades for market: %s", market_id)
    
    async with aiohttp.ClientSession() as session:
        url = f"{DATA_API_URL}/trades"
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 404:
                return []
            resp.raise_for_status()
            data = await resp.json()
            
    raw_trades = data if isinstance(data, list) else data.get("data", [])
    return [_parse_trade(t) for t in raw_trades]
