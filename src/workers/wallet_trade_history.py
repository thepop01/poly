"""
Wallet Trade History Worker

Vets UNCLASSIFIED wallets_v2 rows (the v2 discovery queue, fed by
trade_tracker / deposit_tracker / manual adds) and assigns a tier:
  - Balance = 0                     → DEAD
  - 0 < balance < $1k               → LOW_BALANCE
  - Balance ≥ $1k, never traded     → NEW
  - Balance ≥ $1k, stale > 30d      → STANDARD + is_dormant
  - Balance ≥ $1k, recent trade     → STANDARD (global list)

Assigning the tier is what removes a wallet from the queue.
Runs on a schedule (every 60s recommended).
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

BATCH_SIZE = 100       # wallets to process per run


def _parse(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def canonical_source(queue_source: str) -> str:
    """Map queue source strings ('trade_tracker', 'deposit_tracker',
    'Manual Queue', ...) to the canonical wallet_sources_v2 values."""
    s = (queue_source or "").lower()
    if "deposit" in s:
        return "deposit"
    if "trade" in s or "whale" in s:
        return "trade"
    if "leaderboard" in s:
        return "leaderboard"
    return "manual"


async def fetch_combo_activity(session: aiohttp.ClientSession, address: str) -> tuple[list[dict], list[dict]]:
    """Fetch open and closed combo parlay positions from Polymarket activity API."""
    open_combos = []
    closed_combos = []
    url = f"https://data-api.polymarket.com/activity?user={address}&limit=500"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list):
                    redeemed_cids = {
                        a.get("conditionId") for a in data 
                        if a.get("type") in ("REDEEM", "REDEMPTION") and a.get("conditionId")
                    }
                    
                    seen_open = set()
                    seen_closed = set()
                    
                    for a in data:
                        is_combo = a.get("isCombo") or "AND" in (a.get("title") or "")
                        if not is_combo:
                            continue
                            
                        cid = a.get("conditionId") or ""
                        event_type = (a.get("type") or "").upper()
                        
                        if event_type in ("REDEEM", "REDEMPTION") and cid and cid not in seen_closed:
                            seen_closed.add(cid)
                            closed_combos.append({
                                "conditionId": cid,
                                "asset": a.get("asset", ""),
                                "title": a.get("title", ""),
                                "totalBought": _parse(a.get("usdcSize")),
                                "avgPrice": _parse(a.get("price")),
                                "realizedPnl": _parse(a.get("usdcSize")),
                                "isCombo": True,
                                "category": "Sports",
                                "subcategory": "Sports",
                            })
                        elif event_type in ("TRADE", "BUY") and cid and cid not in redeemed_cids and cid not in seen_open:
                            seen_open.add(cid)
                            open_combos.append({
                                "conditionId": cid,
                                "asset": a.get("asset", ""),
                                "title": a.get("title", ""),
                                "size": _parse(a.get("size")),
                                "avgPrice": _parse(a.get("price")),
                                "currentValue": _parse(a.get("usdcSize")),
                                "realizedPnl": 0.0,
                                "cashPnl": 0.0,
                                "isCombo": True,
                                "category": "Sports",
                                "subcategory": "Sports",
                            })
    except Exception as e:
        logger.debug(f"Combo activity fetch error for {address}: {e}")
        
    return open_combos, closed_combos


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch all positions for a wallet from Polymarket Data API with pagination, including Open Combo Parlays."""
    all_positions = []
    offset = 0
    limit = 500

    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data:
                        break
                    if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                        break
                    all_positions.extend(data)
                    if len(data) < limit:
                        break
                    offset += limit
                else:
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch positions for {address} at offset {offset}: {e}")
            break

    # Merge Open Combo Parlay Positions
    open_combos, _ = await fetch_combo_activity(session, address)
    if open_combos:
        existing_cids = {p.get("conditionId") for p in all_positions if p.get("conditionId")}
        for combo in open_combos:
            if combo["conditionId"] not in existing_cids:
                all_positions.append(combo)

    return all_positions


