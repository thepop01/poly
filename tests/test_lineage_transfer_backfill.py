from src.workers.lineage_transfer_backfill import CTF_CONTRACT, _transfer_rows


def test_ctf_erc1155_metadata_expands_to_token_grain_rows():
    rows = _transfer_rows({
        "rawContract": {"address": CTF_CONTRACT},
        "from": "0x1111111111111111111111111111111111111111",
        "to": "0x2222222222222222222222222222222222222222",
        "hash": "0xabc",
        "blockNum": "0x10",
        "logIndex": "0x2",
        "metadata": {"blockTimestamp": "2026-09-01T00:00:00Z"},
        "erc1155Metadata": [{"tokenId": "123", "value": "4.5"}],
    })

    assert len(rows) == 1
    assert rows[0]["token_id"] == "123"
    assert rows[0]["amount"] == 4.5
    assert rows[0]["log_index"] == 2


def test_non_ctf_or_exchange_counterparty_is_not_lineage_evidence():
    not_ctf = _transfer_rows({"rawContract": {"address": "0x0"}})
    exchange = _transfer_rows({
        "rawContract": {"address": CTF_CONTRACT},
        "from": "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
        "to": "0x2222222222222222222222222222222222222222",
        "erc1155Metadata": [{"tokenId": "123", "value": "1"}],
    })

    assert not_ctf == []
    assert exchange == []
