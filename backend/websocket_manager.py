# backend/websocket_manager.py
"""
WebSocket Manager — Version corrigée
====================================
Corrections:
- Race condition sur reconnexion (ferme l'ancien WS avant remplacement)
- Heartbeat serveur pour détecter les connexions mortes
- Meilleure gestion des erreurs d'envoi
- Queue de messages pour éviter les pertes
"""

import asyncio
import logging
from typing import Dict, Set, Optional, List
from datetime import datetime, timedelta
from collections import deque
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5  # Timeout pour l'envoi de messages
HEARTBEAT_INTERVAL = 30  # Intervalle de ping en secondes
HEARTBEAT_TIMEOUT = 10  # Timeout pour la réponse au ping
MAX_PENDING_MESSAGES = 50  # Nombre max de messages en attente par connexion
CONNECTION_CLEANUP_INTERVAL = 60  # Nettoyage des connexions mortes


class ConnectionInfo:
    """Informations sur une connexion WebSocket"""
    
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
    """
    Gestionnaire de connexions WebSocket avec:
    - Gestion thread-safe des connexions
    - Heartbeat automatique
    - Recovery des messages perdus
    """
    
    def __init__(self):
        # {table_id: {user_id: ConnectionInfo}}
        self.active_connections: Dict[str, Dict[str, ConnectionInfo]] = {}
        self._tournament_manager = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._started = False

    def set_tournament_manager(self, tm):
        """Configure le tournament manager pour les notifications"""
        self._tournament_manager = tm

    async def start(self):
        """Démarre les tâches de fond"""
        if self._started:
            return
        
        self._started = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("WebSocket manager started")

    async def stop(self):
        """Arrête les tâches de fond"""
        self._started = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Fermer toutes les connexions
        async with self._lock:
            for table_id in list(self.active_connections.keys()):
                for user_id, conn_info in list(self.active_connections[table_id].items()):
                    try:
                        await conn_info.websocket.close()
                    except:
                        pass
            self.active_connections.clear()
        
        logger.info("WebSocket manager stopped")

    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        """
        Enregistre une nouvelle connexion WebSocket.
        FIX: Ferme proprement l'ancienne connexion si elle existe.
        """
        async with self._lock:
            if table_id not in self.active_connections:
                self.active_connections[table_id] = {}
            
            # Vérifier si une connexion existe déjà pour cet utilisateur
            existing = self.active_connections[table_id].get(user_id)
            was_connected = existing is not None
            
            if existing:
                # FIX CRITIQUE: Fermer l'ancienne connexion proprement
                logger.info(f"Closing existing connection for {user_id}@{table_id}")
                existing.is_alive = False
                try:
                    await existing.websocket.close(code=1000, reason="Reconnected from another session")
                except Exception as e:
                    logger.debug(f"Error closing old connection: {e}")
            
            # Créer la nouvelle connexion
            conn_info = ConnectionInfo(websocket, user_id, table_id)
            self.active_connections[table_id][user_id] = conn_info
        
        # Notifier le tournament manager de la reconnexion
        if self._tournament_manager and was_connected:
            try:
                self._tournament_manager.on_player_reconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Reconnect notify error: {e}")
        
        # Envoyer un message de confirmation
        if was_connected:
            await self._safe_send(conn_info, {
                'type': 'reconnected',
                'user_id': user_id,
                'message': 'Reconnected successfully'
            })
        else:
            await self._safe_send(conn_info, {
                'type': 'connected',
                'user_id': user_id,
            })
        
        # Notifier les autres joueurs
        await self.broadcast_to_table(
            table_id, 
            {'type': 'player_connected', 'user_id': user_id},
            exclude=user_id
        )
        
        logger.info(f"WS connect: {user_id}@{table_id} (reconnect={was_connected})")

    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Déconnecte un WebSocket"""
        conn_info = None
        
        async with self._lock:
            if table_id in self.active_connections:
                conn_info = self.active_connections[table_id].get(user_id)
                
                # Ne supprimer que si c'est le même websocket
                if conn_info and conn_info.websocket is websocket:
                    conn_info.is_alive = False
                    del self.active_connections[table_id][user_id]
                    
                    if not self.active_connections[table_id]:
                        del self.active_connections[table_id]
                else:
                    # C'est une ancienne connexion, ignorer
                    logger.debug(f"Ignoring disconnect for old connection {user_id}@{table_id}")
                    return
        
        # Notifier le tournament manager
        if self._tournament_manager:
            try:
                self._tournament_manager.on_player_disconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Disconnect notify error: {e}")
        
        # Notifier les autres joueurs
        await self.broadcast_to_table(
            table_id,
            {'type': 'player_disconnected', 'user_id': user_id}
        )
        
        logger.info(f"WS disconnect: {user_id}@{table_id}")

    def is_connected(self, table_id: str, user_id: str) -> bool:
        """Vérifie si un utilisateur est connecté"""
        conn_info = self.active_connections.get(table_id, {}).get(user_id)
        if conn_info is None:
            return False
        
        try:
            if not conn_info.is_alive:
                return False
            return conn_info.websocket.client_state == WebSocketState.CONNECTED
        except:
            return False

    def get_connected_users(self, table_id: str) -> List[str]:
        """Retourne la liste des utilisateurs connectés à une table"""
        if table_id not in self.active_connections:
            return []
        
        connected = []
        for user_id, conn_info in self.active_connections[table_id].items():
            if conn_info.is_alive and self.is_connected(table_id, user_id):
                connected.append(user_id)
        
        return connected

    def get_connection_info(self, table_id: str, user_id: str) -> Optional[ConnectionInfo]:
        """Retourne les infos de connexion d'un utilisateur"""
        return self.active_connections.get(table_id, {}).get(user_id)

    async def _safe_send(self, conn_info: ConnectionInfo, message: dict) -> bool:
        """
        Envoi sécurisé avec timeout et gestion d'erreur.
        Retourne True si l'envoi a réussi.
        """
        if not conn_info.is_alive:
            return False
        
        ws = conn_info.websocket
        
        try:
            if ws.client_state != WebSocketState.CONNECTED:
                conn_info.is_alive = False
                return False
            
            await asyncio.wait_for(
                ws.send_json(message),
                timeout=SEND_TIMEOUT
            )
            
            conn_info.last_activity = datetime.utcnow()
            return True
            
        except asyncio.TimeoutError:
            logger.warning(f"WS send timeout for {conn_info.user_id}@{conn_info.table_id}")
            # Ajouter aux messages en attente pour retry
            conn_info.pending_messages.append(message)
            return False
            
        except Exception as e:
            logger.warning(f"WS send error for {conn_info.user_id}: {e}")
            conn_info.is_alive = False
            return False

    async def send_to_player(self, table_id: str, user_id: str, message: dict) -> bool:
        """Envoie un message à un joueur spécifique"""
        conn_info = self.active_connections.get(table_id, {}).get(user_id)
        
        if not conn_info:
            return False
        
        success = await self._safe_send(conn_info, message)
        
        if not success and not conn_info.is_alive:
            # Connexion morte, la nettoyer
            await self.disconnect(conn_info.websocket, table_id, user_id)
        
        return success

    async def broadcast_to_table(self, table_id: str, message: dict, exclude: str = None):
        """Broadcast un message à tous les utilisateurs d'une table"""
        if table_id not in self.active_connections:
            return
        
        # Copier pour éviter les modifications pendant l'itération
        connections = list(self.active_connections.get(table_id, {}).items())
        failed = []
        
        for user_id, conn_info in connections:
            if user_id == exclude:
                continue
            
            success = await self._safe_send(conn_info, message)
            
            if not success and not conn_info.is_alive:
                failed.append((conn_info.websocket, table_id, user_id))
        
        # Nettoyer les connexions mortes
        for ws, tid, uid in failed:
            try:
                await self.disconnect(ws, tid, uid)
            except Exception as e:
                logger.error(f"Error cleaning up connection {uid}: {e}")

    async def broadcast_to_all(self, message: dict):
        """Broadcast un message à tous les utilisateurs de toutes les tables"""
        for table_id in list(self.active_connections.keys()):
            await self.broadcast_to_table(table_id, message)

    async def _heartbeat_loop(self):
        """
        Boucle de heartbeat pour détecter les connexions mortes.
        Envoie des pings périodiques et vérifie les réponses.
        """
        logger.info("Heartbeat loop started")
        
        while self._started:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
                now = datetime.utcnow()
                dead_connections = []
                
                # Parcourir toutes les connexions
                for table_id, users in list(self.active_connections.items()):
                    for user_id, conn_info in list(users.items()):
                        if not conn_info.is_alive:
                            dead_connections.append((conn_info.websocket, table_id, user_id))
                            continue
                        
                        # Vérifier si le dernier pong est trop ancien
                        time_since_pong = (now - conn_info.last_pong).total_seconds()
                        
                        if time_since_pong > HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT:
                            conn_info.missed_pings += 1
                            
                            if conn_info.missed_pings >= 2:
                                logger.warning(f"Connection {user_id}@{table_id} missed {conn_info.missed_pings} pings")
                                conn_info.is_alive = False
                                dead_connections.append((conn_info.websocket, table_id, user_id))
                                continue
                        
                        # Envoyer un ping
                        try:
                            await self._safe_send(conn_info, {
                                'type': 'ping',
                                'timestamp': now.isoformat()
                            })
                        except:
                            pass
                
                # Nettoyer les connexions mortes
                for ws, tid, uid in dead_connections:
                    try:
                        await self.disconnect(ws, tid, uid)
                    except:
                        pass
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(5)
        
        logger.info("Heartbeat loop stopped")

    async def _cleanup_loop(self):
        """
        Boucle de nettoyage périodique des connexions mortes.
        """
        logger.info("Cleanup loop started")
        
        while self._started:
            try:
                await asyncio.sleep(CONNECTION_CLEANUP_INTERVAL)
                
                async with self._lock:
                    # Trouver les tables vides
                    empty_tables = []
                    
                    for table_id, users in self.active_connections.items():
                        # Supprimer les connexions mortes
                        dead_users = [
                            uid for uid, conn in users.items()
                            if not conn.is_alive
                        ]
                        
                        for uid in dead_users:
                            del users[uid]
                        
                        if not users:
                            empty_tables.append(table_id)
                    
                    # Supprimer les tables vides
                    for table_id in empty_tables:
                        del self.active_connections[table_id]
                    
                    if dead_users or empty_tables:
                        logger.info(f"Cleanup: removed {len(dead_users)} dead connections, {len(empty_tables)} empty tables")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(10)
        
        logger.info("Cleanup loop stopped")

    def handle_pong(self, table_id: str, user_id: str):
        """Appelé quand un client répond à un ping"""
        conn_info = self.active_connections.get(table_id, {}).get(user_id)
        if conn_info:
            conn_info.last_pong = datetime.utcnow()
            conn_info.missed_pings = 0
            conn_info.last_activity = datetime.utcnow()

    async def retry_pending_messages(self, table_id: str, user_id: str):
        """
        Réessaie d'envoyer les messages en attente.
        Appelé après une reconnexion.
        """
        conn_info = self.active_connections.get(table_id, {}).get(user_id)
        if not conn_info or not conn_info.pending_messages:
            return
        
        logger.info(f"Retrying {len(conn_info.pending_messages)} pending messages for {user_id}")
        
        while conn_info.pending_messages:
            message = conn_info.pending_messages.popleft()
            success = await self._safe_send(conn_info, message)
            if not success:
                # Remettre le message dans la queue
                conn_info.pending_messages.appendleft(message)
                break

    def get_stats(self) -> dict:
        """Retourne des statistiques sur les connexions"""
        total_connections = 0
        total_tables = len(self.active_connections)
        
        for users in self.active_connections.values():
            total_connections += len(users)
        
        return {
            'total_tables': total_tables,
            'total_connections': total_connections,
            'tables': {
                tid: {
                    'users': list(users.keys()),
                    'count': len(users)
                }
                for tid, users in self.active_connections.items()
            }
        }
