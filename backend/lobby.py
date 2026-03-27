# backend/lobby.py
import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime
import random
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
    """Gestionnaire du lobby - Uniquement pour les tournois"""
    
    def __init__(self):
        self.tables: Dict[str, PokerTable] = {}
        self.users: Dict[str, User] = {}
        self.user_to_table: Dict[str, str] = {}
        self._cleanup_task = None
        self.storage = XMLStorage()
        self.tournament_manager = TournamentManager(data_dir="data", lobby=self)
        self._load_data()
    
    def _load_data(self):
        """Charge les données depuis XML"""
        # Charger les utilisateurs depuis storage (users.xml)
        for user_id in self.storage.list_users():
            user_data = self.storage.load_user(user_id)
            if user_data:
                try:
                    user = User(**user_data)
                    self.users[user_id] = user
                    logger.info(f"Loaded user: {user.username}")
                except Exception as e:
                    logger.error(f"Error loading user {user_id}: {e}")
    
    def _create_default_admin(self):
        """Crée un utilisateur admin par défaut"""
        from .auth import auth_manager
        
        # Vérifier si l'admin existe déjà
        if "admin" in self.users:
            return
        
        # Créer l'admin via auth_manager
        auth_manager.create_user("admin", "admin123", "admin@poker.local")
        
        # Récupérer et mettre à jour pour admin
        auth_manager.update_user("admin", {"is_admin": "true"})
        
        # Recharger
        user_data = auth_manager.get_user_by_id("admin")
        if user_data:
            admin = User(**user_data)
            self.users["admin"] = admin
            logger.info("Default admin user created")

    # backend/lobby.py - Ajouter cette méthode
    async def create_table(self, request) -> Table:
        """Crée une nouvelle table pour un tournoi"""
        from .game_engine import PokerTable
 
        table_id = f"table_{uuid.uuid4().hex[:8]}"
 
        # game_type est optionnel dans CreateTableRequest
        # On récupère depuis request si disponible, sinon TOURNAMENT par défaut
        game_type = getattr(request, 'game_type', None) or GameType.TOURNAMENT
 
        # Blinds par défaut (seront mises à jour par le tournament manager)
        blinds = {'small_blind': 10, 'big_blind': 20}
 
        table = PokerTable(
            table_id=table_id,
            name=request.name,
            game_type=game_type,
            max_players=request.max_players,
            min_buy_in=0,
            max_buy_in=0,
            small_blind=blinds['small_blind'],
            big_blind=blinds['big_blind']
        )
 
        self.tables[table_id] = table
        logger.info(f"Table {table_id} created: {request.name}")
 
        return table.get_info()
                
    async def start(self):
        logger.info("Lobby started")
    
    async def stop(self):
        logger.info("Lobby stopped")
    
    async def create_tournament_table(self, tournament: Tournament, table_num: int) -> Table:
        """Crée une table pour un tournoi"""
        table_id = f"table_{tournament.id}_{table_num}"
        
        blinds = tournament.blind_structure[tournament.current_level] if tournament.blind_structure else {'small_blind': 10, 'big_blind': 20}
        
        table = PokerTable(
            table_id=table_id,
            name=f"{tournament.name} - Table {table_num}",
            game_type=GameType.TOURNAMENT,
            max_players=9,
            min_buy_in=0,
            max_buy_in=0,
            small_blind=blinds['small_blind'],
            big_blind=blinds['big_blind']
        )
        
        self.tables[table_id] = table
        return table.get_info()
    
    async def join_table(self, user_id: str, table_id: str) -> bool:
        """Rejoint une table (sans buy-in)"""
        if user_id not in self.users:
            return False
            
        if table_id not in self.tables:
            return False
            
        table = self.tables[table_id]
        user = self.users[user_id]
        
        if not table.can_join():
            return False
        
        success = await table.add_player(user, 0)
        
        if success:
            self.user_to_table[user_id] = table_id
            logger.info(f"User {user.username} joined table {table.name}")
            return True
        
        return False
    
    async def leave_table(self, user_id: str):
        if user_id not in self.user_to_table:
            return
            
        table_id = self.user_to_table[user_id]
        table = self.tables.get(table_id)
        
        if table:
            await table.remove_player(user_id)
        
        del self.user_to_table[user_id]
        logger.info(f"User {user_id} left table {table_id}")
    
    async def add_user(self, username: str, email: Optional[str] = None) -> User:
        """Ajoute un nouvel utilisateur"""
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            username=username,
            email=email,
            avatar='default',
            is_admin=False,
            status='active'
        )
        self.users[user_id] = user
    
        # Sauvegarder dans le fichier users.xml
        self.storage.save_user(user.model_dump())
        logger.info(f"New user created: {username} ({user_id})")
        return user
    
    async def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)
    
    async def get_lobby_info(self) -> LobbyInfo:
        active_players = len(self.user_to_table)
        return LobbyInfo(
            tournaments=list(self.tournament_manager.tournaments.values()),
            active_players=active_players,
            total_players=len(self.users),
            total_tables=len(self.tables)
        )
    
    async def close_table(self, table_id: str):
        if table_id in self.tables:
            table = self.tables[table_id]
            await table.close()
            del self.tables[table_id]
