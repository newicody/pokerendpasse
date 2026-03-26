# backend/websocket_manager.py
import asyncio
import json
import logging
from typing import Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Gestionnaire des connexions WebSocket"""
    
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        self._broadcast_tasks: Dict[str, asyncio.Task] = {}
    
    async def connect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Ajoute une connexion"""
        if table_id not in self.active_connections:
            self.active_connections[table_id] = {}
        
        self.active_connections[table_id][user_id] = websocket
        
        # Annoncer la connexion
        await self.broadcast_to_table(table_id, {
            "type": "player_joined",
            "user_id": user_id
        })
        
        logger.info(f"User {user_id} connected to table {table_id}")
    
    async def disconnect(self, websocket: WebSocket, table_id: str, user_id: str):
        """Retire une connexion"""
        if table_id in self.active_connections:
            if user_id in self.active_connections[table_id]:
                del self.active_connections[table_id][user_id]
                
                # Annoncer la déconnexion
                await self.broadcast_to_table(table_id, {
                    "type": "player_left",
                    "user_id": user_id
                })
                
            if not self.active_connections[table_id]:
                del self.active_connections[table_id]
        
        logger.info(f"User {user_id} disconnected from table {table_id}")
    
    async def send_to_player(self, table_id: str, user_id: str, message: dict):
        """Envoie un message à un joueur spécifique"""
        if table_id in self.active_connections:
            if user_id in self.active_connections[table_id]:
                try:
                    await self.active_connections[table_id][user_id].send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to player {user_id}: {e}")
    
    async def broadcast_to_table(self, table_id: str, message: dict):
        """Diffuse un message à toute la table"""
        if table_id not in self.active_connections:
            return
        
        # Créer une tâche de broadcast
        async def broadcast():
            for user_id, websocket in self.active_connections[table_id].items():
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {user_id}: {e}")
        
        # Lancer la diffusion
        asyncio.create_task(broadcast())
    
    async def broadcast_game_state(self, table_id: str, game_state: dict):
        """Diffuse l'état du jeu à toute la table"""
        # Envoyer l'état complet à tous les joueurs
        await self.broadcast_to_table(table_id, {
            "type": "game_state",
            "data": game_state
        })
