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

from src.utils.alchemy_client import (
    fetch_usdc_deposits,
    fetch_usdc_withdrawals,
    alchemy_get_token_balances,
    USDC_CONTRACT,
)
from src.utils.category_classifier import classify_tags, flatten_subcategory
from src.workers.window_stats import compute_category_window_stats, select_headline_pnl, _parse_end

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = 300
CONCURRENCY = int(os.environ.get("STATS_WORKER_CONCURRENCY", "10"))
API_DELAY = 0.03  # 30ms between sequential API calls within a wallet


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


# ── API Fetchers ──────────────────────────────────────────────────────────

async def _get(session: aiohttp.ClientSession, url: str) -> list | dict | None:
    """Single shared GET helper with retry."""
    for attempt in range(2):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            if attempt == 0:
                await asyncio.sleep(0.5)
    return None


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_positions = []
    offset = 0
    limit = 500
    while True:
        data = await _get(session, f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_positions.extend(data)
        if len(data) < limit:
            break
        offset += limit
        await asyncio.sleep(API_DELAY)
    return all_positions


async def fetch_closed_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_closed = []
    offset = 0
    limit = 50
    max_closed = 2500
    while True:
        data = await _get(session, f"https://data-api.polymarket.com/closed-positions?user={address}&limit={limit}&offset={offset}")
        if not data or not isinstance(data, list):
            break
        all_closed.extend(data)
        if len(data) < limit or len(all_closed) >= max_closed:
            break
        offset += limit
        await asyncio.sleep(API_DELAY)
    return all_closed[:max_closed]


async def fetch_trades_after(session: aiohttp.ClientSession, address: str, cutoff: datetime) -> list[dict]:
    all_trades = []
    limit = 500
    max_trades = 2500  # Cap to avoid slow wallets blocking the queue
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
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception:
        pass
    return 0.0


PM_CATEGORIES = ["SPORTS", "POLITICS", "CRYPTO", "ESPORTS", "CULTURE", "TECH", "FINANCE", "ECONOMICS", "WEATHER"]


# ── Compute Functions ─────────────────────────────────────────────────────

def compute_stats(trades, positions, closed_positions, headline_pnl, headline_volume, total_pnl, realized_pnl, unrealized_pnl, start_stats_at):
    total_volume = 0.0
    max_trade_size = 0.0
    trade_dates: set[str] = set()
    for t in trades:
        size = _parse(t.get("size"))
        price = _parse(t.get("price"))
        usdc_vol = size * price
        total_volume += usdc_vol
        if usdc_vol > max_trade_size:
            max_trade_size = usdc_vol
        ts = t.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                trade_dates.add(dt.strftime("%Y-%m-%d"))
            except Exception:
                pass

    resolved_count = 0
    winning_count = 0
    biggest_win = 0.0
    biggest_loss = 0.0
    trades_2x = 0
    trades_1_5x = 0
    for cp in closed_positions:
        rpnl = _parse(cp.get("realizedPnl"))
        total_bought = _parse(cp.get("totalBought"))
        resolved_count += 1
        if rpnl > 0:
            winning_count += 1
        if total_bought > 0:
            if rpnl >= total_bought:
                trades_2x += 1
            if rpnl >= total_bought * 0.5:
                trades_1_5x += 1
        if rpnl > biggest_win:
            biggest_win = rpnl
        if rpnl < biggest_loss:
            biggest_loss = rpnl

    # Fallback: when closed-positions returns empty but trades exist,
    # use trade count so wallet doesn't show as "0 trades"
    effective_volume = headline_volume
    effective_pnl = headline_pnl
    if resolved_count == 0 and len(trades) > 0:
        resolved_count = len(trades)
        # Estimate wins from PnL direction
        if effective_pnl > 0:
            winning_count = max(1, resolved_count // 2)

    active_days = max(len(trade_dates), 1)
    win_rate = (winning_count / resolved_count) if resolved_count > 0 else 0.0
    roi_pct = (effective_pnl / effective_volume * 100) if effective_volume > 0 else 0.0
    alpha_score = (win_rate * 50) + (trades_2x * 10) + (trades_1_5x * 5) + (effective_pnl / 1000)
    if effective_volume >= 1_000_000:
        tier = "Diamond"
    elif effective_volume >= 500_000:
        tier = "Platinum"
    elif effective_volume >= 100_000:
        tier = "Gold"
    elif effective_volume >= 10_000:
        tier = "Silver"
    else:
        tier = "Bronze"
    return {
        "total_volume": effective_volume, "total_pnl": effective_pnl,
        "realized_pnl": realized_pnl, "unrealized_pnl": unrealized_pnl,
        "win_rate": win_rate, "roi_pct": roi_pct,
        "resolved_count": resolved_count, "winning_count": winning_count,
        "max_trade_size": max_trade_size,
        "biggest_win": biggest_win, "biggest_loss": biggest_loss,
        "trades_2x": trades_2x, "trades_1_5x": trades_1_5x,
        "alpha_score": alpha_score, "tier": tier, "active_days": active_days,
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
    trade_by_cid: dict[str, str] = {}
    category_volume: dict[str, float] = {}
    category_pnl: dict[str, float] = {}
    category_wins: dict[str, int] = {}
    category_resolved: dict[str, int] = {}
    category_last_active: dict[str, datetime] = {}

    for t in trades:
        title = t.get("title") or ""
        cid = t.get("conditionId") or ""
        if not title or not cid:
            continue
        cat, _ = classify_tags([title])
        trade_by_cid[cid] = cat
        size = _parse(t.get("size"))
        price = _parse(t.get("price"))
        category_volume[cat] = category_volume.get(cat, 0.0) + size * price

    for cp in closed_positions:
        cid = cp.get("conditionId") or ""
        cat = trade_by_cid.get(cid)
        if not cat:
            cp_title = cp.get("title") or ""
            cat, _ = classify_tags([cp_title]) if cp_title else ("Other", "General")
        rpnl = _parse(cp.get("realizedPnl"))
        category_pnl[cat] = category_pnl.get(cat, 0.0) + rpnl
        category_resolved[cat] = category_resolved.get(cat, 0) + 1
        if rpnl > 0:
            category_wins[cat] = category_wins.get(cat, 0) + 1
        end = _parse_end(cp.get("endDate"))
        if end and (category_last_active.get(cat) is None or end > category_last_active[cat]):
            category_last_active[cat] = end

    all_cats = set(category_volume.keys()) | set(category_pnl.keys()) | set(pm.keys())
    result = []
    for cat in sorted(all_cats):
        if cat in pm and pm[cat].get("pnl") is not None:
            pnl, vol = pm[cat]["pnl"], pm[cat].get("volume", 0.0)
        else:
            pnl, vol = category_pnl.get(cat, 0.0), category_volume.get(cat, 0.0)
        resolved = category_resolved.get(cat, 0)
        wins = category_wins.get(cat, 0)
        win_rate = (wins / resolved) if resolved > 0 else 0.0
        roi = (pnl / vol * 100) if vol > 0 else 0.0
        result.append({
            "category": cat, "total_pnl": round(pnl, 2), "total_volume": round(vol, 2),
            "win_rate": round(win_rate, 4), "resolved_count": resolved,
            "winning_count": wins, "roi_pct": round(roi, 2),
            "last_active": category_last_active.get(cat),
        })
    return result


# ── Core: fetch all data for one wallet concurrently ──────────────────────

async def _fetch_wallet_data(session: aiohttp.ClientSession, address: str, start_stats_at: datetime) -> dict:
    """Fire all API calls for a single wallet concurrently."""
    trades_f, positions_f, closed_f, balance_f, website_f = await asyncio.gather(
        fetch_trades_after(session, address, start_stats_at),
        fetch_positions(session, address),
        fetch_closed_positions(session, address),
        fetch_balance(session, address),
        fetch_website_pnl(session, address),
        return_exceptions=True,
    )
    trades = trades_f if isinstance(trades_f, list) else []
    positions = positions_f if isinstance(positions_f, list) else []
    closed = closed_f if isinstance(closed_f, list) else []
    balance = balance_f if isinstance(balance_f, (int, float)) else 0.0
    website = website_f if isinstance(website_f, dict) else None

    # Deposits/withdrawals (Alchemy) concurrently
    deposits_f, withdrawals_f = await asyncio.gather(
        fetch_usdc_deposits(session, address),
        fetch_usdc_withdrawals(session, address),
        return_exceptions=True,
    )
    deposits = deposits_f if isinstance(deposits_f, (int, float)) else None
    withdrawals = withdrawals_f if isinstance(withdrawals_f, (int, float)) else None

    return {
        "trades": trades, "positions": positions, "closed": closed,
        "balance": balance, "website": website,
        "deposits": deposits, "withdrawals": withdrawals,
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
        "SELECT added_at, start_stats_at, start_balance, start_deposits, start_withdrawals FROM tracked_wallets WHERE address = $1",
        address
    )
    if not row:
        return

    start_stats_at = row["start_stats_at"]
    if not start_stats_at:
        start_stats_at = row["added_at"] or datetime.now(timezone.utc)
        await conn.execute("UPDATE tracked_wallets SET start_stats_at = $1 WHERE address = $2", start_stats_at, address)

    # Fetch all wallet data concurrently
    data = await _fetch_wallet_data(session, address, start_stats_at)
    trades = data["trades"]
    positions = data["positions"]
    closed = data["closed"]
    balance = data["balance"]
    website = data["website"]
    deposits = data["deposits"]
    withdrawals = data["withdrawals"]

    if deposits is None or withdrawals is None:
        logger.warning(f"Skipping {address[:10]}... this cycle — could not fetch deposits/withdrawals")
        return

    website_pnl = website["pnl"] if website else 0.0
    website_volume = website["volume"] if website else 0.0

    if website:
        await conn.execute("""
            UPDATE tracked_wallets SET website_pnl=$2, website_volume=$3, website_rank=$4, username=$5, website_pnl_updated_at=NOW()
            WHERE address=$1
        """, address, website_pnl, website_volume, website["rank"], website["username"])

    start_balance = float(row["start_balance"] or 0)
    start_deposits = float(row["start_deposits"] or 0)
    start_withdrawals = float(row["start_withdrawals"] or 0)
    if start_balance == 0 and start_deposits == 0 and start_withdrawals == 0:
        start_balance = balance
        start_deposits = deposits
        start_withdrawals = withdrawals
        await conn.execute(
            "UPDATE tracked_wallets SET start_balance=$1, start_deposits=$2, start_withdrawals=$3 WHERE address=$4",
            start_balance, start_deposits, start_withdrawals, address
        )

    position_value = 0.0
    unrealized_pnl = 0.0
    for pos in (positions or []):
        curr_val = _parse(pos.get("currentValue"))
        if curr_val > 0:
            position_value += curr_val
            unrealized_pnl += _parse(pos.get("cashPnl"))

    realized_pnl = (balance - start_balance) + (withdrawals - start_withdrawals) - (deposits - start_deposits)
    total_pnl = realized_pnl + unrealized_pnl
    headline = select_headline_pnl(website, total_pnl, _computed_volume(trades))
    await conn.execute("UPDATE tracked_wallets SET pnl_source=$2 WHERE address=$1", address, headline["pnl_source"])
    stats = compute_stats(trades, positions, closed, headline["pnl"], headline["volume"], total_pnl, realized_pnl, unrealized_pnl, start_stats_at)

    # ── Batch DB writes ──
    await conn.execute("""
        INSERT INTO wallet_stats (address, win_rate, roi_pct, resolved_count, winning_count,
            total_volume, total_pnl, unrealised_pnl, biggest_win, biggest_loss, tier,
            active_days, alpha_score, trades_2x, trades_1_5x, last_updated)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NOW())
        ON CONFLICT (address) DO UPDATE SET
            win_rate=EXCLUDED.win_rate, roi_pct=EXCLUDED.roi_pct, resolved_count=EXCLUDED.resolved_count,
            winning_count=EXCLUDED.winning_count, total_volume=EXCLUDED.total_volume, total_pnl=EXCLUDED.total_pnl,
            unrealised_pnl=EXCLUDED.unrealised_pnl, biggest_win=EXCLUDED.biggest_win, biggest_loss=EXCLUDED.biggest_loss,
            tier=EXCLUDED.tier, active_days=EXCLUDED.active_days, alpha_score=EXCLUDED.alpha_score,
            trades_2x=EXCLUDED.trades_2x, trades_1_5x=EXCLUDED.trades_1_5x, last_updated=EXCLUDED.last_updated
    """, address, stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
        stats["total_volume"], stats["total_pnl"], stats["unrealized_pnl"],
        stats["biggest_win"], stats["biggest_loss"], stats["tier"],
        stats["active_days"], stats["alpha_score"], stats["trades_2x"], stats["trades_1_5x"])

    await conn.execute("""
        UPDATE tracked_wallets SET
            total_pnl=$2, realized_pnl=$3, unrealized_pnl=$4, total_volume=$5,
            win_rate=$6, roi_pct=$7, resolved_count=$8, winning_count=$9,
            max_trade_size=$10, tier=$11, alpha_score=$12, balance=$13,
            deposits=$14, withdrawals=$15, position_value=$16, last_indexed=NOW()
        WHERE address=$1
    """, address, stats["total_pnl"], stats["realized_pnl"], stats["unrealized_pnl"],
        stats["total_volume"], stats["win_rate"], stats["roi_pct"],
        stats["resolved_count"], stats["winning_count"],
        stats["max_trade_size"], stats["tier"], stats["alpha_score"],
        balance, deposits, withdrawals, position_value)

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

    cat_stats = compute_category_stats(trades, closed, pm_category_pnl)
    for cs in cat_stats:
        await conn.execute("""
            INSERT INTO wallet_category_stats (address, category, total_pnl, total_volume, win_rate, resolved_count, winning_count, roi_pct, last_active, computed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (address, category) DO UPDATE SET
                total_pnl=EXCLUDED.total_pnl, total_volume=EXCLUDED.total_volume,
                win_rate=EXCLUDED.win_rate, resolved_count=EXCLUDED.resolved_count,
                winning_count=EXCLUDED.winning_count, roi_pct=EXCLUDED.roi_pct,
                last_active=EXCLUDED.last_active, computed_at=NOW()
        """, address, cs["category"], cs["total_pnl"], cs["total_volume"],
            cs["win_rate"], cs["resolved_count"], cs["winning_count"], cs["roi_pct"], cs["last_active"])

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
                "UPDATE tracked_wallets SET last_trade_at = GREATEST(last_trade_at, $2) WHERE address = $1",
                address, latest_dt,
            )

    # ── Dormancy check: inactive > 30 days → is_dormant = true ──
    dormancy_row = await conn.fetchrow(
        "SELECT last_trade_at FROM tracked_wallets WHERE address = $1", address
    )
    if dormancy_row and dormancy_row["last_trade_at"]:
        days_inactive = (datetime.now(timezone.utc) - dormancy_row["last_trade_at"]).days
        is_dormant = days_inactive > 30
        await conn.execute(
            "UPDATE tracked_wallets SET is_dormant = $2 WHERE address = $1",
            address, is_dormant,
        )
    else:
        is_dormant = False

    # ── Curated promotion: PnL > $10k AND (ROI > 30% OR win_rate > 60% OR resolved > 5) ──
    qualifies = (
        not is_dormant
        and stats["total_pnl"] > 10_000
        and (
            stats["roi_pct"] > 30
            or stats["win_rate"] > 0.60
            or stats["resolved_count"] > 5
        )
    )
    await conn.execute("""
        UPDATE tracked_wallets SET
            is_curated = $2,
            curated_at = CASE WHEN $2 = TRUE AND is_curated = FALSE THEN NOW()
                              WHEN $2 = FALSE THEN NULL
                              ELSE curated_at END,
            last_checked_for_curated = NOW()
        WHERE address = $1
    """, address, qualifies)

    # ── Store ALL trades for curated wallets ──
    if qualifies:
        for t in trades:
            title = t.get("title") or t.get("market_name") or ""
            tx_hash = t.get("transactionHash") or t.get("txHash") or ""
            condition_id = t.get("conditionId") or ""
            side = t.get("side") or ""
            price = _parse(t.get("price"))
            size = _parse(t.get("size"))
            usdc = price * size
            ts = t.get("timestamp", 0)
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else datetime.now(timezone.utc)

            cat, detailed_sub = classify_tags([title]) if title else ("Other", "General")
            flat_sub = flatten_subcategory(cat, detailed_sub)

            if tx_hash:
                try:
                    await conn.execute("""
                        INSERT INTO curated_wallet_trades
                        (wallet_address, tx_hash, condition_id, market_name, side, price,
                         size, amount_usdc, traded_at, category, subcategory, detailed_subcategory)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        ON CONFLICT (wallet_address, tx_hash) DO NOTHING
                    """, address, tx_hash, condition_id, title, side, price,
                        size, usdc, dt, cat, flat_sub, detailed_sub)
                except Exception as e:
                    logger.warning(f"Failed to insert curated trade for {address[:10]}: {e}")


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
                    SELECT address FROM tracked_wallets 
                    ORDER BY 
                        last_indexed ASC NULLS FIRST,
                        last_checked_for_curated ASC NULLS FIRST
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
                                await process_wallet(conn, session, addr)
                        done += 1
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
