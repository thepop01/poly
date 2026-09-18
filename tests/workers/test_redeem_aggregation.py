from src.workers.wallet_trade_history import aggregate_redeem_events

def test_two_row_redeem_sums_to_single_row():
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00"},
    ]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 50.0

def test_single_row_unchanged():
    events = [{"type": "REDEEM", "transactionHash": "0xbbb", "usdcSize": "100.00"}]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 100.0

def test_two_row_redeem_sums_usdc():
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00",
         "conditionId": "0x1", "outcome": "YES"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00",
         "conditionId": "0x1", "outcome": "NO"},
    ]
    result = aggregate_redeem_events(events)
    assert len(result) == 1
    assert float(result[0]["usdcSize"]) == 50.0

def test_raw_rows_also_preserved_separately():
    """Raw per-outcome events are returned alongside the aggregated list."""
    from src.workers.wallet_trade_history import aggregate_redeem_events_with_raw
    events = [
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "50.00", "outcome": "YES"},
        {"type": "REDEEM", "transactionHash": "0xaaa", "usdcSize": "0.00", "outcome": "NO"},
    ]
    aggregated, raw = aggregate_redeem_events_with_raw(events)
    assert len(aggregated) == 1     # for cash reconciliation
    assert len(raw) == 2            # for position provenance
