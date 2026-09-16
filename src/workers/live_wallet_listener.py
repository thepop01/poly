"""
Live Polymarket Wallet Creation Listener Worker.

Listens in real time for on-chain proxy wallet creation events on Polygon:
1. Polymarket Deposit Wallet Factory Proxy (0x00000000000Fb5C9ADea0298D729A0CB3823Cc07)
2. Gnosis Safe Proxy Factory v1.3.0 (0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2)
3. Polymarket Legacy Proxy Factory (0xaB45c5A4B0c941a2F231C04C3f49182e1A254052)

Architecture:
- Real-time: WebSocket subscription to mined logs via Alchemy/QuickNode (<2s latency).
- Catch-up: Envio HyperSync scan on startup to backfill any blocks missed while offline.
- Ingestion: Upserts new wallets immediately into wallets_v2 and wallet_sources_v2.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
import aiohttp
import asyncpg
import websockets
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [live_wallet_listener] %(message)s"
)
logger = logging.getLogger("live_wallet_listener")

from src.db import DATABASE_URL as DB_URL, DB_SSL_CONFIG
LAST_BLOCK_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    ".creation_last_block"
)

# Factories & Event Topics
FACTORIES = [
    "0x00000000000fb5c9adea0298d729a0cb3823cc07", # Deposit Wallet Factory Proxy
    "0xa6b71e26c5e0845f74c812102ca7114b6a896ab2", # Gnosis Safe Proxy Factory v1.3.0
    "0xab45c5a4b0c941a2f231c04c3f49182e1a254052", # Legacy Polymarket Proxy Factory
]

# Topic 0 Signatures
DEPOSIT_WALLET_TOPIC = "0x7441de0ad639fe5d2bf1c22447715a0528b682385736bb40ae8dd92555eb8276"
GNOSIS_PROXY_TOPIC   = "0x4f51faf6c4561ff95f067657e43439f0f856d97c04d9ec9070a6199ad418e235"

# Alchemy Keys
ALCHEMY_KEYS = [
    k for k in [
        os.getenv("ALCHEMY_API_KEY_1"),
        os.getenv("ALCHEMY_API_KEY_2"),
        os.getenv("ALCHEMY_API_KEY")
    ] if k and not k.startswith("your_")
]
_key_idx = 0


def get_ws_url() -> str:
    global _key_idx
    if ALCHEMY_KEYS:
        key = ALCHEMY_KEYS[_key_idx % len(ALCHEMY_KEYS)]
        return f"wss://polygon-mainnet.g.alchemy.com/v2/{key}"
    qn_key = os.getenv("QUICKNODE_API_KEY")
    if qn_key:
        return f"wss://polygon-mainnet.discover.quiknode.pro/{qn_key}/"
    return "wss://polygon-mainnet.g.alchemy.com/v2/demo"


def rotate_key():
    global _key_idx
    _key_idx += 1
    logger.info(f"Rotated to next WebSocket key index: {_key_idx % max(1, len(ALCHEMY_KEYS))}")


def read_last_block() -> int | None:
    if os.path.exists(LAST_BLOCK_FILE):
        try:
            with open(LAST_BLOCK_FILE, "r") as f:
                val = f.read().strip()
                if val.isdigit():
                    return int(val)
        except Exception:
            pass
    return None


def save_last_block(block_number: int):
    """Persist the high-water block. Never regresses: an out-of-order write of a
    lower block must not roll back the watermark (would cause redundant rescans)."""
    try:
        current = read_last_block()
        if current is not None and block_number <= current:
            return
        os.makedirs(os.path.dirname(LAST_BLOCK_FILE), exist_ok=True)
        with open(LAST_BLOCK_FILE, "w") as f:
            f.write(str(block_number))
    except Exception as e:
        logger.warning(f"Failed to save last block {block_number}: {e}")


def parse_creation_log(log: dict) -> dict | None:
    """Parse log dict into created wallet and metadata."""
    try:
        t0 = log.get("topic0")
        topics = log.get("topics", [])
        if not t0 and topics:
            t0 = topics[0]
            
        t1 = log.get("topic1") or (topics[1] if len(topics) > 1 else None)
        t2 = log.get("topic2") or (topics[2] if len(topics) > 2 else None)
        
        created_wallet = None
        owner_eoa = None
        source_detail = "Polymarket Proxy Factory Creation"

        if t0 == DEPOSIT_WALLET_TOPIC:
            # Topic1 = owner EOA, Topic2 = newly deployed proxy wallet
            if t1:
                owner_eoa = "0x" + str(t1)[-40:].lower()
            if t2:
                created_wallet = "0x" + str(t2)[-40:].lower()
            source_detail = "Polymarket Deposit Wallet Factory Creation"
        elif t0 == GNOSIS_PROXY_TOPIC:
            # Topic1 = newly deployed Gnosis Safe proxy
            if t1:
                created_wallet = "0x" + str(t1)[-40:].lower()
            source_detail = "Gnosis Safe Proxy Factory (Browser Sign-in)"
        else:
            return None

        if not created_wallet or len(created_wallet) != 42 or created_wallet == "0x" + "0"*40:
            return None

        tx = log.get("transactionHash") or log.get("transaction_hash", "")
        raw_bnum = log.get("blockNumber") or log.get("block_number", 0)
        bnum = int(raw_bnum, 16) if isinstance(raw_bnum, str) and raw_bnum.startswith("0x") else int(raw_bnum or 0)

        return {
            "created_wallet": created_wallet,
            "owner_eoa": owner_eoa,
            "tx_hash": tx,
            "block_number": bnum,
            "source_detail": source_detail,
        }
    except Exception as e:
        logger.debug(f"Error parsing creation log: {e}")
        return None


async def ingest_created_wallets(conn: asyncpg.Connection, wallets: list[dict]):
    """Insert newly created wallets into database."""
    if not wallets:
        return 0

    inserted = 0
    for w in wallets:
        addr = w["created_wallet"].lower()
        detail = w["source_detail"]
        
        try:
            # 1. Insert into wallets_v2 as NEW tier
            await conn.execute("""
                INSERT INTO wallets_v2 (
                    address, tier, tier_reason, is_dormant, 
                    added_at, updated_at, next_check_at
                ) VALUES ($1, 'NEW', 'live_wallet_creation', FALSE, NOW(), NOW(), NOW())
                ON CONFLICT (address) DO UPDATE SET
                    is_dormant = FALSE,
                    updated_at = NOW()
            """, addr)

            # 2. Insert into wallet_sources_v2
            await conn.execute("""
                INSERT INTO wallet_sources_v2 (
                    address, source, source_detail, spotted_at
                ) VALUES ($1, 'creation', $2, NOW())
                ON CONFLICT (address, source) DO UPDATE SET
                    source_detail = EXCLUDED.source_detail,
                    spotted_at = NOW()
            """, addr, detail)

            inserted += 1
            logger.info(f"[*] NEW WALLET INGESTED: {addr} | Source: {detail} | Block: {w['block_number']:,} | Tx: {w['tx_hash'][:14]}...")
        except Exception as e:
            if conn.is_closed():
                raise e
            logger.error(f"Failed to ingest wallet {addr}: {e}")

    return inserted


async def run_hypersync_catchup(from_block: int) -> int:
    """Catch up on missed creation events using Envio HyperSync."""
    envio_token = os.getenv("ENVIO_API_TOKEN", os.getenv("ENVIO_API_KEY"))
    hypersync_url = os.getenv("ENVIO_HYPERSYNC_URL", "https://polygon.hypersync.xyz") + "/query"

    headers = {"Content-Type": "application/json", "User-Agent": "HyperSyncClient"}
    if envio_token:
        headers["Authorization"] = f"Bearer {envio_token}"

    logger.info(f"Running Envio HyperSync catch-up from block {from_block:,}...")
    conn = await asyncpg.connect(DB_URL, ssl=DB_SSL_CONFIG)
    total_caught_up = 0
    curr_block = from_block
    max_seen = from_block

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                query = {
                    "from_block": curr_block,
                    "logs": [
                        {
                            "address": FACTORIES,
                            "topics": [[DEPOSIT_WALLET_TOPIC, GNOSIS_PROXY_TOPIC]]
                        }
                    ],
                    "field_selection": {
                        "log": ["block_number", "transaction_hash", "log_index", "data", "topic0", "topic1", "topic2", "topic3", "address"]
                    }
                }

                async with session.post(hypersync_url, json=query, headers=headers) as resp:
                    if resp.status != 200:
                        break
                    res = await resp.json()
                    data = res.get("data", [])
                    next_block = res.get("next_block")
                    archive_height = res.get("archive_height", 0)

                    batch = []
                    if isinstance(data, list):
                        for d in data:
                            for l in d.get("logs", []):
                                parsed = parse_creation_log(l)
                                if parsed:
                                    batch.append(parsed)
                                    if parsed["block_number"] > max_seen:
                                        max_seen = parsed["block_number"]

                    if batch:
                        cnt = await ingest_created_wallets(conn, batch)
                        total_caught_up += cnt

                    if not next_block or next_block >= archive_height:
                        break
                    curr_block = next_block

        if max_seen > from_block:
            save_last_block(max_seen)

        logger.info(f"HyperSync catch-up complete: {total_caught_up:,} wallets caught up up to block {max_seen:,}")
        return total_caught_up
    finally:
        await conn.close()


async def run_live_listener():
    """Main daemon loop running real-time WebSocket subscription with auto-reconnect."""
    logger.info("=======================================================")
    logger.info("STARTING LIVE POLYMARKET WALLET CREATION LISTENER")
    logger.info(f"Factories Monitored : {len(FACTORIES)}")
    logger.info("=======================================================")

    # 1. Check catch-up on startup
    last_saved = read_last_block()
    if last_saved:
        try:
            await run_hypersync_catchup(last_saved)
        except Exception as e:
            logger.warning(f"Startup catchup failed: {e}")

    retry_count = 0
    max_backoff = 30

    while True:
        url = get_ws_url()
        logger.info(f"Connecting to Polygon WebSocket endpoint...")

        try:
            conn = await asyncpg.connect(DB_URL, ssl=DB_SSL_CONFIG)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                logger.info("WebSocket connected! Subscribing to factory logs...")

                sub_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": [
                        "logs",
                        {
                            "address": FACTORIES,
                            "topics": [[DEPOSIT_WALLET_TOPIC, GNOSIS_PROXY_TOPIC]]
                        }
                    ]
                }
                await ws.send(json.dumps(sub_request))
                resp = await ws.recv()
                logger.info(f"Subscription confirmed: {resp}")
                retry_count = 0  # Reset on successful connect

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if "params" in data:
                        log = data["params"]["result"]
                        parsed = parse_creation_log(log)
                        if parsed:
                            await ingest_created_wallets(conn, [parsed])
                            bnum = parsed["block_number"]
                            if bnum:
                                save_last_block(bnum)

        except (websockets.ConnectionClosed, websockets.WebSocketException, OSError, asyncio.TimeoutError) as e:
            logger.warning(f"WebSocket disconnected ({e}). Reconnecting...")
            rotate_key()
        except Exception as e:
            logger.error(f"Unexpected listener error: {e}", exc_info=True)
            rotate_key()
        finally:
            try:
                if 'conn' in locals() and not conn.is_closed():
                    await conn.close()
            except Exception:
                pass

        retry_count += 1
        delay = min(max_backoff, 2 ** min(retry_count, 5))
        logger.info(f"Waiting {delay}s before reconnecting...")
        await asyncio.sleep(delay)


if __name__ == "__main__":
    try:
        asyncio.run(run_live_listener())
    except KeyboardInterrupt:
        logger.info("Live wallet listener stopped by user.")
