import uuid

import pytest
import pytest_asyncio

from src.research.analytics import ResearchAnalytics, ResultSetAccessError
from src.research.contracts import (
    FindWalletsArgs,
    MarketParticipantsArgs,
    MarketsTradedArgs,
    OutcomeConsensusArgs,
    PositionOverlapArgs,
    SameOutcomeHistoryArgs,
)
from src.research.repository import ResearchRepository


def _wallet(i: int) -> str:
    return f"0x{'e'*34}{i:04d}"


def _market(tag: str) -> str:
    return f"research-test-{tag}-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def research_user(test_pool):
    email = f"research-analytics-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            email, "mock_hash",
        )
    owner_id = str(user_id)
    yield owner_id
    async with test_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id = $1::uuid", owner_id)


@pytest_asyncio.fixture
async def discovery_seed(test_pool):
    """Three wallets separating strict threshold from evidence floor."""
    w80, w70, w90thin = _wallet(1), _wallet(2), _wallet(3)
    async with test_pool.acquire() as conn:
        for addr, username in ((w80, "wallet80"), (w70, "wallet70"), (w90thin, "wallet90thin")):
            await conn.execute(
                "INSERT INTO wallets_v2 (address, username) VALUES ($1, $2)"
                " ON CONFLICT (address) DO UPDATE SET username = $2",
                addr, username,
            )
        await conn.execute(
            """INSERT INTO category_stats_v2
                   (address, category, subcategory, league, window_size, pnl, volume,
                    win_rate, roi_pct, resolved_count, winning_count)
               VALUES ($1, 'SPORTS', 'Cricket', 'T20', 0, 1000, 5000, 80, 20, 40, 32),
                      ($2, 'SPORTS', 'Cricket', 'T20', 0, 900, 4500, 70, 18, 40, 28),
                      ($3, 'SPORTS', 'Cricket', 'T20', 0, 2000, 6000, 90, 30, 10, 9)
               ON CONFLICT (address, category, subcategory, league, window_size)
               DO UPDATE SET pnl = EXCLUDED.pnl, volume = EXCLUDED.volume,
                             win_rate = EXCLUDED.win_rate, roi_pct = EXCLUDED.roi_pct,
                             resolved_count = EXCLUDED.resolved_count,
                             winning_count = EXCLUDED.winning_count""",
            w80, w70, w90thin,
        )
    yield {"w80": w80, "w70": w70, "w90thin": w90thin}
    async with test_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM category_stats_v2 WHERE address = ANY($1)",
            [w80, w70, w90thin],
        )
        await conn.execute("DELETE FROM wallets_v2 WHERE address = ANY($1)", [w80, w70, w90thin])


