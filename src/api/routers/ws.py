import asyncio
import logging
import jwt
import os
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger("ws")

class ConnectionManager:
    def __init__(self):
        # Map user_id -> List of WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def broadcast_to_all(self, message: dict):
        for user_id, connections in list(self.active_connections.items()):
            for connection in list(connections):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection, user_id)

    async def broadcast_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            for connection in list(self.active_connections[user_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection, user_id)

manager = ConnectionManager()

@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.close(code=1008)
        return
        
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET", "super-secret"), algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection open
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception:
        manager.disconnect(websocket, user_id)


async def start_db_poll_broadcaster(pool):
    """
    Background task that polls the DB for real-time events and broadcasts them via WebSocket.
    """
    logger.info("Starting WebSocket DB Poller")
    last_polled_time = datetime.now(timezone.utc)
    
    while True:
        try:
            await asyncio.sleep(1.0)
            
            if not manager.active_connections:
                last_polled_time = datetime.now(timezone.utc)
                continue
                
            async with pool.acquire() as conn:
                # 1. Fetch new price ticks
                ticks = await conn.fetch(
                    "SELECT market_id, price FROM price_ticks WHERE timestamp > $1 ORDER BY timestamp ASC",
                    last_polled_time
                )
                
                # 2. Fetch new trades
                trades = await conn.fetch(
                    """
                    SELECT t.trade_id, t.wallet_address, t.market_id, m.title as market_title, t.side, t.price, t.size,
                           ws.tier, ws.strategy, t.timestamp
                    FROM trades t
                    JOIN markets m ON t.market_id = m.market_id
                    LEFT JOIN wallet_stats ws ON t.wallet_address = ws.address
                    WHERE t.timestamp > $1
                    ORDER BY t.timestamp ASC
                    """,
                    last_polled_time
                )
                
                # 3. Fetch new markets
                new_markets = await conn.fetch(
                    """
                    SELECT market_id, title, category, created_at 
                    FROM markets WHERE created_at > $1
                    """, last_polled_time
                )
                
                # Fetch active watchlists to know who to alert
                watchers = []
                if trades:
                    watchers = await conn.fetch(
                        "SELECT user_id, wallet_address FROM user_watchlists WHERE alerts_enabled = true"
                    )
                
                new_poll_time = datetime.now(timezone.utc)
                
                if ticks or trades or new_markets:
                    # Broadcast ticks globally
                    if ticks:
                        latest_ticks = {}
                        for t in ticks:
                            latest_ticks[t["market_id"]] = t["price"]
                            
                        for market_id, price in latest_ticks.items():
                            await manager.broadcast_to_all({
                                "type": "price_tick",
                                "market_id": market_id,
                                "price": float(price)
                            })
                            
                    # Broadcast New Markets globally
                    for m in new_markets:
                        await manager.broadcast_to_all({
                            "type": "new_market",
                            "market_id": m["market_id"],
                            "title": m["title"],
                            "category": m["category"]
                        })
                    
                    # Broadcast trades
                    if trades:
                        # Map wallet_address -> list of user_ids watching it
                        wallet_to_users = {}
                        for w in watchers:
                            addr = w["wallet_address"]
                            uid = str(w["user_id"])
                            if addr not in wallet_to_users:
                                wallet_to_users[addr] = []
                            wallet_to_users[addr].append(uid)

                        for t in trades:
                            trade_msg = {
                                "type": "new_trade",
                                "trade_id": t["trade_id"],
                                "wallet_address": t["wallet_address"],
                                "market_id": t["market_id"],
                                "market_title": t["market_title"],
                                "side": t["side"],
                                "price": float(t["price"]),
                                "size": float(t["size"]),
                                "tier": t["tier"],
                                "strategy": t["strategy"],
                                "timestamp": t["timestamp"].isoformat()
                            }
                            
                            # Global Whale Alert
                            if t["size"] >= 10000 or t["tier"] == "whale" or t["tier"] == "smart_money":
                                whale_msg = trade_msg.copy()
                                whale_msg["type"] = "whale_alert"
                                await manager.broadcast_to_all(whale_msg)
                            
                            # Specific Watchlist Alert
                            watching_users = wallet_to_users.get(t["wallet_address"], [])
                            for uid in watching_users:
                                await manager.broadcast_to_user(uid, trade_msg)
                        
                last_polled_time = new_poll_time

        except Exception as e:
            logger.error(f"Error in DB poller: {e}")
            await asyncio.sleep(5.0)
