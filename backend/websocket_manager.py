# backend/websocket_manager.py — Anti-freeze + timeout
import asyncio, logging
from typing import Dict
from fastapi import WebSocket
from fastapi.websockets import WebSocketState
logger = logging.getLogger(__name__)
SEND_TIMEOUT = 5

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        self._tournament_manager = None
    def set_tournament_manager(self, tm): self._tournament_manager = tm

    async def connect(self, websocket, table_id, user_id):
        if table_id not in self.active_connections: self.active_connections[table_id] = {}
        was = user_id in self.active_connections[table_id]
        self.active_connections[table_id][user_id] = websocket
        if self._tournament_manager and not was:
            try: self._tournament_manager.on_player_reconnect(user_id, table_id)
            except Exception as e: logger.error(f"Reconnect notify: {e}")
        if was: await self._safe_send(websocket, {'type':'reconnected','user_id':user_id})
        await self.broadcast_to_table(table_id, {'type':'player_connected','user_id':user_id}, exclude=user_id)
        logger.info(f"WS connect: {user_id} @ {table_id}")

    async def disconnect(self, websocket, table_id, user_id):
        if table_id in self.active_connections:
            self.active_connections[table_id].pop(user_id, None)
            if not self.active_connections[table_id]: del self.active_connections[table_id]
        if self._tournament_manager:
            try: self._tournament_manager.on_player_disconnect(user_id, table_id)
            except Exception as e: logger.error(f"Disconnect notify: {e}")
        await self.broadcast_to_table(table_id, {'type':'player_disconnected','user_id':user_id})
        logger.info(f"WS disconnect: {user_id} @ {table_id}")

    def is_connected(self, table_id, user_id):
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if conn is None: return False
        try: return conn.client_state == WebSocketState.CONNECTED
        except: return False

    def get_connected_users(self, table_id): return list(self.active_connections.get(table_id, {}).keys())

    async def _safe_send(self, ws, message):
        try:
            if ws.client_state != WebSocketState.CONNECTED: return False
            await asyncio.wait_for(ws.send_json(message), timeout=SEND_TIMEOUT); return True
        except asyncio.TimeoutError:
            logger.warning(f"WS send timeout (>{SEND_TIMEOUT}s)"); return False
        except Exception as e:
            logger.warning(f"WS send error: {e}"); return False

    async def send_to_player(self, table_id, user_id, message):
        ws = self.active_connections.get(table_id, {}).get(user_id)
        if ws:
            if not await self._safe_send(ws, message): await self.disconnect(ws, table_id, user_id)

    async def broadcast_to_table(self, table_id, message, exclude=None):
        conns = self.active_connections.get(table_id, {}).copy(); failed = []
        for uid, ws in conns.items():
            if uid == exclude: continue
            if not await self._safe_send(ws, message): failed.append((ws, uid))
        for ws, uid in failed:
            try: await self.disconnect(ws, table_id, uid)
            except: pass

    async def broadcast_to_all(self, message):
        for tid in list(self.active_connections.keys()): await self.broadcast_to_table(tid, message)