async def fetch_closed_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch resolved/closed positions for a wallet, including Closed Combo Parlays. Hard cap: 5,000 positions."""
    MAX_CLOSED = 5000
    all_closed = []
    offset = 0
    limit = 50

    while len(all_closed) < MAX_CLOSED:
        url = f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data or not isinstance(data, list):
                        break
                    all_closed.extend(data)
                    if len(data) < limit:
                        break
                    offset += limit
                else:
                    offset += limit
                    await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Failed to fetch closed positions for {address} at offset {offset}: {e}")
            offset += limit
            await asyncio.sleep(1)

    # Merge Closed Combo Parlay Positions
    _, closed_combos = await fetch_combo_activity(session, address)
    if closed_combos:
        existing_cids = {p.get("conditionId") for p in all_closed if p.get("conditionId")}
        for combo in closed_combos:
            if combo["conditionId"] not in existing_cids:
                all_closed.append(combo)

    return all_closed[:MAX_CLOSED]



async def _get_tiered(session: aiohttp.ClientSession, url: str) -> list | dict | None:
    """Helper to fetch from Polymarket with progressive tiered timeouts: 10s, 30s, 60s, 90s, 150s."""
    timeouts = [10, 30, 60, 90, 150]
    for i, t in enumerate(timeouts):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=t)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            if i < len(timeouts) - 1:
                logger.debug(f"Timeout {t}s failed for {url}. Retrying with {timeouts[i+1]}s...")
                await asyncio.sleep(1)
                continue
            logger.warning(f"All tiered timeouts failed for {url}: {e}")
            return None
    return None


async def fetch_website_pnl(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Fetch all-time PnL/volume/rank/username from Polymarket's public leaderboard."""
    url = f"https://data-api.polymarket.com/v1/leaderboard?user={address}&category=OVERALL&timePeriod=ALL"
    data = await _get_tiered(session, url)
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    raw_name = (item.get("userName") or "").strip()[:255]
    if raw_name.lower().startswith("0x") and len(raw_name) > 10:
        raw_name = ""
    return {
        "pnl": _parse(item.get("pnl")),
        "volume": _parse(item.get("vol")),
        "rank": int(item.get("rank") or 0),
        "username": raw_name,
    }


