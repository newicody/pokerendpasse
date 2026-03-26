# backend/game_engine.py
"""
Moteur de jeu poker — PokerKit si disponible, fallback sinon.

Contrat avec lobby.py :
  PokerTable(table_id, name, game_type, max_players,
             min_buy_in, max_buy_in, small_blind, big_blind)
  .can_join()  .add_player(user, buy_in)  .remove_player(user_id)
  .handle_player_action(user_id, action, amount)
  .get_info() -> models.Table   .get_state() -> dict   .close()
  .players (Dict)  .spectators (Set)  .status  .game_state
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from datetime import datetime

from .models import (
    Table, TablePlayer, GameState, GameStatus, TableStatus,
    PlayerStatus, ActionType, PlayerActionRequest, GameType,
)

logger = logging.getLogger(__name__)

# ── PokerKit ------------------------------------------------------------------
try:
    from pokerkit import NoLimitTexasHoldem, Automation, Mode
    POKERKIT_AVAILABLE = True
    logger.info("PokerKit disponible")
except ImportError:
    POKERKIT_AVAILABLE = False
    logger.warning("PokerKit absent - moteur simplifie actif")

_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
) if POKERKIT_AVAILABLE else ()


# ── Modele interne joueur (dataclass, independant de Pydantic) ----------------

@dataclass
class PlayerState:
    user_id:        str
    username:       str
    avatar:         Optional[str]
    chips:          int
    position:       int
    status:         PlayerStatus = PlayerStatus.ACTIVE
    hole_cards:     List[str]    = field(default_factory=list)
    current_bet:    int          = 0
    total_bet:      int          = 0
    is_dealer:      bool         = False
    is_small_blind: bool         = False
    is_big_blind:   bool         = False
    sat_at:         datetime     = field(default_factory=datetime.utcnow)

    def to_pydantic(self) -> TablePlayer:
        return TablePlayer(
            user_id        = self.user_id,
            username       = self.username,
            avatar         = self.avatar,
            position       = self.position,
            status         = self.status,
            current_bet    = self.current_bet,
            total_bet      = self.total_bet,
            hole_cards     = self.hole_cards,
            is_dealer      = self.is_dealer,
            is_small_blind = self.is_small_blind,
            is_big_blind   = self.is_big_blind,
            sat_at         = self.sat_at,
        )


# =============================================================================
# PokerTable
# =============================================================================

class PokerTable:
    """Table de poker multi-joueurs."""

    def __init__(self, table_id: str, name: str, game_type,
                 max_players: int, min_buy_in: int, max_buy_in: int,
                 small_blind: int, big_blind: int,
                 tournament_id: Optional[str] = None):
        self.id            = table_id
        self.name          = name
        self.game_type     = game_type
        self.max_players   = max_players
        self.min_buy_in    = min_buy_in
        self.max_buy_in    = max_buy_in
        self.small_blind   = small_blind
        self.big_blind     = big_blind
        self.tournament_id = tournament_id

        self.players:    Dict[str, PlayerState] = {}
        self.spectators: Set[str]               = set()
        self.status:     TableStatus            = TableStatus.WAITING
        self.game_state: Optional[GameState]    = None

        self._pk_state:        Any       = None
        self._position_to_uid: List[str] = []
        self._street:          str       = 'preflop'

        self._game_task:     Optional[asyncio.Task]  = None
        self._action_queue:  asyncio.Queue           = asyncio.Queue()
        self._player_timers: Dict[str, asyncio.Task] = {}

        self._pot:         int       = 0
        self._current_bet: int       = 0
        self._community:   List[str] = []
        self._deck:        List[str] = []

    # ── Capacite -------------------------------------------------------------

    def can_join(self) -> bool:
        return (self.status in (TableStatus.WAITING, TableStatus.PLAYING)
                and len(self.players) < self.max_players)

    def is_full(self) -> bool:  return len(self.players) >= self.max_players
    def is_empty(self) -> bool: return len(self.players) == 0

    # ── Joueurs --------------------------------------------------------------

    async def add_player(self, user, buy_in: int) -> bool:
        if not self.can_join():
            return False
        ps = PlayerState(
            user_id  = user.id,
            username = user.username,
            avatar   = getattr(user, 'avatar', None),
            chips    = buy_in,
            position = len(self.players),
        )
        self.players[user.id] = ps
        logger.info(f"[{self.name}] {user.username} ({buy_in} chips)")
        if len(self.players) >= 2 and not self.game_state:
            await self.start_game()
        return True

    async def remove_player(self, user_id: str):
        ps = self.players.pop(user_id, None)
        if ps:
            logger.info(f"[{self.name}] {ps.username} quitte")

    def add_spectator(self, user_id: str):    self.spectators.add(user_id)
    def remove_spectator(self, user_id: str): self.spectators.discard(user_id)

    # ── Demarrage ------------------------------------------------------------

    async def start_game(self):
        if self.game_state and self.game_state.status == GameStatus.IN_PROGRESS:
            return
        if len(self.players) < 2:
            return
        self.status = TableStatus.PLAYING
        self.game_state = GameState(
            table_id=self.id, status=GameStatus.IN_PROGRESS,
            round=0, players=[], time_bank=30,
        )
        self._game_task = asyncio.create_task(self._game_loop())
        logger.info(f"[{self.name}] Partie lancee ({len(self.players)} joueurs)")

    # ── Boucle ---------------------------------------------------------------

    async def _game_loop(self):
        try:
            while self.game_state and self.game_state.status == GameStatus.IN_PROGRESS:
                if len(self._get_active()) < 2:
                    break
                await self._play_hand()
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.name}] game_loop: {e}", exc_info=True)
        finally:
            self.game_state = None
            self.status     = TableStatus.WAITING

    async def _play_hand(self):
        if POKERKIT_AVAILABLE:
            await self._hand_pk()
        else:
            await self._hand_fallback()

    # ── Main PokerKit --------------------------------------------------------

    async def _hand_pk(self):
        active = self._get_active()
        if len(active) < 2:
            return
        self._position_to_uid = [p.user_id for p in active]
        stacks = [p.chips for p in active]
        try:
            self._pk_state = NoLimitTexasHoldem.create_state(
                automations             = _AUTOMATIONS,
                ante_trimming_status    = True,
                raw_antes               = 0,
                raw_blinds_or_straddles = (self.small_blind, self.big_blind),
                min_bet                 = self.big_blind,
                raw_starting_stacks     = stacks,
                player_count            = len(stacks),
                mode                    = Mode.TOURNAMENT,
            )
        except Exception as e:
            logger.error(f"[{self.name}] create_state: {e}")
            return
        self.game_state.round += 1

        # Cartes privees
        while self._pk_state.can_deal_hole():
            try:
                op  = self._pk_state.deal_hole()
                uid = self._position_to_uid[op.player_index]
                ps  = self.players.get(uid)
                if ps:
                    ps.hole_cards = [str(c) for c in op.cards]
            except Exception:
                break
            await asyncio.sleep(0.1)

        # Streets
        for street in ('preflop', 'flop', 'turn', 'river'):
            self._street = street
            if street != 'preflop':
                try:
                    if self._pk_state.can_deal_board():
                        op    = self._pk_state.deal_board()
                        cards = [str(c) for c in op.cards]
                        self.game_state.community_cards = (
                            self.game_state.community_cards + cards)
                except Exception:
                    pass
                await asyncio.sleep(0.3)
            await self._bet_pk()
            if self._over_pk():
                break

        # Showdown
        if not self._over_pk():
            while self._pk_state.can_show_or_muck_hole_cards():
                try:
                    self._pk_state.show_or_muck_hole_cards(True)
                except Exception:
                    break

        self._sync_pk()
        self._pk_state = None
        self.game_state.community_cards = []
        for ps in self.players.values():
            ps.hole_cards = []; ps.current_bet = 0; ps.total_bet = 0

    async def _bet_pk(self):
        while True:
            s = self._pk_state
            if s is None or s.actor_index is None or self._over_pk():
                break
            idx = s.actor_index
            if idx >= len(self._position_to_uid):
                break
            uid = self._position_to_uid[idx]
            self.game_state.current_player_index = idx
            try:
                req = await asyncio.wait_for(self._action_queue.get(), timeout=30)
            except asyncio.TimeoutError:
                req = PlayerActionRequest(user_id=uid, table_id=self.id,
                                          action=ActionType.FOLD, amount=0)
            if req.user_id != uid:
                await self._action_queue.put(req)
                continue
            self._do_pk(req)

    def _do_pk(self, req: PlayerActionRequest):
        s = self._pk_state
        if not s:
            return
        try:
            if req.action == ActionType.FOLD:
                if s.can_fold(): s.fold()
            elif req.action in (ActionType.CHECK, ActionType.CALL):
                if s.can_check_or_call(): s.check_or_call()
            elif req.action == ActionType.RAISE:
                if s.can_complete_bet_or_raise_to():
                    lo  = s.min_completion_betting_or_raising_to_amount or self.big_blind
                    hi  = s.max_completion_betting_or_raising_to_amount
                    amt = max(req.amount, lo)
                    if hi: amt = min(amt, hi)
                    s.complete_bet_or_raise_to(amt)
            elif req.action == ActionType.ALL_IN:
                if s.can_complete_bet_or_raise_to():
                    hi = s.max_completion_betting_or_raising_to_amount
                    s.complete_bet_or_raise_to(hi) if hi else None
                elif s.can_check_or_call():
                    s.check_or_call()
        except Exception as e:
            logger.warning(f"[{self.name}] action pk invalide: {e}")

    def _over_pk(self) -> bool:
        if not self._pk_state:
            return True
        return sum(1 for st in self._pk_state.statuses if st) <= 1

    def _sync_pk(self):
        if not self._pk_state:
            return
        for i, uid in enumerate(self._position_to_uid):
            ps = self.players.get(uid)
            if ps and i < len(self._pk_state.stacks):
                ps.chips = self._pk_state.stacks[i]
                if ps.chips <= 0:
                    ps.status = PlayerStatus.ELIMINATED

    # ── Fallback (sans PokerKit) ---------------------------------------------

    async def _hand_fallback(self):
        active = self._get_active()
        if len(active) < 2:
            return
        self.game_state.round += 1
        self._deck      = self._mk_deck(); random.shuffle(self._deck)
        self._community = []; self._pot = 0; self._current_bet = 0
        for ps in active:
            ps.hole_cards = [self._deck.pop(), self._deck.pop()]
            ps.current_bet = 0; ps.total_bet = 0
        self._blind(active[0], self.small_blind)
        self._blind(active[1] if len(active) > 1 else active[0], self.big_blind)
        self._current_bet = self.big_blind
        for street in ('preflop', 'flop', 'turn', 'river'):
            self._street = street
            if street == 'flop':
                self._community = [self._deck.pop() for _ in range(3)]
            elif street in ('turn', 'river'):
                self._community.append(self._deck.pop())
            self.game_state.community_cards = list(self._community)
            await self._bet_fallback(active)
            if sum(1 for p in active if p.status == PlayerStatus.ACTIVE) <= 1:
                break
        for ps in active:
            ps.hole_cards = []; ps.current_bet = 0; ps.total_bet = 0
        self.game_state.community_cards = []
        self._community = []; self._pot = 0; self._current_bet = 0

    def _blind(self, ps: PlayerState, amount: int):
        amt = min(amount, ps.chips)
        ps.chips -= amt; ps.current_bet = amt; ps.total_bet += amt; self._pot += amt

    async def _bet_fallback(self, active: List[PlayerState]):
        for ps in active:
            if ps.status != PlayerStatus.ACTIVE or ps.chips <= 0:
                continue
            try:
                req = await asyncio.wait_for(self._action_queue.get(), timeout=20)
            except asyncio.TimeoutError:
                ps.status = PlayerStatus.FOLDED; continue
            to_call = self._current_bet - ps.current_bet
            if req.action == ActionType.FOLD:
                ps.status = PlayerStatus.FOLDED
            elif req.action in (ActionType.CALL, ActionType.CHECK):
                amt = min(to_call, ps.chips)
                ps.chips -= amt; ps.current_bet += amt; self._pot += amt
            elif req.action in (ActionType.RAISE, ActionType.ALL_IN):
                total = self._current_bet + max(req.amount, self.big_blind)
                amt   = min(total - ps.current_bet, ps.chips)
                ps.chips -= amt; ps.current_bet += amt
                self._pot += amt; self._current_bet = ps.current_bet

    @staticmethod
    def _mk_deck() -> List[str]:
        return [f"{r}{s}" for s in 'hdcs'
                for r in ['2','3','4','5','6','7','8','9','T','J','Q','K','A']]

    # ── Action WebSocket (point d'entree) ------------------------------------

    async def handle_player_action(self, user_id: str, action: ActionType, amount: int = 0):
        await self._action_queue.put(PlayerActionRequest(
            user_id=user_id, table_id=self.id, action=action, amount=amount))

    # ── API publique ---------------------------------------------------------

    def get_info(self) -> Table:
        return Table(
            id            = self.id,
            name          = self.name,
            game_type     = self.game_type,
            tournament_id = self.tournament_id,
            max_players   = self.max_players,
            status        = self.status,
            players       = [ps.to_pydantic() for ps in self.players.values()],
            spectators    = list(self.spectators),
        )

    def get_state(self) -> dict:
        pk = self._pk_state
        if pk:
            board = [str(c) for c in pk.board_cards] if pk.board_cards else []
            actor = None
            if pk.actor_index is not None and pk.actor_index < len(self._position_to_uid):
                actor = self._position_to_uid[pk.actor_index]
            players_out = [
                {'user_id': uid,
                 'username': self.players[uid].username if uid in self.players else uid,
                 'stack':    pk.stacks[i] if i < len(pk.stacks) else 0,
                 'bet':      pk.bets[i]   if i < len(pk.bets)   else 0,
                 'folded':   not pk.statuses[i] if i < len(pk.statuses) else True,
                 'is_actor': pk.actor_index == i}
                for i, uid in enumerate(self._position_to_uid)
            ]
            return {'status': 'in_progress', 'total_pot': pk.total_pot_amount,
                    'board': board, 'players': players_out,
                    'actor': actor, 'street': self._street}

        if not self.game_state:
            return {'status': 'waiting'}
        status_val = (self.game_state.status.value
                      if hasattr(self.game_state.status, 'value')
                      else self.game_state.status)
        return {
            'status': status_val, 'total_pot': self._pot,
            'community_cards': self.game_state.community_cards,
            'current_bet': self._current_bet, 'street': self._street,
            'players': [{'user_id': ps.user_id, 'username': ps.username,
                          'stack': ps.chips, 'bet': ps.current_bet,
                          'folded': ps.status == PlayerStatus.FOLDED}
                         for ps in self.players.values()],
        }

    def get_valid_actions(self, user_id: str) -> dict:
        pk = self._pk_state
        if not pk or pk.actor_index is None: return {}
        if user_id not in self._position_to_uid: return {}
        idx = self._position_to_uid.index(user_id)
        if pk.actor_index != idx: return {}
        out: dict = {}
        if pk.can_fold(): out['fold'] = {}
        if pk.can_check_or_call():
            tc = pk.checking_or_calling_amount or 0
            out['check' if tc == 0 else 'call'] = {'amount': tc}
        if pk.can_complete_bet_or_raise_to():
            out['raise'] = {
                'min': pk.min_completion_betting_or_raising_to_amount or self.big_blind,
                'max': pk.max_completion_betting_or_raising_to_amount,
            }
        return out

    def _get_active(self) -> List[PlayerState]:
        return [ps for ps in self.players.values()
                if ps.status == PlayerStatus.ACTIVE and ps.chips > 0]

    async def close(self):
        if self._game_task:
            self._game_task.cancel()
            try: await self._game_task
            except asyncio.CancelledError: pass
        for t in self._player_timers.values(): t.cancel()
        self._player_timers.clear()
        self.status = TableStatus.WAITING; self.game_state = None
        logger.info(f"[{self.name}] Table fermee")
