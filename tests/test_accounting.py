import pytest
from src.utils.accounting import apply_fill, apply_redemption

def test_apply_fill_buy():
    # Buy 1000 tokens for $500
    state = {}
    trade = {"side": "BUY", "usd_volume": 500.0, "token_size": 1000.0}
    
    new_state = apply_fill(state, trade)
    assert new_state["total_bought_usd"] == 500.0
    assert new_state["total_buy_tokens"] == 1000.0
    assert new_state["total_sold_usd"] == 0.0
    assert new_state["total_sell_tokens"] == 0.0
    assert new_state["realized_pnl"] == 0.0

def test_apply_fill_buy_and_sell_profit():
    # Buy 1000 for $500 (avg $0.50)
    state = {"total_bought_usd": 500.0, "total_buy_tokens": 1000.0}
    
    # Sell 500 for $300 (sold at $0.60)
    # Cost of 500 tokens = 500 * $0.50 = $250
    # Realized PnL = $300 - $250 = $50
    trade = {"side": "SELL", "usd_volume": 300.0, "token_size": 500.0}
    
    new_state = apply_fill(state, trade)
    assert new_state["total_sold_usd"] == 300.0
    assert new_state["total_sell_tokens"] == 500.0
    assert new_state["realized_pnl"] == 50.0

def test_apply_fill_buy_and_sell_loss():
    # Buy 1000 for $500 (avg $0.50)
    state = {"total_bought_usd": 500.0, "total_buy_tokens": 1000.0}
    
    # Sell 500 for $200 (sold at $0.40)
    # Cost of 500 tokens = 500 * $0.50 = $250
    # Realized PnL = $200 - $250 = -$50
    trade = {"side": "SELL", "usd_volume": 200.0, "token_size": 500.0}
    
    new_state = apply_fill(state, trade)
    assert new_state["total_sold_usd"] == 200.0
    assert new_state["total_sell_tokens"] == 500.0
    assert new_state["realized_pnl"] == -50.0

def test_apply_fill_accumulation():
    # Buy 1000 for $200
    state = apply_fill({}, {"side": "BUY", "usd_volume": 200.0, "token_size": 1000.0})
    # Buy 1000 for $400
    state = apply_fill(state, {"side": "BUY", "usd_volume": 400.0, "token_size": 1000.0})
    
    # Total bought: $600. Total tokens: 2000. Avg price: $0.30
    assert state["total_bought_usd"] == 600.0
    assert state["total_buy_tokens"] == 2000.0
    
    # Sell 1000 for $500
    # Cost: 1000 * 0.30 = $300
    # PnL = 500 - 300 = $200
    state = apply_fill(state, {"side": "SELL", "usd_volume": 500.0, "token_size": 1000.0})
    assert state["realized_pnl"] == 200.0

def test_apply_redemption_win():
    # Buy 1000 for $500 (avg $0.50)
    state = {"total_bought_usd": 500.0, "total_buy_tokens": 1000.0}
    
    # Resolves to 1. Payout = $1000.
    # Cost of remaining 1000 tokens = $500.
    # Cash PnL = 1000 - 500 = $500
    redemption = {"payout": 1000.0}
    new_state = apply_redemption(state, redemption)
    
    assert new_state["cash_pnl"] == 500.0
    assert new_state["is_resolved"] is True
    assert new_state["is_win"] is True

def test_apply_redemption_loss():
    # Buy 1000 for $500 (avg $0.50)
    state = {"total_bought_usd": 500.0, "total_buy_tokens": 1000.0}
    
    # Resolves to 0. Payout = $0.
    # Cost of remaining 1000 tokens = $500.
    # Cash PnL = 0 - 500 = -$500
    redemption = {"payout": 0.0}
    new_state = apply_redemption(state, redemption)
    
    assert new_state["cash_pnl"] == -500.0
    assert new_state["is_resolved"] is True
    assert new_state["is_win"] is False

def test_apply_redemption_with_prior_sells():
    # Buy 1000 for $500 (avg $0.50)
    state = apply_fill({}, {"side": "BUY", "usd_volume": 500.0, "token_size": 1000.0})
    
    # Sell 500 for $400 (Cost $250 -> PnL +$150)
    state = apply_fill(state, {"side": "SELL", "usd_volume": 400.0, "token_size": 500.0})
    assert state["realized_pnl"] == 150.0
    
    # Remaining tokens = 500. Cost of remaining = $250.
    # Market resolves to 0. Payout = $0.
    # Cash PnL = 0 - 250 = -$250
    # Total PnL = realized_pnl + cash_pnl = 150 - 250 = -100 (Overall loss)
    new_state = apply_redemption(state, {"payout": 0.0})
    assert new_state["cash_pnl"] == -250.0
    assert new_state["is_win"] is False
    
    # What if market resolves to 1? Payout = $500.
    # Cash PnL = 500 - 250 = $250
    # Total PnL = 150 + 250 = 400 (Overall win)
    win_state = apply_redemption(state, {"payout": 500.0})
    assert win_state["cash_pnl"] == 250.0
    assert win_state["is_win"] is True