@pytest_asyncio.fixture
async def overlap_seed(test_pool, research_user):
    """Three wallets, one market each at full/partial/single coverage, plus history."""
    wallets = [_wallet(11), _wallet(12), _wallet(13)]
    market_a, market_b, market_c = _market("a"), _market("b"), _market("c")
    repo = ResearchRepository(test_pool)
    async with test_pool.acquire() as conn:
        for addr in wallets:
            await conn.execute(
                "INSERT INTO wallets_v2 (address, username) VALUES ($1, $2)"
                " ON CONFLICT (address) DO NOTHING",
                addr, f"overlap-{addr[-4:]}",
            )
            await conn.execute(
                """INSERT INTO wallet_metrics_v2 (address, win_rate, resolved_count, winning_count)
                   VALUES ($1, 80, 30, 24)
                   ON CONFLICT (address) DO UPDATE SET win_rate = 80, resolved_count = 30,
                     winning_count = 24""",
                addr,
            )
        for cid, title in ((market_a, "Overlap A"), (market_b, "Overlap B"), (market_c, "Overlap C")):
            await conn.execute(
                "INSERT INTO markets_v2 (condition_id, title, category, subcategory, league)"
                " VALUES ($1, $2, 'SPORTS', 'Cricket', 'T20') ON CONFLICT (condition_id) DO NOTHING",
                cid, title,
            )
        # Market A: all three wallets (two YES, one NO). B: two. C: one.
        positions = [
            (wallets[0], market_a, "YES", 10, 100), (wallets[1], market_a, "YES", 5, 50),
            (wallets[2], market_a, "NO", 7, 70),
            (wallets[0], market_b, "YES", 3, 30), (wallets[1], market_b, "YES", 4, 40),
            (wallets[0], market_c, "YES", 1, 10),
        ]
        for addr, cid, outcome, size, value in positions:
            await conn.execute(
                """INSERT INTO wallet_positions_v2
                       (address, condition_id, outcome, size, avg_price, current_value)
                   VALUES ($1, $2, $3, $4, 0.5, $5)
                   ON CONFLICT (address, condition_id, outcome)
                   DO UPDATE SET size = $4, current_value = $5""",
                addr, cid, outcome, size, value,
            )
        # Closed history: market A outcome YES shared by wallets 0 and 1.
        for addr in wallets[:2]:
            await conn.execute(
                """INSERT INTO wallet_closed_positions_v2
                       (address, condition_id, outcome, avg_buy_price, avg_sell_price,
                        total_bought, total_sold, realized_pnl, metrics_eligible)
                   VALUES ($1, $2, 'YES', 0.4, 0.9, 100, 100, 50, TRUE)
                   ON CONFLICT (address, condition_id, outcome) DO NOTHING""",
                addr, market_a,
            )
    chat = await repo.create_chat(research_user, "Overlap seed")
    saved = await repo.save_result_set(
        research_user, chat.chat_id, "wallet_set", "Overlap wallets",
        {"tool": "test"},
        [{"entity_type": "wallet", "entity_key": a, "payload": {}} for a in wallets],
    )
    yield {
        "owner": research_user, "chat": chat, "wallets": wallets,
        "market_a": market_a, "market_b": market_b, "market_c": market_c,
        "wallet_set": saved,
    }
    async with test_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM wallet_positions_v2 WHERE address = ANY($1) OR condition_id = ANY($2)",
            wallets, [market_a, market_b, market_c],
        )
        await conn.execute(
            "DELETE FROM wallet_closed_positions_v2 WHERE address = ANY($1) OR condition_id = ANY($2)",
            wallets, [market_a, market_b, market_c],
        )
        await conn.execute("DELETE FROM markets_v2 WHERE condition_id = ANY($1)", [market_a, market_b, market_c])
        await conn.execute("DELETE FROM category_stats_v2 WHERE address = ANY($1)", wallets)
        await conn.execute("DELETE FROM wallet_metrics_v2 WHERE address = ANY($1)", wallets)
        await conn.execute("DELETE FROM wallets_v2 WHERE address = ANY($1)", wallets)
        await conn.execute("DELETE FROM research_chats WHERE chat_id = $1", chat.chat_id)


@pytest.mark.asyncio
async def test_find_wallets_enforces_strict_threshold_and_floor(test_pool, discovery_seed):
    analytics = ResearchAnalytics(test_pool)
    rows = await analytics.find_wallets(
        FindWalletsArgs(category="SPORTS", subcategory="Cricket", league="T20",
                        min_win_rate=70, comparison="gt", min_resolved_count=20, limit=100)
    )
    assert [row["address"] for row in rows] == [discovery_seed["w80"]]
    assert rows[0]["scope"] == {
        "category": "SPORTS", "subcategory": "Cricket", "league": "T20", "window_size": 0,
    }


@pytest.mark.asyncio
async def test_find_wallets_gte_includes_boundary(test_pool, discovery_seed):
    analytics = ResearchAnalytics(test_pool)
    rows = await analytics.find_wallets(
        FindWalletsArgs(category="SPORTS", subcategory="Cricket", league="T20",
                        min_win_rate=70, comparison="gte", min_resolved_count=20, limit=100)
    )
    assert [row["address"] for row in rows] == [discovery_seed["w80"], discovery_seed["w70"]]


