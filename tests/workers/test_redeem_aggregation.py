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
