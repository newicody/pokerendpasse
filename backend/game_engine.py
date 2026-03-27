# backend/game_engine.py
"""PokerKit game engine + SRA Deck Security (mental-poker-toolkit port)."""
import asyncio, hashlib, json, logging, secrets, random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from pokerkit import NoLimitTexasHoldem, Automation, Mode
from .models import (Table, TablePlayer, GameState, GameStatus, TableStatus,
                     PlayerStatus, ActionType, PlayerActionRequest, GameType)
logger = logging.getLogger(__name__)
ACTION_TIMEOUT = 20; PAUSE_BETWEEN_HANDS = 4
STATE_DIR = Path("data/table_states"); STATE_DIR.mkdir(parents=True, exist_ok=True)
AUTOMATIONS = (Automation.ANTE_POSTING, Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING, Automation.CARD_BURNING,
    Automation.HOLE_DEALING, Automation.BOARD_DEALING,
    Automation.RUNOUT_COUNT_SELECTION, Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING, Automation.CHIPS_PUSHING, Automation.CHIPS_PULLING)

class DeckSecurity:
    """Commit-reveal SRA — port du mental-poker-toolkit pour serveur autoritaire."""
    def __init__(self): self._commitments: Dict[int, dict] = {}
    def commit_deck(self, hand_round, deck):
        seed = secrets.token_hex(32); deck_str = ','.join(deck)
        h = hashlib.sha256(f"{seed}:{deck_str}".encode()).hexdigest()
        self._commitments[hand_round] = {'seed': seed, 'hash': h, 'deck_order': list(deck)}
        return h
    def reveal(self, hand_round): return self._commitments.get(hand_round)
    @staticmethod
    def verify(seed, deck_order, commitment_hash):
        return hashlib.sha256(f"{seed}:{','.join(deck_order)}".encode()).hexdigest() == commitment_hash
    @staticmethod
    def sra_encrypt(val, e, mod): return pow(val, e, mod)
    @staticmethod
    def sra_decrypt(cipher, d, mod): return pow(cipher, d, mod)

@dataclass
class PlayerState:
    user_id: str; username: str; avatar: Optional[str]; chips: int; position: int
    status: PlayerStatus = PlayerStatus.ACTIVE; hole_cards: List[str] = field(default_factory=list)
    current_bet: int = 0; total_bet: int = 0
    is_dealer: bool = False; is_small_blind: bool = False; is_big_blind: bool = False
    sat_at: datetime = field(default_factory=datetime.utcnow)
    def to_dict(self):
        return {'user_id':self.user_id,'username':self.username,'avatar':self.avatar,
                'chips':self.chips,'stack':self.chips,'position':self.position,
                'status':self.status.value if hasattr(self.status,'value') else str(self.status),
                'current_bet':self.current_bet,'bet':self.current_bet,'total_bet':self.total_bet,
                'hole_cards':self.hole_cards,'is_dealer':self.is_dealer,
                'is_small_blind':self.is_small_blind,'is_big_blind':self.is_big_blind}
    def to_pydantic(self):
        return TablePlayer(user_id=self.user_id,username=self.username,avatar=self.avatar,
            position=self.position,status=self.status,current_bet=self.current_bet,
            total_bet=self.total_bet,hole_cards=self.hole_cards,is_dealer=self.is_dealer,
            is_small_blind=self.is_small_blind,is_big_blind=self.is_big_blind,sat_at=self.sat_at)

