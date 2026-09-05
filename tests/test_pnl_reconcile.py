from src.pnl.reconcile import reconcile_wallet, classify_wallet


def test_simple_directional_trader_reconciles():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 1000,
               "avgPrice": 0.40, "initialValue": 400.0, "realizedPnl": 600.0}]
    open_rows = [{"conditionId": "0x2", "outcome": "Yes", "totalBought": 500,
                  "avgPrice": 0.20, "initialValue": 100.0,
                  "currentValue": 150.0}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=650.0)
    assert result.realized == 600.0
    assert result.unrealized == 50.0
    assert result.total_pnl == 650.0
    assert result.residual == 0.0


def test_phantom_loss_on_open_side_is_neutralised():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 1000,
               "avgPrice": 0.52, "initialValue": 520.0, "realizedPnl": 480.0}]
    # Minted residual reported as a million-dollar drawdown on zero cash.
    open_rows = [{"conditionId": "0x1", "outcome": "No", "totalBought": 0,
                  "avgPrice": 0.50, "initialValue": 1_010_133.42,
                  "currentValue": 0.0, "redeemable": True}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=480.0)
    assert result.unrealized == 0.0
    assert result.total_pnl == 480.0


def test_orphan_synthetic_leg_is_not_dropped_or_invented():
    closed = []
    open_rows = [{"conditionId": "0x9", "outcome": "No", "totalBought": 100,
                  "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
                  "currentValue": 0.0, "redeemable": True}]
    result = reconcile_wallet(closed, open_rows, pm_pnl=0.0)
    assert result.unrealized == -50.0
    assert result.dropped_synthetic_legs == 0


def test_opposite_outcome_rows_are_summed_independently():
    closed = []
    open_rows = [
        {"conditionId": "0x9", "outcome": "Yes", "totalBought": 100,
         "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
         "currentValue": 100.0},
        {"conditionId": "0x9", "outcome": "No", "totalBought": 100,
         "avgPrice": 0.50, "totalSold": 0, "initialValue": 50.0,
         "currentValue": 0.0},
    ]
    result = reconcile_wallet(closed, open_rows, pm_pnl=0.0)
    # Paid 100 for the set, holding 100 of value: net zero.
    assert result.unrealized == 0.0
    assert result.dropped_synthetic_legs == 0


def test_residual_and_relative_error_are_reported():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
               "avgPrice": 0.50, "initialValue": 50.0, "realizedPnl": 50.0}]
    result = reconcile_wallet(closed, [], pm_pnl=100.0)
    assert result.total_pnl == 50.0
    assert result.residual == -50.0
    assert result.relative_error == 50.0


def test_relative_error_is_zero_when_pm_pnl_is_zero():
    result = reconcile_wallet([], [], pm_pnl=0.0)
    assert result.total_pnl == 0.0
    assert result.relative_error == 0.0


def test_empty_wallet_is_flagged_as_no_data():
    result = reconcile_wallet([], [], pm_pnl=8_052_184.54)
    assert result.source == "no_position_data"


def test_populated_wallet_is_flagged_as_directional():
    closed = [{"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
               "avgPrice": 0.30, "initialValue": 30.0, "realizedPnl": 70.0}]
    result = reconcile_wallet(closed, [], pm_pnl=50.0)
    assert result.source == "directional"


def _row(**kw):
    base = {"conditionId": "0x1", "outcome": "Yes", "totalBought": 100,
            "avgPrice": 0.30, "totalSold": 50, "initialValue": 30.0}
    base.update(kw)
    return base


def test_wallet_with_no_rows_is_no_position_data():
    assert classify_wallet([], [], pm_pnl=8_052_184.0) == "no_position_data"


def test_wallet_dominated_by_synthetic_mints_is_a_minter():
    rows = [_row(conditionId=f"0x{i}", avgPrice=0.5, totalSold=0)
            for i in range(30)]
    rows += [_row(conditionId="0xzz")]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "complete_set_minter"


def test_wallet_at_the_closed_positions_ceiling_is_truncated():
    rows = [_row(conditionId=f"0x{i}") for i in range(30_000)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "truncated_history"


def test_ordinary_wallet_is_directional():
    rows = [_row(conditionId=f"0x{i}") for i in range(50)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "directional"


def test_minter_check_precedes_truncation_check():
    # A minter that also hit the ceiling is still primarily a minter.
    rows = [_row(conditionId=f"0x{i}", avgPrice=0.5, totalSold=0)
            for i in range(30_000)]
    assert classify_wallet(rows, [], pm_pnl=1_000.0) == "complete_set_minter"