@pytest.mark.asyncio
async def test_scope_matching_ignores_case_only(test_pool, discovery_seed):
    analytics = ResearchAnalytics(test_pool)
    rows = await analytics.find_wallets(
        FindWalletsArgs(category="sports", subcategory="cricket", league="t20",
                        min_win_rate=70, comparison="gt", min_resolved_count=20, limit=100)
    )
    assert [row["address"] for row in rows] == [discovery_seed["w80"]]
    other = await analytics.find_wallets(
        FindWalletsArgs(category="SportsX", min_win_rate=0, comparison="gte",
                        min_resolved_count=1, limit=100)
    )
    assert other == []


@pytest.mark.asyncio
async def test_market_participants_require_open_unresolved_positions(test_pool, overlap_seed):
    analytics = ResearchAnalytics(test_pool)
    rows = await analytics.market_participants(
        MarketParticipantsArgs(condition_id=overlap_seed["market_a"])
    )
    by_address = {r["address"]: r for r in rows}
    assert set(by_address) == set(overlap_seed["wallets"])
    assert by_address[overlap_seed["wallets"][2]]["outcome"] == "NO"


@pytest.mark.asyncio
async def test_open_overlap_reports_exact_coverage_and_outcomes(test_pool, overlap_seed):
    analytics = ResearchAnalytics(test_pool)
    overlap = await analytics.open_position_overlap(
        overlap_seed["owner"],
        PositionOverlapArgs(wallet_result_set_id=overlap_seed["wallet_set"].result_set_id),
    )
    assert overlap[0]["condition_id"] == overlap_seed["market_a"]
    assert overlap[0]["wallet_count"] == 3
    assert overlap[0]["coverage_pct"] == 100.0
    assert overlap[0]["outcomes"] == {"NO": 1, "YES": 2}
    assert overlap[1]["condition_id"] == overlap_seed["market_b"]
    assert overlap[1]["coverage_pct"] == round(100.0 * 2 / 3, 2)


@pytest.mark.asyncio
async def test_cross_owner_result_reference_is_rejected(test_pool, overlap_seed, research_user):
    analytics = ResearchAnalytics(test_pool)
    repo = ResearchRepository(test_pool)
    other_email = f"research-other-{uuid.uuid4().hex[:8]}@example.com"
    async with test_pool.acquire() as conn:
        other_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            other_email, "mock_hash",
        )
    try:
        with pytest.raises(ResultSetAccessError):
            await analytics.open_position_overlap(
                str(other_id),
                PositionOverlapArgs(wallet_result_set_id=overlap_seed["wallet_set"].result_set_id),
            )
        assert await repo.page_result_members(
            str(other_id), overlap_seed["wallet_set"].result_set_id) is None
    finally:
        async with test_pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE user_id = $1", other_id)


@pytest.mark.asyncio
async def test_markets_traded_and_consensus_follow_saved_wallets(test_pool, overlap_seed):
    analytics = ResearchAnalytics(test_pool)
    owner = overlap_seed["owner"]
    wallet_set_id = overlap_seed["wallet_set"].result_set_id

    markets = await analytics.markets_traded(owner, MarketsTradedArgs(wallet_result_set_id=wallet_set_id))
    by_market = {m["condition_id"]: m for m in markets}
    assert by_market[overlap_seed["market_a"]]["wallet_count"] == 3
    assert by_market[overlap_seed["market_a"]]["open_wallets"] == 3

    consensus = await analytics.outcome_consensus(
        owner, OutcomeConsensusArgs(wallet_result_set_id=wallet_set_id,
                                   condition_id=overlap_seed["market_a"]))
    assert {r["outcome"] for r in consensus} == {"YES", "NO"}
    yes_row = next(r for r in consensus if r["outcome"] == "YES")
    assert yes_row["wallet_count"] == 2
    assert yes_row["wallet_pct"] == round(100.0 * 2 / 3, 2)


