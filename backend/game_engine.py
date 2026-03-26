# backend/game_engine.py
import asyncio
import logging
import random
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime
import uuid

from .models import (
    Table, TablePlayer, GameState, GameStatus, TableStatus,
    PlayerStatus, ActionType, PlayerActionRequest
)

# Import pokerkit si disponible
try:
    from pokerkit import NoLimitTexasHoldem, Hand, Card
    POKERKIT_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("Pokerkit loaded")
except ImportError:
    POKERKIT_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Pokerkit not available, using simplified engine")

logger = logging.getLogger(__name__)

class PokerTable:
    """Table de poker avec logique de jeu complète"""
    
    def __init__(self, table_id: str, name: str, game_type, max_players: int,
                 min_buy_in: int, max_buy_in: int, small_blind: int, big_blind: int):
        self.id = table_id
        self.name = name
        self.game_type = game_type
        self.max_players = max_players
        self.min_buy_in = min_buy_in
        self.max_buy_in = max_buy_in
        self.small_blind = small_blind
        self.big_blind = big_blind
        
        self.players: Dict[str, TablePlayer] = {}
        self.spectators: Set[str] = set()
        self.status = TableStatus.OPEN
        self.game_state: Optional[GameState] = None
        
        self._game_task: Optional[asyncio.Task] = None
        self._action_queue: asyncio.Queue = asyncio.Queue()
        self._player_timers: Dict[str, asyncio.Task] = {}
        
        self.deck: List[str] = []
        self.current_betting_round = "preflop"
        self.last_raiser: Optional[str] = None
    
    # backend/game_engine.py - Ajouter dans PokerTable
    async def _deal_hand(self):
        """Distribution main par main"""
        # Créer et mélanger le deck
        self.deck = self._create_deck()
        random.shuffle(self.deck)
        
        active_players = self._get_active_players()
        
        # Distribuer les cartes (main par main)
        for player in active_players:
            player.hole_cards = [self.deck.pop(), self.deck.pop()]
        
        # Vérifier la bulle (si c'est un tournoi)
        tournament = self._get_tournament()
        if tournament:
            await self._check_bubble(tournament)
        
        logger.info(f"Hand dealt on table {self.name}")
    
    async def _check_bubble(self, tournament):
        """Vérifie la situation de bulle (proche des places payées)"""
        active_players = len([p for p in self.players.values() if p.status == PlayerStatus.ACTIVE])
        total_players = len(tournament.players)
        itm_count = max(1, int(total_players * tournament.itm_percentage / 100))
        
        # Si on est proche de la bulle (moins de 2x ITM)
        if active_players <= itm_count + 2:
            # Afficher un message dans le chat
            await self._broadcast_bubble_warning(tournament, active_players, itm_count)
    
    async def _broadcast_bubble_warning(self, tournament, active_players, itm_count):
        """Diffuse un message de bulle"""
        message = f"⚠️ BUBBLE WARNING! {active_players} players remaining, {itm_count} paid places!"
        for player in self.players.values():
            if player.user_id in tournament.players:
                # Envoyer un message WebSocket
                if self._websocket:
                    await self._websocket.send_json({
                        'type': 'bubble_warning',
                        'message': message,
                        'players_remaining': active_players,
                        'paid_places': itm_count
                    })


    def can_join(self) -> bool:
        return (self.status in [TableStatus.OPEN, TableStatus.FULL] and 
                len(self.players) < self.max_players)
    
    def is_full(self) -> bool:
        return len(self.players) >= self.max_players
    
    def is_empty(self) -> bool:
        return len(self.players) == 0
    
    async def add_player(self, user, buy_in: int) -> bool:
        if not self.can_join():
            return False
            
        player = TablePlayer(
            user_id=user.id,
            username=user.username,
            avatar=user.avatar,
            chips=buy_in,
            position=len(self.players),
            status=PlayerStatus.ACTIVE
        )
        
        self.players[user.id] = player
        logger.info(f"Player {user.username} joined table {self.name}")
        
        if len(self.players) == self.max_players:
            self.status = TableStatus.FULL
        
        # Si la table est pleine, démarrer la partie
        if self.is_full() and not self.game_state:
            await self.start_game()
        
        return True
    
    async def remove_player(self, user_id: str):
        if user_id in self.players:
            player = self.players[user_id]
            del self.players[user_id]
            logger.info(f"Player {player.username} left table {self.name}")
    
    async def start_game(self):
        if self.game_state and self.game_state.status == GameStatus.IN_PROGRESS:
            return
            
        if len(self.players) < 2:
            return
            
        self.status = TableStatus.PLAYING
        self.game_state = GameState(
            table_id=self.id,
            status=GameStatus.IN_PROGRESS,
            round=1,
            players=[],
            time_bank=30
        )
        
        self._assign_positions()
        self._game_task = asyncio.create_task(self._game_loop())
        logger.info(f"Game started on table {self.name}")
    
    async def _game_loop(self):
        """Boucle principale du jeu"""
        try:
            while self.game_state and self.game_state.status == GameStatus.IN_PROGRESS:
                if len(self._get_active_players()) < 2:
                    logger.info("Not enough players, ending game")
                    break
                
                await self._new_hand()
                
                # Preflop
                self.current_betting_round = "preflop"
                await self._betting_round()
                
                if not self._is_hand_complete():
                    # Flop
                    await self._deal_flop()
                    self.current_betting_round = "flop"
                    await self._betting_round()
                
                if not self._is_hand_complete():
                    # Turn
                    await self._deal_turn()
                    self.current_betting_round = "turn"
                    await self._betting_round()
                
                if not self._is_hand_complete():
                    # River
                    await self._deal_river()
                    self.current_betting_round = "river"
                    await self._betting_round()
                
                if not self._is_hand_complete():
                    await self._showdown()
                
                await asyncio.sleep(3)
                self._rotate_dealer()
                
        except asyncio.CancelledError:
            logger.info(f"Game loop cancelled for table {self.name}")
        except Exception as e:
            logger.error(f"Error in game loop: {e}", exc_info=True)
        finally:
            self.game_state = None
            self.status = TableStatus.OPEN
    
    async def _new_hand(self):
        """Nouvelle main"""
        for player in self.players.values():
            player.current_bet = 0
            player.total_bet = 0
            player.hole_cards = []
            if player.status == PlayerStatus.DISCONNECTED:
                player.status = PlayerStatus.ACTIVE
            if player.chips <= 0:
                player.status = PlayerStatus.BUSTED
        
        self.game_state.pot = 0
        self.game_state.community_cards = []
        self.game_state.current_bet = 0
        self.game_state.min_raise = self.big_blind
        self.game_state.round += 1
        self.last_raiser = None
        
        # Créer et mélanger le deck
        self.deck = self._create_deck()
        random.shuffle(self.deck)
        
        # Distribuer les cartes
        active_players = self._get_active_players()
        for player in active_players:
            if len(self.deck) >= 2:
                player.hole_cards = [self.deck.pop(), self.deck.pop()]
        
        # Post blinds
        await self._post_blinds()
        
        logger.info(f"New hand started on table {self.name}")
    
    async def _deal_flop(self):
        """Distribue le flop"""
        if len(self.deck) >= 4:
            self.deck.pop()  # Burn
            self.game_state.community_cards = [self.deck.pop(), self.deck.pop(), self.deck.pop()]
            logger.info(f"Flop dealt: {self.game_state.community_cards}")
    
    async def _deal_turn(self):
        """Distribue le turn"""
        if len(self.deck) >= 2:
            self.deck.pop()  # Burn
            self.game_state.community_cards.append(self.deck.pop())
            logger.info(f"Turn dealt: {self.game_state.community_cards[-1]}")
    
    async def _deal_river(self):
        """Distribue la river"""
        if len(self.deck) >= 2:
            self.deck.pop()  # Burn
            self.game_state.community_cards.append(self.deck.pop())
            logger.info(f"River dealt: {self.game_state.community_cards[-1]}")
    
    async def _post_blinds(self):
        """Distribue les blinds"""
        active_players = list(self._get_active_players())
        if len(active_players) < 2:
            return
        
        # Small blind
        sb_player = active_players[self.game_state.small_blind_index]
        sb_amount = min(self.small_blind, sb_player.chips)
        if sb_amount > 0:
            sb_player.chips -= sb_amount
            sb_player.current_bet = sb_amount
            sb_player.total_bet += sb_amount
            self.game_state.pot += sb_amount
            self.game_state.current_bet = sb_amount
        
        # Big blind
        bb_player = active_players[self.game_state.big_blind_index]
        bb_amount = min(self.big_blind, bb_player.chips)
        if bb_amount > 0:
            bb_player.chips -= bb_amount
            bb_player.current_bet = bb_amount
            bb_player.total_bet += bb_amount
            self.game_state.pot += bb_amount
            self.game_state.current_bet = bb_amount
        
        # Premier joueur à parler (après le big blind)
        self.game_state.current_player_index = (self.game_state.big_blind_index + 1) % len(active_players)
    
    async def _betting_round(self):
        """Tour de mise"""
        active_players = self._get_active_players()
        if len(active_players) <= 1:
            return
        
        # Réinitialiser les mises pour ce tour
        for player in self.players.values():
            player.current_bet = 0
        
        current_index = self.game_state.current_player_index
        players_acted = set()
        last_raiser = self.last_raiser
        round_complete = False
        
        while not round_complete:
            if current_index >= len(active_players):
                current_index = 0
            
            current_player = active_players[current_index]
            
            # Vérifier si le joueur est encore actif
            if current_player.status != PlayerStatus.ACTIVE or current_player.chips == 0:
                current_index += 1
                continue
            
            # Timer
            self._start_player_timer(current_player.user_id)
            
            try:
                action = await asyncio.wait_for(
                    self._action_queue.get(),
                    timeout=self.game_state.time_bank
                )
            except asyncio.TimeoutError:
                action = PlayerActionRequest(
                    user_id=current_player.user_id,
                    table_id=self.id,
                    action=ActionType.FOLD
                )
            finally:
                self._stop_player_timer(current_player.user_id)
            
            action_result = await self._process_action(action)
            
            if action_result.get("success"):
                players_acted.add(current_player.user_id)
                if action_result.get("raised"):
                    last_raiser = current_player.user_id
                    self.last_raiser = last_raiser
                    players_acted.clear()
                    current_index = 0
                    continue
            
            # Vérifier si le tour est terminé
            round_complete = self._is_betting_round_complete(active_players, players_acted, last_raiser)
            current_index += 1
        
        # Fin du tour, ajouter les mises au pot total
        for player in self.players.values():
            player.total_bet += player.current_bet
    
    async def _process_action(self, action: PlayerActionRequest) -> Dict[str, Any]:
        """Traite une action de joueur"""
        result = {"success": False, "raised": False}
        player = self.players.get(action.user_id)
        if not player:
            return result
        
        to_call = self.game_state.current_bet - player.current_bet
        
        if action.action == ActionType.FOLD:
            player.status = PlayerStatus.FOLDED
            logger.info(f"Player {player.username} folded")
            result["success"] = True
            
        elif action.action == ActionType.CALL:
            call_amount = min(to_call, player.chips)
            if call_amount > 0:
                player.chips -= call_amount
                player.current_bet += call_amount
                self.game_state.pot += call_amount
            logger.info(f"Player {player.username} called {call_amount}")
            result["success"] = True
            
        elif action.action == ActionType.RAISE:
            raise_amount = action.amount
            if raise_amount < self.game_state.min_raise and player.chips > to_call + self.game_state.min_raise:
                raise_amount = self.game_state.min_raise
            
            total_bet = self.game_state.current_bet + raise_amount
            if total_bet > player.chips + player.current_bet:
                total_bet = player.chips + player.current_bet
            
            bet_amount = total_bet - player.current_bet
            if bet_amount > 0:
                player.chips -= bet_amount
                player.current_bet = total_bet
                self.game_state.pot += bet_amount
                self.game_state.current_bet = total_bet
                self.game_state.min_raise = raise_amount
                result["raised"] = True
            
            logger.info(f"Player {player.username} raised to {total_bet}")
            result["success"] = True
            
        elif action.action == ActionType.CHECK:
            if to_call == 0:
                logger.info(f"Player {player.username} checked")
                result["success"] = True
        
        if result["success"]:
            self.game_state.last_action = {
                "player": player.username,
                "action": action.action.value,
                "amount": action.amount
            }
        
        return result
    
    def _is_betting_round_complete(self, active_players: List[TablePlayer], 
                                   players_acted: Set[str], 
                                   last_raiser: Optional[str] = None) -> bool:
        """Vérifie si le tour de mise est terminé"""
        if len(active_players) <= 1:
            return True
        
        # Tous les joueurs actifs ont agi
        active_ids = {p.user_id for p in active_players if p.status == PlayerStatus.ACTIVE and p.chips > 0}
        if players_acted != active_ids:
            return False
        
        # Tous les joueurs ont misé la même somme ou sont all-in
        for player in active_players:
            if player.status == PlayerStatus.ACTIVE and player.chips > 0:
                if player.current_bet != self.game_state.current_bet:
                    return False
        
        return True
    
    async def _showdown(self):
        """Abattage et distribution du pot"""
        active_players = [p for p in self.players.values() 
                         if p.status == PlayerStatus.ACTIVE and p.chips > 0]
        
        if len(active_players) == 0:
            return
        
        if len(active_players) == 1:
            winner = active_players[0]
            winner.chips += self.game_state.pot
            self.game_state.pot = 0
            logger.info(f"Player {winner.username} wins by default")
            return
        
        # Évaluation des mains
        hand_scores = []
        for player in active_players:
            if player.hole_cards:
                all_cards = player.hole_cards + self.game_state.community_cards
                score = self._evaluate_hand(all_cards)
                hand_scores.append((player, score))
        
        if hand_scores:
            hand_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Trouver les gagnants
            winners = [hand_scores[0][0]]
            best_score = hand_scores[0][1]
            
            for i in range(1, len(hand_scores)):
                if hand_scores[i][1] == best_score:
                    winners.append(hand_scores[i][0])
                else:
                    break
            
            # Distribuer le pot
            split_amount = self.game_state.pot // len(winners)
            remainder = self.game_state.pot % len(winners)
            
            for i, winner in enumerate(winners):
                winner.chips += split_amount
                if i == 0:
                    winner.chips += remainder
            
            logger.info(f"Showdown: {len(winners)} winners")
        
        self.game_state.pot = 0
    
    def _evaluate_hand(self, cards: List[str]) -> int:
        """Évalue une main de poker (simplifié)"""
        # Extraire les rangs
        ranks = []
        for card in cards:
            rank_str = card[1:]
            if rank_str.isdigit():
                rank = int(rank_str)
            else:
                rank_map = {'J': 11, 'Q': 12, 'K': 13, 'A': 14}
                rank = rank_map.get(rank_str.upper(), 0)
            ranks.append(rank)
        
        # Score basé sur les 5 meilleures cartes
        return sum(sorted(ranks, reverse=True)[:5])
    
    def _assign_positions(self):
        """Assigne les positions (dealer, SB, BB)"""
        active_players = list(self._get_active_players())
        num_players = len(active_players)
        if num_players == 0:
            return
        
        # Sélectionner aléatoirement le dealer
        self.game_state.dealer_index = random.randint(0, num_players - 1)
        
        # Assigner small blind et big blind
        self.game_state.small_blind_index = (self.game_state.dealer_index + 1) % num_players
        self.game_state.big_blind_index = (self.game_state.dealer_index + 2) % num_players
        
        # Marquer les positions
        for i, player in enumerate(active_players):
            player.is_dealer = (i == self.game_state.dealer_index)
            player.is_small_blind = (i == self.game_state.small_blind_index)
            player.is_big_blind = (i == self.game_state.big_blind_index)
    
    def _get_active_players(self) -> List[TablePlayer]:
        """Retourne la liste des joueurs actifs"""
        return [p for p in self.players.values() 
                if p.status == PlayerStatus.ACTIVE and p.chips > 0]
    
    def _is_hand_complete(self) -> bool:
        """Vérifie si la main est terminée"""
        return len(self._get_active_players()) <= 1
    
    def _rotate_dealer(self):
        """Rotation du dealer"""
        active_players = list(self._get_active_players())
        if active_players:
            self.game_state.dealer_index = (self.game_state.dealer_index + 1) % len(active_players)
    
    def _create_deck(self) -> List[str]:
        """Crée un jeu de 52 cartes"""
        suits = ['h', 'd', 'c', 's']
        ranks = list(range(2, 15))
        deck = []
        for suit in suits:
            for rank in ranks:
                deck.append(f"{suit}{rank}")
        return deck
    
    def get_state(self) -> Dict[str, Any]:
        """Retourne l'état actuel du jeu"""
        if not self.game_state:
            return {
                "table_id": self.id,
                "status": "waiting",
                "pot": 0,
                "community_cards": [],
                "players": [],
                "current_player": None
            }
        
        players_data = []
        for player in self.players.values():
            players_data.append({
                "user_id": player.user_id,
                "username": player.username,
                "chips": player.chips,
                "current_bet": player.current_bet,
                "total_bet": player.total_bet,
                "hole_cards": player.hole_cards if player.user_id == self._get_current_player_id() else [],
                "status": player.status.value,
                "is_dealer": player.is_dealer,
                "is_small_blind": player.is_small_blind,
                "is_big_blind": player.is_big_blind
            })
        
        return {
            "table_id": self.id,
            "status": self.game_state.status.value,
            "round": self.game_state.round,
            "pot": self.game_state.pot,
            "community_cards": self.game_state.community_cards,
            "current_bet": self.game_state.current_bet,
            "current_player": self._get_current_player_id(),
            "dealer_position": self.game_state.dealer_index,
            "players": players_data,
            "last_action": self.game_state.last_action,
            "min_raise": self.game_state.min_raise,
            "time_bank": self.game_state.time_bank,
            "betting_round": self.current_betting_round
        }
    
    def _get_current_player_id(self) -> Optional[str]:
        """Retourne l'ID du joueur courant"""
        active_players = self._get_active_players()
        if active_players and self.game_state and self.game_state.current_player_index < len(active_players):
            return active_players[self.game_state.current_player_index].user_id
        return None
    
    def _start_player_timer(self, user_id: str):
        """Démarre le timer pour un joueur"""
        if user_id in self._player_timers:
            self._player_timers[user_id].cancel()
        self._player_timers[user_id] = asyncio.create_task(self._player_timeout(user_id))
    
    def _stop_player_timer(self, user_id: str):
        """Arrête le timer d'un joueur"""
        if user_id in self._player_timers:
            self._player_timers[user_id].cancel()
            if user_id in self._player_timers:
                del self._player_timers[user_id]
    
    async def _player_timeout(self, user_id: str):
        """Timer de timeout pour un joueur"""
        await asyncio.sleep(self.game_state.time_bank if self.game_state else 30)
        await self._action_queue.put(PlayerActionRequest(
            user_id=user_id, table_id=self.id, action=ActionType.FOLD
        ))
        logger.info(f"Player {user_id} auto-folded due to timeout")
    
    async def handle_player_action(self, user_id: str, action: ActionType, amount: int = 0):
        """Point d'entrée pour les actions des joueurs"""
        await self._action_queue.put(PlayerActionRequest(
            user_id=user_id, table_id=self.id, action=action, amount=amount
        ))
    
    def get_info(self) -> Table:
        """Retourne les informations publiques de la table"""
        from .models import Table as TableModel, TablePlayer as TablePlayerModel
        
        players_list = []
        for player in self.players.values():
            players_list.append(TablePlayerModel(
                user_id=player.user_id,
                username=player.username,
                avatar=player.avatar,
                chips=player.chips,
                position=player.position,
                status=player.status,
                current_bet=player.current_bet,
                total_bet=player.total_bet,
                hole_cards=player.hole_cards,
                is_dealer=player.is_dealer,
                is_small_blind=player.is_small_blind,
                is_big_blind=player.is_big_blind,
                sat_at=player.sat_at
            ))
        
        return TableModel(
            id=self.id,
            name=self.name,
            game_type=self.game_type,
            max_players=self.max_players,
            min_buy_in=self.min_buy_in,
            max_buy_in=self.max_buy_in,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            status=self.status,
            players=players_list,
            spectators=list(self.spectators)
        )
    
    async def close(self):
        """Ferme la table"""
        if self._game_task:
            self._game_task.cancel()
            try:
                await self._game_task
            except asyncio.CancelledError:
                pass
