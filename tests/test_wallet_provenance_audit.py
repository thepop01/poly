from src.workers.wallet_provenance_audit import classify_row, normalize_outcome


CID = "0x" + "1" * 64


def test_equivalent_outcome_labels_do_not_mismatch():
    assert normalize_outcome("Anyone's Legend") == normalize_outcome("Anyones Legend")


def test_matching_activity_buy_marks_row_eligible():
    decision = classify_row(
        {"condition_id": CID, "outcome": "Up", "total_bought": 10, "avg_buy_price": 0.4},
        [],
        [{"conditionId": CID, "outcome": "Up", "type": "TRADE", "side": "BUY"}],
    )
    assert decision.status == "eligible"
    assert decision.reason == "activity_matching_buy"


def test_complementary_signature_requires_review():
    decision = classify_row(
        {"condition_id": CID, "outcome": "Yes", "total_bought": 10, "avg_buy_price": 0.6},
        [{"condition_id": CID, "outcome": "Up", "total_bought": 10, "avg_buy_price": 0.4}],
        [],
    )
    assert decision.status == "review_required"
    assert decision.reason == "complementary_unproven_signature"


def test_position_is_not_its_own_complementary_sibling():
    position = {
        "condition_id": "condition", "outcome": "Yes", "total_bought": 10,
        "avg_buy_price": 0.5,
    }
    decision = classify_row(position, [position], [])

    assert decision.status == "review_required"
    assert decision.reason == "absent_from_activity_requires_source_check"
