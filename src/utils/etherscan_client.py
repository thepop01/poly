import aiohttp
import asyncio
import json
import logging
from collections import defaultdict

from src.utils.category_classifier import classify_tags

logger = logging.getLogger(__name__)

ETHERSCAN_API_KEY = "N43X2NKRKECA53JPYSXRC2B9H14173ESX9"
CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310f59"
CTF_EXCHANGE_V3 = "0xe3333700ca9d93003f00f0f71f8515005f6c00aa"
ALL_EXCHANGES = [CTF_EXCHANGE_V2, NEG_RISK_CTF_EXCHANGE, CTF_EXCHANGE_V3]
ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
BLOCK_CHUNK_SIZE = 200

_title_cache = {}

async def _fetch_market_meta(session: aiohttp.ClientSession, token_id_decimal: str, condition_id_hex: str = None) -> dict:
    """Fetch market title, category and subcategory.
    
    Uses the CLOB API (which is reliable) instead of the Gamma API
    (which has a buggy condition_id endpoint that returns wrong markets).
    
    Strategy:
    1. If condition_id_hex is provided, query CLOB API /markets/{condition_id}
    2. Otherwise, try Gamma clob_token_ids with validation
    3. Fallback to title-based classification
    
    Returns dict with 'title', 'category', and 'subcategory' keys."""
    cache_key = condition_id_hex or token_id_decimal
    if cache_key in _title_cache:
        return _title_cache[cache_key]

    title = None
    category = None
    subcategory = None
    tags = []

    # Strategy 1: Use CLOB API with condition_id (most reliable)
    if condition_id_hex:
        try:
            url = f"https://clob.polymarket.com/markets/{condition_id_hex}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "question" in data:
                        title = data.get("question")
                        raw_tags = data.get("tags", [])
                        tags = [str(t) for t in raw_tags if t]
        except Exception as e:
            logger.warning(f"CLOB API error for condition {condition_id_hex}: {e}")

    # Strategy 2: Fallback to Gamma clob_token_ids with validation
    if not title:
        try:
            url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id_decimal}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        market = data[0]
                        market_token_ids = json.loads(market.get("clobTokenIds", "[]"))
                        if token_id_decimal in market_token_ids:
                            title = market.get("question")
                            events = market.get("events", [])
                            if events:
                                event_id = events[0].get("id")
                                if event_id:
                                    ev_url = f"https://gamma-api.polymarket.com/events?id={event_id}"
                                    async with session.get(ev_url, timeout=aiohttp.ClientTimeout(total=5)) as ev_resp:
                                        if ev_resp.status == 200:
                                            ev_data = await ev_resp.json()
                                            if ev_data and isinstance(ev_data, list) and len(ev_data) > 0:
                                                event = ev_data[0]
                                                category = event.get("category")
                                                raw_tags = event.get("tags", [])
                                                for t in raw_tags:
                                                    if isinstance(t, dict):
                                                        tags.append(t.get("label", ""))
                                                    else:
                                                        tags.append(str(t))
        except Exception as e:
            logger.warning(f"Gamma API error for token {token_id_decimal}: {e}")

    # Classify tags into category + subcategory
    if tags:
        derived_cat, derived_sub = classify_tags(tags)
        if not category:
            category = derived_cat
        subcategory = derived_sub

    # Fallback: classify from title keywords
    if not category and title:
        category, subcategory = classify_tags([title])

    result = {
        "title": title or f"Token {token_id_decimal[:10]}...",
        "category": category,
        "subcategory": subcategory,
    }
    _title_cache[cache_key] = result
    if len(_title_cache) > 10000:
        _title_cache.clear()
    return result


async def get_latest_block_etherscan(session: aiohttp.ClientSession) -> str:
    url = f"https://api.etherscan.io/v2/api?chainid=137&module=proxy&action=eth_blockNumber&apikey={ETHERSCAN_API_KEY}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("result"):
                    return str(int(data["result"], 16))
    except Exception as e:
        logger.warning(f"Failed to fetch latest block: {e}")
    return "89410000"


