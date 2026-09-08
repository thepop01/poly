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
RETIREMENT_MARKER = "RETIRED_METRIC_REPAIR_NO_DB_ACCESS"

# Per-fetch position cap. Each API call fetches at most 5,000 most-recent positions
# (open or closed). This aligns with our largest analysis window (pnl_5000).
# The DB accumulates positions across many fetches over time and will naturally
# grow beyond 5,000 — that is expected. Most-recent win rate > lifetime win rate.
MAX_POSITIONS = 200000



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
    """Single shared GET helper with fast 12s timeout and 429 backoff retry."""
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            return None
    return None


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch open positions for a wallet. Hard cap: MAX_POSITIONS (30,000)."""
    all_positions = []
    offset = 0
    limit = 500
    while len(all_positions) < MAX_POSITIONS:
        data = await _get(session, f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_positions.extend(data)
        if len(data) < limit:
            break
        offset += limit
        await asyncio.sleep(API_DELAY)
    return all_positions[:MAX_POSITIONS]


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
    """Fetch closed positions newest-first, up to 200000.

    newer_than_epoch: incremental cursor — stop paginating once positions at or
    before this epoch are reached, returning only the newer gap (its latest
    200000 if the gap is larger). None = full fetch.

    Returns (positions, complete). complete=False means the deadline cut
    the fetch short with older data still unfetched — callers keeping an
    incremental cursor MUST NOT advance it then, or the unfetched tail becomes
    a permanent hole. Hitting the 200000 cap or the cursor counts as complete."""
    import time
    all_closed = []
    offset = 0
    limit = 50  # API caps closed-positions at 50/page
    max_closed = 200000
    batch_size = 10  # Fetch 10 pages (500 positions) concurrently per batch
    deadline = time.monotonic() + 600  # 600s deadline for 200000 positions
    finished_naturally = False

    while len(all_closed) < max_closed and time.monotonic() < deadline:
        remaining = max_closed - len(all_closed)
        batch_size = 5  # 5 pages (250 items) concurrently per batch to prevent rate limiting
        pages_to_fetch = min(batch_size, (remaining + limit - 1) // limit)

        urls = [
            f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset + i * limit}&sortBy=TIMESTAMP&sortDirection=DESC"
            for i in range(pages_to_fetch)
        ]

        # Fetch batch pages concurrently
        results = await asyncio.gather(
            *[_get(session, url) for url in urls],
            return_exceptions=True
        )

        hit_end = False
        for result in results:
            if isinstance(result, Exception) or not isinstance(result, list):
                continue
            kept, reached = _trim_closed_page(result, newer_than_epoch)
            all_closed.extend(kept)
            if reached or len(result) < limit:
                hit_end = True
                break

        if hit_end or not any(isinstance(r, list) and r for r in results):
            finished_naturally = True
            break

        offset += pages_to_fetch * limit
        await asyncio.sleep(0.05)

    # Complete = reached the end of data / the cursor (natural), or filled the
    # 200000 cap (intended truncation). Anything else = the deadline cut us off.
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


PM_CATEGORIES = ["SPORTS", "POLITICS", "CRYPTO", "ESPORTS", "CULTURE", "TECH", "FINANCE", "ECONOMICS", "WEATHER"]


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
            'realized_pnl': -(_parse(p.get('totalBought')) * _parse(p.get('avgPrice'))) if (status == 'loss' and _parse(p.get('totalBought')) > 0 and _parse(p.get('avgPrice')) > 0) else 0.0,
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
    buys_below_15c = buys_15_30c = buys_30_45c = buys_45_60c = buys_60_75c = buys_above_75c = 0
    active_days = 0 # No longer calculated per-trade

    resolved_count = 0
    winning_count = 0
    biggest_win = 0.0
    biggest_loss = 0.0

    wins_below_15c = wins_15_30c = wins_30_45c = wins_45_60c = wins_60_75c = wins_above_75c = 0
    losses_below_15c = losses_15_30c = losses_30_45c = losses_45_60c = losses_60_75c = losses_above_75c = 0

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
            if avg_p < 0.15: buys_below_15c += 1
            elif avg_p < 0.30: buys_15_30c += 1
            elif avg_p < 0.45: buys_30_45c += 1
            elif avg_p < 0.60: buys_45_60c += 1
            elif avg_p < 0.75: buys_60_75c += 1
            else: buys_above_75c += 1

        # Triangle Logic: Near-worthless or redeemable open positions
        redeemable = p.get("redeemable", False)
        cash_pnl = _parse(p.get("cashPnl"))
        realized_pnl = _parse(p.get("realizedPnl"))
        pos_pnl = realized_pnl + cash_pnl

        if redeemable:
            resolved_count += 1
            # Win detection for redeemable open positions: only has value if the
            # market resolved in its favor (currentValue = shares worth $1).
            # currentValue=0 -> concluded against us -> loss (not PnL based).
            cur_val = _parse(p.get("currentValue"))
            if cur_val > 0:
                winning_count += 1
                if pos_pnl > biggest_win:
                    biggest_win = pos_pnl
            else:
                if cash_pnl < biggest_loss:
                    biggest_loss = cash_pnl
                
                if avg_p > 0:
                    if avg_p < 0.15: losses_below_15c += 1
                    elif avg_p < 0.30: losses_15_30c += 1
                    elif avg_p < 0.45: losses_30_45c += 1
                    elif avg_p < 0.60: losses_45_60c += 1
                    elif avg_p < 0.75: losses_60_75c += 1
                    else: losses_above_75c += 1
        elif cur_price < 0.03:
            # Active market trading at dust price (< $0.03) is treated as a LOSS
            resolved_count += 1
            if cash_pnl < biggest_loss:
                biggest_loss = cash_pnl
            
            if avg_p > 0:
                if avg_p < 0.15: losses_below_15c += 1
                elif avg_p < 0.30: losses_15_30c += 1
                elif avg_p < 0.45: losses_30_45c += 1
                elif avg_p < 0.60: losses_45_60c += 1
                elif avg_p < 0.75: losses_60_75c += 1
                else: losses_above_75c += 1

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
            if avg_p < 0.15:
                buys_below_15c += 1
                if won: wins_below_15c += 1
                else: losses_below_15c += 1
            elif avg_p < 0.30:
                buys_15_30c += 1
                if won: wins_15_30c += 1
                else: losses_15_30c += 1
            elif avg_p < 0.45:
                buys_30_45c += 1
                if won: wins_30_45c += 1
                else: losses_30_45c += 1
            elif avg_p < 0.60:
                buys_45_60c += 1
                if won: wins_45_60c += 1
                else: losses_45_60c += 1
            elif avg_p < 0.75:
                buys_60_75c += 1
                if won: wins_60_75c += 1
                else: losses_60_75c += 1
            else:
                buys_above_75c += 1
                if won: wins_above_75c += 1
                else: losses_above_75c += 1

    avg_buy_price = sum(buy_prices) / len(buy_prices) if buy_prices else 0.0

    # Fallback to headline metrics
    effective_volume = max(total_volume, headline_volume)
    effective_pnl = headline_pnl

    win_rate = (winning_count / resolved_count * 100.0) if resolved_count > 0 else None
    
    # ROI = pnl / volume * 100
    roi_pct = (effective_pnl / effective_volume * 100) if effective_volume > 0 else 0.0
    roi_pct = max(-100.0, min(roi_pct, 10000.0))

    return {
        "total_volume": effective_volume, "total_pnl": effective_pnl,
        "win_rate": win_rate, "roi_pct": roi_pct,
        "resolved_count": resolved_count, "winning_count": winning_count,
        "max_trade_size": max_trade_size,
        "biggest_win": biggest_win, "biggest_loss": biggest_loss,
        "active_days": active_days,
        "avg_buy_price": avg_buy_price,
        "buys_below_15c": buys_below_15c, "buys_15_30c": buys_15_30c,
        "buys_30_45c": buys_30_45c, "buys_45_60c": buys_45_60c,
        "buys_60_75c": buys_60_75c, "buys_above_75c": buys_above_75c,
        "wins_below_15c": wins_below_15c, "wins_15_30c": wins_15_30c,
        "wins_30_45c": wins_30_45c, "wins_45_60c": wins_45_60c,
        "wins_60_75c": wins_60_75c, "wins_above_75c": wins_above_75c,
        "losses_below_15c": losses_below_15c, "losses_15_30c": losses_15_30c,
        "losses_30_45c": losses_30_45c, "losses_45_60c": losses_45_60c,
        "losses_60_75c": losses_60_75c, "losses_above_75c": losses_above_75c,
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
        roi = max(-100.0, min((pnl / vol * 100) if vol > 0 else 0.0, 10000.0))
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
        roi = max(-100.0, min((pnl / vol * 100) if vol > 0 else 0.0, 10000.0))
        subcategory_result.append({
            "category": cat, "subcategory": sub, "total_pnl": round(pnl, 2), "total_volume": round(vol, 2),
            "win_rate": round(win_rate, 4), "resolved_count": resolved,
            "winning_count": wins, "roi_pct": round(roi, 2),
            "last_active": subcategory_last_active.get((cat, sub)),
        })
    
    return category_result, subcategory_result


# ── Core: fetch all data for one wallet concurrently ──────────────────────

async def _fetch_wallet_data(session: aiohttp.ClientSession, address: str, start_stats_at: datetime, capital_state: dict | None = None) -> dict:
    """Fire all API calls for a single wallet concurrently including capital metrics."""
    capital_state = capital_state or {}
    trades_f, positions_f, balance_f, website_f, capital_f = await asyncio.gather(
        fetch_all_trades(session, address),
        fetch_positions(session, address),
        fetch_balance(session, address),
        fetch_website_pnl(session, address),
        fetch_capital_metrics(
            session, address,
            from_block=capital_state.get("from_block", 0),
            current_deposits=capital_state.get("deposits", 0.0),
            current_withdrawals=capital_state.get("withdrawals", 0.0),
            current_net_capital=capital_state.get("net_capital", 0.0),
            current_peak_capital=capital_state.get("peak_capital", 0.0),
        ),
        return_exceptions=True,
    )
    trades = trades_f if isinstance(trades_f, list) else []
    positions = positions_f if isinstance(positions_f, list) else []
    balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
    website = website_f if isinstance(website_f, dict) else None

    if isinstance(capital_f, tuple) and len(capital_f) >= 5 and capital_f[0] is not None:
        deposits, withdrawals, peak_capital, _net_capital, _max_block = capital_f
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

    # Shared capital state (used by both curated and non-curated paths)
    crow = await conn.fetchrow(
        "SELECT deposits, withdrawals, net_capital, peak_capital, last_capital_block FROM wallet_metrics_v2 WHERE address = $1", address
    )
    cur_dep = float(crow["deposits"]) if crow and crow["deposits"] is not None else 0.0
    cur_wdw = float(crow["withdrawals"]) if crow and crow["withdrawals"] is not None else 0.0
    cur_net = float(crow["net_capital"]) if crow and crow["net_capital"] is not None else 0.0
    cur_peak = float(crow["peak_capital"]) if crow and crow["peak_capital"] is not None else 0.0
    last_block = int(crow["last_capital_block"]) if crow and crow["last_capital_block"] is not None else 0
    from_block = last_block + 1 if last_block > 0 else 0
    capital_state = {
        "from_block": from_block,
        "deposits": cur_dep,
        "withdrawals": cur_wdw,
        "net_capital": cur_net,
        "peak_capital": cur_peak,
    }

    # Fetch wallet data based on curated status
    if is_curated:
        # Curated wallets: full tracking with trades and positions
        data = await _fetch_wallet_data(session, address, start_stats_at, capital_state)
        trades = data["trades"]
        positions = data["positions"]
        balance = data["balance"]
        website = data["website"]
        deposits = data["deposits"]
        withdrawals = data["withdrawals"]
    else:
        # Non-curated wallets: balance, website, positions, capital metrics
        balance_f, website_f, positions_f = await asyncio.gather(
            fetch_balance(session, address),
            fetch_website_pnl(session, address),
            fetch_positions(session, address),
            return_exceptions=True,
        )
        balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
        website = website_f if isinstance(website_f, dict) else None
        trades = []
        positions = positions_f if isinstance(positions_f, list) else []

        capital_f = await fetch_capital_metrics(
            session, address, from_block=from_block, current_deposits=cur_dep, current_withdrawals=cur_wdw, current_net_capital=cur_net, current_peak_capital=cur_peak
        )
        if isinstance(capital_f, tuple) and len(capital_f) == 5 and capital_f[0] is not None:
            deposits, withdrawals, peak_capital, net_capital, max_block = capital_f
            next_last_block = max(last_block, max_block or 0)
        else:
            deposits, withdrawals, peak_capital, net_capital, next_last_block = cur_dep, cur_wdw, cur_peak, cur_net, last_block

    if deposits is None or withdrawals is None:
        logger.warning(f"Alchemy unavailable for {address[:10]}... falling back to stored values")
        deposits = deposits if deposits is not None else 0.0
        withdrawals = withdrawals if withdrawals is not None else 0.0

    # ══════════════════════════════════════════════════════════════════════
    # NON-CURATED WALLET: Polymarket API only. No trade scan.
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
        # Rule 1 & 2: total_assets < 1k → below threshold, skip global list, move to "Low Balance" Might Cook
        if total_assets < BALANCE_THRESHOLD:
            await conn.execute(
                "UPDATE wallets_v2 SET tier = 'LOW_BALANCE', last_indexed = NOW() WHERE address = $1",
                address,
            )
            logger.debug(f"Below threshold (Low Balance): {address[:10]}... total_assets={total_assets:.0f}")
            return

        # Rule 2.5: balance > $1k but no trades → Might Cook "New Wallets"
        has_trades = last_trade_dt is not None
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

        # pm_pnl / pm_volume were already stored above. total_pnl is owned by
        # positions_metrics_compute and derived from position rows; mirroring
        # the leaderboard here is what produced 38,769 wallets whose total_pnl
        # was an untraceable copy of pm_pnl. Leave it alone.
        total_volume = website_volume

        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count,
                total_volume, unrealised_pnl, biggest_win, biggest_loss,
                active_days,
                avg_buy_price,
                win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
                sb_win_rate, sb_roi_pct, sb_resolved_count, sb_winning_count,
                tl_win_rate, tl_roi_pct, tl_resolved_count, tl_winning_count,
                deposits, withdrawals, net_capital, peak_capital, last_capital_block,
                last_updated)
            VALUES ($1,NULL,NULL,NULL,NULL,$2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,$3,$4,$5,$6,$7,NOW())
            ON CONFLICT (address) DO UPDATE SET
                total_volume=EXCLUDED.total_volume,
                deposits=EXCLUDED.deposits, withdrawals=EXCLUDED.withdrawals,
                net_capital=EXCLUDED.net_capital, peak_capital=EXCLUDED.peak_capital,
                last_capital_block=EXCLUDED.last_capital_block,
                sb_win_rate=NULL, sb_roi_pct=NULL,
                sb_resolved_count=NULL, sb_winning_count=NULL,
                tl_win_rate=NULL, tl_roi_pct=NULL, tl_resolved_count=NULL, tl_winning_count=NULL,
                last_updated=EXCLUDED.last_updated
        """, address, total_volume, deposits, withdrawals, net_capital, peak_capital, next_last_block)

        await conn.execute("""
            UPDATE wallets_v2 SET
                total_volume=$2, balance=$3,
                deposits=$4, withdrawals=$5,
                last_indexed=NOW(),
                last_trade_at = GREATEST(COALESCE(last_trade_at, $6), $6),
                last_active = GREATEST(COALESCE(last_active, added_at), $6),
                is_dormant = FALSE,
                next_check_at = NOW() + INTERVAL '7 days'
            WHERE address=$1
        """, address, total_volume,
            balance, deposits, withdrawals, last_trade_dt)

        return  # ← Skip all deep fetch / trade scanning / tags / categories

    # ══════════════════════════════════════════════════════════════════════
    # CURATED WALLET: Full trade scan + Triangle Logic
    # ══════════════════════════════════════════════════════════════════════

    # ── Closed positions: REST API, capped at MAX_POSITIONS (30,000) ──
    # This is the hard limit for ALL wallets — curated or not. No on-chain bypass.
    closed_result = await fetch_closed_positions(session, address)
    closed = closed_result[0] if isinstance(closed_result, tuple) else closed_result
    await upsert_closed_positions(conn, address, closed)

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

    # Store Triangle Logic data in tl_ columns for curated page
    tl_wr = db_stats.get("win_rate_all") if db_stats else None
    tl_resolved = db_stats.get("resolved_count") if db_stats else None
    tl_winning = db_stats.get("winning_count") if db_stats else None
    tl_roi = stats.get("roi_pct")  # Computed from trades (effective_pnl / effective_volume)

    # ── Batch DB writes ──
    # sb_ columns are retired (Supabase removed) — always NULL
    sb_wr = None
    sb_roi = None
    sb_resolved = None
    sb_winning = None

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
            avg_buy_price,
            buys_below_15c, buys_15_30c, buys_30_45c, buys_45_60c, buys_60_75c, buys_above_75c,
            wins_below_15c, wins_15_30c, wins_30_45c, wins_45_60c, wins_60_75c, wins_above_75c,
            losses_below_15c, losses_15_30c, losses_30_45c, losses_45_60c, losses_60_75c, losses_above_75c,
            win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
            sb_win_rate, sb_roi_pct, sb_resolved_count, sb_winning_count,
            tl_win_rate, tl_roi_pct, tl_resolved_count, tl_winning_count,
            last_updated
        ) VALUES (
            $1, $2, $3,
            $4, $5, $6, $7,
            $8, $9, $10,
            $11,
            $12, $13, $14, $15, $16, $17,
            $18, $19, $20, $21, $22, $23,
            $24, $25, $26, $27, $28, $29,
            $30, $31, $32, $33, $34,
            $35, $36, $37, $38,
            $39, $40, $41, $42,
            NOW()
        ) ON CONFLICT (address) DO UPDATE SET
            total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
            win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct,
            resolved_count=EXCLUDED.resolved_count, winning_count=EXCLUDED.winning_count,
            biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
            active_days=EXCLUDED.active_days,
            avg_buy_price=EXCLUDED.avg_buy_price,
            buys_below_15c=EXCLUDED.buys_below_15c, buys_15_30c=EXCLUDED.buys_15_30c,
            buys_30_45c=EXCLUDED.buys_30_45c, buys_45_60c=EXCLUDED.buys_45_60c,
            buys_60_75c=EXCLUDED.buys_60_75c, buys_above_75c=EXCLUDED.buys_above_75c,
            wins_below_15c=EXCLUDED.wins_below_15c, wins_15_30c=EXCLUDED.wins_15_30c,
            wins_30_45c=EXCLUDED.wins_30_45c, wins_45_60c=EXCLUDED.wins_45_60c,
            wins_60_75c=EXCLUDED.wins_60_75c, wins_above_75c=EXCLUDED.wins_above_75c,
            losses_below_15c=EXCLUDED.losses_below_15c, losses_15_30c=EXCLUDED.losses_15_30c,
            losses_30_45c=EXCLUDED.losses_30_45c, losses_45_60c=EXCLUDED.losses_45_60c,
            losses_60_75c=EXCLUDED.losses_60_75c, losses_above_75c=EXCLUDED.losses_above_75c,
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
        stats["buys_below_15c"], stats["buys_15_30c"], stats["buys_30_45c"],
        stats["buys_45_60c"], stats["buys_60_75c"], stats["buys_above_75c"],
        stats["wins_below_15c"], stats["wins_15_30c"], stats["wins_30_45c"],
        stats["wins_45_60c"], stats["wins_60_75c"], stats["wins_above_75c"],
        stats["losses_below_15c"], stats["losses_15_30c"], stats["losses_30_45c"],
        stats["losses_45_60c"], stats["losses_60_75c"], stats["losses_above_75c"],
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

    # Category aggregates are exclusively owned by compute_category_stats.py.
    # This legacy leaderboard worker must not write the league-aware canonical
    # table or its retired total_pnl/total_volume columns.
    cat_stats = []
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

    # Historical window publication is exclusively owned by the canonical
    # coordinator; this legacy worker must not write retired wallet_window_* tables.

    logger.info(
        f"Done {address[:10]}... | "
        f"vol=${stats['total_volume']:.0f} pnl=${stats['total_pnl']:.0f} "
        f"wr={stats['win_rate']*100:.0f}%"
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
            stats['win_rate'] = stats['win_rate_all'] * 100
        # Persist triangle logic window stats
        await conn.execute("""
            INSERT INTO wallet_metrics_v2 (address, win_rate, roi_pct, resolved_count, winning_count,
                total_volume, total_pnl, biggest_win, biggest_loss,
                active_days,
                avg_buy_price,
                buys_below_15c, buys_15_30c, buys_30_45c, buys_45_60c, buys_60_75c, buys_above_75c,
                wins_below_15c, wins_15_30c, wins_30_45c, wins_45_60c, wins_60_75c, wins_above_75c,
                losses_below_15c, losses_15_30c, losses_30_45c, losses_45_60c, losses_60_75c, losses_above_75c,
                win_rate_100, win_rate_300, win_rate_800, win_rate_1500, win_rate_2500,
                last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                $12,$13,$14,$15,$16,$17,
                $18,$19,$20,$21,$22,$23,
                $24,$25,$26,$27,$28,$29,
                $30,$31,$32,$33,$34,
                NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                active_days=EXCLUDED.active_days,
                avg_buy_price=EXCLUDED.avg_buy_price,
                buys_below_15c=EXCLUDED.buys_below_15c, buys_15_30c=EXCLUDED.buys_15_30c,
                buys_30_45c=EXCLUDED.buys_30_45c, buys_45_60c=EXCLUDED.buys_45_60c,
                buys_60_75c=EXCLUDED.buys_60_75c, buys_above_75c=EXCLUDED.buys_above_75c,
                wins_below_15c=EXCLUDED.wins_below_15c, wins_15_30c=EXCLUDED.wins_15_30c,
                wins_30_45c=EXCLUDED.wins_30_45c, wins_45_60c=EXCLUDED.wins_45_60c,
                wins_60_75c=EXCLUDED.wins_60_75c, wins_above_75c=EXCLUDED.wins_above_75c,
                losses_below_15c=EXCLUDED.losses_below_15c, losses_15_30c=EXCLUDED.losses_15_30c,
                losses_30_45c=EXCLUDED.losses_30_45c, losses_45_60c=EXCLUDED.losses_45_60c,
                losses_60_75c=EXCLUDED.losses_60_75c, losses_above_75c=EXCLUDED.losses_above_75c,
                win_rate_100=EXCLUDED.win_rate_100, win_rate_300=EXCLUDED.win_rate_300, win_rate_800=EXCLUDED.win_rate_800,
                win_rate_1500=EXCLUDED.win_rate_1500, win_rate_2500=EXCLUDED.win_rate_2500,
                last_updated=EXCLUDED.last_updated
        """, address, stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
            stats["total_volume"], stats["total_pnl"],
            stats["biggest_win"], stats["biggest_loss"],
            stats["active_days"],
            stats["avg_buy_price"],
            stats["buys_below_15c"], stats["buys_15_30c"], stats["buys_30_45c"],
            stats["buys_45_60c"], stats["buys_60_75c"], stats["buys_above_75c"],
            stats["wins_below_15c"], stats["wins_15_30c"], stats["wins_30_45c"],
            stats["wins_45_60c"], stats["wins_60_75c"], stats["wins_above_75c"],
            stats["losses_below_15c"], stats["losses_15_30c"], stats["losses_30_45c"],
            stats["losses_45_60c"], stats["losses_60_75c"], stats["losses_above_75c"],
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
                avg_buy_price,
                buys_below_15c, buys_15_30c, buys_30_45c, buys_45_60c, buys_60_75c, buys_above_75c,
                wins_below_15c, wins_15_30c, wins_30_45c, wins_45_60c, wins_60_75c, wins_above_75c,
                losses_below_15c, losses_15_30c, losses_30_45c, losses_45_60c, losses_60_75c, losses_above_75c,
                last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                $12,$13,$14,$15,$16,$17,
                $18,$19,$20,$21,$22,$23,
                $24,$25,$26,$27,$28,$29,
                $30,NOW())
            ON CONFLICT (address) DO UPDATE SET
                win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
                biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
                active_days=EXCLUDED.active_days,
                avg_buy_price=EXCLUDED.avg_buy_price,
                buys_below_15c=EXCLUDED.buys_below_15c, buys_15_30c=EXCLUDED.buys_15_30c,
                buys_30_45c=EXCLUDED.buys_30_45c, buys_45_60c=EXCLUDED.buys_45_60c,
                buys_60_75c=EXCLUDED.buys_60_75c, buys_above_75c=EXCLUDED.buys_above_75c,
                wins_below_15c=EXCLUDED.wins_below_15c, wins_15_30c=EXCLUDED.wins_15_30c,
                wins_30_45c=EXCLUDED.wins_30_45c, wins_45_60c=EXCLUDED.wins_45_60c,
                wins_60_75c=EXCLUDED.wins_60_75c, wins_above_75c=EXCLUDED.wins_above_75c,
                losses_below_15c=EXCLUDED.losses_below_15c, losses_15_30c=EXCLUDED.losses_15_30c,
                losses_30_45c=EXCLUDED.losses_30_45c, losses_45_60c=EXCLUDED.losses_45_60c,
                losses_60_75c=EXCLUDED.losses_60_75c, losses_above_75c=EXCLUDED.losses_above_75c,
                last_updated=EXCLUDED.last_updated
        """, address, stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
            stats["total_volume"], stats["total_pnl"],
            stats["biggest_win"], stats["biggest_loss"],
            stats["active_days"],
            stats["avg_buy_price"],
            stats["buys_below_15c"], stats["buys_15_30c"], stats["buys_30_45c"],
            stats["buys_45_60c"], stats["buys_60_75c"], stats["buys_above_75c"],
            stats["wins_below_15c"], stats["wins_15_30c"], stats["wins_30_45c"],
            stats["wins_45_60c"], stats["wins_60_75c"], stats["wins_above_75c"],
            stats["losses_below_15c"], stats["losses_15_30c"], stats["losses_30_45c"],
            stats["losses_45_60c"], stats["losses_60_75c"], stats["losses_above_75c"])

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
    logger.info("Starting Leaderboard Stats worker (concurrency=%d, interval=%ds)...", CONCURRENCY, POLL_INTERVAL)
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
    raise RuntimeError(
        f"{RETIREMENT_MARKER}: use poly_leaderboard_sync and positions_metrics_compute"
    )
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
