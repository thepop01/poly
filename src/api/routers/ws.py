import asyncio
import logging
import json
import jwt
import os
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict

from src.api.routers.auth import JWT_SECRET

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger("ws")
ALLOWED_ORIGINS = {o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()}

class ConnectionManager:
    def __init__(self):
        # Map user_id -> List of WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected for user {user_id}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")

    async def broadcast_to_all(self, message: dict):
        # Safely serialize message to handle datetime/Decimal types
        text_payload = json.dumps(message, default=str)
        for user_id, connections in list(self.active_connections.items()):
            for connection in list(connections):
                try:
                    await connection.send_text(text_payload)
                except Exception:
                    self.disconnect(connection, user_id)

    async def send_personal_message(self, message: dict, user_id: str):
        text_payload = json.dumps(message, default=str)
        if user_id in self.active_connections:
            for connection in list(self.active_connections[user_id]):
                try:
                    await connection.send_text(text_payload)
                except Exception:
                    self.disconnect(connection, user_id)

manager = ConnectionManager()

@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    origin = websocket.headers.get("origin", "")
    if origin and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    if not token:
        await websocket.close(code=1008)
        return
        
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
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
    Background task that polls DB for real-time wallet_activity_v2 events and broadcasts via WebSocket.
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
                activity = await conn.fetch(
                    """
                    SELECT id, address, event_type, amount_usdc, title, event_at as timestamp
                    FROM wallet_activity_v2
                    WHERE event_at > $1
                    ORDER BY event_at ASC
                    """,
                    last_polled_time
                )
                
                new_poll_time = datetime.now(timezone.utc)
                
                if activity:
                    events = []
                    for r in activity:
                        ts = r["timestamp"]
                        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                        events.append({
                            "id": r["id"],
                            "address": r["address"],
                            "event_type": r["event_type"],
                            "amount_usdc": float(r["amount_usdc"]) if r["amount_usdc"] is not None else 0.0,
                            "title": r["title"] or "",
                            "timestamp": ts_str,
                        })
                    await manager.broadcast_to_all({"type": "ACTIVITY_UPDATE", "data": events})
                    
                last_polled_time = new_poll_time

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in DB poller: {e}")
            await asyncio.sleep(2.0)
