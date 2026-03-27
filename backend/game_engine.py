# backend/game_engine.py
"""
PokerKit game engine + SRA Deck Security (mental-poker-toolkit port).

Modifications vs version précédente :
  - _play_hand_pokerkit : broadcast 'hand_result' en fin de main (winners + pot)
  - _play_hand_pokerkit : enregistrement des stacks avant la main pour détecter les gagnants
  - get_state()         : inclut 'ring_status' (idle/committed/verified)
"""
import asyncio
import hashlib
import json
import logging
import secrets
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from pokerkit import NoLimitTexasHoldem, Automation, Mode

from .models import (
    Table, TablePlayer, GameState, GameStatus, TableStatus,
    PlayerStatus, ActionType, PlayerActionRequest, GameType,
)

logger = logging.getLogger(__name__)

ACTION_TIMEOUT       = 20   # secondes
PAUSE_BETWEEN_HANDS  = 4    # secondes entre deux mains

STATE_DIR = Path("data/table_states")
STATE_DIR.mkdir(parents=True, exist_ok=True)

AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HOLE_DEALING,
    Automation.BOARD_DEALING,
    Automation.RUNOUT_COUNT_SELECTION,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)

# ─────────────────────────────────────────────────────────────────────────────
# Sécurité du deck (commit-reveal SRA simplifié)
# ─────────────────────────────────────────────────────────────────────────────

class DeckSecurity:
    """Commit-reveal SRA — port du mental-poker-toolkit pour serveur autoritaire."""

    def __init__(self):
        self._commitments: Dict[int, dict] = {}

    def commit_deck(self, hand_round: int, deck: List[str]) -> str:
        """Génère un seed, hache seed+deck, stocke et retourne le hash."""
        seed = secrets.token_hex(32)
        deck_str = ','.join(deck)
        h = hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest()
        self._commitments[hand_round] = {
            'seed': seed,
            'hash': h,
            'deck_order': list(deck),
        }
        return h

    def reveal(self, hand_round: int) -> Optional[dict]:
        """Retourne les données de reveal pour vérification côté client."""
        return self._commitments.get(hand_round)

    def has_commitment(self, hand_round: int) -> bool:
        return hand_round in self._commitments

    @staticmethod
    def verify(seed: str, deck_order: List[str], commitment_hash: str) -> bool:
        deck_str = ','.join(deck_order)
        return hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest() == commitment_hash

    @staticmethod
    def sra_encrypt(val: int, e: int, mod: int) -> int:
        return pow(val, e, mod)

    @staticmethod
    def sra_decrypt(cipher: int, d: int, mod: int) -> int:
        return pow(cipher, d, mod)


