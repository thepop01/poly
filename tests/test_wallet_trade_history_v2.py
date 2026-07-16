"""Task 4 guard: wallet_trade_history must be fully on the v2 schema.

The v1 tables (tracked_wallets, wallet_stats, wallet_discovery_queue) are
dropped from the DB — any reference means a runtime UndefinedTableError.
The v2 discovery queue is wallets_v2 rows with tier = 'UNCLASSIFIED'.
"""
from pathlib import Path

TEXT = Path("src/workers/wallet_trade_history.py").read_text(encoding="utf-8")


def test_no_v1_table_references():
    assert "tracked_wallets" not in TEXT
    assert "wallet_discovery_queue" not in TEXT
    assert "INSERT INTO wallet_stats" not in TEXT


def test_writes_v2_tables():
    assert "wallets_v2" in TEXT and "wallet_sources_v2" in TEXT


def test_covers_all_vetting_tiers():
    for tier in ("'DEAD'", "'LOW_BALANCE'", "'NEW'", "'STANDARD'"):
        assert tier in TEXT, f"missing vetting gate for {tier}"


def test_consumes_unclassified_queue():
    assert "'UNCLASSIFIED'" in TEXT


def test_fetches_last_trade_in_vetting_path():
    # last_trade_dt must be fetched before the vetting gates use it —
    # the old code only fetched it in a removed branch, leaving the main
    # path to crash (NameError) or reuse the previous wallet's value.
    gate_pos = TEXT.index("BALANCE_THRESHOLD")
    fetch_pos = TEXT.index("last_trade_dt = await _fetch_last_trade_dt")
    use_pos = TEXT.index("last_trade_dt is not None")
    assert gate_pos < fetch_pos < use_pos
