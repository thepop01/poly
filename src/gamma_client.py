"""Client for the Polymarket Gamma API."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")


@dataclass
class ParsedMarket:
    """A single tradeable outcome parsed from the Gamma API."""

    market_id: str          # conditionId
    event_id: str
    token_id: str           # first clobTokenId
    slug: str
    title: str              # question field
    outcome_label: str | None
    status: str
    enable_order_book: bool
    current_price: float | None
    total_volume: float
    liquidity: float
    created_at: datetime


@dataclass
class ParsedEvent:
    """An event container (one or more markets) parsed from the Gamma API."""

    event_id: str
    slug: str
    title: str
    category: str | None
    status: str
    created_at: datetime
    markets: list[ParsedMarket] = field(default_factory=list)


def _parse_iso(dt_str: str | None) -> datetime:
    """Parse ISO datetime string, falling back to UTC now."""
    if not dt_str:
        return datetime.now(timezone.utc)
    # Handle 'Z' suffix and various formats
    cleaned = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)


def _parse_event(raw: dict) -> ParsedEvent:
    """Parse a raw Gamma API event dict into our domain model."""
    event_id = str(raw["id"])
    active = raw.get("active", False)
    closed = raw.get("closed", False)

    if closed:
        status = "resolved"
    elif active:
        status = "active"
    else:
        status = "cancelled"

    event = ParsedEvent(
        event_id=event_id,
        slug=raw.get("slug", event_id),
        title=raw.get("title", ""),
        category=raw.get("category"),
        status=status,
        created_at=_parse_iso(raw.get("creationDate") or raw.get("createdAt")),
    )

    for mkt_raw in raw.get("markets", []):
        event.markets.append(_parse_market(mkt_raw, event_id))

    return event


def _parse_market(raw: dict, event_id: str) -> ParsedMarket:
    """Parse a raw Gamma API market dict into our domain model."""
    # clobTokenIds is a JSON-encoded string: '["tokenId1", "tokenId2"]'
    clob_ids_str = raw.get("clobTokenIds", "[]")
    try:
        clob_ids = json.loads(clob_ids_str) if isinstance(clob_ids_str, str) else clob_ids_str
    except (json.JSONDecodeError, TypeError):
        clob_ids = []
    token_id = clob_ids[0] if clob_ids else raw.get("conditionId", raw["id"])

    # outcomes is a JSON-encoded string: '["Yes", "No"]'
    outcomes_str = raw.get("outcomes", "[]")
    try:
        outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
    except (json.JSONDecodeError, TypeError):
        outcomes = []
    outcome_label = outcomes[0] if outcomes else None

    # outcomePrices is a JSON-encoded string: '["0.48", "0.52"]'
    prices_str = raw.get("outcomePrices", "[]")
    try:
        prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
    except (json.JSONDecodeError, TypeError):
        prices = []
    current_price = float(prices[0]) if prices else None

    active = raw.get("active", False)
    closed = raw.get("closed", False)
    if closed:
        status = "resolved"
    elif active:
        status = "active"
    else:
        status = "pending"

    return ParsedMarket(
        market_id=raw.get("conditionId", raw["id"]),
        event_id=event_id,
        token_id=str(token_id),
        slug=raw.get("slug", ""),
        title=raw.get("question", raw.get("slug", "")),
        outcome_label=outcome_label,
        status=status,
        enable_order_book=not closed and active,
        current_price=current_price,
        total_volume=float(raw.get("volumeNum", 0) or 0),
        liquidity=float(raw.get("liquidityNum", 0) or 0),
        created_at=_parse_iso(raw.get("createdAt")),
    )


async def fetch_active_events(
    limit: int | None = None,
    closed: bool = False,
) -> list[ParsedEvent]:
    """
    Fetch events from the Gamma API.

    Args:
        limit: Max number of events to return. None = use env default.
        closed: If False, fetch only active+open events (not closed).
    """
    limit = limit or int(os.getenv("GAMMA_EVENTS_LIMIT", "100"))
    params: dict = {"limit": limit}
    if not closed:
        params["closed"] = "false"

    url = f"{GAMMA_API_URL}/events"
    logger.info("Fetching Gamma events: %s params=%s", url, params)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            raw_events: list[dict] = await resp.json()

    events = [_parse_event(e) for e in raw_events]
    logger.info(
        "Parsed %d events with %d total markets",
        len(events),
        sum(len(e.markets) for e in events),
    )
    return events
