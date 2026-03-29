# backend/game_engine.py
"""
Moteur de jeu poker — PokerKit + SRA Deck Security
===================================================
Version consolidée avec :
- Support Hold'em + PLO via PokerKit
- DeckSecurity commit-reveal avec persistance
- CSPRNG (secrets.SystemRandom) pour le shuffle
- Envoi per-player des hole cards
- Game loop résilient avec auto-restart
- Quick bet calculations (1BB, 2BB, 1/3pot, etc.)
- Fix _determine_winner, action_timer, community cards
"""

import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple

from pokerkit import NoLimitTexasHoldem, Automation, Mode

from .models import (
    Table, TablePlayer, GameState, GameStatus, TableStatus,
    PlayerStatus, ActionType, PlayerActionRequest, GameType, GameVariant,
)

logger = logging.getLogger(__name__)

ACTION_TIMEOUT = 20
PAUSE_BETWEEN_HANDS = 4
MAX_GAME_LOOP_ERRORS = 3

STATE_DIR = Path("data/table_states")
STATE_DIR.mkdir(parents=True, exist_ok=True)

COMMITMENT_DIR = Path("data/deck_commitments")
COMMITMENT_DIR.mkdir(parents=True, exist_ok=True)

# CSPRNG pour le mélange du deck
_CSPRNG = secrets.SystemRandom()

# Automations PokerKit — tout sauf les décisions joueurs
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


# ═══════════════════════════════════════════════════════════════════════════════
# SRA Deck Security — Commit-Reveal avec persistance
# ═══════════════════════════════════════════════════════════════════════════════

