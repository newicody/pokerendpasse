# backend/lobby.py
"""
Lobby — Gestion des tables, utilisateurs, tournois (freeroll only).
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import uuid

from .models import (
    Table, User, TablePlayer, TableStatus, GameType, LobbyInfo,
    PlayerStatus, CreateTableRequest, Tournament
)
from .game_engine import PokerTable
from .storage import XMLStorage
from .tournament import TournamentManager

logger = logging.getLogger(__name__)


class Lobby:
    """Gestionnaire du lobby — freeroll tournaments."""

    def __init__(self):
        self.tables: Dict[str, PokerTable] = {}
        self.users: Dict[str, User] = {}
        self.user_to_table: Dict[str, str] = {}
        self._cleanup_task = None
        self._ws_manager = None
        self.storage = XMLStorage()
        self.tournament_manager = TournamentManager(data_dir="data", lobby=self)
        self._load_data()

    def _load_data(self):
        """Charge les utilisateurs depuis le stockage XML."""
        for user_id in self.storage.list_users():
            user_data = self.storage.load_user(user_id)
            if user_data:
                try:
                    user = User(**user_data)
                    self.users[user_id] = user
                except Exception as e:
                    logger.error(f"Error loading user {user_id}: {e}")

    def _create_default_admin(self):
        """Crée un admin par défaut si inexistant."""
        from .auth import auth_manager
        if "admin" in self.users:
            return
        auth_manager.create_user("admin", "admin123", "admin@poker.local")
        auth_manager.update_user("admin", {"is_admin": "true"})
        user_data = auth_manager.get_user_by_id("admin")
        if user_data:
            admin = User(**user_data)
            self.users["admin"] = admin
            logger.info("Default admin user created")

    # ── Création de table ─────────────────────────────────────────────────

    async def create_table(self, request) -> Table:
        """Crée une nouvelle table (pour tournoi ou manuelle)."""
        table_id = f"table_{uuid.uuid4().hex[:8]}"

        # game_type optionnel dans CreateTableRequest
        game_type = getattr(request, 'game_type', None) or GameType.TOURNAMENT
        tournament_id = getattr(request, 'tournament_id', None)

        # Blinds par défaut (le tournament manager les met à jour)
        blinds = {'small_blind': 10, 'big_blind': 20}

        table = PokerTable(
            table_id=table_id,
            name=request.name,
            game_type=game_type,
            max_players=request.max_players,
            min_buy_in=0,
            max_buy_in=0,
            small_blind=blinds['small_blind'],
            big_blind=blinds['big_blind'],
            tournament_id=tournament_id,
        )

        # Injecter le ws_manager
        if self._ws_manager:
            table.set_ws_manager(self._ws_manager)

        self.tables[table_id] = table
        logger.info(f"Table {table_id} created: {request.name}")

        return table.get_info()

    # ── Rejoindre une table ───────────────────────────────────────────────

    async def join_table(self, user_id: str, table_id: str, chips: int = 10000) -> bool:
        """Rejoint une table avec un certain nombre de chips (freeroll)."""
        # S'assurer que l'utilisateur existe
        if user_id not in self.users:
            from .auth import auth_manager
            user_data = auth_manager.get_user_by_id(user_id)
            if user_data:
                user = User(**user_data)
                self.users[user_id] = user
                logger.info(f"Loaded user {user.username} from auth for table join")
            else:
                logger.error(f"User {user_id} not found — cannot join table")
                return False

        if table_id not in self.tables:
            logger.error(f"Table {table_id} not found")
            return False

        table = self.tables[table_id]
        user = self.users[user_id]

        if not table.can_join():
            logger.warning(f"Table {table_id} full or closed")
            return False

        success = await table.add_player(user, chips)

        if success:
            self.user_to_table[user_id] = table_id
            logger.info(f"User {user.username} joined {table.name} with {chips} chips")
            return True

        return False

    # ── Quitter une table ─────────────────────────────────────────────────

    async def leave_table(self, user_id: str):
        """Quitter la table courante."""
        if user_id not in self.user_to_table:
            return

        table_id = self.user_to_table[user_id]
        table = self.tables.get(table_id)

        if table:
            await table.remove_player(user_id)

        del self.user_to_table[user_id]
        logger.info(f"User {user_id} left table {table_id}")

    # ── Table de tournoi ──────────────────────────────────────────────────

    async def create_tournament_table(self, tournament, table_num: int) -> Table:
        """Crée une table spécifique pour un tournoi."""
        table_id = f"table_{tournament.id}_{table_num}"

        blinds = (tournament.blind_structure[tournament.current_level]
                  if tournament.blind_structure
                  else {'small_blind': 10, 'big_blind': 20})

        table = PokerTable(
            table_id=table_id,
            name=f"{tournament.name} - Table {table_num}",
            game_type=GameType.TOURNAMENT,
            max_players=9,
            min_buy_in=0,
            max_buy_in=0,
            small_blind=blinds['small_blind'],
            big_blind=blinds['big_blind'],
            tournament_id=tournament.id,
        )

        if self._ws_manager:
            table.set_ws_manager(self._ws_manager)

        self.tables[table_id] = table
        return table.get_info()

    # ── Utilisateurs ──────────────────────────────────────────────────────

    async def add_user(self, username: str, email: str = None) -> User:
        user_id = str(uuid.uuid4())
        user = User(id=user_id, username=username, email=email,
                     avatar='default', is_admin=False, status='active')
        self.users[user_id] = user
        self.storage.save_user(user.model_dump())
        logger.info(f"New user: {username} ({user_id})")
        return user

    async def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    # ── Lobby info ────────────────────────────────────────────────────────

    async def get_lobby_info(self) -> LobbyInfo:
        return LobbyInfo(
            tournaments=list(self.tournament_manager.tournaments.values()),
            active_players=len(self.user_to_table),
            total_players=len(self.users),
            total_tables=len(self.tables),
        )

    # ── Fermer une table ──────────────────────────────────────────────────

    async def close_table(self, table_id: str):
        if table_id in self.tables:
            table = self.tables[table_id]
            await table.close()
            del self.tables[table_id]
            # Nettoyer user_to_table
            to_remove = [uid for uid, tid in self.user_to_table.items() if tid == table_id]
            for uid in to_remove:
                del self.user_to_table[uid]
            logger.info(f"Table {table_id} closed")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self):
        logger.info("Lobby started")

    async def stop(self):
        # Fermer toutes les tables proprement
        for table_id in list(self.tables.keys()):
            try:
                await self.close_table(table_id)
            except Exception as e:
                logger.error(f"Error closing table {table_id}: {e}")
        logger.info("Lobby stopped")
