import pytest
from src.agents.execution import (
    ExecutionBroker, DryRunBroker, PolymarketBroker,
    NotConfiguredError, OrderIntent, get_broker,
)


def test_dry_run_broker_records_but_does_not_send():
    broker = DryRunBroker()
    intent = OrderIntent(market_id="m1", token_id="t1", side="BUY",
                         outcome="YES", size_usdc=10.0, limit_price=0.5)
    receipt = broker.place_order(intent)
    assert receipt["status"] == "dry_run"
    assert receipt["sent"] is False
    assert broker.placed == [intent]


def test_polymarket_broker_refuses_without_keys():
    broker = PolymarketBroker()
    intent = OrderIntent(market_id="m1", token_id="t1", side="BUY",
                         outcome="YES", size_usdc=10.0, limit_price=0.5)
    with pytest.raises(NotConfiguredError):
        broker.place_order(intent)


def test_get_broker_defaults_to_dry_run(monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    assert isinstance(get_broker("polymarket"), DryRunBroker)


def test_dry_run_broker_is_execution_broker():
    assert isinstance(DryRunBroker(), ExecutionBroker)
