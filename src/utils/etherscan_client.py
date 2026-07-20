import aiohttp
import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from itertools import cycle

from src.utils.category_classifier import classify_tags

logger = logging.getLogger(__name__)

def _load_polygonscan_keys() -> list[str]:
    """Load Polygonscan API keys from environment with rotation support."""
    keys = []
    i = 1
    while True:
        key = os.environ.get(f"POLYGONSCAN_API_KEY_{i}")
        if not key or key.startswith("your_"):
            break
        keys.append(key)
        i += 1
    if not keys:
        single = os.environ.get("POLYGONSCAN_API_KEY")
        if single and not single.startswith("your_"):
            keys.append(single)
    if not keys:
        keys.append("N43X2NKRKECA53JPYSXRC2B9H14173ESX9")
    return keys

_polygonscan_keys: list[str] = []
_polygonscan_key_cycle = None

def _get_next_polygonscan_key() -> str:
    global _polygonscan_keys, _polygonscan_key_cycle
    if not _polygonscan_keys:
        _polygonscan_keys = _load_polygonscan_keys()
        _polygonscan_key_cycle = cycle(_polygonscan_keys)
        logger.info(f"Loaded {len(_polygonscan_keys)} Polygonscan API key(s) for rotation")
    return next(_polygonscan_key_cycle)
CTF_EXCHANGE_V1 = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310f59"
CTF_EXCHANGE_V3 = "0xe3333700ca9d93003f00f0f71f8515005f6c00aa"
ALL_EXCHANGES = [CTF_EXCHANGE_V1, CTF_EXCHANGE_V2, NEG_RISK_CTF_EXCHANGE, CTF_EXCHANGE_V3]
ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
BLOCK_CHUNK_SIZE = 200

_title_cache = {}

async def _fetch_market_meta(session: aiohttp.ClientSession, token_id_decimal: str, condition_id_hex: str = None) -> dict:
    """Fetch market title, category, subcategory and condition_id.

    Uses the CLOB API (which is reliable) instead of the Gamma API
    (which has a buggy condition_id endpoint that returns wrong markets).

    Strategy:
    1. If condition_id_hex is provided, query CLOB API /markets/{condition_id}
    2. Otherwise, try Gamma clob_token_ids with validation
    3. Fallback to title-based classification

    Returns dict with 'title', 'category', 'subcategory', and 'condition_id' keys."""
    cache_key = condition_id_hex or token_id_decimal
    if cache_key in _title_cache:
        return _title_cache[cache_key]

    title = None
    category = None
    subcategory = None
    condition_id = condition_id_hex
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
                        condition_id = data.get("condition_id") or condition_id
        except Exception as e:
            logger.warning(f"CLOB API error for condition {condition_id_hex}: {e}")

    # Strategy 2: Fallback to Gamma clob_token_ids with validation
    if not title:
        try:
            # Gamma's clob_token_ids filter excludes closed/resolved markets by default,
            # which silently drops most of a whale's older, already-resolved trades.
            # Retry with closed=true if the open-markets query comes back empty.
            data = None
            for query_suffix in ("", "&closed=true"):
                url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id_decimal}{query_suffix}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        candidate = await resp.json()
                        if candidate and isinstance(candidate, list) and len(candidate) > 0:
                            data = candidate
                            break

            if data:
                market = data[0]
                market_token_ids = json.loads(market.get("clobTokenIds", "[]"))
                if token_id_decimal in market_token_ids:
                    title = market.get("question")
                    condition_id = market.get("conditionId") or condition_id
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
        "condition_id": condition_id,
    }
    _title_cache[cache_key] = result
    if len(_title_cache) > 10000:
        _title_cache.clear()
    return result


