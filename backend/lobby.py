# backend/lobby.py — Freeroll tournaments, join_table with chips
import asyncio, logging, uuid
from typing import Dict, List, Optional
from datetime import datetime
from .models import (Table, User, TableStatus, GameType, LobbyInfo, CreateTableRequest)
from .game_engine import PokerTable
from .storage import XMLStorage
from .tournament import TournamentManager
logger = logging.getLogger(__name__)

class Lobby:
    def __init__(self):
        self.tables: Dict[str, PokerTable] = {}
        self.users: Dict[str, User] = {}
        self.user_to_table: Dict[str, str] = {}
        self._ws_manager = None
        self.storage = XMLStorage()
        self.tournament_manager = TournamentManager(data_dir="data", lobby=self)
        self._load_data()

    def _load_data(self):
        for user_id in self.storage.list_users():
            ud = self.storage.load_user(user_id)
            if ud:
                try: self.users[user_id] = User(**ud)
                except Exception as e: logger.error(f"Load user {user_id}: {e}")

    async def create_table(self, request) -> Table:
        table_id = f"table_{uuid.uuid4().hex[:8]}"
        gt = getattr(request, 'game_type', None) or GameType.TOURNAMENT
        tid = getattr(request, 'tournament_id', None)
        table = PokerTable(table_id=table_id, name=request.name, game_type=gt,
                           max_players=request.max_players, min_buy_in=0, max_buy_in=0,
                           small_blind=10, big_blind=20, tournament_id=tid)
        if self._ws_manager: table.set_ws_manager(self._ws_manager)
        self.tables[table_id] = table
        logger.info(f"Table {table_id}: {request.name}"); return table.get_info()

    async def join_table(self, user_id, table_id, chips=10000):
        if user_id not in self.users:
            from .auth import auth_manager
            ud = auth_manager.get_user_by_id(user_id)
            if ud: self.users[user_id] = User(**ud); logger.info(f"Loaded {ud.get('username')} from auth")
            else: logger.error(f"User {user_id} not found"); return False
        if table_id not in self.tables: logger.error(f"Table {table_id} not found"); return False
        table = self.tables[table_id]; user = self.users[user_id]
        if not table.can_join(): return False
        ok = await table.add_player(user, chips)
        if ok: self.user_to_table[user_id] = table_id
        return ok

    async def leave_table(self, user_id):
        tid = self.user_to_table.pop(user_id, None)
        if tid and tid in self.tables: await self.tables[tid].remove_player(user_id)

    async def close_table(self, table_id):
        if table_id in self.tables:
            await self.tables[table_id].close(); del self.tables[table_id]
            for uid in [u for u,t in self.user_to_table.items() if t==table_id]:
                del self.user_to_table[uid]

    async def add_user(self, username, email=None):
        uid = str(uuid.uuid4())
        user = User(id=uid, username=username, email=email, avatar='default', is_admin=False, status='active')
        self.users[uid] = user; self.storage.save_user(user.model_dump()); return user

    async def get_lobby_info(self):
        return LobbyInfo(tournaments=list(self.tournament_manager.tournaments.values()),
                         active_players=len(self.user_to_table),
                         total_players=len(self.users), total_tables=len(self.tables))

    async def start(self): logger.info("Lobby started")
    async def stop(self):
        for tid in list(self.tables.keys()):
            try: await self.close_table(tid)
            except: pass
        logger.info("Lobby stopped")
