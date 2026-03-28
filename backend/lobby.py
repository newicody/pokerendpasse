# backend/lobby.py
"""
Lobby — Gestion des tables et utilisateurs
==========================================
Version corrigée avec:
- Meilleure gestion des erreurs
- Intégration WebSocket
- Support tournois freeroll
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional
from datetime import datetime

from .models import (
    Table, User, TableStatus, GameType, LobbyInfo, CreateTableRequest
)
from .game_engine import PokerTable
from .storage import XMLStorage
from .tournament import TournamentManager

logger = logging.getLogger(__name__)


class Lobby:
    """
    Gestionnaire principal du lobby.
    Gère les tables, utilisateurs et l'interface avec le TournamentManager.
    """
    
    def __init__(self):
        self.tables: Dict[str, PokerTable] = {}
        self.users: Dict[str, User] = {}
        self.user_to_table: Dict[str, str] = {}
        self._ws_manager = None
        self.storage = XMLStorage()
        self.tournament_manager = TournamentManager(data_dir="data", lobby=self)
        self._started = False
        
        self._load_data()

    def _load_data(self):
        """Charge les utilisateurs depuis le stockage"""
        try:
            for user_id in self.storage.list_users():
                ud = self.storage.load_user(user_id)
                if ud:
                    try:
                        self.users[user_id] = User(**ud)
                    except Exception as e:
                        logger.error(f"Load user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error loading users: {e}")

    async def start(self):
        """Démarre le lobby et les services associés"""
        if self._started:
            return
        
        self._started = True
        
        # Démarrer le monitor des tournois
        self.tournament_manager.start_monitor()
        
        # Démarrer le WebSocket manager si disponible
        if self._ws_manager and hasattr(self._ws_manager, 'start'):
            await self._ws_manager.start()
        
        logger.info("Lobby started")

    async def stop(self):
        """Arrête le lobby proprement"""
        self._started = False
        
        # Arrêter le monitor des tournois
        await self.tournament_manager.stop_monitor()
        
        # Fermer toutes les tables
        for table_id in list(self.tables.keys()):
            try:
                await self.close_table(table_id)
            except Exception as e:
                logger.error(f"Error closing table {table_id}: {e}")
        
        # Arrêter le WebSocket manager
        if self._ws_manager and hasattr(self._ws_manager, 'stop'):
            await self._ws_manager.stop()
        
        logger.info("Lobby stopped")

    # ── Tables ────────────────────────────────────────────────────────────────

    async def create_table(self, request: CreateTableRequest) -> Table:
        """Crée une nouvelle table"""
        table_id = f"table_{uuid.uuid4().hex[:8]}"
        
        game_type = getattr(request, 'game_type', None) or GameType.TOURNAMENT
        tournament_id = getattr(request, 'tournament_id', None)
        
        # Récupérer les blinds du tournoi si applicable
        small_blind = 10
        big_blind = 20
        
        if tournament_id:
            tournament = self.tournament_manager.get_tournament(tournament_id)
            if tournament:
                blinds = tournament.get_current_blinds()
                small_blind = blinds.get('small_blind', 10)
                big_blind = blinds.get('big_blind', 20)
        
        table = PokerTable(
            table_id=table_id,
            name=request.name,
            game_type=game_type,
            max_players=request.max_players,
            min_buy_in=0,
            max_buy_in=0,
            small_blind=small_blind,
            big_blind=big_blind,
            tournament_id=tournament_id
        )
        
        if self._ws_manager:
            table.set_ws_manager(self._ws_manager)
        
        self.tables[table_id] = table
        logger.info(f"Table created: {table_id} ({request.name})")
        
        return table.get_info()

    async def get_table(self, table_id: str) -> Optional[Table]:
        """Récupère les infos d'une table"""
        table = self.tables.get(table_id)
        return table.get_info() if table else None

    async def list_tables(self, tournament_id: str = None) -> List[Table]:
        """Liste les tables, optionnellement filtrées par tournoi"""
        tables = []
        for table in self.tables.values():
            if tournament_id and table.tournament_id != tournament_id:
                continue
            tables.append(table.get_info())
        return tables

    async def join_table(self, user_id: str, table_id: str, chips: int = 10000) -> bool:
        """Fait rejoindre un utilisateur à une table"""
        # Charger l'utilisateur si nécessaire
        if user_id not in self.users:
            from .auth import auth_manager
            ud = auth_manager.get_user_by_id(user_id)
            if ud:
                self.users[user_id] = User(**ud)
                logger.info(f"Loaded user {ud.get('username')} from auth")
            else:
                logger.error(f"User {user_id} not found")
                return False
        
        if table_id not in self.tables:
            logger.error(f"Table {table_id} not found")
            return False
        
        table = self.tables[table_id]
        user = self.users[user_id]
        
        if not table.can_join():
            logger.warning(f"Table {table_id} is full")
            return False
        
        # Quitter l'ancienne table si nécessaire
        old_table_id = self.user_to_table.get(user_id)
        if old_table_id and old_table_id != table_id:
            await self.leave_table(user_id)
        
        ok = await table.add_player(user, chips)
        
        if ok:
            self.user_to_table[user_id] = table_id
            logger.info(f"User {user.username} joined table {table_id} with {chips} chips")
        
        return ok

    async def leave_table(self, user_id: str):
        """Fait quitter une table à un utilisateur"""
        table_id = self.user_to_table.pop(user_id, None)
        
        if table_id and table_id in self.tables:
            await self.tables[table_id].remove_player(user_id)
            logger.info(f"User {user_id} left table {table_id}")

    async def close_table(self, table_id: str):
        """Ferme une table"""
        if table_id not in self.tables:
            return
        
        table = self.tables[table_id]
        await table.close()
        del self.tables[table_id]
        
        # Nettoyer les références utilisateurs
        users_to_remove = [
            uid for uid, tid in self.user_to_table.items()
            if tid == table_id
        ]
        for uid in users_to_remove:
            del self.user_to_table[uid]
        
        logger.info(f"Table {table_id} closed")

    # ── Utilisateurs ──────────────────────────────────────────────────────────

    async def add_user(self, username: str, email: str = None) -> User:
        """Ajoute un nouvel utilisateur"""
        uid = str(uuid.uuid4())
        
        user = User(
            id=uid,
            username=username,
            email=email,
            avatar='default',
            is_admin=False,
            status='active'
        )
        
        self.users[uid] = user
        self.storage.save_user(user.model_dump())
        
        logger.info(f"User created: {username} ({uid})")
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Récupère un utilisateur"""
        return self.users.get(user_id)

    def get_user_table(self, user_id: str) -> Optional[str]:
        """Récupère la table d'un utilisateur"""
        return self.user_to_table.get(user_id)

    # ── Info lobby ────────────────────────────────────────────────────────────

    async def get_lobby_info(self) -> LobbyInfo:
        """Récupère les informations du lobby"""
        return LobbyInfo(
            tournaments=list(self.tournament_manager.tournaments.values()),
            active_players=len(self.user_to_table),
            total_players=len(self.users),
            total_tables=len(self.tables)
        )

    def get_stats(self) -> dict:
        """Récupère des statistiques détaillées"""
        return {
            'total_users': len(self.users),
            'active_players': len(self.user_to_table),
            'total_tables': len(self.tables),
            'playing_tables': len([
                t for t in self.tables.values()
                if t.status == TableStatus.PLAYING
            ]),
            'total_tournaments': len(self.tournament_manager.tournaments),
            'active_tournaments': len([
                t for t in self.tournament_manager.tournaments.values()
                if t.status == 'in_progress'
            ]),
        }
