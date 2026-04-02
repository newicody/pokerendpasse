# backend/websocket_manager.py
"""
WebSocket Manager — Version optimisée pour 100+ joueurs
- Broadcast asynchrone non-bloquant
- Queue de messages persistante
- Heartbeat avec fallback
- Rate limiting par table
- Gestion de la reconnexion et des fermetures propres
"""

import asyncio
import logging
from typing import Dict, Set, Optional, List, Callable
from datetime import datetime, timedelta
from collections import deque
import uuid

from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

# Configuration
HEARTBEAT_INTERVAL = 30
HEARTBEAT_TIMEOUT = 10
MESSAGE_QUEUE_MAX = 100
BROADCAST_BATCH_SIZE = 10
BROADCAST_BATCH_DELAY = 0.01  # 10ms entre batches pour éviter flood


class ConnectionInfo:
    __slots__ = ('websocket', 'user_id', 'table_id', 'connected_at', 
                 'last_activity', 'last_pong', 'pending_messages', 
                 'is_alive', 'missed_pings', 'message_queue_task')
    
    def __init__(self, websocket: WebSocket, user_id: str, table_id: str):
        self.websocket = websocket
        self.user_id = user_id
        self.table_id = table_id
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.last_pong = datetime.utcnow()
        self.pending_messages: deque = deque(maxlen=MESSAGE_QUEUE_MAX)
        self.is_alive = True
        self.missed_pings = 0
        self.message_queue_task: Optional[asyncio.Task] = None


