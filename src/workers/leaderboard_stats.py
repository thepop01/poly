"""
Leaderboard Stats Worker (Optimized)

Processes wallets in parallel with concurrent API calls per wallet.
Key optimizations:
  - Semaphore-controlled concurrency (default 10 workers, env STATS_WORKER_CONCURRENCY)
  - All API calls per wallet run concurrently via asyncio.gather
  - Minimal sleep between calls (30ms)
  - Batch DB writes
  - Trade capture capped at 2000 trades/wallet to avoid slow wallets blocking the queue
"""

import asyncio
import asyncpg
import aiohttp
import os
import signal
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from src.utils.alchemy_client import (
    fetch_capital_metrics,
    alchemy_get_token_balances,
    PUSD_CONTRACT,
)
from src.utils.category_classifier import classify_tags, flatten_subcategory
from src.workers.window_stats import compute_category_window_stats, select_headline_pnl, _parse_end
from src.workers.wallet_trade_history import fetch_all_trades

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = 300
BALANCE_THRESHOLD = 1000.0  # $1k minimum balance to qualify for global list
CONCURRENCY = int(os.environ.get("STATS_WORKER_CONCURRENCY", "10"))
WALLET_TIMEOUT = int(os.environ.get("STATS_WALLET_TIMEOUT", "600"))
API_DELAY = 0.03  # 30ms between sequential API calls within a wallet
SUPABASE_RATE_LIMIT = 30  # 30 calls per minute
SUPABASE_DELAY = 60.0 / SUPABASE_RATE_LIMIT  # 2 seconds between calls
_sb_semaphore = None  # Initialized in run_leaderboard_stats


def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _computed_volume(trades) -> float:
    v = 0.0
    for t in trades:
        v += _parse(t.get("size")) * _parse(t.get("price"))
    return v


# ── Closed-position persistence ───────────────────────────────────────────

async def get_latest_end_date(conn: asyncpg.Connection, address: str) -> datetime | None:
    """Get the most recent end_date among stored closed positions."""
    row = await conn.fetchrow(
        "SELECT MAX(end_date) as latest FROM wallet_closed_positions WHERE address = $1",
        address,
    )
    return row["latest"] if row and row["latest"] else None


async def upsert_closed_positions(conn: asyncpg.Connection, address: str, closed_list: list[dict]):
    """Persist resolved positions, deduped by (address, condition_id)."""
    if not closed_list:
        return
    rows = []
    for cp in closed_list:
        cid = cp.get("conditionId") or ""
        if not cid:
            continue
        title = cp.get("title") or ""
        rpnl = _parse(cp.get("realizedPnl"))
        total_bought = _parse(cp.get("totalBought"))
        avg_price = _parse(cp.get("avgPrice"))
        avg_sell_price = _parse(cp.get("avgSellPrice"))
        end_date = _parse_end(cp.get("endDate"))
        cat, subcat = classify_tags([title]) if title else ("Other", "General")
        flat_sub = flatten_subcategory(cat, subcat)
        rows.append((address, cid, title, rpnl, total_bought, avg_price, avg_sell_price, end_date, cat, flat_sub))
    if not rows:
        return
    await conn.executemany("""
        INSERT INTO wallet_closed_positions
            (address, condition_id, title, realized_pnl, total_bought, avg_price, avg_sell_price, end_date, category, subcategory)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (address, condition_id) DO UPDATE SET
            realized_pnl = EXCLUDED.realized_pnl,
            total_bought = EXCLUDED.total_bought,
            avg_price = EXCLUDED.avg_price,
            avg_sell_price = EXCLUDED.avg_sell_price,
            end_date = EXCLUDED.end_date,
            title = EXCLUDED.title,
            category = EXCLUDED.category,
            subcategory = EXCLUDED.subcategory,
            fetched_at = NOW()
    """, rows)


async def load_stored_closed_positions(conn: asyncpg.Connection, address: str) -> list[dict]:
    """Load all stored closed positions for a wallet, formatted as dicts matching the API shape."""
    rows = await conn.fetch(
        """SELECT condition_id, title, realized_pnl, total_bought, avg_price, end_date
           FROM wallet_closed_positions
           WHERE address = $1
           ORDER BY end_date DESC NULLS LAST""",
        address,
    )
    return [
        {
            "conditionId": r["condition_id"],
            "title": r["title"],
            "realizedPnl": float(r["realized_pnl"]),
            "totalBought": float(r["total_bought"]),
            "avgPrice": float(r["avg_price"] or 0),
            "endDate": r["end_date"].isoformat() if r["end_date"] else None,
        }
        for r in rows
    ]


async def fetch_incremental_closed_positions(
    session: aiohttp.ClientSession, address: str, since: datetime
) -> list[dict]:
    """Fetch only positions that resolved after `since`. Concurrent batch fetching.

    Assumes the Polymarket API returns positions in descending endDate order.
    Stops early once a full page is older than `since`.
    """
    all_new: list[dict] = []
    offset = 0
    limit = 50  # API caps closed-positions at 50/page
    batch_size = 10  # 10 concurrent pages per batch

    while True:
        urls = [
            f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset + i * limit}"
            for i in range(batch_size)
        ]

        results = await asyncio.gather(
            *[_get(session, url) for url in urls],
            return_exceptions=True
        )

        consecutive_old = 0
        hit_end = False
        any_page_empty = False
        for i, result in enumerate(results):
            if isinstance(result, Exception) or not result or not isinstance(result, list):
                continue

            for cp in result:
                end_date = _parse_end(cp.get("endDate"))
                if end_date and end_date > since:
                    all_new.append(cp)
                    consecutive_old = 0
                else:
                    consecutive_old += 1

            if len(result) < limit:
                any_page_empty = True

        # Full page of old items — we've caught up
        if consecutive_old >= limit:
            hit_end = True

        if any_page_empty and not any(
            isinstance(r, list) and len(r) == limit for r in results
        ):
            hit_end = True

        if hit_end:
            break

        offset += batch_size * limit
        await asyncio.sleep(API_DELAY)

    return all_new


# ── API Fetchers ──────────────────────────────────────────────────────────

