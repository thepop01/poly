"""
Bug Condition Exploration Test: Deposits Missing from Smart Money Alerts

Property 1: Bug Condition - Deposits Not Inserted into smart_money_alerts

This test is DESIGNED TO FAIL on unfixed code.
The bug: deposit_watcher.py inserts deposits into wallet_deposits but NOT smart_money_alerts.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

Expected counterexamples (on unfixed code):
- process_batch($15k_deposit) → wallet_deposits INSERTED but smart_money_alerts EMPTY
- check_cumulative_deposits($60k_cumulative) → wallet_deposits INSERTED but smart_money_alerts EMPTY
- query_alerts(wallet, 'deposits') → returns 0 rows (expected 1+)

Root cause: "deposit_watcher.py does not call insert into smart_money_alerts"

NOTE: Code analysis shows the current deposit_watcher.py already HAS these inserts.
If these tests pass, it indicates the code is already in a fixed state (unexpected_pass).
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone


# ============================================================================
# Scenario A: Single deposit >= $10k from tracked wallet
# → should insert into smart_money_alerts but (on unfixed code) doesn't
# ============================================================================

@pytest.mark.asyncio
async def test_single_large_deposit_inserts_into_smart_money_alerts():
    """
    Scenario A: Single deposit ≥$10k from tracked wallet.

    Bug Condition: deposit_watcher.process_batch() should insert into smart_money_alerts
    for deposits >= $10k, but on unfixed code it does NOT.

    Expected: smart_money_alerts receives an entry with type='LARGE_DEPOSIT', amount=$15k
    Actual (unfixed): smart_money_alerts is empty — only wallet_deposits is populated

    **Validates: Requirements 1.1, 1.3**
    """
    # Track all DB execute() calls to capture both table inserts
    wallet_deposits_calls = []
    smart_money_alerts_calls = []

    async def mock_execute(query, *args):
        q = query.strip().upper()
        if "WALLET_DEPOSITS" in q and "INSERT" in q:
            wallet_deposits_calls.append({"query": query, "args": args})
            return "INSERT 0 1"  # Simulates a NEW row inserted
        elif "SMART_MONEY_ALERTS" in q and "INSERT" in q:
            smart_money_alerts_calls.append({"query": query, "args": args})
            return "INSERT 0 1"
        elif "UPDATE" in q:
            return "UPDATE 0"
        return None

    async def mock_fetchrow(query, *args):
        q = query.strip().upper()
        if "TRACKED_WALLETS" in q:
            # Wallet stats
            return {
                "win_rate": 0.65,
                "roi_pct": 42.5,
                "total_volume": 500000,
                "total_pnl": 12000,
                "tier": "Gold"
            }
        if "WALLET_DEPOSITS" in q and "SUM" in q:
            # Cumulative query — return 0 so it won't trigger cumulative alert
            return {"total_48h": 0}
        return None

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

    # Mock the API response for a single $15k deposit
    test_wallet = "0xabc123def456abc123def456abc123def456abc1"
    test_tx_hash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    test_amount = 15_000.0  # $15k — above $10k threshold
    test_timestamp = int(datetime.now(timezone.utc).timestamp())

    mock_deposit_data = [{
        "proxyWallet": test_wallet,
        "usdcSize": str(test_amount),
        "timestamp": test_timestamp,
        "transactionHash": test_tx_hash
    }]

    mock_session = AsyncMock()

    with patch("src.workers.deposit_watcher.fetch_recent_deposits",
               new=AsyncMock(return_value=mock_deposit_data)):
        with patch("src.workers.deposit_watcher.check_cumulative_deposits",
                   new=AsyncMock(return_value=None)):
            with patch("src.workers.deposit_watcher.send_discord_webhook",
                       new=AsyncMock(return_value=True)):
                from src.workers.deposit_watcher import process_batch
                await process_batch(mock_conn, mock_session, [test_wallet])

    # Assert wallet_deposits received the insert (this should PASS even on unfixed code)
    assert len(wallet_deposits_calls) >= 1, (
        "COUNTEREXAMPLE: wallet_deposits did NOT receive any insert. "
        f"Expected >= 1 insert for ${test_amount:,.0f} deposit from {test_wallet[:10]}..."
    )

    # Assert smart_money_alerts received the insert (this FAILS on unfixed code)
    # BUG CONDITION: On unfixed code, smart_money_alerts is empty while wallet_deposits is populated
    assert len(smart_money_alerts_calls) >= 1, (
        "BUG CONFIRMED: smart_money_alerts did NOT receive any insert for a $15k deposit. "
        f"wallet_deposits received {len(wallet_deposits_calls)} insert(s) but "
        f"smart_money_alerts received 0 inserts. "
        f"Counterexample: process_batch($15k_deposit) → wallet_deposits INSERTED but smart_money_alerts EMPTY. "
        f"Root cause: deposit_watcher.py does not call insert into smart_money_alerts table."
    )

    # Verify the smart_money_alerts insert has correct data
    sma_call = smart_money_alerts_calls[0]
    sma_args = sma_call["args"]
    # Args should be: wallet, amount, tx_hash
    assert test_wallet in sma_args, (
        f"smart_money_alerts insert missing wallet address. Args: {sma_args}"
    )
    assert test_amount in sma_args or any(
        abs(float(a) - test_amount) < 0.01 for a in sma_args if isinstance(a, (int, float))
    ), (
        f"smart_money_alerts insert missing correct amount ${test_amount:,.0f}. Args: {sma_args}"
    )


# ============================================================================
# Scenario B: Cumulative deposits >= $50k in 48h from tracked wallet
# → should insert into smart_money_alerts but (on unfixed code) doesn't
# ============================================================================

@pytest.mark.asyncio
async def test_cumulative_deposits_inserts_into_smart_money_alerts():
    """
    Scenario B: Cumulative deposits ≥$50k in 48h from tracked wallet.

    Bug Condition: deposit_watcher.check_cumulative_deposits() should insert into
    smart_money_alerts when cumulative total >= $50k, but on unfixed code it does NOT.

    Expected: smart_money_alerts receives an entry with type='LARGE_DEPOSIT', amount=$60k
    Actual (unfixed): smart_money_alerts is empty after cumulative threshold crossed

    **Validates: Requirements 1.2, 1.3**
    """
    smart_money_alerts_calls = []
    wallet_deposits_calls = []

    async def mock_execute(query, *args):
        q = query.strip().upper()
        if "SMART_MONEY_ALERTS" in q and "INSERT" in q:
            smart_money_alerts_calls.append({"query": query, "args": args})
            return "INSERT 0 1"
        elif "WALLET_DEPOSITS" in q and "INSERT" in q:
            wallet_deposits_calls.append({"query": query, "args": args})
            return "INSERT 0 1"
        elif "UPDATE" in q:
            return "UPDATE 1"
        return None

    async def mock_fetchrow(query, *args):
        q = query.strip().upper()
        if "SUM" in q and "WALLET_DEPOSITS" in q:
            # Return cumulative total of $60k — above $50k threshold
            return {"total_48h": 60_000.0}
        if "TRACKED_WALLETS" in q:
            return {
                "win_rate": 0.7,
                "roi_pct": 55.0,
                "total_volume": 800000,
                "total_pnl": 20000,
                "tier": "Diamond"
            }
        return None

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

    test_wallet = "0x456789abcdef456789abcdef456789abcdef4567"

    with patch("src.workers.deposit_watcher.send_discord_webhook",
               new=AsyncMock(return_value=True)):
        from src.workers.deposit_watcher import check_cumulative_deposits
        await check_cumulative_deposits(mock_conn, test_wallet)

    # Assert smart_money_alerts was called (FAILS on unfixed code)
    # BUG CONDITION: cumulative deposit crosses $50k threshold but smart_money_alerts is not updated
    assert len(smart_money_alerts_calls) >= 1, (
        "BUG CONFIRMED: smart_money_alerts did NOT receive any insert for cumulative $60k deposits. "
        f"smart_money_alerts received 0 inserts. "
        f"Counterexample: check_cumulative_deposits($60k_cumulative) → wallet_deposits INSERTED "
        f"but smart_money_alerts EMPTY. "
        f"Root cause: deposit_watcher.check_cumulative_deposits() does not call "
        f"insert into smart_money_alerts table."
    )

    # Verify cumulative insert uses a synthetic tx_hash (not a real one)
    sma_call = smart_money_alerts_calls[0]
    sma_args = sma_call["args"]
    # Synthetic tx hash should contain 'cumulative_' prefix
    tx_hash_arg = next(
        (a for a in sma_args if isinstance(a, str) and "cumulative_" in a),
        None
    )
    assert tx_hash_arg is not None, (
        f"smart_money_alerts cumulative insert missing synthetic tx_hash with 'cumulative_' prefix. "
        f"Args: {sma_args}"
    )


# ============================================================================
# Scenario C: Query alerts for wallet — documents expected vs actual state
# ============================================================================

@pytest.mark.asyncio
async def test_process_batch_inserts_to_both_tables_for_large_deposit():
    """
    Scenario C: Verify process_batch inserts to BOTH tables for single $15k deposit.

    This test verifies the complete bug condition:
    - wallet_deposits MUST receive an insert (baseline behavior)
    - smart_money_alerts MUST also receive an insert (the bug condition: missing on unfixed code)

    Expected (fixed code): BOTH tables receive inserts
    Expected (unfixed code): ONLY wallet_deposits receives insert → smart_money_alerts assertion FAILS

    **Validates: Requirements 1.1, 1.3, 1.4**
    """
    all_execute_calls = []

    async def tracking_mock_execute(query, *args):
        q = query.strip().upper()
        all_execute_calls.append({"query": q, "args": args})
        if "WALLET_DEPOSITS" in q and "INSERT" in q:
            return "INSERT 0 1"
        elif "SMART_MONEY_ALERTS" in q and "INSERT" in q:
            return "INSERT 0 1"
        elif "UPDATE" in q:
            return "UPDATE 0"
        return None

    async def mock_fetchrow(query, *args):
        q = query.strip().upper()
        if "TRACKED_WALLETS" in q:
            return {"win_rate": 0.65, "roi_pct": 42.5, "total_volume": 500000, "total_pnl": 12000, "tier": "Gold"}
        if "WALLET_DEPOSITS" in q and "SUM" in q:
            return {"total_48h": 0}
        return None

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=tracking_mock_execute)
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)

    test_wallet = "0xdeadbeef0000000000000000000000000000dead"
    test_tx_hash = "0xdeadbeef1234567890abcdef1234567890abcdef1234567890abcdef12345678"
    test_amount = 15_000.0
    test_timestamp = int(datetime.now(timezone.utc).timestamp())

    mock_deposit_data = [{
        "proxyWallet": test_wallet,
        "usdcSize": str(test_amount),
        "timestamp": test_timestamp,
        "transactionHash": test_tx_hash
    }]

    mock_session = AsyncMock()

    with patch("src.workers.deposit_watcher.fetch_recent_deposits",
               new=AsyncMock(return_value=mock_deposit_data)):
        with patch("src.workers.deposit_watcher.check_cumulative_deposits",
                   new=AsyncMock(return_value=None)):
            with patch("src.workers.deposit_watcher.send_discord_webhook",
                       new=AsyncMock(return_value=True)):
                from src.workers.deposit_watcher import process_batch
                await process_batch(mock_conn, mock_session, [test_wallet])

    # Separate the calls by table
    wallet_deposits_inserts = [c for c in all_execute_calls if "WALLET_DEPOSITS" in c["query"] and "INSERT" in c["query"]]
    smart_money_alerts_inserts = [c for c in all_execute_calls if "SMART_MONEY_ALERTS" in c["query"] and "INSERT" in c["query"]]

    # wallet_deposits should have the insert (basic sanity check)
    assert len(wallet_deposits_inserts) >= 1, (
        f"wallet_deposits should have received an insert for ${test_amount:,.0f} deposit. "
        f"All execute calls: {[c['query'][:60] for c in all_execute_calls]}"
    )

    # smart_money_alerts MUST also have an insert (BUG: missing on unfixed code)
    assert len(smart_money_alerts_inserts) >= 1, (
        f"BUG CONFIRMED: smart_money_alerts did NOT receive any insert. "
        f"wallet_deposits received {len(wallet_deposits_inserts)} insert(s) but "
        f"smart_money_alerts received 0 inserts for a ${test_amount:,.0f} deposit. "
        f"Counterexample: process_batch($15k_deposit) → wallet_deposits INSERTED, "
        f"smart_money_alerts EMPTY. "
        f"Root cause: deposit_watcher.process_batch() missing INSERT INTO smart_money_alerts."
    )