class DeckSecurity:
    """
    Commit-reveal + SRA verification avec persistance.
    Le serveur s'engage sur un seed AVANT de distribuer,
    puis le révèle après la main pour vérification côté client.
    """

    def __init__(self, table_id: str):
        self.table_id = table_id
        self._commitments: Dict[int, dict] = {}
        self._max_commitments = 200
        self._load_commitments()

    def _get_commitment_file(self) -> Path:
        return COMMITMENT_DIR / f"{self.table_id}.json"

    def _load_commitments(self):
        path = self._get_commitment_file()
        if path.exists():
            try:
                with open(path) as f:
                    raw = json.load(f)
                self._commitments = {int(k): v for k, v in raw.items()}
            except Exception as e:
                logger.error(f"[Table {self.table_id}] Load commitments: {e}")
                self._commitments = {}

    def _save_commitments(self):
        try:
            # Limiter le nombre de commitments stockés
            if len(self._commitments) > self._max_commitments:
                keys = sorted(self._commitments.keys())
                for k in keys[:-self._max_commitments]:
                    del self._commitments[k]
            with open(self._get_commitment_file(), 'w') as f:
                json.dump(self._commitments, f, indent=2)
        except Exception as e:
            logger.error(f"[Table {self.table_id}] Save commitments: {e}")

    def commit_deck(self, hand_round: int, deck: List[str]) -> str:
        seed = secrets.token_hex(32)
        deck_str = ','.join(deck)
        commitment = hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest()
        self._commitments[hand_round] = {
            'seed': seed,
            'hash': commitment,
            'deck_order': list(deck),
            'committed_at': datetime.utcnow().isoformat(),
        }
        self._save_commitments()
        logger.info(f"[Table {self.table_id}] Deck committed hand #{hand_round}: {commitment[:16]}…")
        return commitment

    def reveal(self, hand_round: int) -> Optional[dict]:
        data = self._commitments.get(hand_round)
        if data:
            data['revealed_at'] = datetime.utcnow().isoformat()
            self._save_commitments()
        return data

    def get_commitment(self, hand_round: int) -> Optional[str]:
        data = self._commitments.get(hand_round)
        return data['hash'] if data else None

    @staticmethod
    def verify(seed: str, deck_order: List[str], commitment_hash: str) -> bool:
        deck_str = ','.join(deck_order)
        expected = hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest()
        return expected == commitment_hash

    @staticmethod
    def sra_encrypt(card_val: int, key_e: int, modulus: int) -> int:
        return pow(card_val, key_e, modulus)

    @staticmethod
    def sra_decrypt(cipher: int, key_d: int, modulus: int) -> int:
        return pow(cipher, key_d, modulus)

    def cleanup(self):
        try:
            self._get_commitment_file().unlink(missing_ok=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# PlayerState (dataclass interne — pas Pydantic)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlayerState:
    user_id: str
    username: str
    avatar: Optional[str]
    chips: int
    position: int
    status: PlayerStatus = PlayerStatus.ACTIVE
    hole_cards: List[str] = field(default_factory=list)
    current_bet: int = 0
    total_bet: int = 0
    is_dealer: bool = False
    is_small_blind: bool = False
    is_big_blind: bool = False
    is_all_in: bool = False
    sat_at: datetime = field(default_factory=datetime.utcnow)
    last_action: Optional[str] = None

    def to_dict(self, hide_cards: bool = False) -> dict:
        return {
            'user_id': self.user_id,
            'username': self.username,
            'avatar': self.avatar,
            'chips': self.chips,
            'stack': self.chips,
            'position': self.position,
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'current_bet': self.current_bet,
            'bet': self.current_bet,
            'total_bet': self.total_bet,
            'hole_cards': [] if hide_cards else self.hole_cards,
            'is_dealer': self.is_dealer,
            'is_small_blind': self.is_small_blind,
            'is_big_blind': self.is_big_blind,
            'is_all_in': self.is_all_in,
            'last_action': self.last_action,
        }

    def to_pydantic(self) -> TablePlayer:
        return TablePlayer(
            user_id=self.user_id,
            username=self.username,
            avatar=self.avatar,
            position=self.position,
            status=self.status,
            current_bet=self.current_bet,
            total_bet=self.total_bet,
            hole_cards=self.hole_cards,
            is_dealer=self.is_dealer,
            is_small_blind=self.is_small_blind,
            is_big_blind=self.is_big_blind,
            sat_at=self.sat_at,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Quick Bet Calculator
# ═══════════════════════════════════════════════════════════════════════════════

class QuickBetCalculator:
    """Calcule les mises rapides : 1BB, 2BB, 1/3pot, 1/2pot, 3/4pot, pot, all-in"""

    @staticmethod
    def calculate(pot: int, big_blind: int, current_bet: int,
                  player_chips: int, min_raise: int) -> List[dict]:
        bets = []
        call_amount = current_bet  # montant à caller pour ce joueur

        # 1 BB
        bb_bet = max(big_blind, min_raise)
        if bb_bet <= player_chips:
            bets.append({'label': '1 BB', 'amount': bb_bet, 'key': '1bb'})

        # 2 BB
        bb2 = big_blind * 2
        if bb2 > bb_bet and bb2 <= player_chips:
            bets.append({'label': '2 BB', 'amount': bb2, 'key': '2bb'})

        # 1/3 Pot
        third_pot = max(pot // 3, min_raise)
        if third_pot <= player_chips and third_pot > bb2:
            bets.append({'label': '1/3 Pot', 'amount': third_pot, 'key': '1_3pot'})

        # 1/2 Pot
        half_pot = max(pot // 2, min_raise)
        if half_pot <= player_chips and half_pot > third_pot:
            bets.append({'label': '1/2 Pot', 'amount': half_pot, 'key': '1_2pot'})

        # 3/4 Pot
        three_q_pot = max(pot * 3 // 4, min_raise)
        if three_q_pot <= player_chips and three_q_pot > half_pot:
            bets.append({'label': '3/4 Pot', 'amount': three_q_pot, 'key': '3_4pot'})

        # Pot
        full_pot = max(pot, min_raise)
        if full_pot <= player_chips and full_pot > three_q_pot:
            bets.append({'label': 'Pot', 'amount': full_pot, 'key': 'pot'})

        # All-in (toujours disponible)
        if player_chips > 0:
            bets.append({'label': 'All-in', 'amount': player_chips, 'key': 'allin'})

        return bets


# ═══════════════════════════════════════════════════════════════════════════════
# PokerTable
# ═══════════════════════════════════════════════════════════════════════════════

class PokerTable:
    """
    Table de poker avec moteur PokerKit.
    Supporte Hold'em et PLO.
    Game loop résilient avec auto-restart.
    """

    def __init__(
        self,
        table_id: str,
        name: str,
        tournament_id: str,
        max_players: int = 9,
        small_blind: int = 5,
        big_blind: int = 10,
        game_variant: GameVariant = GameVariant.HOLDEM,
    ):
        self.id = table_id
        self.name = name
        self.game_type = GameType.TOURNAMENT
        self.game_variant = game_variant
        self.tournament_id = tournament_id
        self.max_players = max_players
        self.small_blind = small_blind
        self.big_blind = big_blind

        self.status = TableStatus.WAITING
        self.players: Dict[str, PlayerState] = {}
        self.spectators: Set[str] = set()

        self._pk_state = None          # PokerKit State
        self._deck: List[str] = []
        self._hand_round = 0
        self._dealer_btn = 0
        self._street = 'preflop'
        self._community_cards: List[str] = []
        self._pot = 0
        self._current_actor: Optional[str] = None
        self._min_raise = big_blind
        self._action_event = asyncio.Event()
        self._last_action: Optional[dict] = None
        self._action_timeout_remaining: Optional[float] = None

        self._game_task: Optional[asyncio.Task] = None
        self._game_loop_errors = 0
        self._ws_manager = None
        self._broadcast_lock = asyncio.Lock()

        self._deck_security = DeckSecurity(table_id)

    def set_ws_manager(self, ws_manager):
        self._ws_manager = ws_manager

    # ── Joueurs ───────────────────────────────────────────────────────────────

    def add_player(self, user_id: str, username: str, chips: int,
                   avatar: Optional[str] = None) -> bool:
        if user_id in self.players or len(self.players) >= self.max_players:
            return False
        pos = self._next_free_position()
        self.players[user_id] = PlayerState(
            user_id=user_id, username=username, avatar=avatar,
            chips=chips, position=pos,
        )
        logger.info(f"[{self.name}] {username} assis (pos {pos}, {chips} chips)")
        self._try_start_game()
        return True

    def remove_player(self, user_id: str):
        if user_id in self.players:
            del self.players[user_id]
        self.spectators.discard(user_id)

    def add_spectator(self, user_id: str):
        self.spectators.add(user_id)

    def _next_free_position(self) -> int:
        taken = {p.position for p in self.players.values()}
        for i in range(self.max_players):
            if i not in taken:
                return i
        return len(self.players)

    # ── Blinds (mise à jour par le tournoi) ───────────────────────────────────

    def update_blinds(self, small: int, big: int):
        self.small_blind = small
        self.big_blind = big
        self._min_raise = big

    # ── Démarrage ─────────────────────────────────────────────────────────────

    def _try_start_game(self):
        active = [p for p in self.players.values() if p.chips > 0]
        if len(active) >= 2 and not self._game_task:
            self._game_task = asyncio.create_task(self._game_loop())

    async def _game_loop(self):
        """Boucle de jeu résiliente avec auto-restart"""
        logger.info(f"[{self.name}] Game loop started")
        self.status = TableStatus.PLAYING
        self._game_loop_errors = 0

        try:
            while True:
                active = [p for p in self.players.values() if p.chips > 0]
                if len(active) < 2:
                    logger.info(f"[{self.name}] < 2 joueurs actifs, arrêt")
                    break

                try:
                    await self._play_hand()
                    self._game_loop_errors = 0
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._game_loop_errors += 1
                    logger.error(f"[{self.name}] Hand error ({self._game_loop_errors}/{MAX_GAME_LOOP_ERRORS}): {e}")
                    if self._game_loop_errors >= MAX_GAME_LOOP_ERRORS:
                        logger.error(f"[{self.name}] Too many errors, stopping game loop")
                        break
                    await asyncio.sleep(2)
                    continue

                await asyncio.sleep(PAUSE_BETWEEN_HANDS)

        except asyncio.CancelledError:
            logger.info(f"[{self.name}] Game loop cancelled")
        finally:
            self.status = TableStatus.WAITING
            self._game_task = None
            self._save_state()
            logger.info(f"[{self.name}] Game loop ended")

    # ── Main loop d'une main ──────────────────────────────────────────────────

    async def _play_hand(self):
        self._hand_round += 1
        active_players = [p for p in self.players.values()
                          if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]

        if len(active_players) < 2:
            return

        # Reset
        for p in self.players.values():
            p.current_bet = 0
            p.total_bet = 0
            p.hole_cards = []
            p.is_dealer = False
            p.is_small_blind = False
            p.is_big_blind = False
            p.is_all_in = False
            p.last_action = None
            if p.chips > 0 and p.status != PlayerStatus.ELIMINATED:
                p.status = PlayerStatus.ACTIVE
            elif p.status not in (PlayerStatus.ELIMINATED, PlayerStatus.SITTING_OUT):
                p.status = PlayerStatus.SITTING_OUT

        active_players = sorted(
            [p for p in self.players.values() if p.status == PlayerStatus.ACTIVE],
            key=lambda p: p.position,
        )
        n = len(active_players)
        if n < 2:
            return

        # Dealer button
        self._dealer_btn = self._dealer_btn % n
        dealer_idx = self._dealer_btn
        active_players[dealer_idx].is_dealer = True

        if n == 2:
            active_players[dealer_idx].is_small_blind = True
            active_players[(dealer_idx + 1) % n].is_big_blind = True
        else:
            active_players[(dealer_idx + 1) % n].is_small_blind = True
            active_players[(dealer_idx + 2) % n].is_big_blind = True

        # Mélanger le deck avec CSPRNG
        self._deck = self._make_deck()
        self._community_cards = []
        self._pot = 0
        self._street = 'preflop'
        self._current_actor = None

        # Commit deck (SRA)
        commitment = self._deck_security.commit_deck(self._hand_round, self._deck)
        await self._broadcast({
            'type': 'deck_commitment',
            'hand': self._hand_round,
            'hash': commitment,
        })

        # PokerKit state
        stacks = tuple(p.chips for p in active_players)

        # Créer l'état PokerKit selon la variante
        num_hole = 4 if self.game_variant == GameVariant.PLO else 2
        try:
            self._pk_state = NoLimitTexasHoldem.create_state(
                AUTOMATIONS,
                ante_trimming_status=True,
                raw_antes={-1: 0},
                raw_blinds_or_straddles=(self.small_blind, self.big_blind),
                min_bet=self.big_blind,
                raw_starting_stacks=stacks,
                player_count=n,
                mode=Mode.CASH_GAME,
            )
        except Exception as e:
            logger.error(f"[{self.name}] PokerKit create_state failed: {e}")
            raise

        # Distribuer les cartes — envoi per-player (sécurité)
        card_idx = 0
        for i, p in enumerate(active_players):
            cards = self._deck[card_idx:card_idx + num_hole]
            card_idx += num_hole
            p.hole_cards = cards
            # Envoyer uniquement au joueur concerné
            await self._send_to_player(p.user_id, {
                'type': 'hole_cards',
                'cards': cards,
                'hand': self._hand_round,
            })

        # Broadcast état initial (sans hole cards)
        await self._broadcast_state()

        # Boucle de betting
        streets = ['preflop', 'flop', 'turn', 'river']
        community_sizes = [0, 3, 1, 1]
        burn_offset = card_idx  # après les hole cards

        for street_idx, street_name in enumerate(streets):
            self._street = street_name

            # Community cards
            if street_idx > 0:
                num_cards = community_sizes[street_idx]
                burn_offset += 1  # burn card
                new_cards = self._deck[burn_offset:burn_offset + num_cards]
                burn_offset += num_cards
                self._community_cards.extend(new_cards)
                await self._broadcast({
                    'type': 'community_cards',
                    'cards': list(self._community_cards),
                    'street': street_name,
                })

            # Tour d'enchères
            still_active = [p for p in active_players
                           if p.status in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN)]
            non_allin = [p for p in still_active if p.status == PlayerStatus.ACTIVE]

            if len(non_allin) <= 1 and len(still_active) > 1:
                continue  # tout le monde all-in sauf 1

            if len(still_active) <= 1:
                break  # plus qu'un joueur

            # Reset bets for new street
            if street_idx > 0:
                for p in active_players:
                    p.current_bet = 0
                self._min_raise = self.big_blind

            await self._betting_round(active_players, street_name)

            # Check if only one player left
            active_non_folded = [p for p in active_players if p.status != PlayerStatus.FOLDED]
            if len(active_non_folded) <= 1:
                break

        # Showdown / déterminer le gagnant
        await self._determine_winner(active_players)

        # Reveal deck (SRA)
        reveal_data = self._deck_security.reveal(self._hand_round)
        if reveal_data:
            await self._broadcast({
                'type': 'deck_reveal',
                'hand': self._hand_round,
                'seed': reveal_data['seed'],
                'deck_order': reveal_data['deck_order'],
                'hash': reveal_data['hash'],
            })

        # Avancer le dealer
        self._dealer_btn = (self._dealer_btn + 1) % len(active_players)
        self._save_state()

    # ── Betting round ─────────────────────────────────────────────────────────

    async def _betting_round(self, players: List[PlayerState], street: str):
        active = [p for p in players if p.status == PlayerStatus.ACTIVE]
        if len(active) <= 1:
            return

        n = len(players)
        # Déterminer le premier à parler
        if street == 'preflop':
            # Après le big blind
            bb_idx = next((i for i, p in enumerate(players) if p.is_big_blind), 0)
            start = (bb_idx + 1) % n
        else:
            # Après le dealer
            d_idx = next((i for i, p in enumerate(players) if p.is_dealer), 0)
            start = (d_idx + 1) % n

        last_raiser = None
        current_bet = max(p.current_bet for p in players) if players else 0
        acted = set()
        max_rounds = n * 4  # éviter boucle infinie
        rounds = 0

        idx = start
        while rounds < max_rounds:
            rounds += 1
            p = players[idx % n]
            idx += 1

            if p.status in (PlayerStatus.FOLDED, PlayerStatus.ALL_IN, PlayerStatus.ELIMINATED,
                           PlayerStatus.SITTING_OUT, PlayerStatus.DISCONNECTED):
                if p.user_id in acted or p.status != PlayerStatus.ACTIVE:
                    # Check si tour terminé
                    remaining = [x for x in players if x.status == PlayerStatus.ACTIVE]
                    if all(x.user_id in acted for x in remaining):
                        break
                    continue
                continue

            # Si tout le monde a agi et personne n'a relancé
            if p.user_id in acted and (last_raiser is None or last_raiser == p.user_id):
                break
            if p.user_id == last_raiser and p.user_id in acted:
                break

            # Calculer les actions possibles
            to_call = current_bet - p.current_bet
            can_check = (to_call == 0)
            can_call = (to_call > 0 and to_call < p.chips)
            can_raise = (p.chips > to_call)

            # Quick bets
            quick_bets = QuickBetCalculator.calculate(
                pot=self._pot + sum(x.current_bet for x in players),
                big_blind=self.big_blind,
                current_bet=to_call,
                player_chips=p.chips,
                min_raise=self._min_raise,
            )

            self._current_actor = p.user_id
            self._action_event.clear()

            await self._broadcast_state(quick_bets=quick_bets)

            # Attendre l'action avec timeout
            try:
                action, amount = await asyncio.wait_for(
                    self._wait_for_action(p.user_id),
                    timeout=ACTION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                # Auto-fold/check sur timeout
                if can_check:
                    action, amount = ActionType.CHECK, 0
                    p.last_action = 'check (timeout)'
                else:
                    action, amount = ActionType.FOLD, 0
                    p.last_action = 'fold (timeout)'
                logger.info(f"[{self.name}] {p.username} timeout → {p.last_action}")

            # Appliquer l'action
            if action == ActionType.FOLD:
                p.status = PlayerStatus.FOLDED
                p.last_action = 'fold'
                await self._broadcast({
                    'type': 'player_action',
                    'user_id': p.user_id,
                    'action': 'fold',
                    'amount': 0,
                })

            elif action == ActionType.CHECK:
                p.last_action = 'check'
                await self._broadcast({
                    'type': 'player_action',
                    'user_id': p.user_id,
                    'action': 'check',
                    'amount': 0,
                })

            elif action == ActionType.CALL:
                call_amt = min(to_call, p.chips)
                p.chips -= call_amt
                p.current_bet += call_amt
                p.total_bet += call_amt
                self._pot += call_amt
                if p.chips == 0:
                    p.status = PlayerStatus.ALL_IN
                    p.is_all_in = True
                p.last_action = 'call'
                await self._broadcast({
                    'type': 'player_action',
                    'user_id': p.user_id,
                    'action': 'call',
                    'amount': call_amt,
                })

            elif action in (ActionType.RAISE, ActionType.ALL_IN):
                if action == ActionType.ALL_IN:
                    amount = p.chips

                raise_amt = max(amount, self._min_raise)
                raise_amt = min(raise_amt, p.chips)
                p.chips -= raise_amt
                p.current_bet += raise_amt
                p.total_bet += raise_amt
                self._pot += raise_amt
                current_bet = p.current_bet
                self._min_raise = max(self._min_raise, raise_amt - to_call)
                last_raiser = p.user_id
                acted = {p.user_id}  # reset : tout le monde doit reagir

                if p.chips == 0:
                    p.status = PlayerStatus.ALL_IN
                    p.is_all_in = True
                p.last_action = 'raise' if action == ActionType.RAISE else 'all-in'
                await self._broadcast({
                    'type': 'player_action',
                    'user_id': p.user_id,
                    'action': p.last_action,
                    'amount': raise_amt,
                })

            acted.add(p.user_id)
            self._current_actor = None

            # Vérifier fin du tour
            remaining = [x for x in players if x.status == PlayerStatus.ACTIVE]
            if len(remaining) <= 1:
                break
            if all(x.user_id in acted for x in remaining) and last_raiser is None:
                break
            # Si le raiser est le seul à ne pas avoir agi et tout le monde a agi
            if last_raiser and all(x.user_id in acted for x in remaining):
                break

        self._current_actor = None

    async def _wait_for_action(self, user_id: str) -> Tuple[ActionType, int]:
        """Attend l'action d'un joueur"""
        while True:
            await self._action_event.wait()
            self._action_event.clear()
            if self._last_action and self._last_action.get('user_id') == user_id:
                return (
                    ActionType(self._last_action['action']),
                    self._last_action.get('amount', 0),
                )

    async def handle_player_action(self, user_id: str, action: ActionType, amount: int = 0):
        """API publique — reçoit l'action d'un joueur"""
        if self._current_actor != user_id:
            raise ValueError("Not your turn")
        self._last_action = {
            'user_id': user_id,
            'action': action.value,
            'amount': amount,
        }
        self._action_event.set()

    # ── Showdown ──────────────────────────────────────────────────────────────

    async def _determine_winner(self, players: List[PlayerState]):
        """Détermine le(s) gagnant(s) et distribue le pot"""
        non_folded = [p for p in players if p.status != PlayerStatus.FOLDED]

        if len(non_folded) == 1:
            winner = non_folded[0]
            winner.chips += self._pot
            await self._broadcast({
                'type': 'hand_result',
                'winners': [{'user_id': winner.user_id, 'username': winner.username,
                            'amount': self._pot, 'hand': 'Last standing'}],
                'pot': self._pot,
                'community_cards': self._community_cards,
            })
            return

        # Évaluation des mains avec PokerKit
        # Pour simplifier on compare les mains manuellement
        # (le state PokerKit n'est pas toujours synchronisé dans notre boucle custom)
        from pokerkit import StandardHighHand, Card as PKCard

        best_hands = []
        for p in non_folded:
            try:
                all_cards = p.hole_cards + self._community_cards
                pk_cards = []
                for c in all_cards:
                    rank_map = {'T': '10', 'J': 'J', 'Q': 'Q', 'K': 'K', 'A': 'A'}
                    rank_str = rank_map.get(c[0], c[0])
                    suit_str = c[1]
                    pk_cards.append(PKCard(c))

                if self.game_variant == GameVariant.PLO:
                    # PLO : exactement 2 des 4 hole cards + 3 du board
                    from itertools import combinations
                    best = None
                    for hole_combo in combinations(range(len(p.hole_cards)), 2):
                        for board_combo in combinations(range(len(self._community_cards)), 3):
                            combo = [PKCard(p.hole_cards[i]) for i in hole_combo] + \
                                    [PKCard(self._community_cards[i]) for i in board_combo]
                            hand = StandardHighHand.from_game(combo)
                            if best is None or hand > best:
                                best = hand
                    best_hands.append((p, best))
                else:
                    # Hold'em : meilleure main de 5 parmi 7
                    from itertools import combinations
                    best = None
                    for combo in combinations([PKCard(c) for c in all_cards], 5):
                        hand = StandardHighHand.from_game(combo)
                        if best is None or hand > best:
                            best = hand
                    best_hands.append((p, best))
            except Exception as e:
                logger.error(f"[{self.name}] Hand eval error for {p.username}: {e}")
                best_hands.append((p, None))

        # Trier par force de main (descending)
        best_hands.sort(key=lambda x: x[1] if x[1] else 0, reverse=True)

        if best_hands:
            winning_hand = best_hands[0][1]
            winners = [ph for ph, h in best_hands if h == winning_hand]
            share = self._pot // len(winners)
            remainder = self._pot % len(winners)

            for i, w in enumerate(winners):
                w.chips += share + (1 if i < remainder else 0)

            # Broadcast showdown
            showdown_data = []
            for p in non_folded:
                showdown_data.append({
                    'user_id': p.user_id,
                    'username': p.username,
                    'hole_cards': p.hole_cards,
                })

            await self._broadcast({
                'type': 'hand_result',
                'winners': [{'user_id': w.user_id, 'username': w.username,
                            'amount': share, 'hand': str(winning_hand) if winning_hand else '?'}
                           for w in winners],
                'pot': self._pot,
                'community_cards': self._community_cards,
                'showdown': showdown_data,
            })

    # ── État ──────────────────────────────────────────────────────────────────

    def get_state(self, for_user_id: Optional[str] = None) -> dict:
        players_data = []
        for uid, ps in self.players.items():
            hide = (for_user_id is None or uid != for_user_id)
            players_data.append(ps.to_dict(hide_cards=hide))

        return {
            'table_id': self.id,
            'name': self.name,
            'game_variant': self.game_variant.value if hasattr(self.game_variant, 'value') else str(self.game_variant),
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'round': self._hand_round,
            'pot': self._pot,
            'community_cards': self._community_cards,
            'current_actor': self._current_actor,
            'action_timer': self._action_timeout_remaining,
            'action_timeout_total': ACTION_TIMEOUT,
            'min_raise': self._min_raise,
            'players': players_data,
            'spectators': list(self.spectators),
            'dealer_btn': self._dealer_btn,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'betting_round': self._street,
            'max_players': self.max_players,
        }

    def get_info(self) -> Table:
        return Table(
            id=self.id, name=self.name, game_type=self.game_type,
            game_variant=self.game_variant,
            tournament_id=self.tournament_id, max_players=self.max_players,
            status=self.status,
            players=[ps.to_pydantic() for ps in self.players.values()],
            spectators=list(self.spectators),
        )

    # ── Communication ─────────────────────────────────────────────────────────

    async def _broadcast(self, message: dict):
        if not self._ws_manager:
            return
        async with self._broadcast_lock:
            try:
                await self._ws_manager.broadcast_to_table(self.id, message)
            except Exception as e:
                logger.error(f"[{self.name}] Broadcast error: {e}")

    async def _broadcast_state(self, quick_bets: Optional[List[dict]] = None):
        """Broadcast l'état — envoie les hole_cards uniquement au joueur concerné"""
        if not self._ws_manager:
            return
        async with self._broadcast_lock:
            for uid in list(self.players.keys()) | self.spectators:
                is_player = uid in self.players
                state = self.get_state(for_user_id=uid if is_player else None)
                msg = {'type': 'game_update', 'data': state}
                if quick_bets and uid == self._current_actor:
                    msg['quick_bets'] = quick_bets
                try:
                    await self._ws_manager.send_to_user(self.id, uid, msg)
                except Exception:
                    pass

    async def _send_to_player(self, user_id: str, message: dict):
        if not self._ws_manager:
            return
        try:
            await self._ws_manager.send_to_user(self.id, user_id, message)
        except Exception as e:
            logger.error(f"[{self.name}] Send to {user_id} failed: {e}")

    # ── Utilitaires ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_deck() -> List[str]:
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        suits = ['h', 'd', 'c', 's']
        deck = [f"{r}{s}" for s in suits for r in ranks]
        _CSPRNG.shuffle(deck)
        return deck

    def _save_state(self):
        try:
            data = {
                'table_id': self.id, 'name': self.name,
                'tournament_id': self.tournament_id,
                'game_variant': self.game_variant.value,
                'small_blind': self.small_blind, 'big_blind': self.big_blind,
                'max_players': self.max_players,
                'hand_round': self._hand_round, 'dealer_btn': self._dealer_btn,
                'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
                'players': {
                    uid: {
                        'user_id': ps.user_id, 'username': ps.username,
                        'avatar': ps.avatar, 'chips': ps.chips,
                        'position': ps.position,
                        'status': ps.status.value if hasattr(ps.status, 'value') else str(ps.status),
                    }
                    for uid, ps in self.players.items()
                },
                'saved_at': datetime.utcnow().isoformat(),
            }
            with open(STATE_DIR / f"{self.id}.json", 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[{self.name}] save_state: {e}")

    def _delete_state(self):
        try:
            (STATE_DIR / f"{self.id}.json").unlink(missing_ok=True)
        except Exception:
            pass

    async def close(self):
        if self._game_task:
            self._game_task.cancel()
            try:
                await self._game_task
            except asyncio.CancelledError:
                pass
        self._deck_security.cleanup()
        self._delete_state()
        logger.info(f"[{self.name}] Table closed")

    @classmethod
    def load_state(cls, table_id: str) -> Optional[dict]:
        path = STATE_DIR / f"{table_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"load_state {table_id}: {e}")
            return None
