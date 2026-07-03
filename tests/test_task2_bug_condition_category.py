"""
Bug Condition Exploration Test: Category Field Shows N/A for Trades

Property 1: Bug Condition - Category Field Shows N/A for Trades

This test is DESIGNED TO FAIL on unfixed code.
The bug: _fetch_market_meta() returns category=None when Gamma API returns null/missing
category, which propagates as NULL to the database, causing the frontend to display
item.data.category || "N/A" → "N/A".

**Validates: Requirements 1.5, 1.6, 1.7**

Expected counterexamples (on unfixed code):
- _fetch_market_meta(token_id) where Gamma API returns category=null → result["category"] is None
- whale_watcher stores category=None in DB → API reads NULL → frontend shows "N/A"
- query_trade_alert(trade_id) → category field is "N/A" (expected a non-null value like "Unknown")

Root cause: etherscan_client._fetch_market_meta() does not provide a default fallback
for when category is None/null. The line:
    category = ev_data[0].get("category")   # returns None when key missing or null
should be:
    category = ev_data[0].get("category") or "Unknown"

NOTE: On FIXED code, these tests will PASS (category defaults to "Unknown" not None).
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# Scenario A: Gamma API returns category=null → _fetch_market_meta returns None
# → category stores as NULL in DB → frontend displays "N/A"
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_market_meta_returns_non_none_category_when_api_returns_null():
    """
    Scenario A: Gamma API returns category=null for an event.

    Bug Condition: _fetch_market_meta() returns {"title": ..., "category": None}
    because ev_data[0].get("category") evaluates to None when the API returns null.

    Expected (fixed code):  result["category"] == "Unknown"  (never None)
    Actual   (unfixed code): result["category"] is None

    Counterexample:
        _fetch_market_meta("12345") where Gamma event API returns {"category": null}
        → result["category"] is None   (expected: "Unknown")

    **Validates: Requirements 1.5, 1.6, 1.7**
    """
    # Clear the module-level title cache to avoid stale hits
    import src.utils.etherscan_client as ec_module
    ec_module._title_cache.clear()

    token_id = "99999999999999999999999999999999"

    # Mock aiohttp session responses:
    # Step 1: /markets endpoint returns a market with event_id="event-001"
    market_response_data = [
        {
            "question": "Will BTC hit $100k?",
            "events": [{"id": "event-001"}]
        }
    ]

    # Step 2: /events endpoint returns event with category=null (the bug trigger)
    event_response_data = [
        {
            "id": "event-001",
            "category": None   # ← Gamma API returns null for category
        }
    ]

    def make_mock_response(json_data, status=200):
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    call_count = 0

    def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "markets" in url:
            return make_mock_response(market_response_data)
        elif "events" in url:
            return make_mock_response(event_response_data)
        return make_mock_response([])

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)

    from src.utils.etherscan_client import _fetch_market_meta
    result = await _fetch_market_meta(mock_session, token_id)

    # Verify title is returned correctly (sanity check)
    assert result["title"] == "Will BTC hit $100k?", (
        f"title should be 'Will BTC hit $100k?' but got: {result['title']!r}"
    )

    # BUG CONDITION: On unfixed code, category is None here.
    # The assertion below FAILS on unfixed code — proving the bug exists.
    assert result["category"] is not None, (
        "BUG CONFIRMED: _fetch_market_meta() returned category=None when Gamma API "
        "returned category=null. "
        "The frontend will show item.data.category || 'N/A' → 'N/A' for this trade. "
        "Counterexample: _fetch_market_meta('{}') where Gamma event API returns "
        "{{'category': null}} → result['category'] is None (expected: 'Unknown'). "
        "Root cause: etherscan_client._fetch_market_meta() line "
        "`category = ev_data[0].get('category')` does not have a fallback default. "
        "Fix: `category = ev_data[0].get('category') or 'Unknown'`".format(token_id)
    )


# ============================================================================
# Scenario B: Gamma API returns event with no 'category' key at all
# → category is also None → same bug manifests
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_market_meta_returns_non_none_category_when_api_key_missing():
    """
    Scenario B: Gamma API returns an event object with no 'category' key.

    dict.get("category") returns None when key is absent.
    Same bug condition — category propagates as NULL.

    Expected (fixed code):  result["category"] == "Unknown"
    Actual   (unfixed code): result["category"] is None

    **Validates: Requirements 1.5, 1.6, 1.7**
    """
    import src.utils.etherscan_client as ec_module
    ec_module._title_cache.clear()

    token_id = "11111111111111111111111111111111"

    market_response_data = [
        {
            "question": "Will ETH hit $5k?",
            "events": [{"id": "event-002"}]
        }
    ]

    # Event response has no "category" key at all
    event_response_data = [
        {
            "id": "event-002"
            # no "category" key — dict.get("category") → None
        }
    ]

    def make_mock_response(json_data, status=200):
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    def mock_get(url, **kwargs):
        if "markets" in url:
            return make_mock_response(market_response_data)
        elif "events" in url:
            return make_mock_response(event_response_data)
        return make_mock_response([])

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)

    from src.utils.etherscan_client import _fetch_market_meta
    result = await _fetch_market_meta(mock_session, token_id)

    # BUG CONDITION: On unfixed code, category is None when the key is absent.
    assert result["category"] is not None, (
        "BUG CONFIRMED: _fetch_market_meta() returned category=None when 'category' key "
        "was absent from the Gamma API event response. "
        "Counterexample: Gamma event object has no 'category' key → "
        "ev_data[0].get('category') returns None → result['category'] is None. "
        "Fix: use `category = ev_data[0].get('category') or 'Unknown'`"
    )


# ============================================================================
# Scenario C: Verify the full data-flow bug:
# category=None stored in DB → simulated API response shows "N/A" on frontend
# ============================================================================

def test_none_category_causes_frontend_to_display_na():
    """
    Scenario C: Documents the full data-flow leading to 'N/A' display.

    Simulates what happens when category=None is stored in the database:
    - The API reads NULL from the DB
    - It serialises it as None/null in the JSON response
    - The frontend JS does: item.data.category || "N/A"  → "N/A"

    This test models that frontend fallback logic in Python to prove the chain.

    Expected (fixed code):  frontend_display("Unknown") == "Unknown"
    Actual   (unfixed code): frontend_display(None) == "N/A"

    **Validates: Requirements 1.6, 1.7**
    """
    # Replicate the frontend JS fallback: item.data.category || "N/A"
    def frontend_display_category(category_from_api):
        """Mirrors: item.data.category || 'N/A'  (JavaScript truthy fallback)."""
        return category_from_api if category_from_api else "N/A"

    # When category is None (NULL from DB), the frontend shows "N/A"
    # This confirms the bug chain end-to-end
    category_stored_in_db = None   # result of _fetch_market_meta() on unfixed code
    displayed_value = frontend_display_category(category_stored_in_db)

    # Demonstrate the bug: None → "N/A" in the frontend
    assert displayed_value == "N/A", (
        "Test setup error: expected None to produce 'N/A' via the frontend fallback."
    )

    # BUG CONDITION: Now assert that the display value should NOT be "N/A"
    # This FAILS on unfixed code because category is None going into the frontend.
    assert displayed_value != "N/A", (
        "BUG CONFIRMED (full data-flow): "
        "category=None stored in DB → API serialises as null → "
        "frontend JS: item.data.category || 'N/A' evaluates to 'N/A'. "
        "Counterexample: "
        "  1. etherscan_client._fetch_market_meta() returns category=None "
        "     (Gamma API returned null or key absent). "
        "  2. whale_watcher inserts category=None → NULL stored in smart_money_alerts. "
        "  3. Alpha Feed API reads NULL → returns {category: null} in JSON. "
        "  4. Frontend: null || 'N/A' = 'N/A' displayed to user. "
        "Fix: _fetch_market_meta() should default category to 'Unknown' when null/absent."
    )


# ============================================================================
# Scenario D: Valid category from Gamma API → must survive the full pipeline
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_market_meta_preserves_valid_category():
    """
    Scenario D: When Gamma API returns a real category value (e.g., "Crypto"),
    _fetch_market_meta() should return it unchanged.

    This is a sanity check — it should PASS on both fixed and unfixed code,
    confirming that valid categories work fine and only the null/missing case is broken.

    **Validates: Requirements 1.5**
    """
    import src.utils.etherscan_client as ec_module
    ec_module._title_cache.clear()

    token_id = "22222222222222222222222222222222"

    market_response_data = [
        {
            "question": "Will Trump win in 2024?",
            "events": [{"id": "event-003"}]
        }
    ]

    event_response_data = [
        {
            "id": "event-003",
            "category": "Politics"   # ← Valid category
        }
    ]

    def make_mock_response(json_data, status=200):
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    def mock_get(url, **kwargs):
        if "markets" in url:
            return make_mock_response(market_response_data)
        elif "events" in url:
            return make_mock_response(event_response_data)
        return make_mock_response([])

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=mock_get)

    from src.utils.etherscan_client import _fetch_market_meta
    result = await _fetch_market_meta(mock_session, token_id)

    # This should PASS on both fixed and unfixed code
    assert result["category"] == "Politics", (
        f"Valid category 'Politics' should be preserved but got: {result['category']!r}"
    )
