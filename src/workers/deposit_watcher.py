"""
Deposit Watcher Worker

Monitors tracked wallets for large USDC deposits using the Polymarket Tools API.
Alerts if:
  1. A single deposit >= $10,000
  2. Cumulative deposits in 48 hours >= $50,000

Runs on a schedule (e.g. every 30 minutes).
"""

import asyncio
import asyncpg
import aiohttp
import os
import json
import logging
from datetime import datetime, timezone, timedelta

# Import Discord alerting function
from src.utils.discord import send_discord_webhook

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

SINGLE_DEPOSIT_THRESHOLD = 10_000
CUMULATIVE_DEPOSIT_THRESHOLD = 50_000
BATCH_SIZE = 50


async def fetch_recent_deposits(session: aiohttp.ClientSession, addresses: list[str]) -> list[dict]:
    """Fetch deposit events from Polymarket Tools API for a batch of wallets."""
    url = "https://activity.polymarket-tools.com/api/activity"
    payload = {
        "wallets": addresses,
        "filters": {
            "types": ["DEPOSIT"],
            "timeRange": "ALL_TIME",
            "sortDirection": "DESC"
        }
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("activity", [])
    except Exception as e:
        logger.warning(f"Failed to fetch deposits for batch: {e}")
    return []


async def get_wallet_stats(conn: asyncpg.Connection, address: str) -> dict:
    """Fetch cached stats for the alert message."""
    row = await conn.fetchrow("SELECT win_rate, roi_pct, total_volume, total_pnl, tier FROM tracked_wallets WHERE address = $1", address)
    if row:
        return dict(row)
    return {}


async def trigger_deposit_alert(
    conn: asyncpg.Connection, 
    wallet: str, 
    amount: float, 
    reason: str, 
    tx_hash: str | None = None
):
    """Format and send the Discord alert."""
    stats = await get_wallet_stats(conn, wallet)
    
    win_rate = f"{(stats.get('win_rate', 0) * 100):.1f}%"
    roi = f"{(stats.get('roi_pct', 0)):.1f}%"
    if stats.get('roi_pct', 0) > 0:
        roi = f"+{roi}"
    
    vol = f"${(stats.get('total_volume', 0) / 1000000):.1f}M" if stats.get('total_volume', 0) > 1000000 else f"${stats.get('total_volume', 0):,.0f}"
    pnl = f"${(stats.get('total_pnl', 0)):,.0f}"
    if stats.get('total_pnl', 0) > 0:
        pnl = f"+{pnl}"
        
    tier = stats.get('tier', 'Unknown')
    
    embed = {
        "title": "ðŸ’° Large Deposit Detected!",
        "color": 0x00FF00,
        "fields": [
            {"name": "Wallet", "value": f"[{wallet[:8]}...{wallet[-6:]}](https://polymarket.com/profile/{wallet})", "inline": True},
            {"name": "Amount", "value": f"**${amount:,.0f} USDC**", "inline": True},
            {"name": "Trigger", "value": reason, "inline": False},
            {"name": "Wallet Stats", "value": f"â€¢ Win Rate: {win_rate} | ROI: {roi}\nâ€¢ Volume: {vol} | PnL: {pnl}\nâ€¢ Tier: ðŸ† {tier}", "inline": False}
        ]
    }
    
    if tx_hash:
        embed["url"] = f"https://polygonscan.com/tx/{tx_hash}"
    
    # Send to Discord
    success = await send_discord_webhook(
        content="New whale deposit activity!",
        embeds=[embed],
        channel="deposits"  # We'll map this in the discord function if needed
    )
    if success:
        logger.info(f"Sent deposit alert for {wallet}: ${amount:,.0f}")


async def check_cumulative_deposits(conn: asyncpg.Connection, wallet: str):
    """Check if the 48-hour cumulative deposit amount exceeds $50k."""
    row = await conn.fetchrow("""
        SELECT SUM(amount_usdc) as total_48h 
        FROM wallet_deposits 
        WHERE wallet_address = $1 
          AND deposited_at > NOW() - INTERVAL '48 hours'
          AND flagged_cumulative = FALSE
    """, wallet)
    
    total = row["total_48h"] if row and row["total_48h"] else 0
    if total >= CUMULATIVE_DEPOSIT_THRESHOLD:
        # Insert into smart_money_alerts for dashboard visibility
        # Use synthetic tx_hash since cumulative has no single transaction
        synthetic_tx = f"cumulative_{wallet}_{int(datetime.now(timezone.utc).timestamp())}"
        try:
            await conn.execute("""
                INSERT INTO smart_money_alerts (address, alert_type, amount_usdc, transaction_hash, created_at)
                VALUES ($1, 'LARGE_DEPOSIT', $2, $3, NOW())
                ON CONFLICT (transaction_hash) DO NOTHING
            """, wallet, total, synthetic_tx)
        except Exception as e:
            logger.warning(f"Failed to insert smart_money_alert for cumulative deposit: {e}")

        await trigger_deposit_alert(
            conn, 
            wallet, 
            total, 
            "Cumulative deposits â‰¥ $50k in 48 hours"
        )
        
        # Mark all recent deposits as cumulatively flagged so we don't alert again
        await conn.execute("""
            UPDATE wallet_deposits 
            SET flagged_cumulative = TRUE 
            WHERE wallet_address = $1 AND deposited_at > NOW() - INTERVAL '48 hours'
        """, wallet)


async def process_batch(conn: asyncpg.Connection, session: aiohttp.ClientSession, wallets: list[str]):
    """Process a batch of wallets."""
    deposits = await fetch_recent_deposits(session, wallets)
    
    if not deposits:
        return
        
    for d in deposits:
        wallet = d.get("proxyWallet", "").lower()
        amount = float(d.get("usdcSize", 0) or 0)
        ts = int(d.get("timestamp", 0))
        tx_hash = d.get("transactionHash", "")
        
        if not wallet or not tx_hash or amount <= 0:
            continue
            
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        
        # We only care about somewhat recent deposits (e.g. last 48 hours)
        # to avoid processing the entire history every time
        if dt < datetime.now(timezone.utc) - timedelta(hours=48):
            continue
            
        is_single_flag = amount >= SINGLE_DEPOSIT_THRESHOLD
        
        # Insert deposit, ignore if duplicate tx_hash
        res = await conn.execute("""
            INSERT INTO wallet_deposits (wallet_address, tx_hash, amount_usdc, deposited_at, flagged_single)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tx_hash) DO NOTHING
        """, wallet, tx_hash, amount, dt, is_single_flag)
        
        # If it was actually inserted (not a duplicate)
        if res == "INSERT 0 1":
            logger.info(f"New deposit found: {wallet[:8]}... | ${amount:,.0f}")

            # Insert into smart_money_alerts for dashboard visibility (only >= $10k)
            if amount >= SINGLE_DEPOSIT_THRESHOLD:
                try:
                    await conn.execute("""
                        INSERT INTO smart_money_alerts (address, alert_type, amount_usdc, transaction_hash, created_at)
                        VALUES ($1, 'LARGE_DEPOSIT', $2, $3, NOW())
                        ON CONFLICT (transaction_hash) DO NOTHING
                    """, wallet, amount, tx_hash)
                except Exception as e:
                    logger.warning(f"Failed to insert smart_money_alert: {e}")

            # 1. Alert for single large deposit
            if is_single_flag:
                await trigger_deposit_alert(
                    conn, 
                    wallet, 
                    amount, 
                    f"Single deposit â‰¥ ${SINGLE_DEPOSIT_THRESHOLD:,.0f}",
                    tx_hash
                )
                
    # 2. After processing all new deposits, check cumulative thresholds for these wallets
    # Only need to check wallets that actually had deposits inserted, 
    # but checking all in the batch is safer and fast enough.
    for wallet in set(w.lower() for w in wallets):
        await check_cumulative_deposits(conn, wallet)
        await asyncio.sleep(0.1)


async def get_all_wallet_addresses(conn: asyncpg.Connection) -> list[str]:
    """Get ALL known wallet addresses â€” tracked, queued, and deposit history.
    Uses UNION for efficient dedup."""
    rows = await conn.fetch("""
        SELECT DISTINCT address FROM (
            SELECT address FROM tracked_wallets
            UNION
            SELECT address FROM wallet_discovery_queue
            UNION
            SELECT DISTINCT wallet_address FROM wallet_deposits
        ) all_wallets
    """)
    return [r["address"] for r in rows]


async def run_deposit_watcher(db_url: str = DB_URL):
    """Main entry point â€” globally checks ALL known wallets for deposits."""
    logger.info("Starting deposit watcher worker (global mode)...")
    while True:
        try:
            conn = await asyncpg.connect(db_url)
            try:
                wallets = await get_all_wallet_addresses(conn)
                logger.info(f"Found {len(wallets)} total wallets to check for deposits (global).")

                if wallets:
                    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                        for i in range(0, len(wallets), BATCH_SIZE):
                            batch = wallets[i:i+BATCH_SIZE]
                            await process_batch(conn, session, batch)
                            await asyncio.sleep(1)
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Error in deposit watcher cycle: {e}")

        await asyncio.sleep(1800)
        logger.info("Starting next deposit watcher cycle...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_deposit_watcher())

