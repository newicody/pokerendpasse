# backend/websocket_manager.py - Version corrigée avec gestion déconnexion tournoi
import asyncio
import logging
from typing import Dict, Optional
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Gestionnaire des connexions WebSocket.
    Notifie le TournamentManager lors des déconnexions/reconnexions.
    """

    def __init__(self):
        # {table_id: {user_id: WebSocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # Référence optionnelle vers le TournamentManager (injectée après init)
        self._tournament_manager = None

    def set_tournament_manager(self, tm):
        """Injecter le TournamentManager après instanciation pour éviter les imports circulaires."""
        self._tournament_manager = tm

    # ── Connexion ─────────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Enregistre une nouvelle connexion et notifie la reconnexion éventuelle."""
        if table_id not in self.active_connections:
            self.active_connections[table_id] = {}

        was_connected = user_id in self.active_connections[table_id]
        self.active_connections[table_id][user_id] = websocket

        # Notifier le TournamentManager de la reconnexion
        if self._tournament_manager and not was_connected:
            try:
                self._tournament_manager.on_player_reconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Erreur notif reconnexion tournoi: {e}")

        # Envoyer l'état de reconnexion au joueur
        if was_connected:
            try:
                await websocket.send_json({
                    'type':    'reconnected',
                    'user_id': user_id,
                    'message': 'Reconnexion réussie',
                })
            except Exception:
                pass

        # Annoncer aux autres joueurs de la table
        await self.broadcast_to_table(table_id, {
            'type':    'player_connected',
            'user_id': user_id,
        }, exclude=user_id)

        logger.info(f"User {user_id} connecté à la table {table_id}")

    # ── Déconnexion ───────────────────────────────────────────────────────────

    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Retire la connexion et notifie le TournamentManager."""
        if table_id in self.active_connections:
            if user_id in self.active_connections[table_id]:
                del self.active_connections[table_id][user_id]

            if not self.active_connections[table_id]:
                del self.active_connections[table_id]

        # Notifier le TournamentManager → sit-out automatique
        if self._tournament_manager:
            try:
                self._tournament_manager.on_player_disconnect(user_id, table_id)
            except Exception as e:
                logger.error(f"Erreur notif déco tournoi: {e}")

        # Informer les autres joueurs de la table
        await self.broadcast_to_table(table_id, {
            'type':    'player_disconnected',
            'user_id': user_id,
            'message': f'Le joueur {user_id} s\'est déconnecté (sit-out activé)',
        })

        logger.info(f"User {user_id} déconnecté de la table {table_id}")

    # ── Vérification ─────────────────────────────────────────────────────────

    def is_connected(self, table_id: str, user_id: str) -> bool:
        """Vérifie si un joueur est actuellement connecté à une table."""
        conn = self.active_connections.get(table_id, {}).get(user_id)
        if conn is None:
            return False
        try:
            return conn.client_state == WebSocketState.CONNECTED
        except Exception:
            return False

    def get_connected_users(self, table_id: str) -> list:
        """Retourne la liste des user_ids connectés à une table."""
        return list(self.active_connections.get(table_id, {}).keys())

    # ── Envois ────────────────────────────────────────────────────────────────

    async def send_to_player(self, table_id: str, user_id: str, message: dict):
        """Envoie un message à un joueur spécifique."""
        ws = self.active_connections.get(table_id, {}).get(user_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Erreur envoi à {user_id}@{table_id}: {e}")
                await self.disconnect(ws, table_id, user_id)

    async def broadcast_to_table(self, table_id: str, message: dict, exclude: str = None):
        """Diffuse un message à tous les joueurs d'une table (sauf exclude)."""
        connections = self.active_connections.get(table_id, {}).copy()
        failed = []
        for uid, ws in connections.items():
            if uid == exclude:
                continue
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                else:
                    failed.append((ws, uid))
            except Exception as e:
                logger.warning(f"Erreur broadcast à {uid}@{table_id}: {e}")
                failed.append((ws, uid))

        for ws, uid in failed:
            await self.disconnect(ws, table_id, uid)

    async def broadcast_to_all(self, message: dict):
        """Diffuse un message à toutes les tables."""
        for table_id in list(self.active_connections.keys()):
            await self.broadcast_to_table(table_id, message)
