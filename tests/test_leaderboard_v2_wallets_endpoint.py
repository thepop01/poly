"""Task 8 — tabbed /api/v2/leaderboard/wallets endpoint (source assertions)."""
import re
from pathlib import Path

SRC = Path("src/api/routers/leaderboard_v2.py").read_text(encoding="utf-8")


def test_tab_filters_match_canonical_model():
    assert '"all":' in SRC and "w.tier NOT IN ('DEAD', 'UNCLASSIFIED') AND w.is_dormant = FALSE" in SRC
    assert "w.tier = 'STANDARD' AND w.is_dormant = FALSE" in SRC
    assert "w.tier = 'LOW_BALANCE' AND w.is_dormant = FALSE" in SRC
    assert "w.tier = 'NEW' AND w.is_dormant = FALSE" in SRC
    assert "w.is_dormant = TRUE AND w.tier NOT IN ('DEAD', 'UNCLASSIFIED')" in SRC


def test_tabs_are_disjoint_except_all():
    """curated/standard/low_balance/new require is_dormant = FALSE; hibernated requires TRUE."""
    active_tabs = ["'CURATED'", "'STANDARD'", "'LOW_BALANCE'", "'NEW'"]
    for tier in active_tabs:
        assert f"w.tier = {tier} AND w.is_dormant = FALSE" in SRC


def test_source_filter_uses_exists_not_join():
    """Multi-source wallets must not fan out into duplicate rows."""
    assert "EXISTS (SELECT 1 FROM wallet_sources_v2 s WHERE s.address = w.address AND s.source =" in SRC
    assert "LEFT JOIN wallet_sources_v2" not in SRC
    assert "JOIN wallet_sources_v2" not in SRC


def test_sources_include_custom_not_manual():
    assert '"custom"' in SRC or "'custom'" in SRC
    assert "WALLET_SOURCES" in SRC
    assert '"manual"' not in SRC


def test_no_user_input_interpolated_into_sql():
    """Only whitelisted maps feed the f-string SQL; user values go via $n params."""
    assert "WALLET_SORT_COLUMNS.get(sort_by" in SRC
    assert "TAB_FILTERS[tab]" in SRC
    assert 'raise HTTPException(status_code=400, detail=f"invalid tab' in SRC
    # search/source must be parameterized, never formatted in
    assert "'%{search}%'" not in SRC.replace('f"%{search}%"', "")


def test_counts_endpoint_counts_all_six_tabs():
    m = re.search(r"async def get_wallet_counts.*?FROM wallets_v2", SRC, re.S)
    assert m, "counts endpoint missing"
    body = m.group(0)
    for alias in ("all_count", "curated", "standard", "low_balance", "new", "hibernated"):
        assert f"AS {alias}" in body