async def _get(session: aiohttp.ClientSession, url: str) -> list | dict | None:
    """Single shared GET helper with progressive tiered timeouts: 10s, 30s, 60s, 90s, 150s."""
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


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_positions = []
    offset = 0
    limit = 500
    max_positions = 10000
    while len(all_positions) < max_positions:
        data = await _get(session, f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_positions.extend(data)
        if len(data) < limit:
            break
        offset += limit
        await asyncio.sleep(API_DELAY)
    return all_positions[:max_positions]


def _trim_closed_page(items: list[dict], newer_than_epoch: float | None) -> tuple[list[dict], bool]:
    """Split one newest-first closed-positions page against an epoch cursor.

    Returns (items strictly newer than the cursor, cursor_reached). Items with
    a missing timestamp are kept (idempotent upserts make that safe). Filters
    rather than breaking mid-page so intra-page ordering quirks can't drop
    newer items."""
    if newer_than_epoch is None:
        return list(items), False
    kept, reached = [], False
    for p in items:
        ts = p.get("timestamp")
        if ts is not None and float(ts) <= newer_than_epoch:
            reached = True
        else:
            kept.append(p)
    return kept, reached


async def fetch_closed_positions(
    session: aiohttp.ClientSession,
    address: str,
    newer_than_epoch: float | None = None,
) -> tuple[list[dict], bool]:
    """Fetch closed positions newest-first, up to 5000.

    newer_than_epoch: incremental cursor — stop paginating once positions at or
    before this epoch are reached, returning only the newer gap (its latest
    5000 if the gap is larger). None = full fetch.

    Returns (positions, complete). complete=False means the 120s deadline cut
    the fetch short with older data still unfetched — callers keeping an
    incremental cursor MUST NOT advance it then, or the unfetched tail becomes
    a permanent hole. Hitting the 5000 cap or the cursor counts as complete."""
    import time
    all_closed = []
    offset = 0
    limit = 50  # API caps closed-positions at 50/page
    max_closed = 5000
    batch_size = 20  # Fetch 20 pages concurrently per batch
    deadline = time.monotonic() + 120  # 120s max for this function
    finished_naturally = False

    while len(all_closed) < max_closed and time.monotonic() < deadline:
        remaining = max_closed - len(all_closed)
        pages_to_fetch = min(batch_size, remaining // limit + 1)

        # Build URLs for concurrent fetches. Newest-first is CRITICAL: the API's
        # default order is biggest-PnL-first, which for wallets past the 5000
        # cap would keep only their largest winners and silently drop losers.
        urls = [
            f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset + i * limit}&sortBy=TIMESTAMP&sortDirection=DESC"
            for i in range(pages_to_fetch)
        ]

        # Fetch all pages concurrently
        results = await asyncio.gather(
            *[_get(session, url) for url in urls],
            return_exceptions=True
        )

        # Process results in order, skip failed pages
        hit_end = False
        any_page_empty = False
        for i, result in enumerate(results):
            if isinstance(result, Exception) or not result or not isinstance(result, list):
                continue
            kept, reached = _trim_closed_page(result, newer_than_epoch)
            all_closed.extend(kept)
            if reached:
                hit_end = True  # older pages are all at/before the cursor
            if len(result) < limit:
                any_page_empty = True

        if any_page_empty and not any(
            isinstance(r, list) and len(r) == limit for r in results
        ):
            hit_end = True

        if hit_end:
            finished_naturally = True
            break

        offset += pages_to_fetch * limit
        await asyncio.sleep(API_DELAY)

    # Complete = reached the end of data / the cursor (natural), or filled the
    # 5000 cap (intended truncation). Anything else = the deadline cut us off.
    complete = finished_naturally or len(all_closed) >= max_closed
    return all_closed[:max_closed], complete


async def fetch_trades_after(session: aiohttp.ClientSession, address: str, cutoff: datetime, max_trades: int = 2500) -> list[dict]:
    all_trades = []
    limit = 500
    for role in ("maker", "taker"):
        offset = 0
        while len(all_trades) < max_trades:
            data = await _get(session, f"https://data-api.polymarket.com/trades?{role}={address}&limit={limit}&offset={offset}")
            if not data or not isinstance(data, list):
                break
            for t in data:
                ts = t.get("timestamp")
                if ts:
                    try:
                        trade_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    except Exception:
                        trade_dt = datetime.now(timezone.utc)
                else:
                    trade_dt = datetime.now(timezone.utc)
                if trade_dt >= cutoff:
                    all_trades.append(t)
                elif trade_dt < cutoff - timedelta(days=1):
                    return all_trades[:max_trades]
            if len(data) < limit:
                break
            offset += limit
            if offset > 5000:
                break
            await asyncio.sleep(API_DELAY)
    return all_trades[:max_trades]


async def fetch_website_pnl(session: aiohttp.ClientSession, address: str) -> dict | None:
    data = await _get(session, f"https://data-api.polymarket.com/v1/leaderboard?user={address}&category=OVERALL&timePeriod=ALL")
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


async def fetch_category_pnl(session: aiohttp.ClientSession, address: str, category: str) -> dict | None:
    data = await _get(session, f"https://data-api.polymarket.com/v1/leaderboard?category={category}&timePeriod=ALL&proxyWallet={address}&limit=1")
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    return {"pnl": _parse(item.get("pnl")), "volume": _parse(item.get("vol"))}


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    try:
        b = await asyncio.wait_for(
            alchemy_get_token_balances(session, address, [PUSD_CONTRACT]),
            timeout=10,
        )
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception:
        pass
    return 0.0


SUPABASE_URL = "https://gzydspfquuaudqeztorw.supabase.co/functions/v1/public-api"
SUPABASE_KEY = "psk_d679feca8ad644ddb3ced58992421de0"

PM_CATEGORIES = ["SPORTS", "POLITICS", "CRYPTO", "ESPORTS", "CULTURE", "TECH", "FINANCE", "ECONOMICS", "WEATHER"]


async def fetch_supabase_wallet_profile(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Fetch win_rate, roi, resolved_count, last_trade_at from Supabase PolymarketScan wallet_profile.
    Rate limited to 30 calls per minute."""
    global _sb_semaphore
    if _sb_semaphore is None:
        _sb_semaphore = asyncio.Semaphore(1)  # Single permit = sequential calls
    
    async with _sb_semaphore:
        try:
            url = f"{SUPABASE_URL}?endpoint=wallet_profile&address={address}"
            headers = {"x-api-key": SUPABASE_KEY}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 429:
                    logger.warning(f"Supabase rate limited for {address[:10]}..., waiting 60s")
                    await asyncio.sleep(60)
                    return None
                if resp.status != 200:
                    return None
                body = await resp.json()
                data = body.get("data", {})
                if not data:
                    return None
                win_rate = data.get("win_rate")
                roi = data.get("roi")
                wins = data.get("wins")
                losses = data.get("losses")
                last_trade_at = data.get("last_trade_date")
                # wallet_profile returns win_rate as 0-100 integer, normalize to 0-1
                wr = _parse(win_rate) / 100.0 if win_rate is not None else None
                # Use wins/losses for resolved_count (num_trades is capped at 100k)
                resolved = int(_parse(wins)) + int(_parse(losses))
                winning = int(_parse(wins))
                # Parse last_trade_at if it's a string timestamp
                last_trade_dt = None
                if last_trade_at:
                    try:
                        if isinstance(last_trade_at, str):
                            last_trade_dt = datetime.fromisoformat(last_trade_at.replace("Z", "+00:00"))
                        elif isinstance(last_trade_at, (int, float)):
                            last_trade_dt = datetime.fromtimestamp(last_trade_at, tz=timezone.utc)
                    except Exception:
                        pass
                return {
                    "win_rate": wr if wr is not None else None,
                    "roi_pct": _parse(roi),
                    "resolved_count": resolved,
                    "winning_count": winning,
                    "last_trade_at": last_trade_dt,
                }
        except Exception as e:
            logger.debug(f"Supabase wallet_profile fetch failed for {address[:10]}...: {e}")
            return None
        finally:
            await asyncio.sleep(SUPABASE_DELAY)


# ── Compute Functions ─────────────────────────────────────────────────────


async def aggregate_and_upsert_positions(conn, address, trades, closed_positions, open_positions):
    '''Aggregate positions and upsert to wallet_position_outcomes. Trades are ignored.'''
    pos_map = {} # (conditionId, asset) -> data

    # 1. Process closed positions first (they take precedence)
    for cp in closed_positions:
        cid = cp.get('conditionId')
        asset = cp.get('asset', '')
        if not cid: continue
        
        realized_pnl = _parse(cp.get('realizedPnl'))
        cash_pnl = _parse(cp.get('cashPnl'))
        pos_map[(cid, asset)] = {
            'outcome': cp.get('outcome', ''),
            'title': cp.get('title', ''),
            'opened_at': None,
            'closed_at': _parse_end(cp.get('endDate')),
            'status': 'win' if (realized_pnl + cash_pnl) > 0 else 'loss',
            'avg_buy_price': _parse(cp.get('avgPrice')),
            'avg_sell_price': _parse(cp.get('avgSellPrice')),
            'total_bought': _parse(cp.get('totalBought')),
            'total_sold': 0.0,
            'realized_pnl': realized_pnl,
            'n_buys': 0
        }
        
    # 2. Process open positions (skip if already closed)
    for p in open_positions:
        cid = p.get('conditionId')
        asset = p.get('asset', '')
        if not cid: continue
        key = (cid, asset)
        
        if key in pos_map:
            # Already closed, skip heuristic
            continue
            
        cur_price = _parse(p.get('curPrice'))
        
        # Near-worthless open position heuristic (curPrice < 0.03)
        status = 'loss' if cur_price < 0.03 else 'open'
        
        pos_map[key] = {
            'outcome': p.get('outcome', ''),
            'title': p.get('title', ''),
            'opened_at': None,
            'closed_at': _parse_end(p.get('endDate')) if status == 'loss' else None,
            'status': status,
            'avg_buy_price': _parse(p.get('avgPrice')),
            'avg_sell_price': 0.0,
            'total_bought': _parse(p.get('totalBought')),
            'total_sold': 0.0,
            'realized_pnl': _parse(p.get('cashPnl')) if status == 'loss' else 0.0,
            'n_buys': 0
        }

    # 3. Upsert
    rows = []
    for (cid, asset), data in pos_map.items():
        rows.append((
            address, cid, asset, data['outcome'], data['title'],
            data['opened_at'], data['closed_at'], data['status'],
            data['avg_buy_price'], data['total_bought'], data['total_sold'], 
            data['realized_pnl'], data['n_buys'], data['avg_sell_price']
        ))

    if rows:
        await conn.executemany('''
            INSERT INTO wallet_position_outcomes
            (address, condition_id, asset, outcome, title, opened_at, closed_at, status, avg_buy_price, total_bought, total_sold, realized_pnl, n_buy_trades, avg_sell_price)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (address, condition_id, asset) DO UPDATE SET
                outcome=EXCLUDED.outcome, title=EXCLUDED.title,
                opened_at=COALESCE(wallet_position_outcomes.opened_at, EXCLUDED.opened_at),
                closed_at=EXCLUDED.closed_at, status=EXCLUDED.status,
                avg_buy_price=EXCLUDED.avg_buy_price, total_bought=EXCLUDED.total_bought,
                total_sold=EXCLUDED.total_sold, realized_pnl=EXCLUDED.realized_pnl,
                n_buy_trades=EXCLUDED.n_buy_trades, avg_sell_price=EXCLUDED.avg_sell_price
        ''', rows)

async def compute_window_stats_from_db(conn, address):
    '''Computes multi-window win rate and price brackets directly from DB.'''
    stats = {}
    windows = [100, 300, 800, 1500, 2500, None]
    
    # 1. Brackets (wins/losses per price range for all resolved positions)
    brackets_row = await conn.fetchrow('''
        SELECT 
            SUM(CASE WHEN status='win' AND avg_buy_price < 0.10 THEN 1 ELSE 0 END) as w_10,
            SUM(CASE WHEN status='loss' AND avg_buy_price < 0.10 THEN 1 ELSE 0 END) as l_10,
            SUM(CASE WHEN status='win' AND avg_buy_price < 0.20 THEN 1 ELSE 0 END) as w_20,
            SUM(CASE WHEN status='loss' AND avg_buy_price < 0.20 THEN 1 ELSE 0 END) as l_20,
            SUM(CASE WHEN status='win' AND avg_buy_price < 0.30 THEN 1 ELSE 0 END) as w_30,
            SUM(CASE WHEN status='loss' AND avg_buy_price < 0.30 THEN 1 ELSE 0 END) as l_30,
            SUM(CASE WHEN status='win' AND avg_buy_price < 0.40 THEN 1 ELSE 0 END) as w_40,
            SUM(CASE WHEN status='loss' AND avg_buy_price < 0.40 THEN 1 ELSE 0 END) as l_40,
            SUM(CASE WHEN status='win' AND avg_buy_price > 0.70 THEN 1 ELSE 0 END) as w_70,
            SUM(CASE WHEN status='loss' AND avg_buy_price > 0.70 THEN 1 ELSE 0 END) as l_70,
            COUNT(*) FILTER(WHERE status='win') as total_wins,
            COUNT(*) FILTER(WHERE status IN ('win', 'loss')) as total_resolved
        FROM wallet_position_outcomes
        WHERE address = $1 AND status != 'open'
    ''', address)
    
    if brackets_row:
        stats['wins_below_10c'] = brackets_row['w_10'] or 0
        stats['losses_below_10c'] = brackets_row['l_10'] or 0
        stats['wins_below_20c'] = brackets_row['w_20'] or 0
        stats['losses_below_20c'] = brackets_row['l_20'] or 0
        stats['wins_below_30c'] = brackets_row['w_30'] or 0
        stats['losses_below_30c'] = brackets_row['l_30'] or 0
        stats['wins_below_40c'] = brackets_row['w_40'] or 0
        stats['losses_below_40c'] = brackets_row['l_40'] or 0
        stats['wins_above_70c'] = brackets_row['w_70'] or 0
        stats['losses_above_70c'] = brackets_row['l_70'] or 0
        
        tw = brackets_row['total_wins'] or 0
        tr = brackets_row['total_resolved'] or 0
        stats['win_rate_all'] = (tw / tr) if tr > 0 else 0.0
        stats['winning_count'] = tw
        stats['resolved_count'] = tr
    else:
        for k in ['wins_below_10c', 'losses_below_10c', 'wins_below_20c', 'losses_below_20c', 
                  'wins_below_30c', 'losses_below_30c', 'wins_below_40c', 'losses_below_40c', 
                  'wins_above_70c', 'losses_above_70c', 'winning_count', 'resolved_count']:
            stats[k] = 0
        stats['win_rate_all'] = 0.0

    # Use closed_at (endDate) for windowed win rates
    # "check position based on what it was opened not when it was closed" 
    # ^ (Updated: Actually using closed_at per user agreement on Option A for Position-Based tracking)
    for w in windows:
        if w is None:
            continue
        
        row = await conn.fetchrow(f'''
            WITH cutoff AS (
                SELECT closed_at 
                FROM wallet_position_outcomes 
                WHERE address = $1 AND closed_at IS NOT NULL AND status IN ('win','loss')
                ORDER BY closed_at DESC 
                OFFSET {w-1} LIMIT 1
            )
            SELECT 
                COUNT(*) FILTER (WHERE status = 'win') AS wins,
                COUNT(*) FILTER (WHERE status IN ('win','loss')) AS resolved
            FROM wallet_position_outcomes
            WHERE address = $1
              AND closed_at >= COALESCE((SELECT closed_at FROM cutoff), '1970-01-01'::timestamptz)
              AND closed_at IS NOT NULL
              AND status != 'open'
        ''', address)
        
        wr = 0.0
        if row and row['resolved'] and row['resolved'] > 0:
            wr = row['wins'] / row['resolved']
        stats[f'win_rate_{w}'] = wr

    return stats

def compute_stats(positions, closed_positions, headline_pnl, headline_volume, start_stats_at, peak_capital):
    total_volume = 0.0
    max_trade_size = 0.0
    buy_prices: list[float] = []
    buys_below_10c = buys_below_20c = buys_below_30c = buys_below_40c = buys_above_70c = 0
    active_days = 0 # No longer calculated per-trade

    resolved_count = 0
    winning_count = 0
    biggest_win = 0.0
    biggest_loss = 0.0

    wins_below_10c = wins_below_20c = wins_below_30c = wins_below_40c = wins_above_70c = 0
    losses_below_10c = losses_below_20c = losses_below_30c = losses_below_40c = losses_above_70c = 0

    # ── 1. Process Open Positions ──
    for p in positions:
        avg_p = _parse(p.get("avgPrice"))
        total_bought = _parse(p.get("totalBought"))
        cur_price = _parse(p.get("curPrice"))
        
        # Volume & Max Trade Size approximation
        total_volume += total_bought
        if total_bought > max_trade_size:
            max_trade_size = total_bought
            
        # Buy price distribution
        if avg_p > 0:
            buy_prices.append(avg_p)
            if avg_p < 0.10: buys_below_10c += 1
            elif avg_p < 0.20: buys_below_20c += 1
            elif avg_p < 0.30: buys_below_30c += 1
            elif avg_p < 0.40: buys_below_40c += 1
            elif avg_p > 0.70: buys_above_70c += 1

        # Triangle Logic: Near-worthless open position -> Loss
        if cur_price < 0.03:
            resolved_count += 1
            cash_pnl = _parse(p.get("cashPnl"))
            if cash_pnl < biggest_loss:
                biggest_loss = cash_pnl
            
            if avg_p > 0:
                if avg_p < 0.10: losses_below_10c += 1
                elif avg_p < 0.20: losses_below_20c += 1
                elif avg_p < 0.30: losses_below_30c += 1
                elif avg_p < 0.40: losses_below_40c += 1
                elif avg_p > 0.70: losses_above_70c += 1

    # ── 2. Process Closed Positions ──
    for p in closed_positions:
        realized_pnl = _parse(p.get("realizedPnl"))
        avg_p = _parse(p.get("avgPrice"))
        total_bought = _parse(p.get("totalBought"))
        total_sold = _parse(p.get("totalSold"))
        cash_pnl = _parse(p.get("cashPnl"))
        
        # Volume & Max Trade Size approximation
        total_volume += (total_bought + total_sold)
        if total_bought > max_trade_size:
            max_trade_size = total_bought
            
        # Resolved stats
        resolved_count += 1
        won = (realized_pnl + cash_pnl) > 0
        if won:
            winning_count += 1
            if realized_pnl > biggest_win:
                biggest_win = realized_pnl
        else:
            if realized_pnl < biggest_loss:
                biggest_loss = realized_pnl
                
        if avg_p > 0:
            buy_prices.append(avg_p)
            if avg_p < 0.10:
                if won: wins_below_10c += 1
                else: losses_below_10c += 1
            elif avg_p < 0.20:
                if won: wins_below_20c += 1
                else: losses_below_20c += 1
            elif avg_p < 0.30:
                if won: wins_below_30c += 1
                else: losses_below_30c += 1
            elif avg_p < 0.40:
                if won: wins_below_40c += 1
                else: losses_below_40c += 1
            if avg_p > 0.70:
                if won: wins_above_70c += 1
                else: losses_above_70c += 1

    avg_buy_price = sum(buy_prices) / len(buy_prices) if buy_prices else 0.0

    # Fallback to headline metrics
    effective_volume = max(total_volume, headline_volume)
    effective_pnl = headline_pnl

    win_rate = (winning_count / resolved_count) if resolved_count > 0 else 0.0
    
    # Calculate ROI using Peak Capital logic
    if peak_capital is not None and peak_capital > 0:
        roi_pct = (effective_pnl / peak_capital) * 100
    else:
        # Fallback if peak_capital is somehow missing (e.g., Alchemy failure)
        roi_pct = (effective_pnl / effective_volume * 100) if effective_volume > 0 else 0.0

    return {
        "total_volume": effective_volume, "total_pnl": effective_pnl,
        "win_rate": win_rate, "roi_pct": roi_pct,
        "resolved_count": resolved_count, "winning_count": winning_count,
        "max_trade_size": max_trade_size,
        "biggest_win": biggest_win, "biggest_loss": biggest_loss,
        "active_days": active_days,
        "avg_buy_price": avg_buy_price,
        "buys_below_10c": buys_below_10c, "buys_below_20c": buys_below_20c,
        "buys_below_30c": buys_below_30c, "buys_below_40c": buys_below_40c,
        "buys_above_70c": buys_above_70c,
        "wins_below_10c": wins_below_10c, "wins_below_20c": wins_below_20c,
        "wins_below_30c": wins_below_30c, "wins_below_40c": wins_below_40c,
        "wins_above_70c": wins_above_70c,
        "losses_below_10c": losses_below_10c, "losses_below_20c": losses_below_20c,
        "losses_below_30c": losses_below_30c, "losses_below_40c": losses_below_40c,
        "losses_above_70c": losses_above_70c,
    }


def compute_wallet_tags(trades):
    if not trades:
        return {"category": "Other", "subcategory": "General", "trade_count": 0, "top_markets": []}
    market_titles = []
    market_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    subcategory_counts: dict[str, int] = {}
    for t in trades:
        title = t.get("title") or t.get("market_name") or ""
        if title:
            market_titles.append(title)
            market_counts[title] = market_counts.get(title, 0) + 1
        cat = t.get("category")
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        sub = t.get("subcategory")
        if sub:
            subcategory_counts[sub] = subcategory_counts.get(sub, 0) + 1
    if category_counts:
        category = max(category_counts, key=lambda k: category_counts[k])
        raw_subcategory = max(subcategory_counts, key=lambda k: subcategory_counts[k]) if subcategory_counts else category
    else:
        category, raw_subcategory = classify_tags(market_titles)
    # Flatten subcategory for filter dropdowns (NFL->Football, NBA->Basketball, etc.)
    subcategory = flatten_subcategory(category, raw_subcategory)
    top_markets = sorted(market_counts.keys(), key=lambda k: market_counts[k], reverse=True)[:5]
    return {"category": category, "subcategory": subcategory, "trade_count": len(trades), "top_markets": top_markets}


def compute_category_stats(trades, closed_positions, pm_category_pnl=None):
    pm = pm_category_pnl or {}
    trade_by_cid: dict[str, tuple[str, str]] = {}  # cid -> (category, subcategory)
    category_volume: dict[str, float] = {}
    category_pnl: dict[str, float] = {}
    category_wins: dict[str, int] = {}
    category_resolved: dict[str, int] = {}
    category_last_active: dict[str, datetime] = {}
    
    # Subcategory tracking
    subcategory_volume: dict[tuple[str, str], float] = {}
    subcategory_pnl: dict[tuple[str, str], float] = {}
    subcategory_wins: dict[tuple[str, str], int] = {}
    subcategory_resolved: dict[tuple[str, str], int] = {}
    subcategory_last_active: dict[tuple[str, str], datetime] = {}

    for t in trades:
        title = t.get("title") or ""
        cid = t.get("conditionId") or ""
        if not title or not cid:
            continue
        cat, sub = classify_tags([title])
        flat_sub = flatten_subcategory(cat, sub)
        trade_by_cid[cid] = (cat, flat_sub)
        size = _parse(t.get("size"))
        price = _parse(t.get("price"))
        usdc = size * price
        category_volume[cat] = category_volume.get(cat, 0.0) + usdc
        subcategory_volume[(cat, flat_sub)] = subcategory_volume.get((cat, flat_sub), 0.0) + usdc

    for cp in closed_positions:
        cid = cp.get("conditionId") or ""
        cat_sub = trade_by_cid.get(cid)
        if cat_sub:
            cat, flat_sub = cat_sub
        else:
            cp_title = cp.get("title") or ""
            cat, sub = classify_tags([cp_title]) if cp_title else ("Other", "General")
            flat_sub = flatten_subcategory(cat, sub)
        
        rpnl = _parse(cp.get("realizedPnl"))
        category_pnl[cat] = category_pnl.get(cat, 0.0) + rpnl
        category_resolved[cat] = category_resolved.get(cat, 0) + 1
        if rpnl > 0:
            category_wins[cat] = category_wins.get(cat, 0) + 1
        end = _parse_end(cp.get("endDate"))
        if end and (category_last_active.get(cat) is None or end > category_last_active[cat]):
            category_last_active[cat] = end
        
        sub_key = (cat, flat_sub)
        subcategory_pnl[sub_key] = subcategory_pnl.get(sub_key, 0.0) + rpnl
        subcategory_resolved[sub_key] = subcategory_resolved.get(sub_key, 0) + 1
        if rpnl > 0:
            subcategory_wins[sub_key] = subcategory_wins.get(sub_key, 0) + 1
        if end and (subcategory_last_active.get(sub_key) is None or end > subcategory_last_active[sub_key]):
            subcategory_last_active[sub_key] = end

    # Build category results
    all_cats = set(category_volume.keys()) | set(category_pnl.keys()) | set(pm.keys())
    category_result = []
    for cat in sorted(all_cats):
        if cat in pm and pm[cat].get("pnl") is not None:
            pnl, vol = pm[cat]["pnl"], pm[cat].get("volume", 0.0)
        else:
            pnl, vol = category_pnl.get(cat, 0.0), category_volume.get(cat, 0.0)
        resolved = category_resolved.get(cat, 0)
        wins = category_wins.get(cat, 0)
        win_rate = (wins / resolved) if resolved > 0 else 0.0
        roi = (pnl / vol * 100) if vol > 0 else 0.0
        category_result.append({
            "category": cat, "total_pnl": round(pnl, 2), "total_volume": round(vol, 2),
            "win_rate": round(win_rate, 4), "resolved_count": resolved,
            "winning_count": wins, "roi_pct": round(roi, 2),
            "last_active": category_last_active.get(cat),
        })
    
    # Build subcategory results
    all_subs = set(subcategory_volume.keys()) | set(subcategory_pnl.keys())
    subcategory_result = []
    for (cat, sub) in sorted(all_subs):
        pnl = subcategory_pnl.get((cat, sub), 0.0)
        vol = subcategory_volume.get((cat, sub), 0.0)
        resolved = subcategory_resolved.get((cat, sub), 0)
        wins = subcategory_wins.get((cat, sub), 0)
        win_rate = (wins / resolved) if resolved > 0 else 0.0
        roi = (pnl / vol * 100) if vol > 0 else 0.0
        subcategory_result.append({
            "category": cat, "subcategory": sub, "total_pnl": round(pnl, 2), "total_volume": round(vol, 2),
            "win_rate": round(win_rate, 4), "resolved_count": resolved,
            "winning_count": wins, "roi_pct": round(roi, 2),
            "last_active": subcategory_last_active.get((cat, sub)),
        })
    
    return category_result, subcategory_result


# ── Core: fetch all data for one wallet concurrently ──────────────────────

async def _fetch_wallet_data(session: aiohttp.ClientSession, address: str, start_stats_at: datetime) -> dict:
    """Fire all API calls for a single wallet concurrently (except closed positions)."""
    trades_f, positions_f, balance_f, website_f = await asyncio.gather(
        fetch_all_trades(session, address),
        fetch_positions(session, address),
        fetch_balance(session, address),
        fetch_website_pnl(session, address),
        return_exceptions=True,
    )
    trades = trades_f if isinstance(trades_f, list) else []
    positions = positions_f if isinstance(positions_f, list) else []
    balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
    website = website_f if isinstance(website_f, dict) else None

    # Deposits/withdrawals/peak capital (Alchemy)
    capital_f = await fetch_capital_metrics(session, address)
    if isinstance(capital_f, tuple) and len(capital_f) == 3:
        deposits, withdrawals, peak_capital = capital_f
    else:
        deposits, withdrawals, peak_capital = None, None, None

    return {
        "trades": trades, "positions": positions,
        "balance": balance, "website": website,
        "deposits": deposits, "withdrawals": withdrawals,
        "peak_capital": peak_capital,
    }


async def _fetch_category_pnl_batch(session: aiohttp.ClientSession, address: str, categories: set[str]) -> dict[str, dict]:
    """Fetch per-category PnL for all categories concurrently."""
    cats_to_fetch = [c.upper() for c in categories if c != "Other" and c.upper() in PM_CATEGORIES]
    if not cats_to_fetch:
        return {}

    async def _fetch_one(cat: str):
        return cat, await fetch_category_pnl(session, address, cat)

    results = await asyncio.gather(*[_fetch_one(c) for c in cats_to_fetch], return_exceptions=True)
    pm = {}
    for r in results:
        if isinstance(r, tuple) and len(r) == 2:
            cat, data = r
            if data and (data["pnl"] != 0 or data["volume"] != 0):
                pm[cat.lower().capitalize() if cat != "ESPORTS" else "Esports" if cat == "ESPORTS" else cat.title()] = data
    return pm


# ── Process a single wallet ──────────────────────────────────────────────

async def process_wallet(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    row = await conn.fetchrow(
        """
        SELECT added_at, added_at as start_stats_at, tier = 'CURATED' as is_curated, last_trade_at as last_active,
               EXISTS (SELECT 1 FROM wallet_sources_v2 s WHERE s.address = wallets_v2.address AND s.source = 'leaderboard') as is_leaderboard
        FROM wallets_v2 WHERE address = $1
        """,
        address
    )
    if not row:
        return

    is_curated = row["is_curated"]
    is_leaderboard = row["is_leaderboard"]

    start_stats_at = row["start_stats_at"]
    if not start_stats_at:
        start_stats_at = row["added_at"] or datetime.now(timezone.utc)
        await conn.execute("UPDATE wallets_v2 SET start_stats_at = $1 WHERE address = $2", start_stats_at, address)

    # Fetch wallet data based on curated status
    supabase = None
    if is_curated:
        # Curated wallets: full tracking with trades and positions
        data = await _fetch_wallet_data(session, address, start_stats_at)
        trades = data["trades"]
        positions = data["positions"]
        balance = data["balance"]
        website = data["website"]
        deposits = data["deposits"]
        withdrawals = data["withdrawals"]
    else:
        # Non-curated wallets: balance, website, deposits, withdrawals + Supabase win_rate
        balance_f, website_f, supabase_f, positions_f = await asyncio.gather(
            fetch_balance(session, address),
            fetch_website_pnl(session, address),
            fetch_supabase_wallet_profile(session, address),
            fetch_positions(session, address),
            return_exceptions=True,
        )
        balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
        website = website_f if isinstance(website_f, dict) else None
        supabase = supabase_f if isinstance(supabase_f, dict) else None
        trades = []
        positions = positions_f if isinstance(positions_f, list) else []
        capital_f = await fetch_capital_metrics(session, address)
        if isinstance(capital_f, tuple) and len(capital_f) == 3:
            deposits, withdrawals, peak_capital = capital_f
        else:
            deposits, withdrawals, peak_capital = None, None, None

    if deposits is None or withdrawals is None:
        logger.warning(f"Alchemy unavailable for {address[:10]}... falling back to stored values")
        deposits = deposits if deposits is not None else 0.0
        withdrawals = withdrawals if withdrawals is not None else 0.0

    # ══════════════════════════════════════════════════════════════════════
    # NON-CURATED WALLET: Supabase + Polymarket API only. No trade scan.
    # ══════════════════════════════════════════════════════════════════════
    if not is_curated:
        # ── Vetting gate: balance + last_trade_at ──
        # Fetch last_trade_at BEFORE deciding whether to add to global list
        # NOTE: must use `user=`, not `maker=`/`taker=` — those params do not filter
        # by address on this endpoint and silently return an unrelated wallet's trade.
        last_trade_dt = None
        try:
            url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and data:
                        ts = data[0].get("timestamp")
                        if ts:
                            last_trade_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except Exception:
            pass

        # Also check stored last_trade_at as fallback
        stored_last = row["last_active"] or row.get("added_at")

        effective_last_trade = last_trade_dt or stored_last
        now = datetime.now(timezone.utc)

        # Calculate position_value for vetting
        position_value = 0.0
        for pos in (positions or []):
            curr_val = _parse(pos.get("currentValue", 0))
            if curr_val > 0:
                position_value += curr_val
                
        total_assets = balance + position_value
        sb_resolved = supabase["resolved_count"] if supabase and supabase.get("resolved_count") is not None else None

        # Rule 1 & 2: total_assets < 1k → below threshold, skip global list, move to "Low Balance" Might Cook
        if total_assets < BALANCE_THRESHOLD:
            await conn.execute(
                "UPDATE wallets_v2 SET tier = 'LOW_BALANCE', last_indexed = NOW() WHERE address = $1",
                address,
            )
            logger.debug(f"Below threshold (Low Balance): {address[:10]}... total_assets={total_assets:.0f}")
            return

        # Rule 2.5: balance > $1k but no trades → Might Cook "New Wallets"
        has_trades = (sb_resolved and sb_resolved > 0) or last_trade_dt is not None
        if not has_trades:
            if last_trade_dt and (now - last_trade_dt) >= timedelta(days=30):
                # Stale with no trades → hibernate
                await conn.execute("""
                    UPDATE wallets_v2 SET
                        is_dormant = TRUE,
                        last_indexed = NOW(),
                        next_check_at = NULL
                    WHERE address = $1
                """, address)
                logger.debug(f"Hibernating stale no-trade: {address[:10]}...")
            else:
                # New wallet with balance but no trades yet → Might Cook
                await conn.execute(
                    "UPDATE wallets_v2 SET last_indexed = NOW() WHERE address = $1",
                    address,
                )
                logger.debug(f"New wallet no trades: {address[:10]}... balance={balance:.0f}")
            return

        # Rule 3: balance > $1k but stale → hibernate
        is_stale = True
        if effective_last_trade and (now - effective_last_trade) < timedelta(days=30):
            is_stale = False

        if is_stale:
            await conn.execute("""
                UPDATE wallets_v2 SET
                    is_dormant = TRUE,
                    last_indexed = NOW(),
                    next_check_at = NULL
                WHERE address = $1
            """, address)
            logger.debug(f"Hibernating: {address[:10]}... last_trade={effective_last_trade}")
            return

        # ── Passed vetting gate: balance > $1k + recent trade → add to global list ──
        website_pnl = website["pnl"] if website else None
        website_volume = website["volume"] if website else None
        if website:
            await conn.execute("""
                UPDATE wallets_v2 SET username=$5 WHERE address=$1
            """, address, website_pnl, website_volume, website["rank"], website["username"])
            await conn.execute("""
                UPDATE wallet_metrics_v2 SET pm_pnl=$2, pm_volume=$3, pm_rank=$4 WHERE address=$1
            """, address, website_pnl, website_volume, website["rank"])

        # Use Supabase data for win_rate/roi/resolved — NULL if not available
        sb_wr = supabase["win_rate"] if supabase and supabase.get("win_rate") is not None else None
        sb_roi = supabase["roi_pct"] if supabase and supabase.get("roi_pct") is not None else None
        sb_resolved = supabase["resolved_count"] if supabase and supabase.get("resolved_count") is not None else None
        sb_winning = supabase["winning_count"] if supabase and supabase.get("winning_count") is not None else None

        # PnL from Polymarket leaderboard (website), NULL if not available
        total_pnl = website_pnl
        total_volume = website_volume

        # ── We are completely bypassing the Triangle Logic for Curated wallets right now ──
        # Use Supabase data as the display values (win_rate, roi_pct, etc.) for EVERY wallet.
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count,
                total_volume, total_pnl, unrealised_pnl, biggest_win, biggest_loss,
                active_days,
                avg_buy_price, buys_below_10c, buys_below_20c, buys_below_30c, buys_below_40c, buys_above_70c,
                wins_below_10c, wins_below_20c, wins_below_30c, wins_below_40c, wins_above_70c,
                losses_below_10c, losses_below_20c, losses_below_30c, losses_below_40c, losses_above_70c,
                win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
                sb_win_rate, sb_roi_pct, sb_resolved_count, sb_winning_count,
                tl_win_rate, tl_roi_pct, tl_resolved_count, tl_winning_count,
                last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,$8,$9,$10,$11,NULL,NULL,NULL,NULL,NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                sb_win_rate=EXCLUDED.sb_win_rate, sb_roi_pct=EXCLUDED.sb_roi_pct,
                sb_resolved_count=EXCLUDED.sb_resolved_count, sb_winning_count=EXCLUDED.sb_winning_count,
                tl_win_rate=NULL, tl_roi_pct=NULL, tl_resolved_count=NULL, tl_winning_count=NULL,
                last_updated=EXCLUDED.last_updated
        """, address, sb_wr, sb_roi, sb_resolved, sb_winning, total_volume, total_pnl,
            sb_wr, sb_roi, sb_resolved, sb_winning)

        await conn.execute("""
            UPDATE wallets_v2 SET
                total_pnl=$2, total_volume=$3, balance=$4,
                deposits=$5, withdrawals=$6,
                last_indexed=NOW(),
                last_trade_at = GREATEST(COALESCE(last_trade_at, $7), $7),
                last_active = GREATEST(COALESCE(last_active, added_at), $7),
                is_dormant = FALSE,
                next_check_at = NOW() + INTERVAL '7 days'
            WHERE address=$1
        """, address, total_pnl, total_volume,
            balance, deposits, withdrawals, last_trade_dt)

        return  # ← Skip all deep fetch / trade scanning / tags / categories

    # ══════════════════════════════════════════════════════════════════════
    # CURATED WALLET: Full trade scan + Triangle Logic
    # ══════════════════════════════════════════════════════════════════════
    # Also fetch Supabase data for sb_ columns (comparison)
    if not supabase:
        supabase_f = await fetch_supabase_wallet_profile(session, address)
        supabase = supabase_f if isinstance(supabase_f, dict) else None

    # ── Closed positions: synthetic on-chain build (Bypassing 5,000 API limit) ──
    from src.utils.etherscan_client import fetch_historical_redemptions_polygonscan, build_synthetic_closed_positions
    proxies = set(t.get("proxyWallet") for t in trades if t.get("proxyWallet") and isinstance(t.get("proxyWallet"), str))
    addresses_to_query = [address] + list(proxies)
    
    redemptions = await fetch_historical_redemptions_polygonscan(session, addresses_to_query)
    synthetic_closed = build_synthetic_closed_positions(trades, redemptions)
    
    # We still upsert them to the DB so other parts of the UI/API can use them,
    # but we use `synthetic_closed` directly for compute_stats.
    await upsert_closed_positions(conn, address, synthetic_closed)
    closed = synthetic_closed

    website_pnl = website["pnl"] if website else 0.0
    website_volume = website["volume"] if website else 0.0

    if website:
        await conn.execute("""
            UPDATE wallets_v2 SET username=$5 WHERE address=$1
        """, address, website_pnl, website_volume, website["rank"], website["username"])
        await conn.execute("""
            UPDATE wallet_metrics_v2 SET pm_pnl=$2, pm_volume=$3, pm_rank=$4 WHERE address=$1
        """, address, website_pnl, website_volume, website["rank"])

    position_value = 0.0
    for pos in (positions or []):
        curr_val = _parse(pos.get("currentValue"))
        if curr_val > 0:
            position_value += curr_val

    headline = select_headline_pnl(website, 0.0, _computed_volume(trades))
    await conn.execute("UPDATE wallets_v2 SET pnl_source=$2 WHERE address=$1", address, headline["pnl_source"])

    # --- DEEP FETCH / DATABASE STATS ---
    db_stats = {}
    if is_curated:
        # 1. Store all outcomes using the full history (from Etherscan deep fetch)
        await aggregate_and_upsert_positions(conn, address, trades, closed, positions)
        
        # 2. Compute accurate win rates and brackets strictly from the DB outcomes
        db_stats = await compute_window_stats_from_db(conn, address)

    # Calculate remaining in-memory stats (roi_pct, biggest_win)
    stats = compute_stats(positions, closed, headline["pnl"], headline["volume"], start_stats_at, peak_capital)

    # NOTE: win_rate, roi_pct, resolved_count, winning_count ALWAYS come from Supabase (for global page).
    # Curated page reads Triangle Logic data from tl_ columns.
    # Do NOT overwrite stats with computed/db values for these fields.

    # Store Triangle Logic data in tl_ columns for curated page
    tl_wr = db_stats.get("win_rate_all") if db_stats else None
    tl_resolved = db_stats.get("resolved_count") if db_stats else None
    tl_winning = db_stats.get("winning_count") if db_stats else None
    tl_roi = stats.get("roi_pct")  # Computed from trades (effective_pnl / effective_volume)

    # Override stats with Supabase values for DB write (global page always shows these)
    if supabase:
        if supabase.get("win_rate") is not None:
            stats["win_rate"] = supabase["win_rate"]
        if supabase.get("roi_pct") is not None:
            stats["roi_pct"] = supabase["roi_pct"]
        if supabase.get("resolved_count") is not None:
            stats["resolved_count"] = supabase["resolved_count"]
        if supabase.get("winning_count") is not None:
            stats["winning_count"] = supabase["winning_count"]

    # ── Batch DB writes ──
    sb_wr = supabase["win_rate"] if supabase and supabase.get("win_rate") is not None else None
    sb_roi = supabase["roi_pct"] if supabase and supabase.get("roi_pct") is not None else None
    sb_resolved = supabase["resolved_count"] if supabase and supabase.get("resolved_count") is not None else None
    sb_winning = supabase["winning_count"] if supabase and supabase.get("winning_count") is not None else None

    latest_trade_ts = max(
        (t.get("timestamp", 0) for t in trades if t.get("timestamp")),
        default=0,
    )
    last_trade_dt = datetime.fromtimestamp(latest_trade_ts, tz=timezone.utc) if latest_trade_ts > 0 else None

    # ── Update wallet_metrics_v2 for Curated Wallet ──
    await conn.execute("""
        INSERT INTO wallet_metrics_v2 (
            address, total_volume, total_pnl,
            win_rate, roi_pct, resolved_count, winning_count,
            biggest_win, biggest_loss, active_days,
            avg_buy_price, buys_below_10c, buys_below_20c, buys_below_30c, buys_below_40c, buys_above_70c,
            wins_below_10c, wins_below_20c, wins_below_30c, wins_below_40c, wins_above_70c,
            losses_below_10c, losses_below_20c, losses_below_30c, losses_below_40c, losses_above_70c,
            win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
            sb_win_rate, sb_roi_pct, sb_resolved_count, sb_winning_count,
            tl_win_rate, tl_roi_pct, tl_resolved_count, tl_winning_count,
            last_updated
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6, $7,
            $8, $9, $10,
            $11, $12, $13, $14, $15, $16,
            $17, $18, $19, $20, $21,
            $22, $23, $24, $25, $26,
            $27, $28, $29, $30, $31,
            $32, $33, $34, $35,
            $36, $37, $38, $39,
            NOW()
        ) ON CONFLICT (address) DO UPDATE SET
            total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
            win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct,
            resolved_count=EXCLUDED.resolved_count, winning_count=EXCLUDED.winning_count,
            biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
            active_days=EXCLUDED.active_days,
            avg_buy_price=EXCLUDED.avg_buy_price,
            buys_below_10c=EXCLUDED.buys_below_10c, buys_below_20c=EXCLUDED.buys_below_20c,
            buys_below_30c=EXCLUDED.buys_below_30c, buys_below_40c=EXCLUDED.buys_below_40c,
            buys_above_70c=EXCLUDED.buys_above_70c,
            wins_below_10c=EXCLUDED.wins_below_10c, wins_below_20c=EXCLUDED.wins_below_20c,
            wins_below_30c=EXCLUDED.wins_below_30c, wins_below_40c=EXCLUDED.wins_below_40c,
            wins_above_70c=EXCLUDED.wins_above_70c,
            losses_below_10c=EXCLUDED.losses_below_10c, losses_below_20c=EXCLUDED.losses_below_20c,
            losses_below_30c=EXCLUDED.losses_below_30c, losses_below_40c=EXCLUDED.losses_below_40c,
            losses_above_70c=EXCLUDED.losses_above_70c,
            win_rate_100=EXCLUDED.win_rate_100, win_rate_300=EXCLUDED.win_rate_300,
            win_rate_800=EXCLUDED.win_rate_800, win_rate_1500=EXCLUDED.win_rate_1500,
            win_rate_2500=EXCLUDED.win_rate_2500,
            sb_win_rate=EXCLUDED.sb_win_rate, sb_roi_pct=EXCLUDED.sb_roi_pct,
            sb_resolved_count=EXCLUDED.sb_resolved_count, sb_winning_count=EXCLUDED.sb_winning_count,
            tl_win_rate=EXCLUDED.tl_win_rate, tl_roi_pct=EXCLUDED.tl_roi_pct,
            tl_resolved_count=EXCLUDED.tl_resolved_count, tl_winning_count=EXCLUDED.tl_winning_count,
            last_updated=EXCLUDED.last_updated
    """,
        address, stats["total_volume"], stats["total_pnl"],
        stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
        stats["biggest_win"], stats["biggest_loss"], stats["active_days"],
        stats["avg_buy_price"],
        stats["buys_below_10c"], stats["buys_below_20c"], stats["buys_below_30c"], stats["buys_below_40c"], stats["buys_above_70c"],
        stats["wins_below_10c"], stats["wins_below_20c"], stats["wins_below_30c"], stats["wins_below_40c"], stats["wins_above_70c"],
        stats["losses_below_10c"], stats["losses_below_20c"], stats["losses_below_30c"], stats["losses_below_40c"], stats["losses_above_70c"],
        db_stats.get("win_rate_100"), db_stats.get("win_rate_300"), db_stats.get("win_rate_800"),
        db_stats.get("win_rate_1500"), db_stats.get("win_rate_2500"),
        sb_wr, sb_roi, sb_resolved, sb_winning,
        tl_wr, tl_roi, tl_resolved, tl_winning
    )

    await conn.execute("""
        UPDATE wallets_v2 SET
            total_pnl=$2, total_volume=$3, max_trade_size=$4,
            balance=$5, deposits=$6, withdrawals=$7, position_value=$8,
            last_indexed=NOW(),
            last_trade_at = GREATEST(COALESCE(last_trade_at, $9), $9),
            last_active = GREATEST(COALESCE(last_active, added_at), $9),
            is_dormant = FALSE
        WHERE address=$1
    """, address, stats["total_pnl"], stats["total_volume"], stats["max_trade_size"],
        balance, deposits, withdrawals, position_value,
        last_trade_dt)

    # ── Tags + category stats ──
    tags = compute_wallet_tags(trades)
    await conn.execute("""
        INSERT INTO wallet_tags (address, category, subcategory, trade_count, top_markets, computed_at)
        VALUES ($1,$2,$3,$4,$5,NOW())
        ON CONFLICT (address) DO UPDATE SET
            category=EXCLUDED.category, subcategory=EXCLUDED.subcategory,
            trade_count=EXCLUDED.trade_count, top_markets=EXCLUDED.top_markets, computed_at=NOW()
    """, address, tags["category"], tags["subcategory"], tags["trade_count"], tags["top_markets"])

    # Determine which categories this wallet trades in, fetch PM PnL concurrently
    trade_categories: set[str] = set()
    for t in trades:
        title = t.get("title") or ""
        if title:
            cat, _ = classify_tags([title])
            trade_categories.add(cat)

    pm_category_pnl = await _fetch_category_pnl_batch(session, address, trade_categories)

    cat_stats, sub_stats = compute_category_stats(trades, closed, pm_category_pnl)
    for cs in cat_stats:
        await conn.execute("""
            INSERT INTO category_stats_v2 (address, category, total_pnl, total_volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (address, category) DO UPDATE SET
                total_pnl=EXCLUDED.total_pnl, total_volume=EXCLUDED.total_volume,
                win_rate=EXCLUDED.win_rate, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, roi_pct=EXCLUDED.roi_pct,
                last_active=EXCLUDED.last_active, computed_at=NOW()
        """, address, cs["category"], cs["total_pnl"], cs["total_volume"],
            cs["win_rate"], cs["resolved_count"], cs["winning_count"], cs["roi_pct"], cs["last_active"])

    for ss in sub_stats:
        await conn.execute("""
            INSERT INTO wallet_subcategory_stats (address, category, subcategory, total_pnl, total_volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
            ON CONFLICT (address, category, subcategory) DO UPDATE SET
                total_pnl=EXCLUDED.total_pnl, total_volume=EXCLUDED.total_volume,
                win_rate=EXCLUDED.win_rate, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, roi_pct=EXCLUDED.roi_pct,
                last_active=EXCLUDED.last_active, computed_at=NOW()
        """, address, ss["category"], ss["subcategory"], ss["total_pnl"], ss["total_volume"],
            ss["win_rate"], ss["resolved_count"], ss["winning_count"], ss["roi_pct"], ss["last_active"])

    # ── Per-category windowed stats (last N closed positions per category) ──
    TRADE_WINDOWS = [100, 300, 800, 1500, 2500]
    window_stats = compute_category_window_stats(
        closed or [], TRADE_WINDOWS, lambda title: classify_tags([title])[0] if title else "OTHER"
    )
    for (cat, window), s in window_stats.items():
        await conn.execute(f"""
            INSERT INTO wallet_window_{window}
                (address, category, pnl, volume, win_rate, roi_pct, resolved_count, winning_count, last_active, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (address, category) DO UPDATE SET
                pnl=EXCLUDED.pnl, volume=EXCLUDED.volume, win_rate=EXCLUDED.win_rate,
                roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, last_active=EXCLUDED.last_active, computed_at=NOW()
        """, address, cat.upper(), s["pnl"], s["volume"], s["win_rate"], s["roi_pct"],
             s["resolved_count"], s["winning_count"], s["last_active"])

    logger.info(
        f"Done {address[:10]}... | "
        f"vol=${stats['total_volume']:.0f} pnl=${stats['total_pnl']:.0f} "
        f"wr={stats['win_rate']*100:.0f}% cats={len(cat_stats)}"
    )

    # ── Update last_trade_at from most recent trade ──
    if trades:
        latest_ts = max(
            (t.get("timestamp", 0) for t in trades if t.get("timestamp")),
            default=None,
        )
        if latest_ts:
            latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
            await conn.execute(
                "UPDATE wallets_v2 SET last_trade_at = GREATEST(last_trade_at, $2) WHERE address = $1",
                address, latest_dt,
            )

    # ── Dormancy check: inactive > 30 days → is_dormant = true ──
    dormancy_row = await conn.fetchrow(
        "SELECT last_trade_at FROM wallets_v2 WHERE address = $1", address
    )
    if dormancy_row and dormancy_row["last_trade_at"]:
        days_inactive = (datetime.now(timezone.utc) - dormancy_row["last_trade_at"]).days
        is_dormant = days_inactive > 30
        await conn.execute(
            "UPDATE wallets_v2 SET is_dormant = $2 WHERE address = $1",
            address, is_dormant,
        )
    else:
        is_dormant = False

    # ── Curated promotion: ROI > 30% OR balance > $5k OR PnL > $10k ──
    qualifies = (
        not is_dormant
        and (
            stats["roi_pct"] > 30
            or balance > 5_000
            or stats["total_pnl"] > 10_000
        )
    )
    
    was_curated = row["is_curated"]
    newly_curated = qualifies and not was_curated
    
    await conn.execute("""
        UPDATE wallets_v2 SET
            tier = CASE WHEN $2 THEN 'CURATED' ELSE tier END,
            is_dormant = FALSE,
            curated_at = CASE WHEN $2 = TRUE AND tier != 'CURATED' THEN NOW()
                              WHEN $2 = FALSE THEN NULL
                              ELSE curated_at END,
            last_checked_for_curated = NOW()
        WHERE address = $1
    """, address, qualifies)

    # ── Newly curated: fetch trades/positions and compute category/subcategory ──
    if newly_curated:
        logger.info(f"Wallet {address[:10]}... newly promoted to curated - fetching trades/positions")
        data = await _fetch_wallet_data(session, address, start_stats_at)
        trades = data["trades"]
        positions = data["positions"]
        
        # Recompute stats with trades/positions
        position_value = 0.0
        for pos in (positions or []):
            curr_val = _parse(pos.get("currentValue"))
            if curr_val > 0:
                position_value += curr_val

        stats = compute_stats(positions, closed, headline["pnl"], headline["volume"], start_stats_at)

    if is_curated or newly_curated:
        await aggregate_and_upsert_positions(conn, address, trades, closed, positions)
        db_stats = await compute_window_stats_from_db(conn, address)
        for k, v in db_stats.items():
            stats[k] = v
        # Override the main win rate with the DB-computed all-time win rate
        if 'win_rate_all' in stats:
            stats['win_rate'] = stats['win_rate_all']
        # Persist triangle logic window stats
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count,
                total_volume, total_pnl, biggest_win, biggest_loss,
                active_days,
                avg_buy_price, buys_below_10c, buys_below_20c, buys_below_30c, buys_below_40c, buys_above_70c,
                wins_below_10c, wins_below_20c, wins_below_30c, wins_below_40c, wins_above_70c,
                losses_below_10c, losses_below_20c, losses_below_30c, losses_below_40c, losses_above_70c,
                win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
                last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                active_days=EXCLUDED.active_days,
                avg_buy_price=EXCLUDED.avg_buy_price, buys_below_10c=EXCLUDED.buys_below_10c, buys_below_20c=EXCLUDED.buys_below_20c,
                buys_below_30c=EXCLUDED.buys_below_30c, buys_below_40c=EXCLUDED.buys_below_40c, buys_above_70c=EXCLUDED.buys_above_70c,
                wins_below_10c=EXCLUDED.wins_below_10c, wins_below_20c=EXCLUDED.wins_below_20c,
                wins_below_30c=EXCLUDED.wins_below_30c, wins_below_40c=EXCLUDED.wins_below_40c, wins_above_70c=EXCLUDED.wins_above_70c,
                losses_below_10c=EXCLUDED.losses_below_10c, losses_below_20c=EXCLUDED.losses_below_20c,
                losses_below_30c=EXCLUDED.losses_below_30c, losses_below_40c=EXCLUDED.losses_below_40c, losses_above_70c=EXCLUDED.losses_above_70c,
                win_rate_100=EXCLUDED.win_rate_100, win_rate_300=EXCLUDED.win_rate_300, win_rate_800=EXCLUDED.win_rate_800,
                win_rate_1500=EXCLUDED.win_rate_1500, win_rate_2500=EXCLUDED.win_rate_2500,
                last_updated=EXCLUDED.last_updated
        """, address, stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
            stats["total_volume"], stats["total_pnl"],
            stats["biggest_win"], stats["biggest_loss"],
            stats["active_days"],
            stats["avg_buy_price"], stats["buys_below_10c"], stats["buys_below_20c"],
            stats["buys_below_30c"], stats["buys_below_40c"], stats["buys_above_70c"],
            stats["wins_below_10c"], stats["wins_below_20c"],
            stats["wins_below_30c"], stats["wins_below_40c"], stats["wins_above_70c"],
            stats["losses_below_10c"], stats["losses_below_20c"],
            stats["losses_below_30c"], stats["losses_below_40c"], stats["losses_above_70c"],
            stats.get("win_rate_100", 0.0), stats.get("win_rate_300", 0.0), stats.get("win_rate_800", 0.0),
            stats.get("win_rate_1500", 0.0), stats.get("win_rate_2500", 0.0))
        # Update wallets_v2
        await conn.execute("""
            UPDATE wallets_v2 SET
                total_pnl=$2, total_volume=$3,
                win_rate=$4, roi_pct=$5, resolved_count=$6, winning_count=$7,
                max_trade_size=$8, balance=$9,
                deposits=$10, withdrawals=$11, position_value=$12, last_indexed=NOW()
            WHERE address=$1
        """, address, stats["total_pnl"],
            stats["total_volume"], stats["win_rate"], stats["roi_pct"],
            stats["resolved_count"], stats["winning_count"],
            stats["max_trade_size"],
            balance, deposits, withdrawals, position_value)
    else:
        # Give default 0s for non-curated
        for k in ['win_rate_100', 'win_rate_300', 'win_rate_800', 'win_rate_1500', 'win_rate_2500']:
            stats[k] = 0.0
        
        # Update wallet_metrics_v2 with full trade data
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count,
                total_volume, total_pnl, biggest_win, biggest_loss,
                active_days,
                avg_buy_price, buys_below_10c, buys_below_20c, buys_below_30c, buys_below_40c, buys_above_70c,
                wins_below_10c, wins_below_20c, wins_below_30c, wins_below_40c, wins_above_70c,
                losses_below_10c, losses_below_20c, losses_below_30c, losses_below_40c, losses_above_70c,
                last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
                active_days=EXCLUDED.active_days,
                avg_buy_price=EXCLUDED.avg_buy_price, buys_below_10c=EXCLUDED.buys_below_10c, buys_below_20c=EXCLUDED.buys_below_20c,
                buys_below_30c=EXCLUDED.buys_below_30c, buys_below_40c=EXCLUDED.buys_below_40c, buys_above_70c=EXCLUDED.buys_above_70c,
                wins_below_10c=EXCLUDED.wins_below_10c, wins_below_20c=EXCLUDED.wins_below_20c,
                wins_below_30c=EXCLUDED.wins_below_30c, wins_below_40c=EXCLUDED.wins_below_40c, wins_above_70c=EXCLUDED.wins_above_70c,
                losses_below_10c=EXCLUDED.losses_below_10c, losses_below_20c=EXCLUDED.losses_below_20c,
                losses_below_30c=EXCLUDED.losses_below_30c, losses_below_40c=EXCLUDED.losses_below_40c, losses_above_70c=EXCLUDED.losses_above_70c,
                last_updated=EXCLUDED.last_updated
        """, address, stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
            stats["total_volume"], stats["total_pnl"],
            stats["biggest_win"], stats["biggest_loss"],
            stats["active_days"],
            stats["avg_buy_price"], stats["buys_below_10c"], stats["buys_below_20c"],
            stats["buys_below_30c"], stats["buys_below_40c"], stats["buys_above_70c"],
            stats["wins_below_10c"], stats["wins_below_20c"],
            stats["wins_below_30c"], stats["wins_below_40c"], stats["wins_above_70c"],
            stats["losses_below_10c"], stats["losses_below_20c"],
            stats["losses_below_30c"], stats["losses_below_40c"], stats["losses_above_70c"])

        # Find latest trade timestamp from the fetched trades
        latest_trade_ts = 0
        for t in trades:
            ts = t.get("timestamp", 0)
            if ts and int(ts) > latest_trade_ts:
                latest_trade_ts = int(ts)
        last_trade_dt = datetime.fromtimestamp(latest_trade_ts, tz=timezone.utc) if latest_trade_ts > 0 else None

        # Update wallets_v2 with full data
        await conn.execute("""
            UPDATE wallets_v2 SET
                total_pnl=$2, total_volume=$3,
                win_rate=$4, roi_pct=$5, resolved_count=$6, winning_count=$7,
                max_trade_size=$8, balance=$9,
                deposits=$10, withdrawals=$11, position_value=$12, last_indexed=NOW(),
                last_trade_at = GREATEST(COALESCE(last_trade_at, $13), $13),
                last_active = GREATEST(COALESCE(last_active, added_at), $13),
                is_dormant = CASE
                    WHEN NOW() - GREATEST(COALESCE(last_active, added_at), COALESCE($13, '1970-01-01'::TIMESTAMPTZ)) > INTERVAL '30 days' THEN TRUE
                    ELSE FALSE
                END,
                next_check_at = CASE
                    WHEN NOW() - GREATEST(COALESCE(last_active, added_at), COALESCE($13, '1970-01-01'::TIMESTAMPTZ)) > INTERVAL '30 days' THEN NULL
                    ELSE NOW() + INTERVAL '7 days'
                END
            WHERE address=$1
        """, address, stats["total_pnl"],
            stats["total_volume"], stats["win_rate"], stats["roi_pct"],
            stats["resolved_count"], stats["winning_count"],
            stats["max_trade_size"],
            balance, deposits, withdrawals, position_value, last_trade_dt)




