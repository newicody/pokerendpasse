# backend/websocket_manager.py — Version anti-freeze
import asyncio
import logging
from typing import Dict, Optional
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5  # secondes max par envoi WS


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        self._tournament_manager = None

    def set_tournament_manager(self, tm):
        self._tournament_manager = tm

    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        if table_id not in self.active_connections:
            self.active_connections[table_id] = {}
        was = user_id in self.active_connections[table_id]
        self.active_connections[table_id][user_id] = websocket

        if self._tournament_manager and not was:
            try:
                self._tournament_manager.on_player_reconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Reconnect notify error: {e}")

        if was:
            await self._safe_send(websocket, {'type': 'reconnected', 'user_id': user_id})

        await self.broadcast_to_table(table_id, {'type': 'player_connected', 'user_id': user_id}, exclude=user_id)
        logger.info(f"WS connect: {user_id} @ {table_id}")

    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        if table_id in self.active_connections:
            self.active_connections[table_id].pop(user_id, None)
            if not self.active_connections[table_id]:
                del self.active_connections[table_id]

        if self._tournament_manager:
            try:
                self._tournament_manager.on_player_disconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Disconnect notify error: {e}")

        await self.broadcast_to_table(table_id, {
            'type': 'player_disconnected', 'user_id': user_id
        })
        logger.info(f"WS disconnect: {user_id} @ {table_id}")

    def is_connected(self, table_id: str, user_id: str) -> bool:
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if conn is None:
            return False
        try:
            return conn.client_state == WebSocketState.CONNECTED
        except Exception:
            return False

    def get_connected_users(self, table_id: str) -> list:
        return list(self.active_connections.get(table_id, {}).keys())

    async def _safe_send(self, ws: WebSocket, message: dict) -> bool:
        """Envoie avec timeout — ne bloque JAMAIS plus de SEND_TIMEOUT secondes."""
        try:
            if ws.client_state != WebSocketState.CONNECTED:
                return False
            await asyncio.wait_for(ws.send_json(message), timeout=SEND_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"WS send timeout (>{SEND_TIMEOUT}s) — dropping connection")
            return False
        except Exception as e:
            logger.warning(f"WS send error: {e}")
            return False

    async def send_to_player(self, table_id: str, user_id: str, message: dict):
        ws = self.active_connections.get(table_id, {}).get(user_id)
        if ws:
            ok = await self._safe_send(ws, message)
            if not ok:
                await self.disconnect(ws, table_id, user_id)

    async def broadcast_to_table(self, table_id: str, message: dict, exclude: str = None):
        """Diffuse avec timeout — les WS qui ne répondent pas sont déconnectées."""
        connections = self.active_connections.get(table_id, {}).copy()
        failed = []
        for uid, ws in connections.items():
            if uid == exclude:
                continue
            ok = await self._safe_send(ws, message)
            if not ok:
                failed.append((ws, uid))

        for ws, uid in failed:
            try:
                await self.disconnect(ws, table_id, uid)
            except Exception:
                pass

    async def broadcast_to_all(self, message: dict):
        for table_id in list(self.active_connections.keys()):
            await self.broadcast_to_table(table_id, message)
