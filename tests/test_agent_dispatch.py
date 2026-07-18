import pytest
from src.agents.dispatch import dispatch_actions


class FakeConn:
    def __init__(self):
        self.inserts = []
    async def execute(self, sql, *args):
        self.inserts.append((sql, args))


@pytest.mark.asyncio
async def test_notify_inserts_notification():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "Cheap YES", "trading_armed": False}
    actions = [{"action_type": "notify", "params": {"message": "fired!"}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "Test"},
                                      summary="current_price(0.1)lt0.15=True")
    assert any("notifications" in ins[0] for ins in conn.inserts)
    assert receipts[0]["action_type"] == "notify"


@pytest.mark.asyncio
async def test_trade_skipped_when_not_armed():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "T", "trading_armed": False}
    actions = [{"action_type": "trade", "params": {
        "market_id": "m1", "token_id": "t1", "side": "BUY",
        "outcome": "YES", "size_usdc": 10}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "T"},
                                      summary="x")
    assert receipts[0]["status"] == "skipped_disarmed"


@pytest.mark.asyncio
async def test_trade_dry_run_when_armed():
    conn = FakeConn()
    agent = {"agent_id": 1, "owner_id": 7, "name": "T", "trading_armed": True}
    actions = [{"action_type": "trade", "params": {
        "market_id": "m1", "token_id": "t1", "side": "BUY",
        "outcome": "YES", "size_usdc": 10}}]
    receipts = await dispatch_actions(conn, agent, actions,
                                      market={"market_id": "m1", "title": "T"},
                                      summary="x")
    assert receipts[0]["status"] == "dry_run"
    assert receipts[0]["sent"] is False
