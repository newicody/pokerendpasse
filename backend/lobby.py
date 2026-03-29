# backend/lobby.py
"""
Lobby — Gestion des tables et utilisateurs
==========================================
Avec crash/resume : reconstruction des tables au démarrage.
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional
from datetime import datetime

from .models import (
    Table, User, TableStatus, GameType, GameVariant, LobbyInfo, CreateTableRequest,
)
from .game_engine import PokerTable, STATE_DIR
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
        self._started = False
        self._load_data()

    def _load_data(self):
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
        if self._started:
            return
        self._started = True

        # Crash recovery : reconstruire les tables en cours
        await self._recover_tables()

        # Démarrer le monitor des tournois
        self.tournament_manager.start_monitor()

        logger.info("Lobby started")

    async def stop(self):
        self._started = False
        await self.tournament_manager.stop_monitor()
        for table_id in list(self.tables.keys()):
            try:
                await self.close_table(table_id)
            except Exception as e:
                logger.error(f"Error closing table {table_id}: {e}")
        logger.info("Lobby stopped")

    # ── Crash Recovery ────────────────────────────────────────────────────────

    async def _recover_tables(self):
        """Reconstruit les tables depuis les fichiers JSON sauvegardés"""
        recovered = 0
        for state_file in STATE_DIR.glob("*.json"):
            try:
                state_data = PokerTable.load_state(state_file.stem)
                if not state_data:
                    continue

                table_id = state_data['table_id']
                if table_id in self.tables:
                    continue

                variant_str = state_data.get('game_variant', 'holdem')
                try:
                    variant = GameVariant(variant_str)
                except ValueError:
                    variant = GameVariant.HOLDEM

                table = PokerTable(
                    table_id=table_id,
                    name=state_data.get('name', 'Recovered Table'),
                    tournament_id=state_data.get('tournament_id', ''),
                    max_players=state_data.get('max_players', 9),
                    small_blind=state_data.get('small_blind', 5),
                    big_blind=state_data.get('big_blind', 10),
                    game_variant=variant,
                )

                # Restaurer les joueurs
                for uid, pdata in state_data.get('players', {}).items():
                    from .game_engine import PlayerState, PlayerStatus
                    try:
                        status = PlayerStatus(pdata.get('status', 'active'))
                    except ValueError:
                        status = PlayerStatus.ACTIVE

                    table.players[uid] = PlayerState(
                        user_id=pdata['user_id'],
                        username=pdata['username'],
                        avatar=pdata.get('avatar'),
                        chips=pdata.get('chips', 0),
                        position=pdata.get('position', 0),
                        status=status,
                    )
                    self.user_to_table[uid] = table_id

                table._hand_round = state_data.get('hand_round', 0)
                table._dealer_btn = state_data.get('dealer_btn', 0)

                self.tables[table_id] = table
                recovered += 1
                logger.info(f"Recovered table: {table.name} ({table_id})")

            except Exception as e:
                logger.error(f"Recovery failed for {state_file}: {e}")

        if recovered:
            logger.info(f"Recovered {recovered} table(s) from crash")

    # ── Tables ────────────────────────────────────────────────────────────────

    async def create_table(
        self,
        request: CreateTableRequest,
        game_variant: GameVariant = GameVariant.HOLDEM,
    ) -> PokerTable:
        table_id = str(uuid.uuid4())

        # Blinds depuis le tournoi si applicable
        small_blind, big_blind = 5, 10
        if request.tournament_id:
            t = self.tournament_manager.get_tournament(request.tournament_id)
            if t:
                blinds = t.get_current_blinds()
                small_blind = blinds['small_blind']
                big_blind = blinds['big_blind']

        table = PokerTable(
            table_id=table_id,
            name=request.name,
            tournament_id=request.tournament_id,
            max_players=request.max_players,
            small_blind=small_blind,
            big_blind=big_blind,
            game_variant=game_variant,
        )

        if self._ws_manager:
            table.set_ws_manager(self._ws_manager)

        self.tables[table_id] = table
        logger.info(f"Table created: {request.name} ({table_id})")
        return table

    async def close_table(self, table_id: str):
        table = self.tables.pop(table_id, None)
        if table:
            await table.close()
            # Nettoyer user_to_table
            for uid in list(self.user_to_table.keys()):
                if self.user_to_table.get(uid) == table_id:
                    del self.user_to_table[uid]
            logger.info(f"Table closed: {table_id}")

    async def join_table(self, user_id: str, table_id: str) -> bool:
        table = self.tables.get(table_id)
        if not table:
            return False

        # Récupérer les infos utilisateur
        user = self.users.get(user_id)
        username = user.username if user else user_id
        avatar = user.avatar if user else None

        # Chips depuis le tournoi
        chips = 10000
        if table.tournament_id:
            t = self.tournament_manager.get_tournament(table.tournament_id)
            if t:
                player_data = next(
                    (p for p in t.players if p['user_id'] == user_id), None
                )
                if player_data:
                    chips = player_data.get('chips', t.starting_chips)
                    username = player_data.get('username', username)
                    avatar = player_data.get('avatar', avatar)

        success = table.add_player(user_id, username, chips, avatar)
        if success:
            self.user_to_table[user_id] = table_id
        return success

    async def leave_table(self, user_id: str):
        table_id = self.user_to_table.pop(user_id, None)
        if table_id and table_id in self.tables:
            self.tables[table_id].remove_player(user_id)

    async def get_table(self, table_id: str) -> Optional[Table]:
        table = self.tables.get(table_id)
        return table.get_info() if table else None

    async def list_tables(self) -> List[Table]:
        return [t.get_info() for t in self.tables.values()]

    # ── Users ─────────────────────────────────────────────────────────────────

    async def register_user(self, user_id: str, username: str):
        if user_id not in self.users:
            user = User(id=user_id, username=username)
            self.users[user_id] = user
            self.storage.save_user(user_id, user.model_dump())

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        active_players = len(self.user_to_table)
        return {
            'active_players': active_players,
            'total_players': len(self.users),
            'total_tables': len(self.tables),
            'tournaments': len(self.tournament_manager.tournaments),
            'tables': {
                tid: {
                    'name': t.name,
                    'players': len(t.players),
                    'status': t.status.value if hasattr(t.status, 'value') else str(t.status),
                }
                for tid, t in self.tables.items()
            },
        }
