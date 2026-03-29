# backend/websocket_manager.py
"""
WebSocket Manager — Version consolidée
=======================================
- send_to_user() pour envoi per-player (sécurité hole cards)
- Race condition sur reconnexion
- Heartbeat serveur
- Queue de messages pendants
"""

import asyncio
import logging
from typing import Dict, Set, Optional, List
from datetime import datetime, timedelta
from collections import deque
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5
HEARTBEAT_INTERVAL = 30
HEARTBEAT_TIMEOUT = 10
MAX_PENDING_MESSAGES = 50
CONNECTION_CLEANUP_INTERVAL = 60


class ConnectionInfo:
    def __init__(self, websocket: WebSocket, user_id: str, table_id: str):
        self.websocket = websocket
        self.user_id = user_id
        self.table_id = table_id
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.last_pong = datetime.utcnow()
        self.pending_messages: deque = deque(maxlen=MAX_PENDING_MESSAGES)
        self.is_alive = True
        self.missed_pings = 0


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, ConnectionInfo]] = {}
        self._tournament_manager = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._started = False

    def set_tournament_manager(self, tm):
        self._tournament_manager = tm

    async def start(self):
        if self._started:
            return
        self._started = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("WebSocket manager started")

    async def stop(self):
        self._started = False
        for task in (self._heartbeat_task, self._cleanup_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        async with self._lock:
            for table_id in list(self.active_connections.keys()):
                for uid, conn in list(self.active_connections[table_id].items()):
                    try:
                        await conn.websocket.close()
                    except Exception:
                        pass
            self.active_connections.clear()
        logger.info("WebSocket manager stopped")

    # ── Connect / Disconnect ──────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        async with self._lock:
            if table_id not in self.active_connections:
                self.active_connections[table_id] = {}
            existing = self.active_connections[table_id].get(user_id)
            was_connected = existing is not None
            if existing:
                logger.info(f"Closing old connection for {user_id}@{table_id}")
                existing.is_alive = False
                try:
                    await existing.websocket.close(code=1000, reason="Reconnected")
                except Exception:
                    pass
            conn_info = ConnectionInfo(websocket, user_id, table_id)
            self.active_connections[table_id][user_id] = conn_info

        if self._tournament_manager and was_connected:
            try:
                self._tournament_manager.on_player_reconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Reconnect notify: {e}")

        msg_type = 'reconnected' if was_connected else 'connected'
        await self._safe_send(conn_info, {
            'type': msg_type, 'user_id': user_id,
        })

        await self.broadcast_to_table(
            table_id,
            {'type': 'player_connected', 'user_id': user_id},
            exclude=user_id,
        )
        logger.info(f"WS {msg_type}: {user_id}@{table_id}")

    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        async with self._lock:
            if table_id in self.active_connections:
                conn = self.active_connections[table_id].get(user_id)
                if conn and conn.websocket is websocket:
                    conn.is_alive = False
                    del self.active_connections[table_id][user_id]
                    if not self.active_connections[table_id]:
                        del self.active_connections[table_id]
                else:
                    return

        if self._tournament_manager:
            try:
                self._tournament_manager.on_player_disconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Disconnect notify: {e}")

        await self.broadcast_to_table(
            table_id, {'type': 'player_disconnected', 'user_id': user_id},
        )
        logger.info(f"WS disconnect: {user_id}@{table_id}")

    # ── Envoi ─────────────────────────────────────────────────────────────────

    async def _safe_send(self, conn_info: ConnectionInfo, message: dict) -> bool:
        try:
            if conn_info.websocket.client_state != WebSocketState.CONNECTED:
                return False
            await asyncio.wait_for(conn_info.websocket.send_json(message), timeout=SEND_TIMEOUT)
            conn_info.last_activity = datetime.utcnow()
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Send timeout for {conn_info.user_id}")
            conn_info.pending_messages.append(message)
            return False
        except Exception:
            conn_info.pending_messages.append(message)
            return False

    async def send_to_user(self, table_id: str, user_id: str, message: dict) -> bool:
        """Envoie un message à un utilisateur spécifique (per-player send)"""
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if conn:
            return await self._safe_send(conn, message)
        return False

    async def broadcast_to_table(self, table_id: str, message: dict, exclude: str = None):
        connections = self.active_connections.get(table_id, {})
        for uid, conn in list(connections.items()):
            if uid == exclude:
                continue
            await self._safe_send(conn, message)

    def handle_pong(self, table_id: str, user_id: str):
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if conn:
            conn.last_pong = datetime.utcnow()
            conn.missed_pings = 0

    # ── État ──────────────────────────────────────────────────────────────────

    def is_connected(self, table_id: str, user_id: str) -> bool:
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if not conn:
            return False
        try:
            return conn.is_alive and conn.websocket.client_state == WebSocketState.CONNECTED
        except Exception:
            return False

    def get_connected_users(self, table_id: str) -> List[str]:
        return [uid for uid, conn in self.active_connections.get(table_id, {}).items()
                if conn.is_alive and self.is_connected(table_id, uid)]

    def get_connection_info(self, table_id: str, user_id: str) -> Optional[ConnectionInfo]:
        return self.active_connections.get(table_id, {}).get(user_id)

    # ── Tâches de fond ────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        while self._started:
            try:
                for table_id in list(self.active_connections.keys()):
                    for uid, conn in list(self.active_connections.get(table_id, {}).items()):
                        if not conn.is_alive:
                            continue
                        try:
                            await asyncio.wait_for(
                                conn.websocket.send_json({'type': 'ping'}),
                                timeout=SEND_TIMEOUT,
                            )
                            conn.missed_pings += 1
                            if conn.missed_pings > 3:
                                logger.warning(f"Heartbeat lost: {uid}@{table_id}")
                                conn.is_alive = False
                        except Exception:
                            conn.is_alive = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _cleanup_loop(self):
        while self._started:
            try:
                async with self._lock:
                    for table_id in list(self.active_connections.keys()):
                        for uid, conn in list(self.active_connections[table_id].items()):
                            if not conn.is_alive:
                                del self.active_connections[table_id][uid]
                        if not self.active_connections[table_id]:
                            del self.active_connections[table_id]
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(CONNECTION_CLEANUP_INTERVAL)

    async def retry_pending(self, table_id: str, user_id: str):
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if not conn or not conn.pending_messages:
            return
        while conn.pending_messages:
            msg = conn.pending_messages.popleft()
            if not await self._safe_send(conn, msg):
                conn.pending_messages.appendleft(msg)
                break

    def get_stats(self) -> dict:
        total = sum(len(u) for u in self.active_connections.values())
        return {
            'total_tables': len(self.active_connections),
            'total_connections': total,
            'tables': {
                tid: {'users': list(users.keys()), 'count': len(users)}
                for tid, users in self.active_connections.items()
            },
        }
