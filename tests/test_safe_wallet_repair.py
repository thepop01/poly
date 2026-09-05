import pytest

from src.scripts import repair_and_sync_wallet as repair


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.in_transaction = True

    async def __aexit__(self, *_args):
        self.conn.in_transaction = False


class _Conn:
    def __init__(self, old_count=5):
        self.old_count = old_count
        self.in_transaction = False
        self.executed = []

    async def fetchval(self, query, *_args):
        if "COUNT(*)" in query:
            return self.old_count
        return None

    async def execute(self, query, *_args):
        normalized = " ".join(query.split())
        if normalized.startswith("DELETE"):
            assert self.in_transaction
        self.executed.append(normalized)
        return "DELETE 5"

    async def fetchrow(self, *_args):
        return {
            "pm_pnl": 10,
            "total_pnl": 8,
            "total_volume": 20,
            "win_rate": 50,
            "winning_count": 1,
            "resolved_count": 2,
            "data_completeness_pct": 100,
        }

    def transaction(self):
        return _Transaction(self)


@pytest.mark.asyncio
async def test_incomplete_preflight_never_mutates_database(monkeypatch):
    async def closed(*_args):
        return [], False

    async def opened(*_args):
        return [], True

    monkeypatch.setattr(repair, "fetch_closed_positions", closed)
    monkeypatch.setattr(repair, "fetch_positions", opened)
    conn = _Conn()

    with pytest.raises(RuntimeError, match="incomplete"):
        await repair.repair_single_wallet(conn, object(), "0xabc", apply=True)

    assert conn.executed == []


@pytest.mark.asyncio
async def test_dry_run_passes_preflight_without_mutation(monkeypatch):
    async def closed(*_args):
        return [{"conditionId": "0x1", "outcome": "Yes"}], True

    async def opened(*_args):
        return [], True

    monkeypatch.setattr(repair, "fetch_closed_positions", closed)
    monkeypatch.setattr(repair, "fetch_positions", opened)
    conn = _Conn()

    result = await repair.repair_single_wallet(conn, object(), "0xabc")

    assert result["closed_count"] == 1
    assert conn.executed == []


@pytest.mark.asyncio
async def test_apply_replaces_rows_only_inside_transaction(monkeypatch):
    async def closed(*_args):
        return [{"conditionId": "0x1", "outcome": "Yes", "realizedPnl": 2}], True

    async def opened(*_args):
        return [], True

    async def inserted(*_args):
        return 1

    async def no_op(*_args):
        return 0

    monkeypatch.setattr(repair, "fetch_closed_positions", closed)
    monkeypatch.setattr(repair, "fetch_positions", opened)
    monkeypatch.setattr(repair, "upsert_closed_positions_v2", inserted)
    monkeypatch.setattr(repair, "aggregate_and_upsert_positions_v2", no_op)
    monkeypatch.setattr(repair, "sync_redeemable_positions", no_op)
    monkeypatch.setattr(repair, "compute_metrics_for_wallet", no_op)
    conn = _Conn()

    await repair.repair_single_wallet(conn, object(), "0xabc", apply=True)

    deletes = [query for query in conn.executed if query.startswith("DELETE")]
    assert len(deletes) == 2