async def _fetch_exchange_logs(session: aiohttp.ClientSession, contract: str, from_block: int, to_block: int) -> list[dict]:
    """Fetch OrderFilled logs from a single exchange contract for a block range."""
    url = (
        f"https://api.etherscan.io/v2/api?chainid=137&module=logs&action=getLogs"
        f"&address={contract}"
        f"&fromBlock={from_block}&toBlock={to_block}"
        f"&topic0={ORDER_FILLED_TOPIC}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("status") == "1" and isinstance(data.get("result"), list):
                    return data["result"]
                elif data.get("message") == "No records found":
                    return []
                else:
                    logger.warning(f"Etherscan API warning for {contract}: {data.get('message')}")
    except Exception as e:
        logger.warning(f"Failed to fetch logs from {contract}: {e}")
    return []


async def fetch_recent_trades_etherscan(session: aiohttp.ClientSession, from_block: int | str = "latest", to_block: int | str = "latest") -> list[dict]:
    if from_block == "latest":
        from_block = await get_latest_block_etherscan(session)
    from_block = int(from_block)

    if to_block == "latest":
        to_block = int(await get_latest_block_etherscan(session))
    else:
        to_block = int(to_block)

    all_logs = []
    for contract in ALL_EXCHANGES:
        logs = await _fetch_exchange_logs(session, contract, from_block, to_block)
        all_logs.extend(logs)

    if not all_logs:
        return []

    return await _parse_etherscan_logs(session, all_logs)


async def _parse_etherscan_logs(session: aiohttp.ClientSession, logs: list[dict]) -> list[dict]:
    tx_groups = defaultdict(lambda: {
        "wallets": defaultdict(float),
        "timestamp": 0,
        "blockNumber": 0,
        "title": "",
        "category": None,
        "subcategory": None,
    })

    for log in logs:
        try:
            topics = log.get("topics", [])
            if len(topics) < 4:
                continue
            maker = "0x" + topics[2][-40:]
            taker = "0x" + topics[3][-40:]
            data_hex = log.get("data", "")
            if data_hex.startswith("0x"):
                data_hex = data_hex[2:]
            if len(data_hex) >= 128:
                side_hex = data_hex[0:64]
                tokenId_hex = data_hex[64:128]
                makerAmt_hex = data_hex[128:192]
                takerAmt_hex = data_hex[192:256]

                side = int(side_hex, 16)
                token_id_decimal = str(int(tokenId_hex, 16))
                maker_amt = int(makerAmt_hex, 16)
                taker_amt = int(takerAmt_hex, 16)

                usdc_amount = min(maker_amt, taker_amt) / 1e6

                tx_hash = log.get("transactionHash", "")
                ts = int(log.get("timeStamp", 0) or 0, 16) if isinstance(log.get("timeStamp"), str) and log.get("timeStamp").startswith("0x") else int(log.get("timeStamp", 0) or 0)
                b_num = int(log.get("blockNumber", "0"), 16) if isinstance(log.get("blockNumber"), str) and log.get("blockNumber").startswith("0x") else int(log.get("blockNumber", 0))

                group_key = (tx_hash, token_id_decimal)

                meta = tx_groups[group_key]
                if not meta["title"]:
                    fetched = await _fetch_market_meta(session, token_id_decimal)
                    meta["title"] = fetched["title"]
                    meta["category"] = fetched["category"]
                    meta["subcategory"] = fetched["subcategory"]

                meta["timestamp"] = ts
                meta["blockNumber"] = b_num

                meta["wallets"][maker.lower()] += usdc_amount
                meta["wallets"][taker.lower()] += usdc_amount

                if "side" not in meta:
                    meta["side"] = "BUY" if side == 0 else "SELL"

        except Exception as e:
            logger.warning(f"Error parsing Etherscan log: {e}")

    trades = []
    for (tx_hash, market_id), data in tx_groups.items():
        for wallet, usd_volume in data["wallets"].items():
            trades.append({
                "wallet": wallet,
                "size": usd_volume,
                "transactionHash": tx_hash,
                "timestamp": data["timestamp"],
                "side": data.get("side", "TRADE"),
                "title": data["title"],
                "category": data.get("category"),
                "subcategory": data.get("subcategory"),
                "market_id": market_id,
                "blockNumber": data["blockNumber"]
            })

    return trades
