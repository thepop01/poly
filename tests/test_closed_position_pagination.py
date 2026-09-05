import pytest

from src.workers import wallet_trade_history


def _rows(start: int, count: int = 50) -> list[dict]:
    return [
        {"conditionId": f"0x{i:064x}", "outcome": "Yes", "realizedPnl": 1}
        for i in range(start, start + count)
    ]


class _Response:
    status = 200

    def __init__(self, data):
        self.data = data
        self.released = False

    async def json(self):
        return self.data

    def release(self):
        self.released = True


class _StatusResponse(_Response):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status


class _Request:
    def __init__(self, response):
        self.response = response

    def __await__(self):
        async def _value():
            return self.response

        return _value().__await__()

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **_kwargs):
        offset = int(url.split("offset=")[1].split("&")[0])
        return _Request(_Response(self.pages.get(offset, [])))


class _SequencedSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = {}

    def get(self, url, **_kwargs):
        offset = int(url.split("offset=")[1].split("&")[0])
        choices = self.pages.get(offset, [[]])
        call = self.calls.get(offset, 0)
        self.calls[offset] = call + 1
        return _Request(_Response(choices[min(call, len(choices) - 1)]))


class _PartialFailureSession:
    def get(self, url, **_kwargs):
        offset = int(url.split("offset=")[1].split("&")[0])
        if offset == 0:
            return _Request(_StatusResponse(_rows(0), 200))
        if offset == 50:
            return _Request(_StatusResponse([], 503))
        return _Request(_StatusResponse([], 200))


@pytest.mark.asyncio
async def test_short_page_is_a_complete_closed_history(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    rows, complete = await wallet_trade_history.fetch_closed_positions(
        _Session({0: _rows(0, 2)}), "0xwallet"
    )

    assert complete is True
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_repeated_boundary_page_is_deduplicated_and_incomplete(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    monkeypatch.setattr(wallet_trade_history, "CLOSED_POSITIONS_MAX_OFFSET", 100)
    first = _rows(0)
    boundary = _rows(50)
    session = _Session({0: first, 50: boundary, 100: boundary})

    rows, complete = await wallet_trade_history.fetch_closed_positions(
        session, "0xwallet"
    )

    assert complete is False
    assert len(rows) == 50
    assert len({(row["conditionId"], row["outcome"]) for row in rows}) == 50


@pytest.mark.asyncio
async def test_repeated_page_before_ceiling_is_incomplete_after_retries(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    first = _rows(0)
    boundary = _rows(50)
    session = _Session({0: first, 50: boundary, 100: boundary})

    rows, complete = await wallet_trade_history.fetch_closed_positions(
        session, "0xwallet"
    )

    assert complete is False
    assert len(rows) == 50


@pytest.mark.asyncio
async def test_transient_repeated_page_retries_without_partial_batch_state(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    first = _rows(0)
    boundary = _rows(50)
    session = _SequencedSession({
        0: [first],
        50: [boundary],
        100: [boundary, _rows(100)],
        150: [_rows(150, 2)],
    })

    rows, complete = await wallet_trade_history.fetch_closed_positions(
        session, "0xwallet"
    )

    assert complete is True
    assert len(rows) == 152


@pytest.mark.asyncio
async def test_failed_first_page_is_not_reported_complete(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    class FailedResponse(_Response):
        status = 503

    class FailedSession:
        def get(self, *_args, **_kwargs):
            return _Request(FailedResponse([]))

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    rows, complete = await wallet_trade_history.fetch_closed_positions(
        FailedSession(), "0xwallet"
    )

    assert rows == []
    assert complete is False


@pytest.mark.asyncio
async def test_failed_page_before_empty_page_does_not_create_false_completion(monkeypatch):
    async def no_combos(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(wallet_trade_history, "fetch_combo_activity", no_combos)
    rows, complete = await wallet_trade_history.fetch_closed_positions(
        _PartialFailureSession(), "0xwallet"
    )

    assert complete is False
    assert len(rows) == 50
