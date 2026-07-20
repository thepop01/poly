# tests/test_market_resolution.py
import pytest
from src.utils.market_resolution import classify_resolution


def test_resolved_market_picks_winner():
    payload = {
        "closed": True,
        "tokens": [
            {"outcome": "Yes", "winner": False},
            {"outcome": "No", "winner": True},
        ],
    }
    r = classify_resolution(payload)
    assert r == {"resolved": True, "winning_outcome": "No"}


def test_open_market_is_unresolved():
    payload = {"closed": False, "tokens": [{"outcome": "Yes", "winner": False}]}
    assert classify_resolution(payload) == {"resolved": False, "winning_outcome": None}


def test_missing_payload_is_unresolved():
    assert classify_resolution(None) == {"resolved": False, "winning_outcome": None}
