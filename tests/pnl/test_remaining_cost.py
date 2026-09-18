from src.pnl.rules import remaining_cost

def test_remaining_cost_uses_current_size():
    assert remaining_cost({"current_size": 500.0, "avg_price": 0.80}) == 400.0

def test_remaining_cost_ignores_initial_value():
    # Old formula: min(900, 800) = 800. New: 500 * 0.80 = 400
    row = {"current_size": 500.0, "avg_price": 0.80, "total_bought": 1000.0, "initial_value": 900.0}
    assert remaining_cost(row) == 400.0
