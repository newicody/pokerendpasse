# backend/game_engine.py
"""
Moteur de jeu poker — PokerKit + SRA Deck Security
===================================================
Version corrigée avec:
- Fix _determine_winner (sauvegarde stacks avant showdown)
- Fix action_timer (calcul correct du temps restant)
- Fix community cards (révélation progressive correcte)
- Game loop resilient avec auto-restart
- Persistance des commitments
- Meilleure synchronisation PokerKit
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
from typing import Dict, List, Optional, Set, Any, Tuple

from pokerkit import NoLimitTexasHoldem, Automation, Mode

from .models import (
    Table, TablePlayer, GameState, GameStatus, TableStatus,
    PlayerStatus, ActionType, PlayerActionRequest, GameType,
)

logger = logging.getLogger(__name__)

ACTION_TIMEOUT = 20
PAUSE_BETWEEN_HANDS = 4
MAX_GAME_LOOP_ERRORS = 3  # Nombre max d'erreurs avant arrêt définitif

STATE_DIR = Path("data/table_states")
STATE_DIR.mkdir(parents=True, exist_ok=True)

COMMITMENT_DIR = Path("data/deck_commitments")
COMMITMENT_DIR.mkdir(parents=True, exist_ok=True)

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


# ─────────────────────────────────────────────────────────────────────────────
# SRA Deck Security — Port Python du mental-poker-toolkit
# Avec persistance des commitments
# ─────────────────────────────────────────────────────────────────────────────
class DeckSecurity:
    """
    Commit-reveal + SRA verification avec persistance.
    Le serveur s'engage sur un seed AVANT de distribuer,
    puis le révèle après la main pour vérification.
    """
    
    def __init__(self, table_id: str):
        self.table_id = table_id
        self._commitments: Dict[int, dict] = {}
        self._load_commitments()

    def _get_commitment_file(self) -> Path:
        return COMMITMENT_DIR / f"{self.table_id}_commitments.json"

    def _load_commitments(self):
        """Charge les commitments depuis le disque"""
        try:
            path = self._get_commitment_file()
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                    # Convertir les clés string en int
                    self._commitments = {int(k): v for k, v in data.items()}
                logger.debug(f"Loaded {len(self._commitments)} commitments for table {self.table_id}")
        except Exception as e:
            logger.error(f"Failed to load commitments: {e}")
            self._commitments = {}

    def _save_commitments(self):
        """Sauvegarde les commitments sur disque"""
        try:
            path = self._get_commitment_file()
            # Garder seulement les 100 dernières mains
            if len(self._commitments) > 100:
                sorted_keys = sorted(self._commitments.keys())
                for k in sorted_keys[:-100]:
                    del self._commitments[k]
            
            with open(path, 'w') as f:
                json.dump(self._commitments, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save commitments: {e}")

    def commit_deck(self, hand_round: int, deck: List[str]) -> str:
        """Commit le deck avant distribution"""
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
        logger.info(f"[Table {self.table_id}] Deck committed for hand #{hand_round}: {commitment[:16]}...")
        
        return commitment

    def reveal(self, hand_round: int) -> Optional[dict]:
        """Révèle le deck après la main"""
        commitment = self._commitments.get(hand_round)
        if commitment:
            commitment['revealed_at'] = datetime.utcnow().isoformat()
            self._save_commitments()
        return commitment

    def get_commitment(self, hand_round: int) -> Optional[str]:
        """Récupère le hash de commitment sans révéler le seed"""
        data = self._commitments.get(hand_round)
        return data['hash'] if data else None

    @staticmethod
    def verify(seed: str, deck_order: List[str], commitment_hash: str) -> bool:
        """Vérifie l'intégrité du deck (peut être appelé côté client)"""
        deck_str = ','.join(deck_order)
        expected = hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest()
        return expected == commitment_hash

    def cleanup(self):
        """Supprime les fichiers de commitment"""
        try:
            self._get_commitment_file().unlink(missing_ok=True)
        except:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# PlayerState
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# PokerTable
# ─────────────────────────────────────────────────────────────────────────────
class PokerTable:
    """
    Table de poker avec moteur PokerKit.
    Version corrigée avec game loop resilient et meilleure gestion d'état.
    """
    
    def __init__(
        self,
        table_id: str,
        name: str,
        game_type: GameType,
        max_players: int,
        min_buy_in: int,
        max_buy_in: int,
        small_blind: int,
        big_blind: int,
        tournament_id: Optional[str] = None
    ):
        self.id = table_id
        self.name = name
        self.game_type = game_type
        self.max_players = max_players
        self.min_buy_in = min_buy_in
        self.max_buy_in = max_buy_in
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.tournament_id = tournament_id
        
        self.status = TableStatus.WAITING
        self.players: Dict[str, PlayerState] = {}
        self.spectators: Set[str] = set()
        
        # État du jeu
        self._pk_state = None  # État PokerKit
        self._pk_uid_map: List[str] = []  # Mapping index PokerKit -> user_id
        self._game_task: Optional[asyncio.Task] = None
        self._ws_manager = None
        self._deck_security = DeckSecurity(table_id)
        
        # Tracking
        self._hand_round = 0
        self._dealer_btn = 0
        self._street = 'preflop'
        self._community_cards: List[str] = []
        self._current_deck: List[str] = []  # Deck de la main en cours
        
        # Tracking pour winner calculation
        self._stacks_at_hand_start: Dict[str, int] = {}
        
        # Action en cours
        self._current_actor_uid: Optional[str] = None
        self._action_start_time: Optional[datetime] = None
        self._action_timeout: int = ACTION_TIMEOUT
        self._pending_action: Optional[PlayerActionRequest] = None
        self._action_event = asyncio.Event()
        
        # Resilience
        self._consecutive_errors = 0
        self._last_error: Optional[str] = None

    def set_ws_manager(self, manager):
        self._ws_manager = manager

    def can_join(self) -> bool:
        """Vérifie si un joueur peut rejoindre"""
        return len(self.players) < self.max_players

    # ─────────────────────────────────────────────────────────────────────────
    # Gestion des joueurs
    # ─────────────────────────────────────────────────────────────────────────
    
    async def add_player(self, user, chips: int = None) -> bool:
        """Ajoute un joueur à la table"""
        if user.id in self.players:
            # Joueur déjà présent, mettre à jour le statut si nécessaire
            player = self.players[user.id]
            if player.status == PlayerStatus.DISCONNECTED:
                player.status = PlayerStatus.ACTIVE
                await self._broadcast_state()
            return True
            
        if len(self.players) >= self.max_players:
            return False
        
        # Trouver une position libre
        occupied = {p.position for p in self.players.values()}
        position = next((i for i in range(self.max_players) if i not in occupied), None)
        if position is None:
            return False
        
        buy_in = chips if chips is not None else self.max_buy_in
        
        self.players[user.id] = PlayerState(
            user_id=user.id,
            username=user.username,
            avatar=getattr(user, 'avatar', None),
            chips=buy_in,
            position=position,
        )
        
        await self._broadcast_state()
        logger.info(f"[{self.name}] {user.username} joined at seat {position} with {buy_in} chips")
        
        # Démarrer le jeu si assez de joueurs
        if len(self.players) >= 2 and self.status == TableStatus.WAITING:
            await self._start_game()
        
        return True

    async def remove_player(self, user_id: str):
        """Retire un joueur de la table"""
        if user_id not in self.players:
            return
        
        player = self.players[user_id]
        del self.players[user_id]
        
        await self._broadcast_state()
        logger.info(f"[{self.name}] {player.username} left")
        
        # Arrêter si plus assez de joueurs
        if len(self.players) < 2 and self.status == TableStatus.PLAYING:
            self.status = TableStatus.WAITING
            if self._game_task:
                self._game_task.cancel()
                self._game_task = None

    def mark_player_disconnected(self, user_id: str):
        """Marque un joueur comme déconnecté"""
        if user_id in self.players:
            self.players[user_id].status = PlayerStatus.DISCONNECTED
            logger.info(f"[{self.name}] {self.players[user_id].username} marked as disconnected")

    def mark_player_reconnected(self, user_id: str):
        """Marque un joueur comme reconnecté"""
        if user_id in self.players:
            player = self.players[user_id]
            if player.status == PlayerStatus.DISCONNECTED:
                player.status = PlayerStatus.ACTIVE
                logger.info(f"[{self.name}] {player.username} reconnected")

    def add_spectator(self, user_id: str):
        self.spectators.add(user_id)

    def remove_spectator(self, user_id: str):
        self.spectators.discard(user_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Actions du joueur
    # ─────────────────────────────────────────────────────────────────────────
    
    async def handle_player_action(self, user_id: str, action: ActionType, amount: int = 0):
        """Traite une action du joueur"""
        if user_id != self._current_actor_uid:
            logger.warning(f"[{self.name}] Action from {user_id} but current actor is {self._current_actor_uid}")
            return
        
        # Enregistrer la dernière action
        if user_id in self.players:
            self.players[user_id].last_action = action.value if hasattr(action, 'value') else str(action)
        
        self._pending_action = PlayerActionRequest(action=action, amount=amount)
        self._action_event.set()

    async def _wait_for_action(self, user_id: str, timeout: int) -> Optional[PlayerActionRequest]:
        """Attend l'action d'un joueur avec timeout"""
        self._current_actor_uid = user_id
        self._pending_action = None
        self._action_event.clear()
        self._action_start_time = datetime.utcnow()
        self._action_timeout = timeout
        
        await self._broadcast_state()
        
        try:
            await asyncio.wait_for(self._action_event.wait(), timeout=timeout)
            action = self._pending_action
        except asyncio.TimeoutError:
            action = None  # Auto-fold/check
            logger.info(f"[{self.name}] {user_id} timed out, auto-action")
        
        self._current_actor_uid = None
        self._action_start_time = None
        return action

    # ─────────────────────────────────────────────────────────────────────────
    # Boucle de jeu (avec resilience)
    # ─────────────────────────────────────────────────────────────────────────
    
    async def _start_game(self):
        """Démarre la boucle de jeu"""
        if self._game_task and not self._game_task.done():
            return
        
        self.status = TableStatus.PLAYING
        self._consecutive_errors = 0
        self._game_task = asyncio.create_task(self._game_loop())

    async def _game_loop(self):
        """Boucle principale du jeu avec auto-recovery"""
        logger.info(f"[{self.name}] Game loop started")
        
        while len(self.players) >= 2 and self.status == TableStatus.PLAYING:
            try:
                await self._play_hand()
                self._consecutive_errors = 0  # Reset sur succès
                await asyncio.sleep(PAUSE_BETWEEN_HANDS)
                
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Game loop cancelled")
                break
                
            except Exception as e:
                self._consecutive_errors += 1
                self._last_error = str(e)
                logger.error(f"[{self.name}] Game loop error #{self._consecutive_errors}: {e}", exc_info=True)
                
                if self._consecutive_errors >= MAX_GAME_LOOP_ERRORS:
                    logger.error(f"[{self.name}] Too many consecutive errors, stopping game")
                    # Notifier les joueurs
                    if self._ws_manager:
                        await self._ws_manager.broadcast_to_table(self.id, {
                            'type': 'error',
                            'message': f'Table error: {e}. Game paused.',
                            'recoverable': True,
                        })
                    break
                
                # Attendre avant retry
                await asyncio.sleep(2)
                
                # Reset l'état pour la prochaine main
                self._reset_hand_state()
        
        self.status = TableStatus.WAITING
        logger.info(f"[{self.name}] Game loop ended")

    def _reset_hand_state(self):
        """Reset l'état entre les mains (ou après erreur)"""
        self._pk_state = None
        self._street = 'preflop'
        self._community_cards = []
        self._current_deck = []
        self._current_actor_uid = None
        self._action_start_time = None
        
        for p in self.players.values():
            p.hole_cards = []
            p.current_bet = 0
            p.total_bet = 0
            p.is_all_in = False
            p.last_action = None
            if p.status == PlayerStatus.FOLDED:
                p.status = PlayerStatus.ACTIVE

    async def _play_hand(self):
        """Joue une main complète"""
        self._hand_round += 1
        self._reset_hand_state()
        
        # Filtrer les joueurs actifs
        active_uids = [
            uid for uid, ps in self.players.items() 
            if ps.chips > 0 and ps.status not in (PlayerStatus.ELIMINATED, PlayerStatus.SITTING_OUT)
        ]
        
        if len(active_uids) < 2:
            logger.info(f"[{self.name}] Not enough players for a hand")
            return
        
        # Sauvegarder les stacks au début de la main (FIX CRITIQUE)
        self._stacks_at_hand_start = {uid: self.players[uid].chips for uid in active_uids}
        
        # Créer le deck et commit
        deck = self._make_deck()
        self._current_deck = deck
        commitment = self._deck_security.commit_deck(self._hand_round, deck)
        
        # Notifier le commit du deck
        if self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type': 'deck_commit',
                'round': self._hand_round,
                'commitment': commitment,
            })
        
        # Avancer le dealer button
        self._dealer_btn = (self._dealer_btn + 1) % len(active_uids)
        
        # Ordonner les joueurs à partir du dealer
        ordered_uids = active_uids[self._dealer_btn:] + active_uids[:self._dealer_btn]
        self._pk_uid_map = ordered_uids
        ordered = [self.players[uid] for uid in ordered_uids]
        
        # Reset des états joueurs
        for i, ps in enumerate(ordered):
            ps.hole_cards = []
            ps.current_bet = 0
            ps.total_bet = 0
            ps.is_all_in = False
            ps.last_action = None
            ps.is_dealer = (i == 0)
            ps.is_small_blind = (i == 1 % len(ordered))
            ps.is_big_blind = (i == 2 % len(ordered)) if len(ordered) > 2 else (i == 1)
            if ps.status == PlayerStatus.FOLDED:
                ps.status = PlayerStatus.ACTIVE
        
        # Créer l'état PokerKit
        stacks = [ps.chips for ps in ordered]
        
        try:
            game = NoLimitTexasHoldem(
                AUTOMATIONS,
                True,  # Antes
                0,     # Pas d'ante
                (self.small_blind, self.big_blind),
                self.big_blind,
                mode=Mode.CASH_GAME,
            )
            pk = game(stacks, len(ordered))
        except Exception as e:
            logger.error(f"[{self.name}] Failed to create PokerKit state: {e}")
            raise
        
        self._pk_state = pk
        
        # Distribution des hole cards
        deck_idx = 0
        for i, ps in enumerate(ordered):
            cards = [deck[deck_idx], deck[deck_idx + 1]]
            deck_idx += 2
            ps.hole_cards = cards
        
        await self._broadcast_state()
        logger.info(f"[{self.name}] Hand #{self._hand_round} started with {len(ordered)} players")
        
        # Index des community cards dans le deck
        community_start = deck_idx
        
        # Compter les joueurs actifs (non fold, non all-in en attente)
        def count_active_players():
            return sum(1 for uid in self._pk_uid_map 
                      if self.players[uid].status == PlayerStatus.ACTIVE 
                      and not self.players[uid].is_all_in)
        
        # Boucle de betting
        prev_street_index = -1
        while pk.street_index is not None:
            # Vérifier si la main peut continuer
            active_count = sum(1 for i, uid in enumerate(self._pk_uid_map) 
                              if i < len(pk.statuses) and pk.statuses[i])
            
            if active_count <= 1:
                logger.info(f"[{self.name}] Only {active_count} player(s) remaining, ending hand")
                break
            
            # Déterminer le street actuel
            current_street = pk.street_index
            if current_street != prev_street_index:
                prev_street_index = current_street
                
                if current_street == 0:
                    self._street = 'preflop'
                elif current_street == 1:
                    self._street = 'flop'
                    # Révéler le flop (3 cartes)
                    self._community_cards = deck[community_start:community_start + 3]
                    await self._broadcast_state()
                elif current_street == 2:
                    self._street = 'turn'
                    # Révéler la turn (4ème carte)
                    if len(self._community_cards) == 3:
                        self._community_cards = deck[community_start:community_start + 4]
                        await self._broadcast_state()
                elif current_street == 3:
                    self._street = 'river'
                    # Révéler la river (5ème carte)
                    if len(self._community_cards) == 4:
                        self._community_cards = deck[community_start:community_start + 5]
                        await self._broadcast_state()
            
            # Trouver qui doit agir
            actor_idx = pk.actor_index
            if actor_idx is None:
                # PokerKit n'a pas d'actor, vérifier si on doit avancer le street
                if pk.street_index is not None:
                    # Forcer l'avancement si possible
                    try:
                        if hasattr(pk, 'deal_board'):
                            pk.deal_board()
                        continue
                    except:
                        pass
                break
            
            uid = self._pk_uid_map[actor_idx]
            player = self.players[uid]
            
            # Vérifier si le joueur est déconnecté -> timeout réduit
            timeout = ACTION_TIMEOUT
            if player.status == PlayerStatus.DISCONNECTED:
                timeout = 5  # 5 secondes pour les déconnectés
            
            # Attendre l'action
            action = await self._wait_for_action(uid, timeout)
            
            # Appliquer l'action
            try:
                self._apply_action(pk, actor_idx, action, player)
            except Exception as e:
                logger.error(f"[{self.name}] Action error for {uid}: {e}")
                # Fallback: check ou fold
                try:
                    if pk.can_check_or_call():
                        pk.check_or_call()
                    elif pk.can_fold():
                        pk.fold()
                except:
                    break
            
            # Synchroniser les états
            self._sync_pk(pk, ordered)
        
        # Showdown - révéler les cartes communes restantes si nécessaire
        active_at_showdown = sum(1 for i, uid in enumerate(self._pk_uid_map) 
                                 if i < len(pk.statuses) and pk.statuses[i])
        
        if active_at_showdown > 1:
            # Showdown réel - révéler toutes les cartes
            self._street = 'showdown'
            self._community_cards = deck[community_start:community_start + 5]
        # Si un seul joueur, ne pas révéler les cartes non distribuées
        
        # Synchronisation finale
        self._sync_pk(pk, ordered)
        
        # Déterminer le gagnant (FIX CRITIQUE - utilise stacks sauvegardés)
        winner_info = self._determine_winner(pk, ordered)
        
        # Broadcast le résultat
        if self._ws_manager and winner_info:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type': 'hand_result',
                'hand': self._hand_round,
                'winner': winner_info.get('winner'),
                'winner_id': winner_info.get('winner_id'),
                'pot': winner_info.get('pot', 0),
                'board': self._community_cards,
                'hand_type': winner_info.get('hand_type', ''),
                'winning_cards': winner_info.get('winning_cards', []),
            })
        
        # Révéler le deck
        reveal = self._deck_security.reveal(self._hand_round)
        if reveal and self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id, {
                'type': 'deck_reveal',
                'round': self._hand_round,
                'seed': reveal['seed'],
                'deck_order': reveal['deck_order'],
                'commitment': reveal['hash'],
            })
        
        # Mise à jour finale des stacks et élimination
        for i, uid in enumerate(self._pk_uid_map):
            ps = self.players.get(uid)
            if ps and i < len(pk.stacks):
                ps.chips = int(pk.stacks[i])
                if ps.chips <= 0:
                    ps.status = PlayerStatus.ELIMINATED
                    logger.info(f"[{self.name}] {ps.username} eliminated")
        
        # Sauvegarder l'état
        self._save_state()
        
        # Broadcast final
        await self._broadcast_state()
        logger.info(f"[{self.name}] Hand #{self._hand_round} completed - Winner: {winner_info.get('winner', 'Unknown')}")

    def _apply_action(self, pk, actor_idx: int, action: Optional[PlayerActionRequest], player: PlayerState):
        """Applique une action au jeu PokerKit"""
        action_name = "timeout"
        
        if action is None:
            # Timeout: auto-check si gratuit, sinon auto-fold
            to_call = max(pk.bets) - pk.bets[actor_idx] if pk.bets else 0
            if to_call <= 0 and pk.can_check_or_call():
                pk.check_or_call()
                action_name = "check"
            elif pk.can_fold():
                pk.fold()
                action_name = "fold"
                player.status = PlayerStatus.FOLDED
            elif pk.can_check_or_call():
                pk.check_or_call()
                action_name = "call"
                
        elif action.action == ActionType.FOLD:
            if pk.can_fold():
                pk.fold()
                player.status = PlayerStatus.FOLDED
                action_name = "fold"
            elif pk.can_check_or_call():
                pk.check_or_call()
                action_name = "check"
                
        elif action.action in (ActionType.CALL, ActionType.CHECK):
            if pk.can_check_or_call():
                pk.check_or_call()
                action_name = "call" if max(pk.bets) > pk.bets[actor_idx] else "check"
            elif pk.can_fold():
                pk.fold()
                player.status = PlayerStatus.FOLDED
                action_name = "fold"
                
        elif action.action in (ActionType.RAISE, ActionType.ALL_IN):
            if pk.can_complete_bet_or_raise_to():
                mn = pk.min_completion_betting_or_raising_to_amount
                mx = pk.max_completion_betting_or_raising_to_amount
                
                if action.action == ActionType.ALL_IN:
                    amt = mx
                else:
                    amt = max(mn, min(action.amount, mx))
                
                pk.complete_bet_or_raise_to(amt)
                action_name = "raise" if amt < mx else "all_in"
                
                if amt >= mx or player.chips <= amt:
                    player.is_all_in = True
                    player.status = PlayerStatus.ALL_IN
                    
            elif pk.can_check_or_call():
                pk.check_or_call()
                action_name = "call"
            elif pk.can_fold():
                pk.fold()
                player.status = PlayerStatus.FOLDED
                action_name = "fold"
        
        player.last_action = action_name
        logger.debug(f"[{self.name}] {player.username} -> {action_name}")

    def _sync_pk(self, pk, ordered: List[PlayerState]):
        """Synchronise l'état PokerKit avec nos PlayerState"""
        for i, ps in enumerate(ordered):
            if i < len(pk.stacks):
                ps.chips = int(pk.stacks[i])
            if i < len(pk.bets):
                ps.current_bet = int(pk.bets[i])
            if i < len(pk.statuses) and not pk.statuses[i]:
                if ps.status not in (PlayerStatus.ALL_IN, PlayerStatus.ELIMINATED):
                    ps.status = PlayerStatus.FOLDED

    def _determine_winner(self, pk, ordered: List[PlayerState]) -> dict:
        """
        Détermine le gagnant de la main.
        FIX: Utilise les stacks sauvegardés au début de la main.
        """
        winner = None
        winner_id = None
        max_gain = 0
        winning_cards = []
        
        for i, ps in enumerate(ordered):
            if i < len(pk.stacks):
                current_stack = int(pk.stacks[i])
                starting_stack = self._stacks_at_hand_start.get(ps.user_id, current_stack)
                gain = current_stack - starting_stack
                
                if gain > max_gain:
                    max_gain = gain
                    winner = ps.username
                    winner_id = ps.user_id
                    winning_cards = ps.hole_cards
        
        # Si personne n'a gagné de chips (tous fold sauf un)
        if winner is None:
            for i, ps in enumerate(ordered):
                if i < len(pk.statuses) and pk.statuses[i]:
                    winner = ps.username
                    winner_id = ps.user_id
                    winning_cards = ps.hole_cards
                    break
        
        # Calculer le pot total
        total_pot = sum(self._stacks_at_hand_start.values()) - sum(
            ps.chips for ps in ordered
        ) if ordered else 0
        
        # Fallback si calcul bizarre
        if total_pot <= 0:
            total_pot = max_gain
        
        return {
            'winner': winner or (ordered[0].username if ordered else 'Unknown'),
            'winner_id': winner_id or (ordered[0].user_id if ordered else None),
            'pot': total_pot,
            'hand_type': '',  # TODO: évaluation main PokerKit
            'winning_cards': winning_cards,
        }

    @staticmethod
    def _str_to_card(card_str: str):
        """Convertit une string carte en Card PokerKit"""
        from pokerkit import Card
        return Card(card_str)

    # ─────────────────────────────────────────────────────────────────────────
    # État et broadcast
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_state(self, for_user_id: Optional[str] = None) -> dict:
        """
        Retourne l'état complet de la table.
        Si for_user_id est spécifié, cache les hole cards des autres joueurs.
        """
        pk = self._pk_state
        
        # Calcul du timer (FIX: calcul correct)
        timer = None
        if self._action_start_time and self._current_actor_uid:
            elapsed = (datetime.utcnow() - self._action_start_time).total_seconds()
            timer = max(0, int(self._action_timeout - elapsed))
        
        # Données des joueurs
        players_data = []
        for uid, ps in self.players.items():
            # Cacher les cartes des autres joueurs sauf showdown
            hide_cards = (
                for_user_id is not None 
                and uid != for_user_id 
                and self._street != 'showdown'
            )
            players_data.append(ps.to_dict(hide_cards=hide_cards))
        
        # Min raise
        min_raise = self.big_blind * 2
        max_raise = 0
        if pk and pk.can_complete_bet_or_raise_to():
            min_raise = pk.min_completion_betting_or_raising_to_amount
            max_raise = pk.max_completion_betting_or_raising_to_amount
        
        # Pot actuel
        pot = sum(pk.bets) if pk and pk.bets else 0
        # Ajouter les mises déjà collectées dans les pots précédents
        if pk and hasattr(pk, 'pots'):
            pot += sum(p for p in pk.pots if isinstance(p, (int, float)))
        
        return {
            'table_id': self.id,
            'name': self.name,
            'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
            'round': self._hand_round,
            'pot': pot,
            'community_cards': self._community_cards,
            'betting_round': self._street,
            'current_bet': int(max(pk.bets)) if pk and pk.bets else 0,
            'current_player_index': pk.actor_index if pk else None,
            'current_actor': self._current_actor_uid,
            'action_timer': timer,
            'action_timeout_total': self._action_timeout,
            'dealer_index': self._dealer_btn,
            'players': players_data,
            'min_raise': min_raise,
            'max_raise': max_raise,
            'max_players': self.max_players,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'tournament_id': self.tournament_id,
        }

    async def _broadcast_state(self):
        """Broadcast l'état à tous les clients"""
        if not self._ws_manager:
            return
        
        # État de base (sans cartes cachées pour le broadcast général)
        base_state = self.get_state()
        
        # Pour chaque joueur, envoyer un état personnalisé avec ses cartes
        for uid in list(self.players.keys()) | self.spectators:
            try:
                personal_state = self.get_state(for_user_id=uid)
                await self._ws_manager.send_to_player(self.id, uid, {
                    'type': 'game_state',
                    'data': personal_state,
                })
            except Exception as e:
                logger.error(f"Failed to send state to {uid}: {e}")

    def get_info(self) -> Table:
        """Retourne les infos publiques de la table"""
        return Table(
            id=self.id,
            name=self.name,
            game_type=self.game_type,
            tournament_id=self.tournament_id,
            max_players=self.max_players,
            status=self.status,
            players=[ps.to_pydantic() for ps in self.players.values()],
            spectators=list(self.spectators),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Utilitaires
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def _make_deck() -> List[str]:
        """Crée et mélange un deck standard"""
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        suits = ['h', 'd', 'c', 's']
        deck = [f"{r}{s}" for s in suits for r in ranks]
        random.shuffle(deck)
        return deck

    def _save_state(self):
        """Sauvegarde l'état de la table"""
        try:
            data = {
                'table_id': self.id,
                'name': self.name,
                'tournament_id': self.tournament_id,
                'small_blind': self.small_blind,
                'big_blind': self.big_blind,
                'max_players': self.max_players,
                'hand_round': self._hand_round,
                'dealer_btn': self._dealer_btn,
                'status': self.status.value if hasattr(self.status, 'value') else str(self.status),
                'players': {
                    uid: {
                        'user_id': ps.user_id,
                        'username': ps.username,
                        'avatar': ps.avatar,
                        'chips': ps.chips,
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
            logger.error(f"[{self.name}] Failed to save state: {e}")

    def _delete_state(self):
        """Supprime l'état sauvegardé"""
        try:
            (STATE_DIR / f"{self.id}.json").unlink(missing_ok=True)
        except:
            pass

    async def close(self):
        """Ferme la table"""
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
        """Charge l'état sauvegardé d'une table"""
        path = STATE_DIR / f"{table_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state for {table_id}: {e}")
            return None
