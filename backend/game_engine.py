# backend/game_engine.py
"""
Moteur de jeu poker — PokerKit + SRA Deck Security
===================================================
Version consolidée avec corrections :
- get_state sans doublon
- Sauvegarde de l'historique des mains
- Redémarrage automatique après crash
- Affichage correct des cartes et des mises
- PokerKit pour l'évaluation des mains
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

from pokerkit import NoLimitTexasHoldem, PotLimitOmahaHoldem, Automation, Mode
from pokerkit import StandardHighHand, OmahaHoldemHand, Card, Deck

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

HISTORY_DIR = Path("data/hand_history")
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

_CSPRNG = secrets.SystemRandom()

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
# PlayerState (dataclass interne)
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
    @staticmethod
    def calculate(pot: int, big_blind: int, current_bet: int,
                  player_chips: int, min_raise: int) -> List[dict]:
        bets = []
        call_amount = current_bet

        bb_bet = max(big_blind, min_raise)
        if bb_bet <= player_chips:
            bets.append({'label': '1 BB', 'amount': bb_bet, 'key': '1bb'})

        bb2 = big_blind * 2
        if bb2 > bb_bet and bb2 <= player_chips:
            bets.append({'label': '2 BB', 'amount': bb2, 'key': '2bb'})

        third_pot = max(pot // 3, min_raise)
        if third_pot <= player_chips and third_pot > bb2:
            bets.append({'label': '1/3 Pot', 'amount': third_pot, 'key': '1_3pot'})

        half_pot = max(pot // 2, min_raise)
        if half_pot <= player_chips and half_pot > third_pot:
            bets.append({'label': '1/2 Pot', 'amount': half_pot, 'key': '1_2pot'})

        three_q_pot = max(pot * 3 // 4, min_raise)
        if three_q_pot <= player_chips and three_q_pot > half_pot:
            bets.append({'label': '3/4 Pot', 'amount': three_q_pot, 'key': '3_4pot'})

        full_pot = max(pot, min_raise)
        if full_pot <= player_chips and full_pot > three_q_pot:
            bets.append({'label': 'Pot', 'amount': full_pot, 'key': 'pot'})

        if player_chips > 0:
            bets.append({'label': 'All-in', 'amount': player_chips, 'key': 'allin'})

        return bets


# ═══════════════════════════════════════════════════════════════════════════════
# PokerTable
# ═══════════════════════════════════════════════════════════════════════════════

class PokerTable:
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
        self.ante = 0

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

    # ── Joueurs ───────────────────────────────────────────────────────────────
    def set_ws_manager(self, ws_manager):
        self._ws_manager = ws_manager

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
    def update_blinds(self, small: int, big: int, ante: int = 0):
        self.small_blind = small
        self.big_blind = big
        self.ante = ante
        self._min_raise = big

    # ── Démarrage ─────────────────────────────────────────────────────────────
    def _try_start_game(self):
        active = [p for p in self.players.values() if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]
        if len(active) >= 2 and not self._game_task:
            logger.info(f"[{self.name}] Starting game loop with {len(active)} players")
            self._game_task = asyncio.create_task(self._game_loop())
        elif len(active) < 2:
            logger.debug(f"[{self.name}] Not enough players: {len(active)}/2")

    # ── Game Loop ────────────────────────────────────────────────────────────
    async def _game_loop(self):
        logger.info(f"[{self.name}] Game loop started")
        self.status = TableStatus.PLAYING
        self._game_loop_errors = 0

        try:
            while True:
                active = [p for p in self.players.values()
                          if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]

                if len(active) < 2:
                    logger.info(f"[{self.name}] < 2 joueurs actifs, arrêt")
                    break

                # Vérifier si le tournoi est en pause
                if self.tournament_id and self._ws_manager and self._ws_manager._tournament_manager:
                    tm = self._ws_manager._tournament_manager
                    tournament = tm.get_tournament(self.tournament_id)
                    if tournament:
                        while tournament.status == 'paused':
                            await self._broadcast({
                                'type': 'tournament_paused',
                                'message': 'Tournoi en pause…',
                            })
                            await asyncio.sleep(5)
                            tournament = tm.get_tournament(self.tournament_id)
                            if not tournament:
                                break
                        if tournament and tournament.status == 'finished':
                            break

                try:
                    await self._play_hand()
                    self._game_loop_errors = 0
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._game_loop_errors += 1
                    logger.error(f"[{self.name}] Hand error ({self._game_loop_errors}/{MAX_GAME_LOOP_ERRORS}): {e}", exc_info=True)
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

    # ── Main d'une main ──────────────────────────────────────────────────────
    async def _play_hand(self):
        self._hand_round += 1

        # Récupérer les joueurs actifs (avec chips)
        players = [p for p in self.players.values() if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]
        if len(players) < 2:
            return

        # Réinitialiser les statuts des joueurs
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

        # Filtrer les actifs et trier par position
        active_players = sorted(
            [p for p in self.players.values() if p.status == PlayerStatus.ACTIVE],
            key=lambda p: p.position
        )
        self._active_players = active_players  # utilisé pour le timer

        if len(active_players) < 2:
            return

        n = len(active_players)
        self._dealer_btn = self._dealer_btn % n
        dealer_idx = self._dealer_btn
        active_players[dealer_idx].is_dealer = True

        # Définir SB et BB
        if n == 2:
            active_players[dealer_idx].is_small_blind = True
            active_players[(dealer_idx + 1) % n].is_big_blind = True
        else:
            active_players[(dealer_idx + 1) % n].is_small_blind = True
            active_players[(dealer_idx + 2) % n].is_big_blind = True

        # Poster les antes
        self._pot = 0
        if self.ante > 0:
            for p in active_players:
                ante_amt = min(self.ante, p.chips)
                if ante_amt > 0:
                    p.chips -= ante_amt
                    p.total_bet += ante_amt
                    self._pot += ante_amt
                    if p.chips == 0:
                        p.status = PlayerStatus.ALL_IN
                        p.is_all_in = True
                    await self._broadcast({
                        'type': 'player_action',
                        'user_id': p.user_id, 'username': p.username,
                        'action': 'ante', 'amount': ante_amt,
                    })

        # Poster les blinds
        for p in active_players:
            if p.is_small_blind:
                sb_amt = min(self.small_blind, p.chips)
                if sb_amt > 0:
                    p.chips -= sb_amt
                    p.current_bet = sb_amt
                    p.total_bet += sb_amt
                    self._pot += sb_amt
                    if p.chips == 0:
                        p.status = PlayerStatus.ALL_IN
                        p.is_all_in = True
                    await self._broadcast({
                        'type': 'player_action',
                        'user_id': p.user_id, 'username': p.username,
                        'action': 'small_blind', 'amount': sb_amt,
                    })
            elif p.is_big_blind:
                bb_amt = min(self.big_blind, p.chips)
                if bb_amt > 0:
                    p.chips -= bb_amt
                    p.current_bet = bb_amt
                    p.total_bet += bb_amt
                    self._pot += bb_amt
                    if p.chips == 0:
                        p.status = PlayerStatus.ALL_IN
                        p.is_all_in = True
                    await self._broadcast({
                        'type': 'player_action',
                        'user_id': p.user_id, 'username': p.username,
                        'action': 'big_blind', 'amount': bb_amt,
                    })

        # Mélanger le deck
        self._deck = self._make_deck()

        # Commit deck
        commitment = self._deck_security.commit_deck(self._hand_round, self._deck)
        await self._broadcast({
            'type': 'deck_commitment',
            'hand': self._hand_round,
            'hash': commitment,
        })

        # Distribuer les hole cards
        num_hole = 4 if self.game_variant == GameVariant.PLO else 2
        deck_idx = 0
        for p in active_players:
            cards = self._deck[deck_idx:deck_idx + num_hole]
            deck_idx += num_hole
            p.hole_cards = [f"{c[0]}{c[1]}" for c in cards]
            await self._send_to_player(p.user_id, {
                'type': 'hole_cards',
                'cards': p.hole_cards,
                'hand': self._hand_round,
            })

        # Broadcast état initial
        await self._broadcast_state()

        # Fonctions utilitaires pour distribuer les cartes communautaires


        async def _distribute_community(count: int):
            nonlocal deck_idx
            # Burn card
            if deck_idx < len(self._deck):
                deck_idx += 1
            cards = self._deck[deck_idx:deck_idx + count]
            deck_idx += count
            self._community_cards.extend([f"{c[0]}{c[1]}" for c in cards])
            self._street = self._get_street_name(len(self._community_cards))
            # FIX#11 — await au lieu de create_task
            await self._broadcast({
                'type': 'community_cards',
                'cards': self._community_cards,
            })
            await self._broadcast_state()

        def active_count(p_list):
            return sum(1 for p in p_list if p.status == PlayerStatus.ACTIVE and p.chips > 0)

        # Tour d’enchères préflop
        await self._betting_round(active_players, 'preflop')
        if active_count(active_players) <= 1:
            winners = await self._resolve_hand(active_players)
            self._save_hand_history(self._hand_round, active_players, winners, self._community_cards, self._pot)
            await self._cleanup_hand(active_players)
            return

        # Flop
        await _distribute_community(3)
        await self._betting_round(active_players, 'flop')
        if active_count(active_players) <= 1:
            winners = await self._resolve_hand(active_players)
            self._save_hand_history(self._hand_round, active_players, winners, self._community_cards, self._pot)
            await self._cleanup_hand(active_players)
            return

        # Turn
        await _distribute_community(1)
        await self._betting_round(active_players, 'turn')
        if active_count(active_players) <= 1:
            winners = await self._resolve_hand(active_players)
            self._save_hand_history(self._hand_round, active_players, winners, self._community_cards, self._pot)
            await self._cleanup_hand(active_players)
            return

        # River
        await _distribute_community(1)
        await self._betting_round(active_players, 'river')
        if active_count(active_players) <= 1:
            winners = await self._resolve_hand(active_players)
            self._save_hand_history(self._hand_round, active_players, winners, self._community_cards, self._pot)
            await self._cleanup_hand(active_players)
            return

        # Showdown avec PokerKit
        winners = await self._determine_winner_with_pokerkit(active_players)
        self._save_hand_history(self._hand_round, active_players, winners, self._community_cards, self._pot)

        # Nettoyage
        await self._cleanup_hand(active_players)

    # ── Betting Round ────────────────────────────────────────────────────────
 

    async def _betting_round(self, players: List[PlayerState], street: str):
        logger.info(f"[{self.name}] ===== BETTING ROUND: {street} =====")
 
        acting = [p for p in players if p.status == PlayerStatus.ACTIVE and p.chips > 0]
        if len(acting) <= 1:
            return
 
        n = len(players)
 
        # Déterminer le premier à parler
        if street == 'preflop':
            bb_idx = next((i for i, p in enumerate(players) if p.is_big_blind), 0)
            first = (bb_idx + 1) % n
        else:
            d_idx = next((i for i, p in enumerate(players) if p.is_dealer), 0)
            first = (d_idx + 1) % n
 
        # Avancer vers le prochain joueur actif
        attempts = 0
        while players[first].status != PlayerStatus.ACTIVE or players[first].chips <= 0:
            first = (first + 1) % n
            attempts += 1
            if attempts >= n:
                return  # Personne ne peut agir
 
        current_bet = max(p.current_bet for p in players) if players else 0
 
        # Set de joueurs qui doivent encore agir dans cette orbite
        # Au départ, tout le monde. Quand quelqu'un raise, on reset.
        must_act = set()
        for p in players:
            if p.status == PlayerStatus.ACTIVE and p.chips > 0:
                must_act.add(p.user_id)
 
        pos = first
        max_iterations = n * 6  # garde-fou absolu
        iterations = 0
 
        while must_act and iterations < max_iterations:
            iterations += 1
            p = players[pos % n]
 
            if p.status != PlayerStatus.ACTIVE or p.chips <= 0:
                must_act.discard(p.user_id)
                pos += 1
                continue
 
            if p.user_id not in must_act:
                pos += 1
                # Vérifier si on a fait un tour complet
                if pos % n == first:
                    break
                continue
 
            to_call = current_bet - p.current_bet
            can_check = (to_call == 0)
 
            # Quick bets
            quick_bets = QuickBetCalculator.calculate(
                pot=self._pot + sum(x.current_bet for x in players),
                big_blind=self.big_blind,
                current_bet=to_call,
                player_chips=p.chips,
                min_raise=self._min_raise,
            )
 
            self._current_actor = p.user_id
            await self._broadcast_state(quick_bets=quick_bets)
 
            action, amount = await self._get_player_action(p, can_check)
            was_raise = await self._apply_action(p, action, amount, to_call, players)
 
            # Retirer ce joueur de must_act (il a agi)
            must_act.discard(p.user_id)
 
            if was_raise:
                current_bet = p.current_bet
                # Tout le monde doit re-agir sauf le raiser
                must_act = set()
                for pp in players:
                    if (pp.status == PlayerStatus.ACTIVE and pp.chips > 0
                            and pp.user_id != p.user_id):
                        must_act.add(pp.user_id)
 
            self._current_actor = None
 
            # Vérifier s'il reste assez de joueurs
            remaining = [x for x in players if x.status == PlayerStatus.ACTIVE and x.chips > 0]
            if len(remaining) <= 1:
                break
 
            pos += 1
 
        self._current_actor = None
        logger.info(f"[{self.name}] ===== BETTING ROUND END ===== (pot={self._pot})")

    async def _apply_action(self, p: PlayerState, action: ActionType, amount: int,
                            to_call: int, players: List[PlayerState]) -> bool:
        logger.info(f"[{self.name}] Applying action: {p.username} {action.value} amount={amount} to_call={to_call}")

        if action == ActionType.FOLD:
            p.status = PlayerStatus.FOLDED
            p.last_action = 'fold'
            await self._broadcast({
                'type': 'player_action', 'user_id': p.user_id,
                'username': p.username, 'action': 'fold', 'amount': 0,
            })
            return False

        elif action == ActionType.CHECK:
            p.last_action = 'check'
            await self._broadcast({
                'type': 'player_action', 'user_id': p.user_id,
                'username': p.username, 'action': 'check', 'amount': 0,
            })
            return False

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
                'type': 'player_action', 'user_id': p.user_id,
                'username': p.username, 'action': 'call', 'amount': call_amt,
            })
            return False

        elif action in (ActionType.RAISE, ActionType.ALL_IN):
            if action == ActionType.ALL_IN:
                amount = p.chips

            raise_amt = max(amount, self._min_raise)
            raise_amt = min(raise_amt, p.chips)

            if self.game_variant == GameVariant.PLO:
                pot_total = self._pot + sum(x.current_bet for x in players)
                pot_limit_max = pot_total + to_call + to_call
                raise_amt = min(raise_amt, pot_limit_max)

            if raise_amt <= 0:
                p.last_action = 'check'
                await self._broadcast({
                    'type': 'player_action', 'user_id': p.user_id,
                    'username': p.username, 'action': 'check', 'amount': 0,
                })
                return False

            p.chips -= raise_amt
            p.current_bet += raise_amt
            p.total_bet += raise_amt
            self._pot += raise_amt

            self._min_raise = max(self._min_raise, raise_amt - to_call)

            if p.chips == 0:
                p.status = PlayerStatus.ALL_IN
                p.is_all_in = True

            p.last_action = 'raise' if action == ActionType.RAISE else 'all-in'
            await self._broadcast({
                'type': 'player_action', 'user_id': p.user_id,
                'username': p.username, 'action': p.last_action, 'amount': raise_amt,
            })
            return True

        return False

    def _get_street_name(self, card_count: int) -> str:
        if card_count == 0:
            return 'preflop'
        elif card_count == 3:
            return 'flop'
        elif card_count == 4:
            return 'turn'
        elif card_count == 5:
            return 'river'
        return 'preflop'

    async def _resolve_hand(self, players: List[PlayerState]) -> List[dict]:
        active = [p for p in players if p.status == PlayerStatus.ACTIVE and p.chips > 0]
        if len(active) == 1:
            winner = active[0]
            winner.chips += self._pot
            winners_data = [{
                'user_id': winner.user_id,
                'username': winner.username,
                'amount': self._pot,
                'hand': 'Last standing'
            }]
            await self._broadcast({
                'type': 'hand_result',
                'winners': winners_data,
                'pot': self._pot,
                'community_cards': self._community_cards,
            })
        else:
            winners_data = []
            share = self._pot // len(active) if active else 0
            for p in active:
                p.chips += share
                winners_data.append({
                    'user_id': p.user_id,
                    'username': p.username,
                    'amount': share,
                    'hand': '?'
                })
            await self._broadcast({
                'type': 'hand_result',
                'winners': winners_data,
                'pot': self._pot,
                'community_cards': self._community_cards,
            })
        self._pot = 0
        return winners_data

    async def _determine_winner_with_pokerkit(self, players: List[PlayerState]) -> List[dict]:
        def to_pokerkit_card(card_str: str):
            rank = card_str[0]
            suit = card_str[1]
            return Card.from_str(f"{rank}{suit}")

        hole_cards = [list(map(to_pokerkit_card, p.hole_cards)) for p in players]
        board_cards = list(map(to_pokerkit_card, self._community_cards))

        if self.game_variant == GameVariant.PLO:
            hand_type = OmahaHoldemHand
        else:
            hand_type = StandardHighHand

        hands = []
        for hole, board in zip(hole_cards, [board_cards] * len(players)):
            try:
                hole_str = ' '.join(str(card) for card in hole)
                board_str = ' '.join(str(card) for card in board)
                hand = hand_type.from_game(hole_str, board_str)
                hands.append(hand)
            except Exception as e:
                logger.error(f"[{self.name}] Hand eval error: {e}")
                hands.append(None)

        best_hand = None
        best_index = -1
        for i, hand in enumerate(hands):
            if hand is None:
                continue
            if best_hand is None or hand > best_hand:
                best_hand = hand
                best_index = i

        if best_hand is not None:
            active_indices = [i for i, p in enumerate(players) if p.status != PlayerStatus.FOLDED]
            winners = [i for i in active_indices if hands[i] == best_hand]
            amount = self._pot // len(winners)
            remainder = self._pot % len(winners)
            winners_data = []
            for idx, i in enumerate(winners):
                player = players[i]
                won = amount + (1 if idx < remainder else 0)
                player.chips += won
                winners_data.append({
                    'user_id': player.user_id,
                    'username': player.username,
                    'amount': won,
                    'hand': str(hands[i]),
                })
            await self._broadcast({
                'type': 'hand_result',
                'winners': winners_data,
                'pot': self._pot,
                'community_cards': self._community_cards,
                'showdown': [{'user_id': p.user_id, 'username': p.username, 'hole_cards': p.hole_cards} for p in players if p.status != PlayerStatus.FOLDED],
            })
        else:
            active = [p for p in players if p.status != PlayerStatus.FOLDED]
            share = self._pot // len(active) if active else 0
            winners_data = []
            for p in active:
                p.chips += share
                winners_data.append({
                    'user_id': p.user_id,
                    'username': p.username,
                    'amount': share,
                    'hand': '?',
                })
            await self._broadcast({
                'type': 'hand_result',
                'winners': winners_data,
                'pot': self._pot,
                'community_cards': self._community_cards,
            })
        self._pot = 0
        return winners_data

    async def _cleanup_hand(self, active_players: List[PlayerState]):
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

        # Éliminations
        eliminated = []
        for p in self.players.values():
            if p.chips <= 0 and p.status not in (PlayerStatus.ELIMINATED,):
                p.status = PlayerStatus.ELIMINATED
                eliminated.append(p)
                logger.info(f"[{self.name}] {p.username} éliminé (0 chips)")

        if eliminated and self.tournament_id and self._ws_manager:
            try:
                tm = self._ws_manager._tournament_manager
                if tm:
                    tournament = tm.get_tournament(self.tournament_id)
                    if tournament:
                        total_remaining = len(tournament.get_registered_players())
                        for p in eliminated:
                            rank = total_remaining + 1
                            tournament.eliminate_player(p.user_id, rank)
                            total_remaining -= 1
                            await tm._broadcast_player_eliminated(tournament, p.user_id, rank)
                        await tm.save_tournament(tournament)
            except Exception as e:
                logger.error(f"[{self.name}] Elimination notify error: {e}")

        self._save_state()

    # ── Gestion des actions ──────────────────────────────────────────────────
    async def _wait_for_action(self, user_id: str) -> Tuple[ActionType, int]:
        self._action_event.clear()
        self._last_action = None
        await self._action_event.wait()
        if self._last_action and self._last_action.get('user_id') == user_id:
            action = ActionType(self._last_action['action'])
            amount = self._last_action.get('amount', 0)
            return action, amount
        raise Exception("Invalid action event")

    async def _get_player_action(self, p: PlayerState, can_check: bool) -> Tuple[ActionType, int]:
        if p.user_id not in self.players:
            return ActionType.FOLD, 0

        is_connected = self._ws_manager and self._ws_manager.is_connected(self.id, p.user_id)
        if not is_connected:
            await self._broadcast({
                'type': 'player_action',
                'user_id': p.user_id,
                'username': p.username,
                'action': 'fold',
                'amount': 0,
                'reason': 'disconnected'
            })
            p.status = PlayerStatus.FOLDED
            p.last_action = 'fold (disconnected)'
            return ActionType.FOLD, 0

        self._action_timeout_remaining = ACTION_TIMEOUT
        async def update_timer():
            while self._action_timeout_remaining > 0 and self._current_actor == p.user_id:
                await asyncio.sleep(1)
                if self._current_actor == p.user_id:
                    self._action_timeout_remaining -= 1
                    await self._broadcast_state()
        timer_task = asyncio.create_task(update_timer())

        try:
            action, amount = await asyncio.wait_for(
                self._wait_for_action(p.user_id),
                timeout=ACTION_TIMEOUT
            )
            return action, amount
        except asyncio.TimeoutError:
            if can_check:
                p.last_action = 'check (timeout)'
                return ActionType.CHECK, 0
            else:
                p.last_action = 'fold (timeout)'
                return ActionType.FOLD, 0
        finally:
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass
            self._action_timeout_remaining = None

    async def handle_player_action(self, user_id: str, action: ActionType, amount: int = 0):
        if self._current_actor != user_id:
            raise ValueError("Not your turn")
        self._last_action = {
            'user_id': user_id,
            'action': action.value,
            'amount': amount,
        }
        self._action_event.set()

    # ── État ──────────────────────────────────────────────────────────────────
    def get_state(self, for_user_id: Optional[str] = None) -> dict:
        players_data = []
        my_position = -1

        for uid, ps in self.players.items():
            hide = (for_user_id is None or uid != for_user_id)
            player_dict = ps.to_dict(hide_cards=hide)
            players_data.append(player_dict)
            if uid == for_user_id:
                my_position = ps.position

        players_data.sort(key=lambda p: p['position'])

        table_current_bet = max((p.current_bet for p in self.players.values()), default=0)
        min_raise = self._min_raise
        pot = self._pot
        community = self._community_cards

        action_timer = None
        if self._current_actor and self._action_timeout_remaining is not None:
            action_timer = int(self._action_timeout_remaining)
        elif self._current_actor:
            action_timer = ACTION_TIMEOUT

        return {
            'table_id': self.id,
            'name': self.name,
            'game_variant': self.game_variant.value if hasattr(self.game_variant, 'value') else str(self.game_variant),
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'round': self._hand_round,
            'pot': pot,
            'community_cards': community,
            'current_actor': self._current_actor,
            'current_bet': table_current_bet,
            'action_timer': action_timer,
            'action_timeout_total': ACTION_TIMEOUT,
            'min_raise': min_raise,
            'players': players_data,
            'my_position': my_position,
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
        if not self._ws_manager:
            return
        async with self._broadcast_lock:
            all_users = set(self.players.keys()) | set(self.spectators)
            for uid in all_users:
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
                'table_id': self.id,
                'name': self.name,
                'tournament_id': self.tournament_id,
                'game_variant': self.game_variant.value if hasattr(self.game_variant, 'value') else str(self.game_variant),
                'small_blind': self.small_blind,
                'big_blind': self.big_blind,
                'ante': self.ante,
                'max_players': self.max_players,
                'hand_round': self._hand_round,
                'dealer_btn': self._dealer_btn,
                'pot': self._pot,
                'community_cards': self._community_cards,
                'street': self._street,
                'current_actor': self._current_actor,
                'min_raise': self._min_raise,
                'deck': self._deck,
                'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
                'players': {
                    uid: {
                        'user_id': ps.user_id,
                        'username': ps.username,
                        'avatar': ps.avatar,
                        'chips': ps.chips,
                        'position': ps.position,
                        'status': ps.status.value if hasattr(ps.status, 'value') else str(ps.status),
                        'current_bet': ps.current_bet,
                        'total_bet': ps.total_bet,
                        'hole_cards': ps.hole_cards,
                        'is_dealer': ps.is_dealer,
                        'is_small_blind': ps.is_small_blind,
                        'is_big_blind': ps.is_big_blind,
                        'is_all_in': ps.is_all_in,
                    }
                    for uid, ps in self.players.items()
                },
                'saved_at': datetime.utcnow().isoformat(),
            }
            with open(STATE_DIR / f"{self.id}.json", 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[{self.name}] save_state: {e}")

    def _save_hand_history(self, hand_round: int, players: List[PlayerState],
                           winners: list, community_cards: list, pot: int):
        try:
            table_dir = HISTORY_DIR / self.id
            table_dir.mkdir(parents=True, exist_ok=True)
            data = {
                'table_id': self.id,
                'table_name': self.name,
                'tournament_id': self.tournament_id,
                'game_variant': self.game_variant.value,
                'hand': hand_round,
                'small_blind': self.small_blind,
                'big_blind': self.big_blind,
                'ante': self.ante,
                'pot': pot,
                'community_cards': community_cards,
                'players': [
                    {
                        'user_id': p.user_id, 'username': p.username,
                        'hole_cards': p.hole_cards, 'chips_before': p.chips + p.total_bet,
                        'chips_after': p.chips, 'total_bet': p.total_bet,
                        'status': p.status.value if hasattr(p.status, 'value') else str(p.status),
                    }
                    for p in players
                ],
                'winners': winners,
                'timestamp': datetime.utcnow().isoformat(),
            }
            with open(table_dir / f"hand_{hand_round:06d}.json", 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[{self.name}] save_hand_history: {e}")

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