async def get_latest_block_etherscan(session: aiohttp.ClientSession) -> str:
    url = f"https://api.etherscan.io/v2/api?chainid=137&module=proxy&action=eth_blockNumber&apikey={_get_next_polygonscan_key()}"
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
        f"&apikey={_get_next_polygonscan_key()}"
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
        "wallet_tokens": defaultdict(float),
        "timestamp": 0,
        "blockNumber": 0,
        "title": "",
        "category": None,
        "subcategory": None,
        "condition_id": None,
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

                # One leg is USDC (6 decimals), the other is outcome tokens (6 decimals).
                # Price is always <= 1, so the smaller amount is the USDC leg.
                usdc_amount = min(maker_amt, taker_amt) / 1e6
                token_qty = max(maker_amt, taker_amt) / 1e6

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
                    meta["condition_id"] = fetched["condition_id"]

                meta["timestamp"] = ts
                meta["blockNumber"] = b_num

                meta["wallets"][maker.lower()] += usdc_amount
                meta["wallets"][taker.lower()] += usdc_amount
                meta["wallet_tokens"][maker.lower()] += token_qty
                meta["wallet_tokens"][taker.lower()] += token_qty

                if "side" not in meta:
                    meta["side"] = "BUY" if side == 0 else "SELL"

        except Exception as e:
            logger.warning(f"Error parsing Etherscan log: {e}")

    trades = []
    for (tx_hash, market_id), data in tx_groups.items():
        for wallet, usd_volume in data["wallets"].items():
            token_qty = data["wallet_tokens"].get(wallet, 0.0)
            price = (usd_volume / token_qty) if token_qty > 0 else 0.0
            trades.append({
                "wallet": wallet,
                "size": token_qty,
                "token_size": token_qty,
                "price": price,
                "usd_volume": usd_volume,
                "asset": market_id,
                "conditionId": data.get("condition_id"),
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


async def fetch_historical_trades_polygonscan(session: aiohttp.ClientSession, addresses: list[str], start_block: int = 0) -> list[dict]:
    """
    Fetch all OrderFilled logs for the given wallet(s) directly from the CTF Exchanges.
    Bypasses the 3000-record limit of the Polymarket REST API's /trades endpoint.

    start_block: only scan logs at or after this block. Pass a wallet's
    last_synced_block+1 for incremental syncs; defaults to 0 (full history).
    """
    all_logs = []

    for address in set(addr for addr in addresses if addr):
        address = address.lower()
        wallet_padded = "0x000000000000000000000000" + address[2:]

        for contract in ALL_EXCHANGES:
            # We must fetch where user is maker (topic2) AND where user is taker (topic3).
            # Etherscan requires the operator matching the exact topic pair being combined
            # with topic0: topic0_2_opr for topic0<->topic2, topic0_3_opr for topic0<->topic3.
            for role_topic in ["topic2", "topic3"]:
                topic_opr = "topic0_2_opr" if role_topic == "topic2" else "topic0_3_opr"
                from_block = start_block
                to_block = 999999999

                while True:
                    url = (
                        f"https://api.etherscan.io/v2/api?chainid=137"
                        f"&module=logs&action=getLogs"
                        f"&fromBlock={from_block}&toBlock={to_block}"
                        f"&address={contract}"
                        f"&topic0={ORDER_FILLED_TOPIC}"
                        f"&{topic_opr}=and"
                        f"&{role_topic}={wallet_padded}"
                        f"&apikey={_get_next_polygonscan_key()}"
                        f"&page=1&offset=1000"
                    )

                    try:
                        async with session.get(url, timeout=60.0) as r:
                            data = await r.json()

                            if data.get("status") == "0" and data.get("message") == "NOTOK":
                                logger.warning(f"Polygonscan rate limit hit. Retrying in 2s...")
                                await asyncio.sleep(2.0)
                                continue

                            logs = data.get("result", [])
                            if isinstance(logs, list) and logs:
                                all_logs.extend(logs)

                                if len(logs) == 1000:
                                    last_block = int(logs[-1]["blockNumber"], 16) if isinstance(logs[-1]["blockNumber"], str) and logs[-1]["blockNumber"].startswith("0x") else int(logs[-1]["blockNumber"])
                                    from_block = last_block + 1
                                    await asyncio.sleep(0.3)
                                else:
                                    break
                            else:
                                break

                            await asyncio.sleep(0.3)

                    except Exception as e:
                        logger.warning(f"Timeout/Network error on Polygonscan: {e}. Retrying in 2s...")
                        await asyncio.sleep(2.0)

    if not all_logs:
        return []

    # Deduplicate logs by tx hash and log index
    unique_logs = {}
    for log in all_logs:
        tx_hash = log.get("transactionHash", "")
        log_idx = log.get("logIndex", "0")
        if isinstance(log_idx, str) and log_idx.startswith("0x"):
            log_idx = int(log_idx, 16)
        else:
            log_idx = int(log_idx)
        unique_logs[f"{tx_hash}_{log_idx}"] = log

    return await _parse_etherscan_logs(session, list(unique_logs.values()))


CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_PAYOUT_REDEMPTION_TOPIC = "0x6b1076f62b7042533ba1e808fcb2f768b7ca67c52a0a2df3bb406df7ea66b262"

# Neg Risk markets (elections, multi-candidate/multi-outcome markets) redeem through a
# separate contract with its own PayoutRedemption event — a plain CTF-contract scan alone
# silently misses every win on this class of market.
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
NEG_RISK_PAYOUT_REDEMPTION_TOPIC = "0xba33ac50d8894676597e6e35dc09cff59854708b642cd069d21eb9c7ca072a04"

# (contract, topic0, redeemer topic index) — redeemer is topic1 on both contracts.
REDEMPTION_SOURCES = [
    (CTF_CONTRACT, CTF_PAYOUT_REDEMPTION_TOPIC),
    (NEG_RISK_ADAPTER, NEG_RISK_PAYOUT_REDEMPTION_TOPIC),
]


def _parse_redemption_log(log: dict, topic0: str) -> dict | None:
    """Parse a single PayoutRedemption log into {condition_id, payout, timestamp, transactionHash}.

    The base CTF contract and the Neg Risk Adapter emit differently-shaped
    PayoutRedemption events:
      - CTF contract: conditionId/indexSets-pointer/payout packed as 3 x 32-byte chunks in `data`.
      - Neg Risk Adapter: conditionId is topics[2] (indexed), `data` is just the payout uint256.
    """
    try:
        ts = int(log.get("timeStamp", 0) or 0, 16) if isinstance(log.get("timeStamp"), str) and log.get("timeStamp").startswith("0x") else int(log.get("timeStamp", 0) or 0)
        tx_hash = log.get("transactionHash", "")

        if topic0 == NEG_RISK_PAYOUT_REDEMPTION_TOPIC:
            topics = log.get("topics", [])
            if len(topics) < 3:
                return None
            condition_id = "0x" + topics[2][-64:]
            data_hex = log.get("data", "")
            if data_hex.startswith("0x"):
                data_hex = data_hex[2:]
            if not data_hex:
                return None
            payout_usdc = int(data_hex, 16) / 1e6
        else:
            data_hex = log.get("data", "")
            if data_hex.startswith("0x"):
                data_hex = data_hex[2:]
            if len(data_hex) < 192:
                return None
            # PayoutRedemption data layout:
            # chunk 0: conditionId (bytes32)
            # chunk 1: pointer to indexSets (uint256)
            # chunk 2: payout (uint256)
            condition_id = "0x" + data_hex[0:64]
            payout_hex = data_hex[128:192]
            payout_usdc = int(payout_hex, 16) / 1e6

        return {
            "condition_id": condition_id,
            "payout": payout_usdc,
            "timestamp": ts,
            "transactionHash": tx_hash,
        }
    except Exception as e:
        logger.warning(f"Error parsing redemption log: {e}")
        return None


async def fetch_historical_redemptions_polygonscan(session: aiohttp.ClientSession, addresses: list[str]) -> list[dict]:
    """
    Fetch all PayoutRedemption logs for the given wallet(s) from both the base CTF contract
    and the Neg Risk Adapter (elections/multi-outcome markets redeem through the latter).
    Bypasses the 5000-record limit of the Polymarket REST API's /closed-positions endpoint.
    Returns a list of dicts with `condition_id`, `payout`, `timestamp`, `tx_hash`.
    """
    all_redemptions = []

    for address in set(addr for addr in addresses if addr):
        address = address.lower()
        wallet_padded = "0x000000000000000000000000" + address[2:]

        for contract, topic0 in REDEMPTION_SOURCES:
            from_block = 0
            to_block = 999999999
            retries = 0
            max_retries = 5

            while True:
                url = (
                    f"https://api.etherscan.io/v2/api?chainid=137"
                    f"&module=logs&action=getLogs"
                    f"&fromBlock={from_block}&toBlock={to_block}"
                    f"&address={contract}"
                    f"&topic0={topic0}"
                    f"&topic0_1_opr=and"
                    f"&topic1={wallet_padded}"
                    f"&apikey={_get_next_polygonscan_key()}"
                    f"&page=1&offset=1000"
                )
                try:
                    async with session.get(url, timeout=60.0) as r:
                        data = await r.json()

                        if data.get("status") == "0" and data.get("message") == "NOTOK":
                            logger.warning(f"Polygonscan rate limit hit for redemptions {address}. Retrying in 2s...")
                            await asyncio.sleep(2.0)
                            continue

                        logs = data.get("result", [])
                        if isinstance(logs, list) and logs:
                            for log in logs:
                                parsed = _parse_redemption_log(log, topic0)
                                if parsed:
                                    all_redemptions.append(parsed)

                            if len(logs) == 1000:
                                last_block = int(logs[-1]["blockNumber"], 16) if isinstance(logs[-1]["blockNumber"], str) and logs[-1]["blockNumber"].startswith("0x") else int(logs[-1]["blockNumber"])
                                from_block = last_block + 1
                                await asyncio.sleep(0.3)
                            else:
                                break
                        else:
                            break

                        await asyncio.sleep(0.3)

                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    if retries >= max_retries:
                        logger.error(f"Max retries reached for {address}")
                        break
                    retries += 1
                    logger.warning(f"Timeout/Network error on redemptions for {address}: {e}. Retrying in 2s...")
                    await asyncio.sleep(2.0)
                except Exception as e:
                    if retries >= max_retries:
                        logger.error(f"Max retries reached for {address}")
                        break
                    retries += 1
                    logger.warning(f"Unexpected error on redemptions for {address}: {e}. Retrying in 2s...")
                    await asyncio.sleep(2.0)

    all_redemptions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return all_redemptions


def build_synthetic_closed_positions(trades: list[dict], redemptions: list[dict]) -> list[dict]:
    """
    Combines raw trades and on-chain PayoutRedemption logs to build a mathematically perfect
    list of closed positions, bypassing the REST API entirely.
    """
    # 1. Group trades by conditionId
    positions_map = {}

    for t in trades:
        cid = t.get("conditionId")
        if not cid:
            # Fallback if the trade only has asset/market_id instead of conditionId
            cid = t.get("asset") or t.get("market_id")

        if not cid:
            continue

        if cid not in positions_map:
            positions_map[cid] = {
                "conditionId": cid,
                "title": t.get("title") or "",
                "totalBought": 0.0,
                "totalSold": 0.0,
                "totalBuyTokens": 0.0,
                "totalSellTokens": 0.0,
                "trades": [],
                "redeemed": False,
                "payout": 0.0,
                "endDate": None
            }

        side = (t.get("side") or "").upper()
        size_tokens = float(t.get("size") or 0.0)
        price = float(t.get("price") or 0.0)
        usdc_vol = size_tokens * price

        if side == "BUY":
            positions_map[cid]["totalBought"] += usdc_vol
            positions_map[cid]["totalBuyTokens"] += size_tokens
        elif side == "SELL":
            positions_map[cid]["totalSold"] += usdc_vol
            positions_map[cid]["totalSellTokens"] += size_tokens

        if not positions_map[cid]["title"] and t.get("title"):
            positions_map[cid]["title"] = t.get("title")

    # 2. Apply redemptions
    for r in redemptions:
        cid = r.get("condition_id")
        if not cid:
            continue
        payout = float(r.get("payout") or 0.0)
        if cid in positions_map:
            positions_map[cid]["redeemed"] = True
            positions_map[cid]["payout"] += payout
            # Set endDate to the timestamp of the redemption
            if not positions_map[cid]["endDate"]:
                ts = r.get("timestamp")
                if ts:
                    positions_map[cid]["endDate"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        else:
            # They redeemed a market we don't have trades for?
            # Could be airdrop, or trade before indexer start. We can create a synthetic position.
            ts = r.get("timestamp")
            end_date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
            positions_map[cid] = {
                "conditionId": cid,
                "title": f"Market {cid[:8]}",
                "totalBought": 0.0,  # We don't know
                "totalSold": 0.0,
                "totalBuyTokens": 0.0,
                "totalSellTokens": 0.0,
                "redeemed": True,
                "payout": payout,
                "endDate": end_date
            }

    # 3. Format as closed_positions expected by compute_stats
    synthetic_closed = []
    for cid, pos in positions_map.items():
        # A position is closed if it has been redeemed, OR if it's completely sold out.
        # If they sell everything before resolution, they don't get a PayoutRedemption,
        # but the REST API's closed_positions still includes markets they fully sold out of.
        is_fully_sold = (pos["totalSold"] > 0) and (pos["totalBuyTokens"] > 0)

        if pos["redeemed"] or is_fully_sold:
            realized_pnl = pos["payout"] + pos["totalSold"] - pos["totalBought"]
            avg_price = pos["totalBought"] / pos["totalBuyTokens"] if pos["totalBuyTokens"] > 0 else 0.0
            avg_sell_price = pos["totalSold"] / pos["totalSellTokens"] if pos["totalSellTokens"] > 0 else 0.0

            synthetic_closed.append({
                "conditionId": cid,
                "title": pos["title"],
                "realizedPnl": realized_pnl,
                "totalBought": pos["totalBought"],
                "avgPrice": avg_price,
                "avgSellPrice": avg_sell_price,
                "endDate": pos["endDate"]
            })

    return synthetic_closed