class PokerTable:
    def __init__(self, table_id, name, game_type, max_players, min_buy_in, max_buy_in,
                 small_blind, big_blind, tournament_id=None):
        self.id=table_id; self.name=name; self.game_type=game_type
        self.max_players=max_players; self.min_buy_in=min_buy_in; self.max_buy_in=max_buy_in
        self.small_blind=small_blind; self.big_blind=big_blind; self.tournament_id=tournament_id
        self.players: Dict[str, PlayerState] = {}; self.spectators: Set[str] = set()
        self.status = TableStatus.WAITING; self.game_state: Optional[GameState] = None
        self._pk_state=None; self._pk_uid_map: List[str]=[]; self._street='preflop'
        self._game_task=None; self._action_queue=asyncio.Queue()
        self._ws_manager=None; self._current_actor_uid=None; self._action_deadline=None
        self._deck_security=DeckSecurity(); self._dealer_btn=0; self._hand_round=0
    def set_ws_manager(self, ws): self._ws_manager = ws
    def can_join(self): return self.status in (TableStatus.WAITING, TableStatus.PLAYING) and len(self.players)<self.max_players

    async def add_player(self, user, buy_in):
        if not self.can_join(): return False
        ps = PlayerState(user_id=user.id,username=user.username,avatar=getattr(user,'avatar',None),
                         chips=buy_in,position=len(self.players))
        self.players[user.id]=ps
        logger.info(f"[{self.name}] {user.username} seated ({buy_in} chips)")
        if len([p for p in self.players.values() if p.chips>0])>=2 and not self._game_task:
            await self.start_game()
        return True
    async def remove_player(self, uid): self.players.pop(uid, None)

    async def start_game(self):
        if self._game_task: return
        self.status=TableStatus.PLAYING
        self.game_state=GameState(table_id=self.id,status=GameStatus.IN_PROGRESS,round=0,players=[],time_bank=ACTION_TIMEOUT)
        self._game_task=asyncio.create_task(self._game_loop())
        logger.info(f"[{self.name}] Game started ({len(self.players)} players)")

    async def _game_loop(self):
        try:
            while self.game_state and self.game_state.status==GameStatus.IN_PROGRESS:
                active=[p for p in self.players.values() if p.chips>0]
                if len(active)<2:
                    if active: logger.info(f"[{self.name}] Winner: {active[0].username}")
                    break
                await self._play_hand_pokerkit(); self._save_state()
                await asyncio.sleep(PAUSE_BETWEEN_HANDS)
        except asyncio.CancelledError: pass
        except Exception as e: logger.error(f"[{self.name}] game_loop: {e}",exc_info=True)
        finally:
            if self.game_state: self.game_state.status=GameStatus.FINISHED
            self.status=TableStatus.WAITING; self._game_task=None; self._save_state()

    async def _play_hand_pokerkit(self):
        active=[p for p in self.players.values() if p.chips>0]
        if len(active)<2: return
        self._hand_round+=1; self.game_state.round=self._hand_round
        self._dealer_btn=self._hand_round%len(active)
        ordered=active[self._dealer_btn:]+active[:self._dealer_btn]
        self._pk_uid_map=[p.user_id for p in ordered]; stacks=tuple(p.chips for p in ordered)
        deck=self._make_deck(); commitment=self._deck_security.commit_deck(self._hand_round,deck)
        for p in self.players.values():
            p.hole_cards=[]; p.current_bet=0; p.total_bet=0
            p.is_dealer=False; p.is_small_blind=False; p.is_big_blind=False
            if p.chips>0: p.status=PlayerStatus.ACTIVE
        ordered[0].is_dealer=True
        if len(ordered)==2: ordered[0].is_small_blind=True; ordered[1].is_big_blind=True
        elif len(ordered)>=3: ordered[1].is_small_blind=True; ordered[2].is_big_blind=True
        try:
            self._pk_state=NoLimitTexasHoldem.create_state(
                AUTOMATIONS,True,0,(self.small_blind,self.big_blind),
                self.big_blind,stacks,len(ordered),mode=Mode.TOURNAMENT)
        except Exception as e: logger.error(f"[{self.name}] PK create: {e}",exc_info=True); return
        pk=self._pk_state; self._sync_pk(pk,ordered); await self._broadcast_state()
        if self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id,{'type':'deck_commitment','round':self._hand_round,'commitment':commitment})
        # Action loop
        while pk.status and pk.actor_index is not None:
            ai=pk.actor_index
            if ai>=len(self._pk_uid_map): break
            uid=self._pk_uid_map[ai]; self._current_actor_uid=uid
            bl=len(pk.board_cards)
            self._street='preflop' if bl==0 else 'flop' if bl<=3 else 'turn' if bl==4 else 'river'
            self._action_deadline=asyncio.get_event_loop().time()+ACTION_TIMEOUT
            self._sync_pk(pk,ordered); await self._broadcast_state()
            action=await self._wait_for_action(uid,ACTION_TIMEOUT)
            try: self._apply_action(pk,ai,action)
            except Exception as e:
                logger.error(f"[{self.name}] Action err {uid}: {e}")
                try:
                    if pk.can_check_or_call(): pk.check_or_call()
                    elif pk.can_fold(): pk.fold()
                except: break
            self._sync_pk(pk,ordered)
        self._current_actor_uid=None; self._action_deadline=None
        for i,uid in enumerate(self._pk_uid_map):
            ps=self.players.get(uid)
            if ps and i<len(pk.stacks):
                ps.chips=int(pk.stacks[i])
                if ps.chips<=0: ps.status=PlayerStatus.ELIMINATED
        reveal=self._deck_security.reveal(self._hand_round)
        if reveal and self._ws_manager:
            await self._ws_manager.broadcast_to_table(self.id,{'type':'deck_reveal','round':self._hand_round,
                'seed':reveal['seed'],'deck_order':reveal['deck_order'],'commitment':reveal['hash']})
        for p in self.players.values():
            p.hole_cards=[]; p.current_bet=0; p.total_bet=0
            p.is_dealer=False; p.is_small_blind=False; p.is_big_blind=False
        self._pk_state=None; self._street='preflop'; await self._broadcast_state()
        logger.info(f"[{self.name}] Hand #{self._hand_round} done")

    def _apply_action(self,pk,ai,action):
        if action is None:
            tc=max(pk.bets)-pk.bets[ai] if pk.bets else 0
            if tc<=0 and pk.can_check_or_call(): pk.check_or_call()
            elif pk.can_fold(): pk.fold()
            elif pk.can_check_or_call(): pk.check_or_call()
        elif action.action==ActionType.FOLD:
            if pk.can_fold(): pk.fold()
            elif pk.can_check_or_call(): pk.check_or_call()
        elif action.action in (ActionType.CALL,ActionType.CHECK):
            if pk.can_check_or_call(): pk.check_or_call()
            elif pk.can_fold(): pk.fold()
        elif action.action in (ActionType.RAISE,ActionType.ALL_IN):
            if pk.can_complete_bet_or_raise_to():
                mn=pk.min_completion_betting_or_raising_to_amount
                mx=pk.max_completion_betting_or_raising_to_amount
                pk.complete_bet_or_raise_to(max(mn,min(action.amount,mx)))
            elif pk.can_check_or_call(): pk.check_or_call()
            elif pk.can_fold(): pk.fold()

    def _sync_pk(self,pk,ordered):
        for i,ps in enumerate(ordered):
            if i<len(pk.stacks): ps.chips=int(pk.stacks[i])
            if i<len(pk.bets): ps.current_bet=int(pk.bets[i])
            if i<len(pk.hole_cards) and pk.hole_cards[i]:
                ps.hole_cards=[str(c) for c in pk.hole_cards[i] if c]
            if i<len(pk.statuses) and not pk.statuses[i]: ps.status=PlayerStatus.FOLDED

    async def _wait_for_action(self,user_id,timeout):
        deadline=asyncio.get_event_loop().time()+timeout
        while True:
            rem=deadline-asyncio.get_event_loop().time()
            if rem<=0: return None
            try:
                req=await asyncio.wait_for(self._action_queue.get(),timeout=rem)
                if req.user_id==user_id: return req
            except asyncio.TimeoutError: return None

    async def handle_player_action(self,user_id,action,amount=0):
        await self._action_queue.put(PlayerActionRequest(user_id=user_id,table_id=self.id,action=action,amount=amount))

    async def _broadcast_state(self):
        if not self._ws_manager: return
        try: await self._ws_manager.broadcast_to_table(self.id,{'type':'game_update','data':self.get_state()})
        except Exception as e: logger.error(f"[{self.name}] broadcast: {e}")

    def get_state(self):
        pk=self._pk_state; pd=[ps.to_dict() for ps in self.players.values()]
        community=[str(c) for c in pk.board_cards if c] if pk and pk.board_cards else []
        pot=0
        if pk:
            try: pot=int(pk.total_pot_amount)
            except: pot=sum(int(b) for b in pk.bets) if pk.bets else 0
        timer=None
        if self._action_deadline:
            try: timer=max(0,int(self._action_deadline-asyncio.get_event_loop().time()))
            except: pass
        mr=self.big_blind
        if pk and pk.actor_index is not None:
            try:
                v=pk.min_completion_betting_or_raising_to_amount
                if v: mr=int(v)
            except: pass
        gs=self.game_state
        return {'table_id':self.id,'table_name':self.name,
            'status':gs.status.value if gs and hasattr(gs.status,'value') else 'waiting',
            'round':gs.round if gs else 0,'pot':pot,'community_cards':community,
            'current_bet':int(max(pk.bets)) if pk and pk.bets else 0,
            'current_player_index':gs.current_player_index if gs else 0,
            'current_actor':self._current_actor_uid,'action_timer':timer,
            'dealer_index':gs.dealer_index if gs else 0,'players':pd,
            'min_raise':mr,'max_players':self.max_players,
            'small_blind':self.small_blind,'big_blind':self.big_blind,'betting_round':self._street}

    def get_info(self):
        return Table(id=self.id,name=self.name,game_type=self.game_type,tournament_id=self.tournament_id,
            max_players=self.max_players,status=self.status,
            players=[ps.to_pydantic() for ps in self.players.values()],spectators=list(self.spectators))

    async def close(self):
        if self._game_task: self._game_task.cancel()
        self._delete_state()

    @staticmethod
    def _make_deck():
        d=[f"{r}{s}" for s in 'hdcs' for r in ['2','3','4','5','6','7','8','9','T','J','Q','K','A']]
        random.shuffle(d); return d

    def _save_state(self):
        try:
            data={'table_id':self.id,'name':self.name,'tournament_id':self.tournament_id,
                  'small_blind':self.small_blind,'big_blind':self.big_blind,'max_players':self.max_players,
                  'hand_round':self._hand_round,'dealer_btn':self._dealer_btn,
                  'status':self.status.value if hasattr(self.status,'value') else str(self.status),
                  'players':{uid:{'user_id':ps.user_id,'username':ps.username,'avatar':ps.avatar,
                                  'chips':ps.chips,'position':ps.position,
                                  'status':ps.status.value if hasattr(ps.status,'value') else str(ps.status)}
                             for uid,ps in self.players.items()},
                  'saved_at':datetime.utcnow().isoformat()}
            with open(STATE_DIR/f"{self.id}.json",'w') as f: json.dump(data,f,indent=2)
        except Exception as e: logger.error(f"[{self.name}] save: {e}")
    def _delete_state(self):
        try: (STATE_DIR/f"{self.id}.json").unlink(missing_ok=True)
        except: pass
    @classmethod
    def load_state(cls,table_id):
        p=STATE_DIR/f"{table_id}.json"
        if not p.exists(): return None
        try:
            with open(p) as f: return json.load(f)
        except: return None
