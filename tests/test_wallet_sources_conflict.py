"""Task 3 — wallet_sources_v2 inserts must target the composite PK (address, source)."""
from pathlib import Path


def test_trade_tracker_conflict_targets_composite_pk():
    text = Path("src/workers/trade_tracker.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (address, source)" in text
    # No bare single-column conflict left on the sources table
    remainder = text.replace("ON CONFLICT (address, source)", "")
    assert "wallet_sources_v2" in text
    assert "ON CONFLICT (address)\n" not in remainder


def test_deposit_tracker_conflict_targets_composite_pk():
    text = Path("src/workers/deposit_tracker.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (address, source)" in text


def test_deposit_tracker_threshold_strings_match_5k():
    """tier_reason strings must say $5k (the real MIN_DEPOSIT), not the stale $10k."""
    text = Path("src/workers/deposit_tracker.py").read_text(encoding="utf-8")
    assert "$10k" not in text
    assert "MIN_DEPOSIT = 5_000" in text
