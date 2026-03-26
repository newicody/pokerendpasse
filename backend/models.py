# backend/models.py - Version complète avec tous les modèles
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import uuid

# ==================== ENUMS ====================
class GameType(str, Enum):
    TOURNAMENT = "tournament"
    SIT_AND_GO = "sit_and_go"

class GameStatus(str, Enum):
    WAITING = "waiting"
    REGISTRATION = "registration"
    STARTING = "starting"
    IN_PROGRESS = "in_progress"
    SHOWDOWN = "showdown"
    FINISHED = "finished"

class TableStatus(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    CLOSED = "closed"

class PlayerStatus(str, Enum):
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"
    SITTING_OUT = "sitting_out"
    DISCONNECTED = "disconnected"
    ELIMINATED = "eliminated"

class ActionType(str, Enum):
    FOLD = "fold"
    CALL = "call"
    RAISE = "raise"
    CHECK = "check"
    ALL_IN = "all_in"

class TournamentStatus(str, Enum):
    REGISTRATION = "registration"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"

# ==================== USER MODELS ====================
# backend/models.py - Modifier User
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    is_admin: bool = False
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if 'created_at' in data and data['created_at']:
            data['created_at'] = data['created_at'].isoformat() if hasattr(data['created_at'], 'isoformat') else str(data['created_at'])
        if 'last_active' in data and data['last_active']:
            data['last_active'] = data['last_active'].isoformat() if hasattr(data['last_active'], 'isoformat') else str(data['last_active'])
        return data

# ==================== TABLE MODELS ====================
class TablePlayer(BaseModel):
    user_id: str
    username: str
    avatar: Optional[str] = None
    position: int = -1
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0
    total_bet: int = 0
    hole_cards: List[str] = []
    is_dealer: bool = False
    is_small_blind: bool = False
    is_big_blind: bool = False
    sat_at: datetime = Field(default_factory=datetime.utcnow)
    
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if 'sat_at' in data and data['sat_at']:
            data['sat_at'] = data['sat_at'].isoformat() if hasattr(data['sat_at'], 'isoformat') else str(data['sat_at'])
        if 'status' in data and hasattr(data['status'], 'value'):
            data['status'] = data['status'].value
        return data

class Table(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    game_type: GameType = GameType.TOURNAMENT
    tournament_id: Optional[str] = None
    max_players: int = 9
    status: TableStatus = TableStatus.WAITING
    players: List[TablePlayer] = []
    spectators: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if 'created_at' in data and data['created_at']:
            data['created_at'] = data['created_at'].isoformat() if hasattr(data['created_at'], 'isoformat') else str(data['created_at'])
        if 'status' in data and hasattr(data['status'], 'value'):
            data['status'] = data['status'].value
        if 'game_type' in data and hasattr(data['game_type'], 'value'):
            data['game_type'] = data['game_type'].value
        return data

class GameState(BaseModel):
    table_id: str
    status: GameStatus
    round: int = 0
    pot: int = 0
    community_cards: List[str] = []
    current_bet: int = 0
    current_player_index: int = 0
    dealer_index: int = 0
    small_blind_index: int = 0
    big_blind_index: int = 0
    players: List[Dict[str, Any]]
    last_action: Optional[Dict[str, Any]] = None
    min_raise: int = 10
    time_bank: int = 30
    
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if 'status' in data and hasattr(data['status'], 'value'):
            data['status'] = data['status'].value
        return data

# ==================== TOURNAMENT MODELS ====================
class TournamentPlayer(BaseModel):
    user_id: str
    username: str
    avatar: Optional[str] = None
    table_id: Optional[str] = None
    position: int = -1
    status: str = "registered"
    eliminated_at: Optional[datetime] = None
    eliminated_rank: int = 0
    registered_at: datetime = Field(default_factory=datetime.utcnow)

class Tournament(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    registration_start: datetime
    registration_end: datetime
    start_time: datetime
    max_players: int = 100
    min_players_to_start: int = 4
    status: TournamentStatus = TournamentStatus.REGISTRATION
    players: List[TournamentPlayer] = []
    tables: List[str] = []
    winners: List[Dict] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    current_level: int = 0
    blind_structure: List[Dict] = Field(default_factory=list)

# ==================== API REQUEST MODELS ====================
class CreateTableRequest(BaseModel):
    name: str
    tournament_id: str
    max_players: int = 9

class JoinTableRequest(BaseModel):
    user_id: str

class PlayerActionRequest(BaseModel):
    user_id: str
    table_id: str
    action: ActionType
    amount: Optional[int] = 0

class CreateUserRequest(BaseModel):
    username: str
    email: Optional[str] = None

# ==================== AUTH MODELS ====================
class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    email: Optional[str] = None
    avatar: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# ==================== TOURNAMENT API MODELS ====================
# backend/models.py - Modifier CreateTournamentRequest
# backend/models.py - Modifier CreateTournamentRequest
class CreateTournamentRequest(BaseModel):
    name: str
    description: Optional[str] = None
    registration_start: datetime
    registration_end: datetime
    start_time: datetime
    max_players: int = 100
    min_players_to_start: int = 4
    prize_pool: int = 0
    itm_percentage: float = 10.0
    blind_structure: Optional[List[Dict]] = None
    
    @field_validator('registration_start', 'registration_end', 'start_time', mode='before')
    @classmethod
    def parse_datetime(cls, value):
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)
        if hasattr(value, 'tzinfo') and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value
class UpdateTournamentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    registration_start: Optional[datetime] = None
    registration_end: Optional[datetime] = None
    start_time: Optional[datetime] = None
    max_players: Optional[int] = None
    min_players_to_start: Optional[int] = None
    blind_structure: Optional[List[Dict]] = None

class RegisterTournamentRequest(BaseModel):
    user_id: str

# ==================== LOBBY MODELS ====================
class LobbyInfo(BaseModel):
    tournaments: List[Tournament]
    active_players: int
    total_players: int
    total_tables: int

# backend/models.py - Ajouter ce modèle
class TournamentInfo(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    registration_start: datetime
    registration_end: datetime
    start_time: datetime
    max_players: int
    min_players_to_start: int
    status: TournamentStatus
    players_count: int
    total_players: int
    registered_players: List[Dict]
    ranking: List[Dict]
    current_level: int
    current_blinds: Dict
    blind_structure: List[Dict]
    tables: List[str]
    winners: List[Dict]
    time_until_start: Optional[int]
    can_register: bool

# backend/models.py - Supprimer les champs chips
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    is_admin: bool = False
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if 'created_at' in data and data['created_at']:
            data['created_at'] = data['created_at'].isoformat() if hasattr(data['created_at'], 'isoformat') else str(data['created_at'])
        if 'last_active' in data and data['last_active']:
            data['last_active'] = data['last_active'].isoformat() if hasattr(data['last_active'], 'isoformat') else str(data['last_active'])
        return data
