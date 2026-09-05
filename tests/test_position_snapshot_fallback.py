import csv
import io
import zipfile

import pytest

from src.workers import wallet_trade_history


def _snapshot(rows: list[tuple[str, str]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(["conditionId", "asset", "size", "curPrice", "valuationTime"])
        for condition_id, asset in rows:
            writer.writerow([condition_id, asset, "1", "0", "2026-09-01T00:00:00Z"])
        archive.writestr("positions.csv", text.getvalue())
    return output.getvalue()


class _Response:
    status = 200

    def __init__(self, *, data=None, payload=b""):
        self.data = data
        self.payload = payload

    async def json(self):
        return self.data

    async def read(self):
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, snapshot_rows, partition_rows):
        self.snapshot_rows = snapshot_rows
        self.partition_rows = partition_rows

    def get(self, url, **kwargs):
        if url.endswith("/accounting/snapshot"):
            return _Response(payload=_snapshot(self.snapshot_rows))
        if kwargs.get("params"):
            return _Response(data=self.partition_rows)
        return _Response(data=[
            {"conditionId": f"old-{i}", "asset": f"old-asset-{i}"}
            for i in range(500)
        ])


@pytest.mark.asyncio
async def test_capped_positions_are_replaced_by_complete_snapshot_inventory(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    monkeypatch.setattr(wallet_trade_history, "POSITIONS_MAX_OFFSET", 0)
    expected = [("condition-a", "asset-a"), ("condition-b", "asset-b")]
    partition = [
        {"conditionId": condition_id, "asset": asset, "initialValue": 10}
        for condition_id, asset in expected
    ]

    rows, complete = await wallet_trade_history.fetch_positions(
        _Session(expected, partition), "0xwallet"
    )

    assert complete is True
    assert {(row["conditionId"], row["asset"]) for row in rows} == set(expected)


@pytest.mark.asyncio
async def test_missing_snapshot_position_is_never_reported_complete(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    monkeypatch.setattr(wallet_trade_history, "POSITIONS_MAX_OFFSET", 0)
    expected = [("condition-a", "asset-a"), ("condition-b", "asset-b")]
    partition = [{"conditionId": "condition-a", "asset": "asset-a"}]

    _rows, complete = await wallet_trade_history.fetch_positions(
        _Session(expected, partition), "0xwallet"
    )

    assert complete is False
