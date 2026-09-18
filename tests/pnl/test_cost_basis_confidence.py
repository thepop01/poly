from src.pnl.invariants import compute_cost_basis_confidence


def test_high_confidence():
    assert compute_cost_basis_confidence({"transfer_in_size": 0.0, "unattributed_size": 0.0}) == "high"


def test_low_on_transfer_in():
    assert compute_cost_basis_confidence({"transfer_in_size": 100.0, "unattributed_size": 0.0}) == "low"


def test_low_on_unattributed():
    assert compute_cost_basis_confidence({"transfer_in_size": 0.0, "unattributed_size": 50.0}) == "low"
