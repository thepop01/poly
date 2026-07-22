def apply_fill(position_state: dict, trade: dict) -> dict:
    """
    Applies a buy or sell to a position state.
    Calculates average entry price (cost basis).
    On a SELL, calculates realized PnL = (sell_usd) - (sell_tokens * avg_entry_price).
    Returns the new position state.
    """
    state = {
        "total_bought_usd": float(position_state.get("total_bought_usd", 0.0)),
        "total_buy_tokens": float(position_state.get("total_buy_tokens", 0.0)),
        "total_sold_usd": float(position_state.get("total_sold_usd", 0.0)),
        "total_sell_tokens": float(position_state.get("total_sell_tokens", 0.0)),
        "realized_pnl": float(position_state.get("realized_pnl", 0.0)),
    }
    
    side = trade.get("side", "BUY")
    usd_volume = float(trade.get("usd_volume", 0.0))
    token_size = float(trade.get("token_size", 0.0))
    
    if side == "BUY":
        state["total_bought_usd"] += usd_volume
        state["total_buy_tokens"] += token_size
    else: # SELL
        # Cost Basis Calculation
        # average entry price = total_bought_usd / total_buy_tokens
        avg_entry_price = 0.0
        if state["total_buy_tokens"] > 0:
            avg_entry_price = state["total_bought_usd"] / state["total_buy_tokens"]
        
        cost_of_sold_tokens = token_size * avg_entry_price
        
        state["total_sold_usd"] += usd_volume
        state["total_sell_tokens"] += token_size
        state["realized_pnl"] += (usd_volume - cost_of_sold_tokens)
        
    return state


def apply_redemption(position_state: dict, redemption: dict) -> dict:
    """
    Applies a market resolution payout.
    Sets cash_pnl = payout - (remaining_tokens * avg_entry_price).
    Sets is_resolved = True.
    """
    state = {
        "total_bought_usd": float(position_state.get("total_bought_usd", 0.0)),
        "total_buy_tokens": float(position_state.get("total_buy_tokens", 0.0)),
        "total_sold_usd": float(position_state.get("total_sold_usd", 0.0)),
        "total_sell_tokens": float(position_state.get("total_sell_tokens", 0.0)),
        "realized_pnl": float(position_state.get("realized_pnl", 0.0)),
        "cash_pnl": 0.0,
        "is_resolved": True,
        "is_win": False
    }
    
    payout = float(redemption.get("payout", 0.0))
    
    avg_entry_price = 0.0
    if state["total_buy_tokens"] > 0:
        avg_entry_price = state["total_bought_usd"] / state["total_buy_tokens"]
        
    remaining_tokens = state["total_buy_tokens"] - state["total_sell_tokens"]
    if remaining_tokens < 0:
        remaining_tokens = 0.0
        
    cost_of_remaining_tokens = remaining_tokens * avg_entry_price
    
    state["cash_pnl"] = payout - cost_of_remaining_tokens
    state["is_win"] = (state["realized_pnl"] + state["cash_pnl"]) > 0
    
    return state
