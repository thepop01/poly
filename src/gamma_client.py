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
    game_start_time: datetime | None = None   # kickoff time for sports markets
    outcomes: list[str] = field(default_factory=list)


@dataclass
class ParsedEvent:
    """An event container (one or more markets) parsed from the Gamma API."""

    event_id: str
    slug: str
    title: str
    category: str | None
    status: str
    created_at: datetime
    start_date: datetime | None = None   # actual kickoff / game start
    end_date: datetime | None = None     # market resolution date
    tags: list[str] = field(default_factory=list)
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

    tags = raw.get("tags", [])
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = []
    if not isinstance(tags, list):
        tags = []

    raw_start = raw.get("startDate") or raw.get("gameStartTime")
    raw_end = raw.get("endDate")

    event = ParsedEvent(
        event_id=event_id,
        slug=raw.get("slug", event_id),
        title=raw.get("title", ""),
        category=raw.get("category"),
        status=status,
        created_at=_parse_iso(raw.get("creationDate") or raw.get("createdAt")),
        start_date=_parse_iso(raw_start) if raw_start else None,
        end_date=_parse_iso(raw_end) if raw_end else None,
        tags=[str(t) for t in tags],
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

    raw_game_start = raw.get("gameStartTime") or raw.get("startDate")

    return ParsedMarket(
        market_id=str(raw.get("conditionId") or raw.get("id") or ""),
        event_id=event_id,
        token_id=str(token_id),
        slug=raw.get("slug", ""),
        title=str(raw.get("question") or raw.get("slug") or ""),
        outcome_label=outcome_label,
        status=status,
        enable_order_book=not closed and active,
        current_price=current_price,
        total_volume=float(raw.get("volumeNum", 0) or 0),
        liquidity=float(raw.get("liquidityNum", 0) or 0),
        created_at=_parse_iso(raw.get("createdAt")),
        game_start_time=_parse_iso(raw_game_start) if raw_game_start else None,
        outcomes=outcomes,
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


# Sport tag slugs supported by the Polymarket Gamma API
SPORT_TAG_SLUGS: dict[str, str] = {
    "soccer": "soccer",
    "football": "nfl",
    "basketball": "nba",
    "cricket": "cricket",
    "tennis": "tennis",
    "mma": "mma",
    "ufc": "ufc",
    "baseball": "mlb",
    "hockey": "nhl",
}


async def fetch_sports_fixtures(
    tag_slug: str | None = None,
    limit: int = 80,
) -> list[dict]:
    """
    Fetch upcoming sports events from Polymarket and return structured fixture data.
    Uses startDate (kickoff) not endDate (resolution).

    Args:
        tag_slug: Optional Polymarket tag slug to filter by sport (e.g. 'soccer', 'nba')
        limit: Max events to fetch from Gamma API.
    """
    import re

    import asyncio

    async def fetch_for_slug(slug: str | None) -> list[dict]:
        params: dict = {
            "limit": limit,
            "active": "true",
            "closed": "false",
            "order": "startDate",
            "ascending": "true",
        }
        if slug:
            params["tag_slug"] = slug
            
        url = f"{GAMMA_API_URL}/events"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning("Gamma API error for slug %s: %s", slug, resp.status)
                    return []
                return await resp.json()

    if tag_slug is not None:
        logger.info("Fetching sports fixtures for slug: %s", tag_slug)
        raw_events = await fetch_for_slug(tag_slug)
    else:
        logger.info("Fetching sports fixtures for ALL sports")
        # Fetch the top sports concurrently
        top_slugs = ["soccer", "nfl", "nba", "cricket", "tennis", "mma", "mlb", "nhl"]
        tasks = [fetch_for_slug(slug) for slug in top_slugs]
        results = await asyncio.gather(*tasks)
        
        # Flatten and deduplicate by event ID
        seen = set()
        raw_events = []
        for res in results:
            for event in res:
                if event["id"] not in seen:
                    seen.add(event["id"])
                    raw_events.append(event)
        
        # Sort by startDate
        def get_start(e):
            return e.get("startDate") or e.get("gameStartTime") or "9999"
        raw_events.sort(key=get_start)

    fixtures = []
    vs_pattern = re.compile(r"\s+(?:vs\.?|v\.?|versus|beat|defeat)\s+", re.IGNORECASE)
    will_pattern = re.compile(r"^will\s+", re.IGNORECASE)

    for raw in raw_events:
        # We need a future end date (resolution time) to consider it "upcoming"
        raw_start = raw.get("startDate") or raw.get("gameStartTime")
        raw_end = raw.get("endDate")
        
        if not raw_end:
            continue
            
        end_dt = _parse_iso(raw_end)
        now = datetime.now(timezone.utc)
        if end_dt < now:
            continue  # skip past/resolved events
            
        # Determine sport from tags
        raw_tags = raw.get("tags", []) or []
        sport = "Sports"
        league = ""
        tag_labels = []
        for tag in raw_tags:
            label = tag.get("label", "") if isinstance(tag, dict) else str(tag)
            slug = tag.get("slug", "") if isinstance(tag, dict) else ""
            tag_labels.append(label)
            lc = label.lower()
            if any(s in lc for s in ["soccer", "football", "cricket", "tennis", "basketball", "nba", "nfl", "mma", "ufc", "mlb", "nhl", "rugby"]):
                sport = label.title()
            else:
                league = label  # use non-sport tag as league name

        # Parse team names from the event title
        title = raw.get("title", "")
        markets = raw.get("markets", []) or []
        question = markets[0].get("question", title) if markets else title

        clean_title = will_pattern.sub("", title).rstrip("?")
        parts = vs_pattern.split(clean_title)
        
        is_prop = len(parts) < 2
        
        team_home = parts[0].strip() if not is_prop else title
        team_away = " vs ".join(p.strip() for p in parts[1:]) if not is_prop else ""

        # Pick the market with highest volume for the market_id
        best_market = max(markets, key=lambda m: float(m.get("volumeNum", 0) or 0)) if markets else {}
        market_id = best_market.get("conditionId") or best_market.get("id") or raw["id"]
        total_volume = float(raw.get("volume", 0) or 0)
        
        live_odds = []
        try:
            m_outcomes = json.loads(best_market.get("outcomes", "[]"))
            m_prices = json.loads(best_market.get("outcomePrices", "[]"))
            for o, p in zip(m_outcomes, m_prices):
                live_odds.append({"outcome": o, "price": float(p)})
        except Exception:
            pass

        fixtures.append({
            "event_id": str(raw["id"]),
            "market_id": str(market_id),
            "team_home": team_home,
            "team_away": team_away,
            "sport": sport,
            "league": league or "Polymarket",
            "kickoff_time": end_dt.isoformat(),
            "resolution_time": end_dt.isoformat(),
            "volume": total_volume,
            "slug": raw.get("slug", ""),
            "source": "polymarket",
            "is_prop": is_prop,
            "question": question,
            "tags": tag_labels,
            "live_odds": live_odds,
        })

    return fixtures