@pytest.mark.asyncio
async def test_same_outcome_history_uses_eligible_closed_rows(test_pool, overlap_seed):
    analytics = ResearchAnalytics(test_pool)
    history = await analytics.same_outcome_history(
        overlap_seed["owner"],
        SameOutcomeHistoryArgs(wallet_result_set_id=overlap_seed["wallet_set"].result_set_id,
                               min_wallet_count=2),
    )
    match = [h for h in history if h["condition_id"] == overlap_seed["market_a"]
             and h["outcome"] == "YES"]
    assert match and match[0]["wallet_count"] == 2
    assert "closed" in match[0]["sources"]


@pytest.mark.asyncio
async def test_scope_hint_lists_real_taxonomy_values(test_pool):
    analytics = ResearchAnalytics(test_pool)
    hint = await analytics.scope_hint(FindWalletsArgs(category="SPORTS", subcategory="Cricket"))
    assert hint
    assert {row["league"] for row in hint} >= {"", "IPL"}
    assert await analytics.scope_hint(FindWalletsArgs()) == []


@pytest.mark.asyncio
async def test_list_positions_owner_and_chat_scoped(test_pool):
    analytics = ResearchAnalytics(test_pool)
    repo = ResearchRepository(test_pool)

    # Create two users
    async with test_pool.acquire() as conn:
        owner_a = str(await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            f"owner-a-{uuid.uuid4().hex[:8]}@example.com", "mock_hash",
        ))
        owner_b = str(await conn.fetchval(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING user_id",
            f"owner-b-{uuid.uuid4().hex[:8]}@example.com", "mock_hash",
        ))

    chat_a = await repo.create_chat(owner_a, "Chat A")
    chat_other = await repo.create_chat(owner_a, "Chat Other")
    chat_b = await repo.create_chat(owner_b, "Chat B")

    w1, w2, w3, w4 = _wallet(31), _wallet(32), _wallet(33), _wallet(34)
    m_a, m_b, m_c, m_d = _market("pos_a"), _market("pos_b"), _market("pos_c"), _market("pos_d")

    wallets = [w1, w2, w3, w4]
    markets = [m_a, m_b, m_c, m_d]

    try:
        async with test_pool.acquire() as conn:
            for w in wallets:
                await conn.execute(
                    "INSERT INTO wallets_v2 (address, username) VALUES ($1, $2) ON CONFLICT (address) DO NOTHING",
                    w, f"pos-{w[-4:]}",
                )
            for m, title in ((m_a, "Market A Title"), (m_b, "Market B Title"), (m_c, "Market C Title"), (m_d, "Market D Title")):
                await conn.execute(
                    "INSERT INTO markets_v2 (condition_id, title) VALUES ($1, $2) ON CONFLICT (condition_id) DO NOTHING",
                    m, title,
                )

            # Positions:
            # w1: m_a (val 100, open), m_b (val 50, open)
            # w2: m_a (val 200, open), m_c (val 0, zero-value), m_d (val 80, resolved)
            # w3: m_a (val 300, open) - in chat_other
            # w4: m_a (val 400, open) - in chat_b
            pos_data = [
                (w1, m_a, "YES", 10, 10.0, 100.0, 15.0, False),
                (w1, m_b, "NO", 5, 10.0, 50.0, -5.0, False),
                (w2, m_a, "YES", 20, 10.0, 200.0, 25.0, False),
                (w2, m_c, "YES", 1, 0.0, 0.0, 0.0, False),       # zero-value
                (w2, m_d, "YES", 8, 10.0, 80.0, 0.0, True),        # resolved
                (w3, m_a, "YES", 30, 10.0, 300.0, 50.0, False),    # chat_other
                (w4, m_a, "YES", 40, 10.0, 400.0, 60.0, False),    # chat_b
            ]
            for addr, cid, outcome, size, avg_price, cur_val, un_pnl, is_res in pos_data:
                await conn.execute(
                    """INSERT INTO wallet_positions_v2
                           (address, condition_id, outcome, size, avg_price, current_value, unrealized_pnl, is_resolved)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       ON CONFLICT (address, condition_id, outcome)
                       DO UPDATE SET current_value = $6, is_resolved = $8""",
                    addr, cid, outcome, size, avg_price, cur_val, un_pnl, is_res,
                )

        # Save result sets
        await repo.save_result_set(
            owner_a, chat_a.chat_id, "wallet_set", "Chat A Wallets", {"tool": "test"},
            [{"entity_type": "wallet", "entity_key": w1, "payload": {}},
             {"entity_type": "wallet", "entity_key": w2, "payload": {}}],
        )
        await repo.save_result_set(
            owner_a, chat_other.chat_id, "wallet_set", "Chat Other Wallets", {"tool": "test"},
            [{"entity_type": "wallet", "entity_key": w3, "payload": {}}],
        )
        await repo.save_result_set(
            owner_b, chat_b.chat_id, "wallet_set", "Chat B Wallets", {"tool": "test"},
            [{"entity_type": "wallet", "entity_key": w4, "payload": {}}],
        )

        # Query chat_a under owner_a
        rows = await analytics.list_positions(owner_a, chat_a.chat_id, 0, 100)

        # Must contain only w1 and w2 open positions (3 rows total)
        assert len(rows) == 3
        # Deterministic ordering by current_value DESC
        assert [r["current_value"] for r in rows] == [200.0, 100.0, 50.0]
        assert [r["address"] for r in rows] == [w2, w1, w1]
        assert rows[0]["condition_id"] == m_a
        assert rows[0]["market_title"] == "Market A Title"
        assert rows[0]["outcome"] == "YES"
        assert rows[0]["size"] == 20.0
        assert rows[0]["avg_price"] == 10.0
        assert rows[0]["unrealized_pnl"] == 25.0
        assert "entry_at" in rows[0]
        assert "computed_at" in rows[0]

        # Zero-value (m_c) and resolved (m_d) positions must NOT appear
        assert m_c not in [r["condition_id"] for r in rows]
        assert m_d not in [r["condition_id"] for r in rows]

        # Wallets from another chat (w3) or another user (w4) must NOT appear
        assert w3 not in [r["address"] for r in rows]
        assert w4 not in [r["address"] for r in rows]

        # Pagination test: offset=1, limit=1
        page = await analytics.list_positions(owner_a, chat_a.chat_id, 1, 1)
        assert len(page) == 1
        assert page[0]["address"] == w1
        assert page[0]["current_value"] == 100.0

        # Cross-owner isolation: owner_b querying chat_a gets nothing
        cross_rows = await analytics.list_positions(owner_b, chat_a.chat_id, 0, 100)
        assert cross_rows == []

    finally:
        async with test_pool.acquire() as conn:
            await conn.execute("DELETE FROM wallet_positions_v2 WHERE address = ANY($1) OR condition_id = ANY($2)", wallets, markets)
            await conn.execute("DELETE FROM wallet_closed_positions_v2 WHERE address = ANY($1) OR condition_id = ANY($2)", wallets, markets)
            await conn.execute("DELETE FROM markets_v2 WHERE condition_id = ANY($1)", markets)
            await conn.execute("DELETE FROM wallets_v2 WHERE address = ANY($1)", wallets)
            await conn.execute("DELETE FROM research_chats WHERE chat_id = ANY($1)", [chat_a.chat_id, chat_other.chat_id, chat_b.chat_id])
            await conn.execute("DELETE FROM users WHERE user_id = ANY($1::uuid[])", [owner_a, owner_b])

