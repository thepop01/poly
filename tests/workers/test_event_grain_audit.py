from src.workers.wallet_provenance_audit import classify_position_coverage


def test_conversion_on_sibling_question_authorizes_minted_leg():
    positions = [
        {"condition_id": "0xA", "event_id": "evt_1", "total_size": 99999.0},
        {"condition_id": "0xB", "event_id": "evt_1", "total_size": 1392932.0},
    ]
    activity = [{"type": "CONVERSION", "conditionId": "0xA", "event_id": "evt_1"}]
    result = classify_position_coverage(positions, activity)
    assert result["0xB"] == "conversion_authorized"
    assert result["0xA"] == "direct_buy" or result["0xA"] == "conversion_authorized"
