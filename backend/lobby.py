# backend/lobby.py
"""
Lobby — Gestion des tables et utilisateurs
==========================================
Version v4 :
  - Multi-table : user_to_tables (Dict[str, Set[str]]) au lieu de user_to_table
    → un joueur peut être inscrit à plusieurs tournois simultanément
    → les spectateurs ne sont plus bloqués
  - Crash recovery : annulation safe, délai de grâce, rebuild mapping
  - join_table gère rejoin + multi-tournoi
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, List, Optional, Set
from datetime import datetime

from .models import (
    Table, User, TableStatus, GameType, GameVariant, LobbyInfo, CreateTableRequest, TournamentStatus,
)
from .game_engine import PokerTable, STATE_DIR, PlayerStatus, PlayerState
from .storage import XMLStorage
from .tournament import TournamentManager

logger = logging.getLogger(__name__)

RECOVERY_GRACE_DELAY = 15


class Lobby:
    def __init__(self):
        self._ready = False
        self.tables: Dict[str, PokerTable] = {}
        self.users: Dict[str, User] = {}

        # Multi-table : chaque user peut être à PLUSIEURS tables (multi-tournoi)
        self.user_to_tables: Dict[str, Set[str]] = {}

        # Compat : propriété pour le code qui lit encore user_to_table
        @property
        def user_to_table(self_inner):
            """Compat : retourne la première table du user (ou None)."""
            raise AttributeError("Use user_to_tables instead")

        self._ws_manager = None
        self.storage = XMLStorage()
        self.tournament_manager = TournamentManager(data_dir="data", lobby=self)
        self._started = False
        self._table_cache: Dict[str, dict] = {}
        self._cache_ttl = 30
        self._join_attempts: Dict[str, List[datetime]] = {}
        self._join_limit = 5
        self._join_window = 60
        self._periodic_save_task: Optional[asyncio.Task] = None

    # ── Helpers multi-table ──────────────────────────────────────────────────

    def _add_user_table(self, user_id: str, table_id: str):
        if user_id not in self.user_to_tables:
            self.user_to_tables[user_id] = set()
        self.user_to_tables[user_id].add(table_id)

    def _remove_user_table(self, user_id: str, table_id: str):
        if user_id in self.user_to_tables:
            self.user_to_tables[user_id].discard(table_id)
            if not self.user_to_tables[user_id]:
                del self.user_to_tables[user_id]

    def _user_is_at_table(self, user_id: str, table_id: str) -> bool:
        return table_id in self.user_to_tables.get(user_id, set())

    def _user_table_for_tournament(self, user_id: str, tournament_id: str) -> Optional[str]:
        """Retourne la table_id du joueur dans un tournoi donné, ou None."""
        for tid in self.user_to_tables.get(user_id, set()):
            table = self.tables.get(tid)
            if table and table.tournament_id == tournament_id:
                return tid
        return None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        if self._started:
            return
        self._started = True
        await self._recover_tables()
        await self._recreate_tournament_tables()
        self._rebuild_user_to_tables()
        self._ready = True
        logger.info("Lobby ready")
        await self.tournament_manager.start_monitor()
        self._periodic_save_task = asyncio.create_task(self._periodic_save_tables())
        logger.info("Lobby started")

    async def stop(self):
        self._started = False
        if self._periodic_save_task:
            self._periodic_save_task.cancel()
            try:
                await self._periodic_save_task
            except asyncio.CancelledError:
                pass
        await self.tournament_manager.stop_monitor()
        for table_id in list(self.tables.keys()):
            try:
                await self.close_table(table_id)
            except Exception as e:
                logger.error(f"Error closing table {table_id}: {e}")
        logger.info("Lobby stopped")

    # ── Rebuild mapping ──────────────────────────────────────────────────────

    def _rebuild_user_to_tables(self):
        """Reconstruit user_to_tables depuis l'état réel des tables."""
        self.user_to_tables.clear()
        for table_id, table in self.tables.items():
            for uid in table.players:
                self._add_user_table(uid, table_id)
        logger.info(f"user_to_tables rebuilt: {sum(len(v) for v in self.user_to_tables.values())} mappings for {len(self.user_to_tables)} users")

    # ── Crash Recovery ────────────────────────────────────────────────────────

    async def _recover_tables(self):
        import json
        recovered = 0
        for state_file in STATE_DIR.glob("*.json"):
            try:
                with open(state_file, 'r') as f:
                    state_data = json.load(f)
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

                tournament_id = state_data.get('tournament_id', '')
                tournament = self.tournament_manager.get_tournament(tournament_id) if tournament_id else None

                small_blind = state_data.get('small_blind', 5)
                big_blind = state_data.get('big_blind', 10)
                if tournament and tournament.status in ("in_progress", TournamentStatus.IN_PROGRESS):
                    blinds = tournament.get_current_blinds()
                    small_blind = blinds['small_blind']
                    big_blind = blinds['big_blind']

                table = PokerTable(
                    table_id=table_id,
                    name=state_data.get('name', 'Recovered Table'),
                    tournament_id=tournament_id,
                    max_players=state_data.get('max_players', 9),
                    small_blind=small_blind,
                    big_blind=big_blind,
                    game_variant=variant,
                )
                if self._ws_manager:
                    table.set_ws_manager(self._ws_manager)

                deck = state_data.get('deck', [])
                if deck:
                    table._deck = deck

                for uid, pdata in state_data.get('players', {}).items():
                    try:
                        status = PlayerStatus(pdata.get('status', 'active'))
                    except ValueError:
                        status = PlayerStatus.ACTIVE

                    chips = pdata.get('chips', 0)
                    if tournament:
                        player_data = next((p for p in tournament.players if p['user_id'] == uid), None)
                        if player_data:
                            chips = player_data.get('chips', 0)

                    player_state = PlayerState(
                        user_id=pdata['user_id'],
                        username=pdata['username'],
                        avatar=pdata.get('avatar'),
                        chips=chips,
                        position=pdata.get('position', 0),
                        status=status,
                    )
                    player_state.current_bet = pdata.get('current_bet', 0)
                    player_state.total_bet = pdata.get('total_bet', 0)
                    player_state.hole_cards = pdata.get('hole_cards', [])
                    player_state.is_dealer = pdata.get('is_dealer', False)
                    player_state.is_small_blind = pdata.get('is_small_blind', False)
                    player_state.is_big_blind = pdata.get('is_big_blind', False)
                    player_state.is_all_in = pdata.get('is_all_in', False)
                    table.players[uid] = player_state

                table._hand_round = state_data.get('hand_round', 0)
                table._dealer_btn = state_data.get('dealer_btn', 0)
                table._pot = state_data.get('pot', 0)
                table._community_cards = state_data.get('community_cards', [])
                table._street = state_data.get('street', 'preflop')
                table._current_actor = state_data.get('current_actor', None)
                table._min_raise = state_data.get('min_raise', big_blind)

                # Annuler main en cours (safe — pas de showdown forcé)
                if table._current_actor is not None or (table._street != 'preflop' and table._pot > 0):
                    logger.info(f"Cancelling in-progress hand for {table_id}")
                    for p in table.players.values():
                        p.chips += p.current_bet
                        p.current_bet = 0
                        p.total_bet = 0
                        p.hole_cards = []
                        if p.status not in (PlayerStatus.ELIMINATED,):
                            p.status = PlayerStatus.ACTIVE
                        p.is_all_in = False
                        p.is_dealer = False
                        p.is_small_blind = False
                        p.is_big_blind = False
                    table._pot = 0
                    table._community_cards = []
                    table._street = 'preflop'
                    table._current_actor = None
                    table.status = TableStatus.WAITING
                    table._save_state()
                elif table._street != 'preflop' or table._pot > 0:
                    table.status = TableStatus.PLAYING
                else:
                    table.status = TableStatus.WAITING

                self.tables[table_id] = table
                recovered += 1
                logger.info(f"Recovered table: {table.name} ({table_id}) with {len(table.players)} players")

            except Exception as e:
                logger.error(f"Recovery failed for {state_file}: {e}")

        if recovered:
            logger.info(f"Recovered {recovered} table(s) from crash")
            for table_id, table in self.tables.items():
                active = [p for p in table.players.values() if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]
                if len(active) >= 2 and not table._game_task:
                    asyncio.create_task(self._delayed_game_restart(table, RECOVERY_GRACE_DELAY))

    @staticmethod
    async def _delayed_game_restart(table: PokerTable, delay: float):
        try:
            await asyncio.sleep(delay)
            active = [p for p in table.players.values() if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]
            if len(active) >= 2 and not table._game_task:
                logger.info(f"[{table.name}] Grace period over, starting game loop")
                table._game_task = asyncio.create_task(table._game_loop())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Delayed restart error: {e}")

    async def _recreate_tournament_tables(self):
        from .models import CreateTableRequest, GameVariant
        for tournament in self.tournament_manager.list_tournaments():
            if tournament.status in ("in_progress", TournamentStatus.IN_PROGRESS):
                for old_table_id in list(tournament.tables):
                    if old_table_id not in self.tables:
                        logger.info(f"Recreating table {old_table_id} for tournament {tournament.name}")
                        players_in_table = [p for p in tournament.players if p.get('table_id') == old_table_id]
                        if players_in_table:
                            table_request = CreateTableRequest(
                                name=f"{tournament.name} — Table",
                                tournament_id=tournament.id,
                                max_players=9,
                            )
                            game_variant = GameVariant(tournament.game_variant) if tournament.game_variant else GameVariant.HOLDEM
                            new_table = await self.create_table(table_request, game_variant=game_variant)

                            idx = tournament.tables.index(old_table_id)
                            tournament.tables[idx] = new_table.id

                            for i, player in enumerate(players_in_table):
                                uid = player['user_id']
                                chips = player.get('chips', tournament.starting_chips)
                                new_table.add_player(uid, player['username'], chips, player.get('avatar'))
                                self._add_user_table(uid, new_table.id)
                                player['table_id'] = new_table.id
                                player['position'] = i

                            await self.tournament_manager.save_tournament(tournament)
                            logger.info(f"Recreated table {new_table.id} with {len(players_in_table)} players")
                        else:
                            tournament.tables.remove(old_table_id)

    async def _periodic_save_tables(self):
        while self._started:
            await asyncio.sleep(30)
            for table in self.tables.values():
                if table.status == TableStatus.PLAYING:
                    table._save_state()

    # ── Table CRUD ───────────────────────────────────────────────────────────

    async def create_table(self, request: CreateTableRequest, game_variant: GameVariant = GameVariant.HOLDEM) -> PokerTable:
        table_id = str(uuid.uuid4())
        small_blind, big_blind = 5, 10
        if request.tournament_id:
            t = self.tournament_manager.get_tournament(request.tournament_id)
            if t:
                blinds = t.get_current_blinds()
                small_blind = blinds['small_blind']
                big_blind = blinds['big_blind']

        table = PokerTable(
            table_id=table_id, name=request.name,
            tournament_id=request.tournament_id,
            max_players=request.max_players,
            small_blind=small_blind, big_blind=big_blind,
            game_variant=game_variant,
        )
        if self._ws_manager:
            table.set_ws_manager(self._ws_manager)
        self.tables[table_id] = table
        table._try_start_game()
        logger.info(f"Table created: {request.name} ({table_id})")
        return table

    async def close_table(self, table_id: str):
        table = self.tables.pop(table_id, None)
        if not table:
            return
        for uid in list(table.players.keys()):
            self._remove_user_table(uid, table_id)
        if self._ws_manager:
            await self._ws_manager.close_table_connections(table_id)
        await table.close()
        self._table_cache.pop(table_id, None)
        logger.info(f"Table {table_id} closed")

    async def join_table(self, user_id: str, table_id: str) -> bool:
        """Join table — multi-table aware.

        Un joueur peut être à plusieurs tables SI elles appartiennent à
        des tournois différents. Un joueur déjà dans cette table = succès (rejoin).
        """
        table = self.tables.get(table_id)
        if not table:
            logger.warning(f"Table {table_id} not found")
            return False

        # Déjà dans cette table → succès (rejoin)
        if user_id in table.players:
            self._add_user_table(user_id, table_id)
            logger.info(f"User {user_id} already in table {table_id} (rejoin)")
            return True

        # Vérifier si déjà dans une table du MÊME tournoi
        if table.tournament_id:
            existing = self._user_table_for_tournament(user_id, table.tournament_id)
            if existing and existing != table_id and existing in self.tables:
                logger.info(f"User {user_id} already at table {existing} in same tournament {table.tournament_id}")
                return False

        # Rate limiting (tournoi exempté)
        is_tournament_player = False
        if table.tournament_id:
            t = self.tournament_manager.get_tournament(table.tournament_id)
            if t:
                is_tournament_player = any(p['user_id'] == user_id for p in t.players)

        if not is_tournament_player:
            now = datetime.utcnow()
            attempts = self._join_attempts.get(user_id, [])
            attempts = [a for a in attempts if (now - a).total_seconds() < self._join_window]
            if len(attempts) >= self._join_limit:
                logger.warning(f"Join rate limit exceeded for {user_id}")
                return False
            attempts.append(now)
            self._join_attempts[user_id] = attempts

        # Infos utilisateur
        user = self.users.get(user_id)
        username = user.username if user else user_id
        avatar = user.avatar if user else None
        chips = 10000

        if table.tournament_id:
            t = self.tournament_manager.get_tournament(table.tournament_id)
            if t:
                player_data = next((p for p in t.players if p['user_id'] == user_id), None)
                if player_data:
                    chips = player_data.get('chips', t.starting_chips)
                    username = player_data.get('username', username)
                    avatar = player_data.get('avatar', avatar)

        success = table.add_player(user_id, username, chips, avatar)
        if success:
            self._add_user_table(user_id, table_id)
            logger.info(f"User {username} ({user_id}) joined table {table_id}")
            self._table_cache.pop(table_id, None)
        else:
            logger.warning(f"Failed to add {username} to table {table_id}")
        return success

    async def leave_table(self, user_id: str, table_id: str = None):
        """Retire un joueur d'une table (ou de toutes si table_id=None)."""
        if table_id:
            self._remove_user_table(user_id, table_id)
            if table_id in self.tables:
                self.tables[table_id].remove_player(user_id)
        else:
            # Quitter toutes les tables
            for tid in list(self.user_to_tables.get(user_id, set())):
                if tid in self.tables:
                    self.tables[tid].remove_player(user_id)
            self.user_to_tables.pop(user_id, None)

    async def get_table(self, table_id: str) -> Optional[Table]:
        cached = self._table_cache.get(table_id)
        if cached and (datetime.utcnow() - cached['timestamp']).total_seconds() < self._cache_ttl:
            return cached['data']
        table = self.tables.get(table_id)
        if not table:
            return None
        table_info = table.get_info()
        self._table_cache[table_id] = {'data': table_info, 'timestamp': datetime.utcnow()}
        return table_info

    async def list_tables(self) -> List[Table]:
        return [t.get_info() for t in self.tables.values()]

    async def register_user(self, user_id: str, username: str):
        if user_id not in self.users:
            user = User(id=user_id, username=username)
            self.users[user_id] = user
            self.storage.save_user(user_id, user.model_dump())

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    def get_stats(self) -> dict:
        return {
            'active_players': len(self.user_to_tables),
            'total_players': len(self.users),
            'total_tables': len(self.tables),
            'tournaments': len(self.tournament_manager.tournaments),
            'avg_players_per_table': (
                sum(len(t.players) for t in self.tables.values()) / max(len(self.tables), 1)
            ) if self.tables else 0,
        }