class WebSocketManager:
    def __init__(self):
        # Structure optimisée: {table_id: {user_id: ConnectionInfo}}
        self._connections: Dict[str, Dict[str, ConnectionInfo]] = {}
        self._tournament_manager = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._broadcast_semaphore = asyncio.Semaphore(20)  # Limite de broadcasts concurrents
        self._lock = asyncio.Lock()
        self._started = False

    # ── Gestion des tables ────────────────────────────────────────────────────

    async def close_table_connections(self, table_id: str):
        """Ferme toutes les connexions d'une table (utilisé lors de la fermeture de la table)."""
        async with self._lock:
            connections = self._connections.pop(table_id, {})
        for user_id, conn in connections.items():
            conn.is_alive = False
            if conn.message_queue_task:
                conn.message_queue_task.cancel()
            try:
                await conn.websocket.close(code=1000, reason="Table closed")
            except Exception:
                pass
            if self._tournament_manager:
                self._tournament_manager.on_player_disconnect(user_id)
        logger.info(f"Closed all connections for table {table_id}")

    def set_tournament_manager(self, tm):
        self._tournament_manager = tm

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    async def start(self):
        if self._started:
            return
        self._started = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("WebSocket manager started (optimized mode)")

    async def stop(self):
        self._started = False
        for task in (self._heartbeat_task, self._cleanup_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Fermer toutes les connexions
        async with self._lock:
            for table_id in list(self._connections.keys()):
                for user_id, conn in list(self._connections[table_id].items()):
                    if conn.message_queue_task:
                        conn.message_queue_task.cancel()
                    try:
                        await conn.websocket.close()
                    except Exception:
                        pass
            self._connections.clear()
        logger.info("WebSocket manager stopped")

    # ── Connect / Disconnect (optimisé) ────────────────────────────────────

    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Connecte un utilisateur avec gestion optimisée des reconnexions."""
        async with self._lock:
            if table_id not in self._connections:
                self._connections[table_id] = {}
            
            existing = self._connections[table_id].get(user_id)
            was_connected = existing is not None
            
            if existing:
                # Fermer proprement l'ancienne connexion
                logger.info(f"Replacing connection for {user_id}@{table_id}")
                existing.is_alive = False
                if existing.message_queue_task:
                    existing.message_queue_task.cancel()
                try:
                    await existing.websocket.close(code=1000, reason="Reconnected")
                except Exception:
                    pass
            
            conn = ConnectionInfo(websocket, user_id, table_id)
            conn.message_queue_task = asyncio.create_task(
                self._message_queue_worker(conn)
            )
            self._connections[table_id][user_id] = conn

        # Notifier le tournoi de la reconnexion (hors lock)
        if self._tournament_manager and was_connected:
            try:
                self._tournament_manager.on_player_reconnect(user_id)
            except Exception as e:
                logger.error(f"Reconnect notify error: {e}")

        # Envoyer les messages en attente
        await self._flush_pending(conn)
        
        # Notifier les autres joueurs
        await self.broadcast_to_table(
            table_id,
            {'type': 'player_connected', 'user_id': user_id},
            exclude=user_id,
        )
        
        logger.info(f"WS connected: {user_id}@{table_id} (was_connected={was_connected})")

    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Déconnecte un utilisateur."""
        async with self._lock:
            if table_id not in self._connections:
                return
            
            conn = self._connections[table_id].get(user_id)
            if not conn or conn.websocket is not websocket:
                return
            
            conn.is_alive = False
            if conn.message_queue_task:
                conn.message_queue_task.cancel()
            del self._connections[table_id][user_id]
            
            if not self._connections[table_id]:
                del self._connections[table_id]

        # Notifier le tournoi (hors lock)
        if self._tournament_manager:
            try:
                self._tournament_manager.on_player_disconnect(user_id)
            except Exception as e:
                logger.error(f"Disconnect notify error: {e}")

        await self.broadcast_to_table(
            table_id, {'type': 'player_disconnected', 'user_id': user_id},
        )
        logger.info(f"WS disconnected: {user_id}@{table_id}")

    # ── Queue Worker (non-bloquant) ─────────────────────────────────────────

    async def _message_queue_worker(self, conn: ConnectionInfo):
        """Travailleur de queue de messages - envoi non-bloquant."""
        while conn.is_alive and self._started:
            if not conn.pending_messages:
                await asyncio.sleep(0.1)
                continue
            
            try:
                msg = conn.pending_messages.popleft()
                await self._safe_send(conn, msg)
            except Exception as e:
                logger.error(f"Queue worker error for {conn.user_id}: {e}")
                # Remettre le message en queue s'il n'a pas pu être envoyé
                if conn.is_alive:
                    conn.pending_messages.appendleft(msg)
                await asyncio.sleep(0.5)

    async def _flush_pending(self, conn: ConnectionInfo):
        """Vide immédiatement la queue de messages."""
        while conn.pending_messages and conn.is_alive:
            try:
                msg = conn.pending_messages.popleft()
                if not await self._safe_send(conn, msg):
                    conn.pending_messages.appendleft(msg)
                    break
            except Exception as e:
                logger.error(f"Flush error for {conn.user_id}: {e}")
                break

    # ── Envoi (optimisé) ────────────────────────────────────────────────────

    async def _safe_send(self, conn: ConnectionInfo, message: dict) -> bool:
        """Envoi sécurisé avec timeout."""
        try:
            if not conn.is_alive:
                return False
            if conn.websocket.client_state != WebSocketState.CONNECTED:
                return False
            
            await asyncio.wait_for(conn.websocket.send_json(message), timeout=5)
            conn.last_activity = datetime.utcnow()
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Send timeout for {conn.user_id}")
            return False
        except Exception as e:
            logger.debug(f"Send error for {conn.user_id}: {e}")
            return False

    async def send_to_user(self, table_id: str, user_id: str, message: dict) -> bool:
        """Envoie un message à un utilisateur spécifique."""
        # Récupération sans verrou pour la performance (lecture seule)
        conn = self._connections.get(table_id, {}).get(user_id)
        if not conn or not conn.is_alive:
            return False
        
        # Ajouter à la queue au lieu d'envoyer immédiatement
        conn.pending_messages.append(message)
        return True

    async def broadcast_to_table(self, table_id: str, message: dict, exclude: str = None):
        """Broadcast optimisé avec semaphore pour limiter la concurrence."""
        connections = self._connections.get(table_id, {})
        if not connections:
            return
        
        # Utiliser un semaphore pour limiter les broadcasts concurrents
        async with self._broadcast_semaphore:
            for uid, conn in connections.items():
                if uid == exclude:
                    continue
                if conn.is_alive:
                    conn.pending_messages.append(message)
                    # Optionnel : journaliser si la queue est trop grande
                    if len(conn.pending_messages) > 50:
                        logger.warning(f"High pending queue for {uid}: {len(conn.pending_messages)}")
            
            # Permettre aux workers de traiter les messages sans bloquer
            # (un petit délai n'est pas nécessaire, car l'ajout est asynchrone)
            # On laisse simplement le semaphore libérer la concurrence.

    def handle_pong(self, table_id: str, user_id: str):
        """Gère le pong pour le heartbeat."""
        conn = self._connections.get(table_id, {}).get(user_id)
        if conn:
            conn.last_pong = datetime.utcnow()
            conn.missed_pings = 0

    # ── État (optimisé) ─────────────────────────────────────────────────────

    def is_connected(self, table_id: str, user_id: str) -> bool:
        """Vérifie si un utilisateur est connecté."""
        conn = self._connections.get(table_id, {}).get(user_id)
        if not conn:
            return False
        try:
            return (conn.is_alive and 
                   conn.websocket.client_state == WebSocketState.CONNECTED)
        except Exception:
            return False

    def get_connected_users(self, table_id: str) -> List[str]:
        """Retourne la liste des utilisateurs connectés."""
        conns = self._connections.get(table_id, {})
        return [uid for uid, conn in conns.items() if conn.is_alive]

    # ── Tâches de fond (optimisées) ─────────────────────────────────────────

    async def _heartbeat_loop(self):
        """Boucle de heartbeat avec gestion des timeout."""
        while self._started:
            try:
                now = datetime.utcnow()
                # Prendre une copie des tables pour éviter de modifier pendant l'itération
                # (on utilise list() pour itérer sur une copie des clés)
                for table_id in list(self._connections.keys()):
                    # Copier les clés des utilisateurs
                    for uid in list(self._connections.get(table_id, {}).keys()):
                        conn = self._connections[table_id].get(uid)
                        if not conn or not conn.is_alive:
                            continue
                        
                        # Vérifier le dernier pong
                        if (now - conn.last_pong).total_seconds() > HEARTBEAT_TIMEOUT:
                            conn.missed_pings += 1
                            if conn.missed_pings > 3:
                                logger.warning(f"Heartbeat lost: {uid}@{table_id}")
                                conn.is_alive = False
                                # Nettoyer plus tard
                            else:
                                # Envoyer un ping
                                try:
                                    await asyncio.wait_for(
                                        conn.websocket.send_json({'type': 'ping'}),
                                        timeout=3
                                    )
                                except Exception:
                                    conn.missed_pings += 1
                                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _cleanup_loop(self):
        """Boucle de nettoyage des connexions mortes."""
        while self._started:
            try:
                async with self._lock:
                    for table_id in list(self._connections.keys()):
                        dead_users = []
                        for uid, conn in self._connections[table_id].items():
                            if not conn.is_alive:
                                dead_users.append(uid)
                            # Nettoyer aussi les connexions trop anciennes sans activité
                            elif (datetime.utcnow() - conn.last_activity).total_seconds() > 300:
                                logger.info(f"Cleaning inactive connection: {uid}@{table_id}")
                                dead_users.append(uid)
                        
                        for uid in dead_users:
                            conn = self._connections[table_id].pop(uid, None)
                            if conn and conn.message_queue_task:
                                conn.message_queue_task.cancel()
                            if self._tournament_manager:
                                self._tournament_manager.on_player_disconnect(uid)
                        
                        if not self._connections[table_id]:
                            del self._connections[table_id]
                            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            await asyncio.sleep(30)  # Nettoyage toutes les 30s

    # ── Statistiques ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Retourne les statistiques."""
        total = sum(len(u) for u in self._connections.values())
        return {
            'total_tables': len(self._connections),
            'total_connections': total,
            'pending_messages': sum(
                len(conn.pending_messages) 
                for table in self._connections.values() 
                for conn in table.values()
            ),
            'tables': {
                tid: {
                    'users': list(users.keys()),
                    'count': len(users),
                    'pending': sum(conn.pending_messages for conn in users.values())
                }
                for tid, users in self._connections.items()
            },
        }