# ─────────────────────────────────────────────────────────────────────────────
# État d'un joueur à la table
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlayerState:
    user_id:        str
    username:       str
    avatar:         Optional[str]
    chips:          int
    position:       int
    status:         PlayerStatus     = PlayerStatus.ACTIVE
    hole_cards:     List[str]        = field(default_factory=list)
    current_bet:    int              = 0
    total_bet:      int              = 0
    is_dealer:      bool             = False
    is_small_blind: bool             = False
    is_big_blind:   bool             = False
    sat_at:         datetime         = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            'user_id':        self.user_id,
            'username':       self.username,
            'avatar':         self.avatar,
            'chips':          self.chips,
            'stack':          self.chips,           # alias
            'position':       self.position,
            'status':         self.status.value if hasattr(self.status, 'value') else str(self.status),
            'current_bet':    self.current_bet,
            'bet':            self.current_bet,     # alias
            'total_bet':      self.total_bet,
            'hole_cards':     self.hole_cards,
            'is_dealer':      self.is_dealer,
            'is_small_blind': self.is_small_blind,
            'is_big_blind':   self.is_big_blind,
        }

    def to_pydantic(self) -> TablePlayer:
        return TablePlayer(
            user_id=self.user_id,   username=self.username,     avatar=self.avatar,
            position=self.position, status=self.status,          current_bet=self.current_bet,
            total_bet=self.total_bet, hole_cards=self.hole_cards,
            is_dealer=self.is_dealer, is_small_blind=self.is_small_blind,
            is_big_blind=self.is_big_blind, sat_at=self.sat_at,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Table de poker
# ─────────────────────────────────────────────────────────────────────────────

class PokerTable:

    def __init__(self, table_id: str, name: str, game_type, max_players: int,
                 min_buy_in: int, max_buy_in: int,
                 small_blind: int, big_blind: int,
                 tournament_id: Optional[str] = None):
        self.id             = table_id
        self.name           = name
        self.game_type      = game_type
        self.max_players    = max_players
        self.min_buy_in     = min_buy_in
        self.max_buy_in     = max_buy_in
        self.small_blind    = small_blind
        self.big_blind      = big_blind
        self.tournament_id  = tournament_id

        self.players:    Dict[str, PlayerState] = {}
        self.spectators: Set[str]               = set()
        self.status:     TableStatus            = TableStatus.WAITING

        self.game_state:            Optional[GameState]    = None
        self._pk_state                                     = None
        self._pk_uid_map:           List[str]              = []
        self._street:               str                    = 'preflop'
        self._game_task:            Optional[asyncio.Task] = None
        self._action_queue:         asyncio.Queue          = asyncio.Queue()
        self._ws_manager                                   = None
        self._current_actor_uid:    Optional[str]          = None
        self._action_deadline:      Optional[float]        = None
        self._deck_security:        DeckSecurity           = DeckSecurity()
        self._dealer_btn:           int                    = 0
        self._hand_round:           int                    = 0

    # ── Config ──────────────────────────────────────────────────────────────

    def set_ws_manager(self, ws) -> None:
        self._ws_manager = ws

    def can_join(self) -> bool:
        return (self.status in (TableStatus.WAITING, TableStatus.PLAYING)
                and len(self.players) < self.max_players)

    # ── Joueurs ──────────────────────────────────────────────────────────────

    async def add_player(self, user, buy_in: int) -> bool:
        if not self.can_join():
            return False
        ps = PlayerState(
            user_id=user.id, username=user.username,
            avatar=getattr(user, 'avatar', None),
            chips=buy_in, position=len(self.players),
        )
        self.players[user.id] = ps
        logger.info(f"[{self.name}] {user.username} seated ({buy_in} chips)")
        if len([p for p in self.players.values() if p.chips > 0]) >= 2 and not self._game_task:
            await self.start_game()
        return True

    async def remove_player(self, uid: str) -> None:
        self.players.pop(uid, None)

    # ── Démarrage ────────────────────────────────────────────────────────────

    async def start_game(self) -> None:
        if self._game_task:
            return
        self.status = TableStatus.PLAYING
        self.game_state = GameState(
            table_id=self.id, status=GameStatus.IN_PROGRESS,
            round=0, players=[], time_bank=ACTION_TIMEOUT,
        )
        self._game_task = asyncio.create_task(self._game_loop())
        logger.info(f"[{self.name}] Game started ({len(self.players)} players)")

    # ── Boucle principale ────────────────────────────────────────────────────

    async def _game_loop(self) -> None:
        try:
            while self.game_state and self.game_state.status == GameStatus.IN_PROGRESS:
                active = [p for p in self.players.values() if p.chips > 0]
                if len(active) < 2:
                    if active:
                        logger.info(f"[{self.name}] Winner: {active[0].username}")
                    break
                await self._play_hand_pokerkit()
                self._save_state()
                await asyncio.sleep(PAUSE_BETWEEN_HANDS)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.name}] game_loop: {e}", exc_info=True)
        finally:
            if self.game_state:
                self.game_state.status = GameStatus.FINISHED
            self.status     = TableStatus.WAITING
            self._game_task = None
            self._save_state()

    # ── Main de poker (PokerKit) ──────────────────────────────────────────────

    async def _play_hand_pokerkit(self) -> None:
        active = [p for p in self.players.values() if p.chips > 0]
        if len(active) < 2:
            return

        self._hand_round     += 1
        self.game_state.round = self._hand_round
        self._dealer_btn      = self._hand_round % len(active)

        ordered          = active[self._dealer_btn:] + active[:self._dealer_btn]
        self._pk_uid_map = [p.user_id for p in ordered]
        stacks           = tuple(p.chips for p in ordered)

        # ── NOUVEAU : enregistrer les stacks avant la main (pour détecter gagnants) ──
        stacks_before: Dict[str, int] = {p.user_id: p.chips for p in self.players.values()}

        # SRA commit
        deck_preview = self._make_deck_preview()
        commitment   = self._deck_security.commit_deck(self._hand_round, deck_preview)

        # Reset marqueurs
        for p in self.players.values():
            p.hole_cards    = []
            p.current_bet   = 0
            p.total_bet     = 0
            p.is_dealer      = False
            p.is_small_blind = False
            p.is_big_blind   = False
            if p.chips > 0:
                p.status = PlayerStatus.ACTIVE

        ordered[0].is_dealer = True
        if len(ordered) == 2:
            ordered[0].is_small_blind = True
            ordered[1].is_big_blind   = True
        elif len(ordered) >= 3:
            ordered[1].is_small_blind = True
            ordered[2].is_big_blind   = True

        # PokerKit state
        try:
            self._pk_state = NoLimitTexasHoldem.create_state(
                AUTOMATIONS, True, 0,
                (self.small_blind, self.big_blind),
                self.big_blind, stacks, len(ordered),
                mode=Mode.TOURNAMENT,
            )
        except Exception as e:
            logger.error(f"[{self.name}] PokerKit create_state: {e}", exc_info=True)
            return

        pk = self._pk_state
        self._sync_pk(pk, ordered)
        await self._broadcast_state()

        # Broadcast SRA commitment
        if self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type':       'deck_commitment',
                'round':      self._hand_round,
                'commitment': commitment,
            })

        # ── Boucle d'action ──────────────────────────────────────────────────
        while pk.status and pk.actor_index is not None:
            actor_idx = pk.actor_index
            if actor_idx >= len(self._pk_uid_map):
                break

            actor_uid                = self._pk_uid_map[actor_idx]
            self._current_actor_uid  = actor_uid
            board_len                = len(pk.board_cards)
            self._street             = (
                'preflop' if board_len == 0 else
                'flop'    if board_len <= 3 else
                'turn'    if board_len == 4 else
                'river'
            )
            self._action_deadline = asyncio.get_event_loop().time() + ACTION_TIMEOUT

            self._sync_pk(pk, ordered)
            await self._broadcast_state()

            action = await self._wait_for_action(actor_uid, ACTION_TIMEOUT)
            try:
                self._apply_action(pk, actor_idx, action)
            except Exception as e:
                logger.error(f"[{self.name}] Action error {actor_uid}: {e}")
                try:
                    if pk.can_check_or_call(): pk.check_or_call()
                    elif pk.can_fold():        pk.fold()
                except Exception:
                    break

            self._sync_pk(pk, ordered)

        # ── Fin de la boucle d'action ────────────────────────────────────────

        self._current_actor_uid = None
        self._action_deadline   = None

        # Mettre à jour les chips depuis PokerKit
        for i, uid in enumerate(self._pk_uid_map):
            ps = self.players.get(uid)
            if ps and i < len(pk.stacks):
                ps.chips = int(pk.stacks[i])
                if ps.chips <= 0:
                    ps.status = PlayerStatus.ELIMINATED

        # ── NOUVEAU : calculer les gagnants (joueurs dont les chips ont augmenté) ──
        winners_info = []
        for uid, ps in self.players.items():
            gained = ps.chips - stacks_before.get(uid, 0)
            if gained > 0:
                winners_info.append({'user_id': uid, 'username': ps.username, 'gained': gained})

        # Pot final (somme de ce que les gagnants ont ramassé)
        final_pot = sum(w['gained'] for w in winners_info)
        winner_names = [w['username'] for w in winners_info]

        # Community cards finales (avant le nettoyage)
        final_community = [str(c) for c in pk.board_cards if c] if pk.board_cards else []

        # SRA reveal
        reveal = self._deck_security.reveal(self._hand_round)
        if reveal and self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type':       'deck_reveal',
                'round':      self._hand_round,
                'seed':       reveal['seed'],
                'deck_order': reveal['deck_order'],
                'commitment': reveal['hash'],
            })

        # ── NOUVEAU : broadcast hand_result ──────────────────────────────────
        if self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type':            'hand_result',
                'round':           self._hand_round,
                'winners':         winner_names,
                'winners_detail':  winners_info,
                'pot':             final_pot,
                'community_cards': final_community,
            })

        # Nettoyage
        for p in self.players.values():
            p.hole_cards     = []
            p.current_bet    = 0
            p.total_bet      = 0
            p.is_dealer      = False
            p.is_small_blind = False
            p.is_big_blind   = False

        self._pk_state = None
        self._street   = 'preflop'
        await self._broadcast_state()

        logger.info(
            f"[{self.name}] Hand #{self._hand_round} done — "
            f"winners: {winner_names} — pot: {final_pot}"
        )

    # ── Appliquer une action ──────────────────────────────────────────────────

    def _apply_action(self, pk, actor_idx: int, action) -> None:
        if action is None:
            # Timeout : auto-check si possible, sinon fold
            to_call = max(pk.bets) - pk.bets[actor_idx] if pk.bets else 0
            if to_call <= 0 and pk.can_check_or_call():
                pk.check_or_call()
            elif pk.can_fold():
                pk.fold()
            elif pk.can_check_or_call():
                pk.check_or_call()
        elif action.action == ActionType.FOLD:
            if pk.can_fold():           pk.fold()
            elif pk.can_check_or_call(): pk.check_or_call()
        elif action.action in (ActionType.CALL, ActionType.CHECK):
            if pk.can_check_or_call(): pk.check_or_call()
            elif pk.can_fold():        pk.fold()
        elif action.action in (ActionType.RAISE, ActionType.ALL_IN):
            if pk.can_complete_bet_or_raise_to():
                mn  = pk.min_completion_betting_or_raising_to_amount
                mx  = pk.max_completion_betting_or_raising_to_amount
                amt = max(mn, min(action.amount, mx))
                pk.complete_bet_or_raise_to(amt)
            elif pk.can_check_or_call(): pk.check_or_call()
            elif pk.can_fold():          pk.fold()

    # ── Synchronisation PokerKit → PlayerState ────────────────────────────────

    def _sync_pk(self, pk, ordered: List[PlayerState]) -> None:
        for i, ps in enumerate(ordered):
            if i < len(pk.stacks):
                ps.chips = int(pk.stacks[i])
            if i < len(pk.bets):
                ps.current_bet = int(pk.bets[i])
            if i < len(pk.hole_cards) and pk.hole_cards[i]:
                ps.hole_cards = [str(c) for c in pk.hole_cards[i] if c]
            if i < len(pk.statuses) and not pk.statuses[i]:
                ps.status = PlayerStatus.FOLDED

    # ── Attente d'action joueur ───────────────────────────────────────────────

    async def _wait_for_action(self, user_id: str, timeout: float):
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                req = await asyncio.wait_for(self._action_queue.get(), timeout=remaining)
                if req.user_id == user_id:
                    return req
            except asyncio.TimeoutError:
                return None

    async def handle_player_action(self, user_id: str, action, amount: int = 0) -> None:
        await self._action_queue.put(
            PlayerActionRequest(user_id=user_id, table_id=self.id, action=action, amount=amount)
        )

    # ── Broadcast ────────────────────────────────────────────────────────────

    async def _broadcast_state(self) -> None:
        if not self._ws_manager:
            return
        try:
            await self._ws_manager.broadcast_to_table(
                self.id, {'type': 'game_update', 'data': self.get_state()}
            )
        except Exception as e:
            logger.error(f"[{self.name}] broadcast: {e}")

    # ── État courant ──────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        pk           = self._pk_state
        players_data = [ps.to_dict() for ps in self.players.values()]
        community    = [str(c) for c in pk.board_cards if c] if pk and pk.board_cards else []

        pot = 0
        if pk:
            try:
                pot = int(pk.total_pot_amount)
            except Exception:
                pot = sum(int(b) for b in pk.bets) if pk.bets else 0

        timer = None
        if self._action_deadline:
            try:
                timer = max(0, int(self._action_deadline - asyncio.get_event_loop().time()))
            except Exception:
                pass

        min_raise = self.big_blind
        if pk and pk.actor_index is not None:
            try:
                mr = pk.min_completion_betting_or_raising_to_amount
                if mr:
                    min_raise = int(mr)
            except Exception:
                pass

        gs = self.game_state

        # ── NOUVEAU : ring status pour le widget deck côté frontend ──────────
        ring_status = 'idle'
        if self._deck_security.has_commitment(self._hand_round):
            ring_status = 'committed'

        return {
            'table_id':       self.id,
            'table_name':     self.name,
            'tournament_id':  self.tournament_id,
            'status':         gs.status.value if gs and hasattr(gs.status, 'value') else 'waiting',
            'round':          gs.round if gs else 0,
            'pot':            pot,
            'community_cards': community,
            'current_bet':    int(max(pk.bets)) if pk and pk.bets else 0,
            'current_player_index': gs.current_player_index if gs else 0,
            'current_actor':  self._current_actor_uid,
            'action_timer':   timer,
            'dealer_index':   gs.dealer_index if gs else 0,
            'players':        players_data,
            'min_raise':      min_raise,
            'max_players':    self.max_players,
            'small_blind':    self.small_blind,
            'big_blind':      self.big_blind,
            'betting_round':  self._street,
            'ring_status':    ring_status,           # ← nouveau
        }

    def get_info(self) -> Table:
        return Table(
            id=self.id, name=self.name, game_type=self.game_type,
            tournament_id=self.tournament_id, max_players=self.max_players,
            status=self.status,
            players=[ps.to_pydantic() for ps in self.players.values()],
            spectators=list(self.spectators),
        )

    async def close(self) -> None:
        if self._game_task:
            self._game_task.cancel()
        self._delete_state()

    # ── Deck helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_deck_preview() -> List[str]:
        """Génère et mélange un deck standard 52 cartes."""
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        suits = ['h', 'd', 'c', 's']
        deck  = [f"{r}{s}" for s in suits for r in ranks]
        random.shuffle(deck)
        return deck

    # Alias maintenu pour compatibilité avec code existant
    @staticmethod
    def _make_deck() -> List[str]:
        return PokerTable._make_deck_preview()

    # ── Persistance état ─────────────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            data = {
                'table_id':    self.id,
                'name':        self.name,
                'tournament_id': self.tournament_id,
                'small_blind': self.small_blind,
                'big_blind':   self.big_blind,
                'max_players': self.max_players,
                'hand_round':  self._hand_round,
                'dealer_btn':  self._dealer_btn,
                'status':      self.status.value if hasattr(self.status, 'value') else str(self.status),
                'players':     {
                    uid: {
                        'user_id':  ps.user_id,
                        'username': ps.username,
                        'avatar':   ps.avatar,
                        'chips':    ps.chips,
                        'position': ps.position,
                        'status':   ps.status.value if hasattr(ps.status, 'value') else str(ps.status),
                    }
                    for uid, ps in self.players.items()
                },
                'saved_at': datetime.utcnow().isoformat(),
            }
            with open(STATE_DIR / f"{self.id}.json", 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[{self.name}] save_state: {e}")

    def _delete_state(self) -> None:
        try:
            (STATE_DIR / f"{self.id}.json").unlink(missing_ok=True)
        except Exception:
            pass

    @classmethod
    def load_state(cls, table_id: str) -> Optional[dict]:
        p = STATE_DIR / f"{table_id}.json"
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"load_state {table_id}: {e}")
            return None