async def fetch_all_trades(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Lightweight 1-trade fetch to get recent trade metadata without heavy pagination."""
    url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
    data = await _get_tiered(session, url)
    if isinstance(data, list):
        return data
    return []


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch exact portfolio balance from Alchemy."""
    from src.utils.alchemy_client import alchemy_get_token_balances, PUSD_CONTRACT
    try:
        b = await alchemy_get_token_balances(session, address, [PUSD_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance for {address}: {e}")
    return 0.0


async def _fetch_last_trade_dt(session: aiohttp.ClientSession, address: str) -> datetime | None:
    """Fetch the most recent trade timestamp using the correct ?user= param."""
    url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
    data = await _get_tiered(session, url)
    if isinstance(data, list) and data:
        ts = data[0].get("timestamp")
        if ts:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return None


async def process_batch(conn: asyncpg.Connection, session: aiohttp.ClientSession, wallets: list[dict]):
    """Vet UNCLASSIFIED wallets: fetch balance + positions + website_pnl,
    assign a tier. leaderboard_stats picks up promoted wallets via next_check_at."""
    BALANCE_THRESHOLD = 1000.0

    for item in wallets:
        address = item["address"]
        queue_source = item["source"]

        is_leaderboard = queue_source and "leaderboard" in queue_source.lower()

        try:
            balance = await fetch_balance(session, address)
            website = await fetch_website_pnl(session, address)
            last_trade_dt = await _fetch_last_trade_dt(session, address)
            # Only fetch positions for non-leaderboard wallets
            positions = [] if is_leaderboard else await fetch_positions(session, address)
        except Exception as e:
            # Leave the wallet UNCLASSIFIED — it will be retried next run
            # instead of being misclassified as DEAD on a transient failure.
            logger.warning(f"Error fetching data for wallet {address[:10]}..., will retry: {e}")
            continue

        # Compute position_value from open positions
        position_value = 0.0
        for pos in (positions or []):
            curr_val = _parse(pos.get("currentValue"))
            if curr_val > 0:
                position_value += curr_val

        # Use website_pnl/volume if available, else fallback to 0
        website_pnl = website["pnl"] if website else 0.0
        website_volume = website["volume"] if website else 0.0
        website_rank = website["rank"] if website else None
        username = website["username"] if website else ""

        # Total Capital = cash balance + open position value
        total_cap = balance + position_value

        # ── decide promotion ──
        # Vetting gate: total_cap (balance + position_value) + last_trade_at determine global list entry
        now = datetime.now(timezone.utc)
        is_dormant_flag = (last_trade_dt is None or (now - last_trade_dt) >= timedelta(days=30))

        if total_cap < BALANCE_THRESHOLD:
            # total_cap < $1k (including 0 capital) → LOW_BALANCE tier
            # is_dormant = TRUE if inactive > 30 days or never traded; FALSE if active in last 30 days
            tier_reason_str = 'zero capital' if total_cap <= 0 else 'capital < $1k at vetting'
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'LOW_BALANCE', $5, $4, $3, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier ELSE 'LOW_BALANCE' END,
                    tier_reason = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier_reason ELSE $5 END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                    is_dormant = $4,
                    updated_at = NOW()
            """, address, username, last_trade_dt, is_dormant_flag, tier_reason_str)
            logger.info(f"Low capital (<$1k, cap={total_cap:.0f}): {address[:10]}... marking LOW_BALANCE (dormant={is_dormant_flag})")
            continue

        # Balance > $1k — check last trade recency
        has_trades = last_trade_dt is not None
        now_utc = datetime.now(timezone.utc)

        if not has_trades:
            # Balance > $1k but no trades → New Wallets (Might Cook badge)
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'NEW', 'balance >= $1k, 0 trades', FALSE, NULL, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier ELSE 'NEW' END,
                    tier_reason = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier_reason ELSE 'balance >= $1k, 0 trades' END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    is_dormant = FALSE,
                    updated_at = NOW()
            """, address, username)
            logger.info(f"New wallet no trades: {address[:10]}... balance={balance:.0f} → NEW (Might Cook)")
            continue

        is_stale = (now_utc - last_trade_dt) >= timedelta(days=30)

        if is_stale:
            # Stale → STANDARD but dormant (hibernated) or PREVIOUSLY_CURATED if previously curated
            await conn.execute("""
                INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
                VALUES ($1, $2, 'STANDARD', 'hibernated: >30d inactive', TRUE, $3, NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    tier = CASE 
                        WHEN wallets_v2.tier = 'CURATED' THEN 'PREVIOUSLY_CURATED'
                        WHEN wallets_v2.tier = 'PREVIOUSLY_CURATED' THEN 'PREVIOUSLY_CURATED'
                        ELSE 'STANDARD'
                    END,
                    tier_reason = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier_reason ELSE 'hibernated: >30d inactive' END,
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                    last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                    is_dormant = TRUE,
                    updated_at = NOW()
            """, address, username, last_trade_dt)
            logger.info(f"Hibernating stale wallet: {address[:10]}... balance={balance:.0f} last_trade={last_trade_dt}")
            continue

        # ── Passed vetting: balance > $1k + recent trade → add to global list ──
        logger.info(f"Promoting {address[:10]}... balance={balance:.0f} pos_val={position_value:.0f} pnl=${website_pnl:.0f} vol=${website_volume:.0f}")

        await conn.execute("""
            INSERT INTO wallets_v2 (address, username, tier, tier_reason, is_dormant, last_trade_at, added_at, updated_at)
            VALUES ($1, $2, 'STANDARD', 'passed vetting', FALSE, $3, NOW(), NOW())
            ON CONFLICT (address) DO UPDATE SET
                tier = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN 'CURATED' ELSE 'STANDARD' END,
                tier_reason = CASE WHEN wallets_v2.tier IN ('CURATED', 'PREVIOUSLY_CURATED') THEN wallets_v2.tier_reason ELSE 'passed vetting' END,
                username = COALESCE(NULLIF(EXCLUDED.username, ''), wallets_v2.username),
                last_trade_at = GREATEST(COALESCE(wallets_v2.last_trade_at, EXCLUDED.last_trade_at), EXCLUDED.last_trade_at),
                is_dormant = FALSE,
                updated_at = NOW()
        """, address, username, last_trade_dt)

        await conn.execute("""
            INSERT INTO wallet_sources_v2 (address, source, source_detail, spotted_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (address, source) DO NOTHING
        """, address, canonical_source(queue_source), queue_source if queue_source else 'Unknown')

        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (
                address, balance, deposits, withdrawals, position_value,
                pm_pnl, pm_volume, pm_rank, computed_at
            ) VALUES ($1, $2, 0, 0, $3, $4, $5, $6, NOW())
            ON CONFLICT (address) DO UPDATE SET
                balance = EXCLUDED.balance,
                position_value = EXCLUDED.position_value,
                pm_pnl = EXCLUDED.pm_pnl,
                pm_volume = EXCLUDED.pm_volume,
                pm_rank = EXCLUDED.pm_rank,
                computed_at = NOW()
        """, address, balance, position_value, website_pnl, website_volume, website_rank)


async def run_discovery(pool: asyncpg.Pool | None = None, db_url: str = DB_URL):
    """Main entry point for the discovery worker."""
    logger.info("Starting wallet discovery worker...")
    
    own_pool = False
    if pool is None:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        own_pool = True

    try:
        async with pool.acquire() as conn:
            # The v2 discovery queue: UNCLASSIFIED wallets awaiting vetting
            rows = await conn.fetch(
                """
                SELECT address, tier_reason AS source FROM wallets_v2
                WHERE tier = 'UNCLASSIFIED'
                  AND (next_check_at IS NULL OR next_check_at <= NOW())
                ORDER BY added_at ASC LIMIT $1
                """,
                BATCH_SIZE
            )
            wallets = [{"address": r["address"], "source": r["source"]} for r in rows]
            logger.info(f"Found {len(wallets)} wallets to evaluate.")

            if wallets:
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    await process_batch(conn, session, wallets)
    finally:
        if own_pool and pool:
            await pool.close()
    logger.info("Discovery worker finished.")


async def main():
    """Infinite loop for the orchestrator."""
    import signal
    shutdown = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    logger.info("Starting Wallet Queue Processor (interval=60s)")
    while not shutdown.is_set():
        try:
            await run_discovery()
        except Exception:
            logger.exception("Error in wallet discovery queue processor")

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("Wallet Queue Processor shut down cleanly")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
