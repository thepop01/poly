"""Tests for src.gamma_client — hits the live Gamma API."""

import pytest
from src.gamma_client import fetch_active_events, _parse_event


@pytest.mark.skip(reason="Hits live API - needs mocking for CI")
@pytest.mark.asyncio
async def test_fetch_active_events_returns_data():
    events = await fetch_active_events(limit=3, closed=False)
    assert len(events) > 0, "Expected at least 1 event from Gamma API"

    event = events[0]
    assert event.event_id, "event_id should not be empty"
    assert event.title, "title should not be empty"
    assert event.slug, "slug should not be empty"
    assert event.status in ("active", "resolved", "cancelled")


@pytest.mark.skip(reason="Hits live API - needs mocking for CI")
@pytest.mark.asyncio
async def test_parsed_markets_have_required_fields():
    events = await fetch_active_events(limit=2, closed=False)
    # Find an event with at least one market
    events_with_markets = [e for e in events if e.markets]
    assert len(events_with_markets) > 0, "Expected at least one event with markets"

    market = events_with_markets[0].markets[0]
    assert market.market_id, "market_id should not be empty"
    assert market.token_id, "token_id should not be empty"
    assert market.title, "title should not be empty"


def test_parse_event_handles_minimal_data():
    raw = {
        "id": "test_123",
        "slug": "test-event",
        "title": "Test Event",
        "active": True,
        "closed": False,
        "createdAt": "2026-01-01T00:00:00Z",
        "markets": [],
    }
    event = _parse_event(raw)
    assert event.event_id == "test_123"
    assert event.status == "active"
    assert event.markets == []
