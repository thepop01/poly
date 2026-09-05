"""Tests for the shared position-sync market metadata upsert."""

import pytest

from src.workers.market_metadata import upsert_position_markets

FAKE_CIDS = [
    "0x" + "aa" * 31 + "01",
    "0x" + "aa" * 31 + "02",
    "0x" + "aa" * 31 + "03",
]


@pytest.mark.asyncio
async def test_creates_row_with_title_taxonomy(test_pool):
    async with test_pool.acquire() as conn:
        try:
            n = await upsert_position_markets(conn, [{
                "conditionId": FAKE_CIDS[0],
                "title": "Indian Premier League: Kolkata Knight Riders vs Delhi Capitals",
                "eventSlug": "cricipl-kol-del-2099-01-01",
            }])
            assert n == 1
            row = await conn.fetchrow(
                "SELECT title, category, subcategory, league, event_slug FROM markets_v2 "
                "WHERE condition_id = $1", FAKE_CIDS[0])
            assert row["category"] == "SPORTS"
            assert row["subcategory"] == "Cricket"
            assert row["league"] == "IPL"
            assert row["event_slug"] == "cricipl-kol-del-2099-01-01"
        finally:
            await conn.execute("DELETE FROM markets_v2 WHERE condition_id = ANY($1)", FAKE_CIDS)


@pytest.mark.asyncio
async def test_never_overwrites_curated_taxonomy(test_pool):
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO markets_v2 (condition_id, title, category, subcategory, league) "
                "VALUES ($1, '', 'SPORTS', 'Soccer', 'EPL') "
                "ON CONFLICT (condition_id) DO NOTHING", FAKE_CIDS[1])
            await upsert_position_markets(conn, [{
                "conditionId": FAKE_CIDS[1],
                "title": "Indian Premier League: Mumbai Indians vs Royals",
                "eventSlug": "cricipl-mum-raj-2099-01-01",
            }])
            row = await conn.fetchrow(
                "SELECT title, category, subcategory, league FROM markets_v2 "
                "WHERE condition_id = $1", FAKE_CIDS[1])
            assert (row["category"], row["subcategory"], row["league"]) == (
                "SPORTS", "Soccer", "EPL")
            assert "Mumbai Indians" in row["title"]
        finally:
            await conn.execute("DELETE FROM markets_v2 WHERE condition_id = ANY($1)", FAKE_CIDS)


@pytest.mark.asyncio
async def test_upgrades_other_and_skips_empty_payloads(test_pool):
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO markets_v2 (condition_id, category) VALUES ($1, 'OTHER') "
                "ON CONFLICT (condition_id) DO NOTHING", FAKE_CIDS[2])
            n = await upsert_position_markets(conn, [
                {"conditionId": FAKE_CIDS[2], "title": "NBA Finals: Celtics vs Mavericks",
                 "eventSlug": ""},
                {"conditionId": "", "title": "No ID here", "eventSlug": ""},
                {"conditionId": "0x" + "bb" * 32},
            ])
            assert n == 1
            row = await conn.fetchrow(
                "SELECT category, subcategory, league FROM markets_v2 WHERE condition_id = $1",
                FAKE_CIDS[2])
            assert row["category"] == "SPORTS"
            assert row["subcategory"] == "Basketball"
            assert row["league"] == "NBA"
            assert await conn.fetchval(
                "SELECT COUNT(*) FROM markets_v2 WHERE condition_id = $1",
                "0x" + "bb" * 32) == 0
        finally:
            await conn.execute("DELETE FROM markets_v2 WHERE condition_id = ANY($1)", FAKE_CIDS)
