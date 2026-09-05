from src.utils.polymarket_rate_limit import DEFAULT_LIMITS


def test_data_api_limit_configuration_is_explicit_and_nonzero():
    assert set(DEFAULT_LIMITS) == {"positions", "closed-positions", "trades", "activity"}
    for rate, capacity in DEFAULT_LIMITS.values():
        assert rate > 0
        assert capacity >= 1
