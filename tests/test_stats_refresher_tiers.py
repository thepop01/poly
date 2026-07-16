"""Task 7 guard: stats_refresher runs the canonical tier machine.

Tiers are DEAD / LOW_BALANCE / NEW / STANDARD (+ CURATED, never auto-demoted;
UNCLASSIFIED is the vetting queue and is left alone). The asset-based
TIER_1..TIER_4 values were a divergence nothing reads — they must not return.
"""
from pathlib import Path

TEXT = Path("src/workers/stats_refresher.py").read_text(encoding="utf-8")


def test_all_canonical_branches_present():
    for tier in ("'DEAD'", "'LOW_BALANCE'", "'NEW'", "'STANDARD'"):
        assert tier in TEXT, f"missing tier branch {tier}"


def test_no_asset_tiers():
    for tier in ("TIER_1", "TIER_2", "TIER_3", "TIER_4"):
        assert tier not in TEXT


def test_curated_and_queue_excluded():
    assert "'CURATED', 'UNCLASSIFIED'" in TEXT


def test_dormancy_flips_both_ways():
    assert "SET is_dormant = TRUE" in TEXT
    assert "SET is_dormant = FALSE" in TEXT