# ── Parallel runner ──────────────────────────────────────────────────────

async def run_leaderboard_stats(db_url: str = DB_URL):
    logger.info("Starting Leaderboard Stats worker (concurrency=%d, interval=%ds, supabase_rate=%d/min)...", CONCURRENCY, POLL_INTERVAL, SUPABASE_RATE_LIMIT)
    global _sb_semaphore
    _sb_semaphore = asyncio.Semaphore(1)  # Sequential Supabase calls
    try:
        pool = await asyncpg.create_pool(db_url, min_size=2, max_size=15)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return

    while True:
        try:
            async with pool.acquire() as conn:
                # Prioritize:
                # 1. Wallets never indexed (last_indexed IS NULL)
                # 2. Wallets not checked for curated in 5 days
                # 3. Oldest indexed wallets
                rows = await conn.fetch("""
                    SELECT w.address FROM wallets_v2 w LEFT JOIN wallet_metrics_v2 m ON w.address = m.address WHERE w.is_dormant = FALSE ORDER BY m.computed_at ASC NULLS FIRST
                """)
                wallets = [r["address"] for r in rows]
                total = len(wallets)
                logger.info(f"Processing {total} wallets with concurrency={CONCURRENCY}...")

            sem = asyncio.Semaphore(CONCURRENCY)
            done = 0
            errors = 0

            async def _process_one(addr):
                nonlocal done, errors
                async with sem:
                    try:
                        async with pool.acquire() as conn:
                            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                                await asyncio.wait_for(process_wallet(conn, session, addr), timeout=WALLET_TIMEOUT)
                        done += 1
                    except asyncio.TimeoutError:
                        errors += 1
                        logger.warning(f"Timeout {addr[:10]}... ({WALLET_TIMEOUT}s)")
                    except Exception as e:
                        errors += 1
                        logger.warning(f"Error {addr[:10]}...: {e}")
                    if (done + errors) % 50 == 0:
                        logger.info(f"Progress: {done + errors}/{total} (ok={done} err={errors})")

            # Fire all at once — semaphore controls concurrency
            await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)
            logger.info(f"Full pass complete: {done} ok, {errors} errors out of {total}")

        except Exception as e:
            logger.error(f"Leaderboard stats error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def main():
    shutdown = asyncio.Event()
    def _handler():
        logger.info("Shutdown signal received")
        shutdown.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except NotImplementedError:
            pass
    logger.info(f"Starting Leaderboard Stats worker (concurrency={CONCURRENCY})")
    while not shutdown.is_set():
        try:
            await run_leaderboard_stats()
        except Exception:
            logger.exception("Error in leaderboard stats loop")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass
    logger.info("Leaderboard Stats Worker shut down cleanly")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
