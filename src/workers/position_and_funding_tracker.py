"""
P2P Position Transfers & Internal Wallet Funding Scanner Worker.

Scans:
1. ERC-1155 TransferSingle/TransferBatch on CTF Contract (0x4D97DCd97eC945f40cF65F87097ACe5EA0476045) for P2P outcome token transfers.
2. Direct PositionSplit events outside the CLOB exchange.
3. ERC-20 Transfer events for USDC/USDC.e/pUSD wallet-to-wallet funding.

Updates:
- wallet_position_transfers_v2
- wallet_internal_funding_v2
- wallet_splits_v2
- wallets_v2 & wallet_metrics_v2 funding_source & funded_by lineage.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
import aiohttp
import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

from src.db import get_pool

logger = logging.getLogger("position_and_funding_tracker")

# Polygon Contracts
CTF_CONTRACT = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
USDC_BRIDGED = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
PUSD_TOKEN = "0x48962635f9261e08c35b7c728795a44eb3eb796b"

# Excluded Exchange & Factory Contracts
EXCHANGE_CONTRACTS = {
    "0x0000000000000000000000000000000000000000",
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTF Exchange
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # Neg Risk CTF Exchange
    "0xd91e80cf2e7be2e162c6513ced06f1dD0dA35296",  # Neg Risk Adapter
    "0xab45c5a4b0c941a2f231c04c3f49182e1a254052",  # Proxy Factory
    "0xa6b71e26c5e0845f74c812102ca7114b6a896ab2",  # Gnosis Safe Factory
    "0x00000000000fb5c9adea0298d729a0cb3823cc07",  # Deposit Factory
}

# Known CEX Hot Wallets to distinguish from private internal funding
CEX_HOT_WALLETS = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance 2",
    "0xdfd5293d8e347dfee59e53b239b7e0388d473a7b": "Binance 3",
    "0x503828976d22510aad0201ac7ec88293211d23dc": "Coinbase",
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": "Coinbase 2",
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
    "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "Binance Hot",
}

# Event Signatures
TRANSFER_SINGLE_TOPIC = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
POSITION_SPLIT_TOPIC = "0x40ef03063f135b62b1b590e8d0e74f17730ea45009ec8e546114eb1be36d4df3"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYNC_FILE = os.path.join(_REPO_ROOT, ".transfer_tracker_last_block")


def read_last_block(default_block: int = 91_500_000) -> int:
    if os.path.exists(SYNC_FILE):
        try:
            with open(SYNC_FILE, "r") as f:
                val = f.read().strip()
                if val.isdigit():
                    return int(val)
        except Exception:
            pass
    return default_block


def save_last_block(block: int):
    try:
        with open(SYNC_FILE, "w") as f:
            f.write(str(block))
    except Exception:
        pass


def decode_hex_address(topic: str) -> str:
    if not topic:
        return ""
    clean = str(topic).lower()
    return "0x" + clean[-40:]


def decode_uint256(hex_str: str) -> int:
    if not hex_str:
        return 0
    try:
        clean = hex_str[2:] if hex_str.startswith("0x") else hex_str
        return int(clean, 16)
    except Exception:
        return 0


async def refresh_lineage_summary(conn: asyncpg.Connection, addresses: set[str]):
    """Recompute precomputed lineage aggregates for the given wallets.

    The leaderboard joins wallet_lineage_summary_v2 instead of running
    per-wallet aggregates over the (huge) transfer tables — keeping this
    fresh here keeps those queries fast.
    """
    if not addresses:
        return
    addrs = list(addresses)
    await conn.execute("""
        INSERT INTO wallet_lineage_summary_v2 (
            address, p2p_txn_value, p2p_txn_count,
            fund_transfer_value, fund_transfer_count, updated_at
        )
        SELECT w.address,
               COALESCE(p.v, 0), COALESCE(p.c, 0),
               COALESCE(f.v, 0), COALESCE(f.c, 0), NOW()
        FROM unnest($1::text[]) AS a(addr)
        JOIN wallets_v2 w ON w.address = a.addr
        LEFT JOIN LATERAL (
            SELECT COALESCE(SUM(x.amount), 0) AS v, COUNT(*) AS c FROM (
                SELECT t.amount FROM wallet_position_transfers_v2 t WHERE t.from_address = a.addr
                UNION ALL
                SELECT t.amount FROM wallet_position_transfers_v2 t WHERE t.to_address = a.addr
            ) x
        ) p ON true
        LEFT JOIN LATERAL (
            SELECT COALESCE(SUM(y.amount_usd), 0) AS v, COUNT(*) AS c FROM (
                SELECT f2.amount_usd FROM wallet_internal_funding_v2 f2 WHERE f2.funder_address = a.addr
                UNION ALL
                SELECT f2.amount_usd FROM wallet_internal_funding_v2 f2 WHERE f2.funded_address = a.addr
            ) y
        ) f ON true
        ON CONFLICT (address) DO UPDATE SET
            p2p_txn_value = EXCLUDED.p2p_txn_value,
            p2p_txn_count = EXCLUDED.p2p_txn_count,
            fund_transfer_value = EXCLUDED.fund_transfer_value,
            fund_transfer_count = EXCLUDED.fund_transfer_count,
            updated_at = NOW()
    """, addrs)


async def process_p2p_position_transfers(conn: asyncpg.Connection, logs: list[dict]):
    """Process TransferSingle logs for P2P ERC-1155 position transfers."""
    if not logs:
        return 0

    inserted = 0
    touched: set[str] = set()
    for log in logs:
        try:
            topics = log.get("topics", [])
            t2 = log.get("topic2") or (topics[2] if len(topics) > 2 else None)
            t3 = log.get("topic3") or (topics[3] if len(topics) > 3 else None)
            if not t2 or not t3:
                continue

            from_addr = decode_hex_address(t2)
            to_addr = decode_hex_address(t3)

            # Filter out exchanges and zero-address burns/mints
            if from_addr in EXCHANGE_CONTRACTS or to_addr in EXCHANGE_CONTRACTS:
                continue

            touched.update((from_addr, to_addr))
            data = log.get("data", "")
            if len(data) < 128:  # 64 hex chars for id + 64 hex chars for value
                continue

            clean_data = data[2:] if data.startswith("0x") else data
            token_id_int = int(clean_data[:64], 16)
            amount_raw = int(clean_data[64:128], 16)
            amount = amount_raw / 1_000_000.0  # Polymarket shares have 6 decimals

            if amount <= 0:
                continue

            token_id_str = str(token_id_int)
            tx_hash = log.get("transactionHash") or log.get("transaction_hash", "")
            bnum = int(log.get("blockNumber") or log.get("block_number", 0))
            log_index = int(log.get("logIndex") or log.get("log_index", 0))
            ts = log.get("block_timestamp") or log.get("timestamp")
            
            if ts:
                transferred_at = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                transferred_at = datetime.now(timezone.utc)

            # Insert into wallet_position_transfers_v2
            insert_status = await conn.execute("""
                INSERT INTO wallet_position_transfers_v2 (
                    from_address, to_address, token_id, amount,
                    tx_hash, block_number, transferred_at, log_index
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (tx_hash, log_index, token_id, from_address, to_address) DO NOTHING
            """, from_addr, to_addr, token_id_str, amount, tx_hash, bnum, transferred_at, log_index)

            # Only bump counters / lineage tags when this transfer is NEW.
            # Re-scanning overlapping block ranges must not double-count.
            if insert_status and insert_status.endswith("1"):
                # Keep the unified, uncapped lineage ledger synchronized with
                # its canonical P2P-transfer source as new logs arrive.
                await conn.executemany("""
                    INSERT INTO wallet_lineage_trades_v2 (
                        wallet_address, event_type, counterparty, asset, amount, amount_usd,
                        tx_hash, block_number, event_at, log_index
                    ) VALUES ($1,$2,$3,$4,$5,0,$6,$7,$8,$9)
                    ON CONFLICT DO NOTHING
                """, [
                    (from_addr, "TRANSFER_OUT", to_addr, token_id_str, amount, tx_hash, bnum, transferred_at, log_index),
                    (to_addr, "TRANSFER_IN", from_addr, token_id_str, amount, tx_hash, bnum, transferred_at, log_index),
                ])
                await conn.execute("""
                    UPDATE wallets_v2
                    SET transferred_positions_count = COALESCE(transferred_positions_count, 0) + 1,
                        funding_source = CASE
                            WHEN funding_source = 'cex_deposit' THEN 'inherited_positions'
                            ELSE funding_source
                        END,
                        funded_by = COALESCE(funded_by, $2)
                    WHERE address = $1
                """, to_addr, from_addr)

            inserted += 1
            logger.info(f"[P2P TRANSFER] {amount:,.1f} shares | Token: {token_id_str[:12]}... | From: {from_addr[:10]}... -> To: {to_addr[:10]}... | Tx: {tx_hash[:14]}...")

        except Exception as e:
            logger.debug(f"Error processing position transfer: {e}")

    # Keep the precomputed lineage summary fresh for touched wallets
    try:
        await refresh_lineage_summary(conn, touched)
    except Exception as e:
        logger.warning(f"lineage summary refresh failed: {e}")

    return inserted


async def process_internal_funding_transfers(conn: asyncpg.Connection, logs: list[dict]):
    """Process ERC-20 Transfer logs for direct wallet-to-wallet USDC/pUSD funding."""
    if not logs:
        return 0

    inserted = 0
    touched_funding: set[str] = set()
    for log in logs:
        try:
            contract = (log.get("address") or "").lower()
            asset = "USDC" if contract in (USDC_NATIVE, USDC_BRIDGED) else "pUSD"

            topics = log.get("topics", [])
            t1 = log.get("topic1") or (topics[1] if len(topics) > 1 else None)
            t2 = log.get("topic2") or (topics[2] if len(topics) > 2 else None)
            if not t1 or not t2:
                continue

            from_addr = decode_hex_address(t1)
            to_addr = decode_hex_address(t2)

            if from_addr in EXCHANGE_CONTRACTS or to_addr in EXCHANGE_CONTRACTS:
                continue

            touched_funding.update((from_addr, to_addr))

            raw_val = decode_uint256(log.get("data", ""))
            amount_usd = raw_val / 1_000_000.0

            # Ignore tiny micro-dust transfers (< $5)
            if amount_usd < 5.0:
                continue

            tx_hash = log.get("transactionHash") or log.get("transaction_hash", "")
            bnum = int(log.get("blockNumber") or log.get("block_number", 0))
            ts = log.get("block_timestamp") or log.get("timestamp")
            
            if ts:
                funded_at = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                funded_at = datetime.now(timezone.utc)

            # Insert into wallet_internal_funding_v2
            await conn.execute("""
                INSERT INTO wallet_internal_funding_v2 (
                    funder_address, funded_address, asset, amount, amount_usd,
                    tx_hash, block_number, funded_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (tx_hash, funder_address, funded_address, asset) DO NOTHING
            """, from_addr, to_addr, asset, amount_usd, amount_usd, tx_hash, bnum, funded_at)

            # Check if funder is a known CEX or private wallet
            source_tag = "cex_deposit" if from_addr in CEX_HOT_WALLETS else "internal_funded"

            await conn.execute("""
                UPDATE wallets_v2
                SET funding_source = $2,
                    funded_by = $3,
                    updated_at = NOW()
                WHERE address = $1 AND (funding_source = 'cex_deposit' OR funding_source IS NULL)
            """, to_addr, source_tag, from_addr)

            inserted += 1
            logger.info(f"[INTERNAL FUNDING] ${amount_usd:,.2f} {asset} | From: {from_addr[:10]}... ({CEX_HOT_WALLETS.get(from_addr, 'Private')}) -> To: {to_addr[:10]}... | Tx: {tx_hash[:14]}...")

        except Exception as e:
            logger.error(f"Error processing funding transfer: {e}", exc_info=True)

    try:
        await refresh_lineage_summary(conn, touched_funding)
    except Exception as e:
        logger.warning(f"lineage summary refresh failed: {e}")

    return inserted


async def run_tracker_loop():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [tracker] %(message)s"
    )
    logger.info("==================================================================")
    logger.info("STARTING P2P POSITION TRANSFER & INTERNAL FUNDING TRACKER")
    logger.info("==================================================================")

    pool = await get_pool()
    envio_token = os.getenv("ENVIO_API_TOKEN", os.getenv("ENVIO_API_KEY"))
    hypersync_url = os.getenv("ENVIO_HYPERSYNC_URL", "https://polygon.hypersync.xyz") + "/query"

    headers = {"Content-Type": "application/json", "User-Agent": "TransferTracker"}
    if envio_token:
        headers["Authorization"] = f"Bearer {envio_token}"

    curr_block = read_last_block(91_800_000)
    logger.info(f"Scanning from block: {curr_block:,}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                query = {
                    "from_block": curr_block,
                    "logs": [
                        {
                            "address": [CTF_CONTRACT],
                            "topics": [[TRANSFER_SINGLE_TOPIC]]
                        },
                        {
                            "address": [USDC_NATIVE, USDC_BRIDGED, PUSD_TOKEN],
                            "topics": [[ERC20_TRANSFER_TOPIC]]
                        }
                    ],
                    "field_selection": {
                        "log": ["block_number", "transaction_hash", "log_index", "data", "topic0", "topic1", "topic2", "topic3", "address"],
                        "block": ["number", "timestamp"]
                    },
                    "join_by_block": True
                }

                async with session.post(hypersync_url, json=query, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        logger.warning(f"HyperSync query returned status {resp.status}. Retrying in 5s...")
                        await asyncio.sleep(5)
                        continue

                    res = await resp.json()
                    data = res.get("data", [])
                    next_block = res.get("next_block")
                    archive_height = res.get("archive_height", curr_block)

                    p2p_logs = []
                    funding_logs = []

                    if isinstance(data, list):
                        for d in data:
                            # join_by_block pairs each log group with its block,
                            # giving us the real on-chain timestamp
                            block_ts = (d.get("block") or {}).get("timestamp")
                            for l in d.get("logs", []):
                                if block_ts:
                                    l["block_timestamp"] = block_ts
                                t0 = l.get("topic0") or (l.get("topics", [])[0] if l.get("topics") else None)
                                addr = (l.get("address") or "").lower()

                                if t0 == TRANSFER_SINGLE_TOPIC and addr == CTF_CONTRACT:
                                    p2p_logs.append(l)
                                elif t0 == ERC20_TRANSFER_TOPIC and addr in (USDC_NATIVE, USDC_BRIDGED, PUSD_TOKEN):
                                    funding_logs.append(l)

                    async with pool.acquire() as conn:
                        if p2p_logs:
                            await process_p2p_position_transfers(conn, p2p_logs)
                        if funding_logs:
                            await process_internal_funding_transfers(conn, funding_logs)

                    if next_block and next_block > curr_block:
                        curr_block = next_block
                        save_last_block(curr_block)
                        logger.info(f"Synced up to block: {curr_block:,} / {archive_height:,} (P2P: {len(p2p_logs)}, Funding: {len(funding_logs)})")

                    if curr_block >= archive_height - 10:
                        # Real-time tip reached, sleep for block time
                        await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Error in transfer tracker loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_tracker_loop())
