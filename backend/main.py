# backend/main.py - Version corrigée

from datetime import timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketState
import os
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Set
import uuid
import json
import hashlib
import magic

from .utils import json_response, JSONEncoder
from .models import (
    CreateTableRequest, JoinTableRequest, PlayerActionRequest,
    ActionType, CreateUserRequest, TableStatus,
    LoginRequest, RegisterRequest, UpdateProfileRequest, ChangePasswordRequest,
    CreateTournamentRequest, RegisterTournamentRequest, TournamentInfo, UpdateTournamentRequest, 
)
from .lobby import Lobby
from .websocket_manager import WebSocketManager
from .logger import poker_logger
from .auth import auth_manager
from .session import get_current_user, get_current_user_optional, require_admin
from .tournament import TournamentManager, TournamentStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Multiplayer Poker Game", version="1.0.0")

# Configuration des uploads
UPLOAD_DIR = Path("frontend/assets/uploads/avatars")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

# Encodeur JSON personnalisé
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if hasattr(obj, 'value'):
            return obj.value
        return super().default(obj)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chemins
BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

# Servir les fichiers statiques
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
    app.mount("/uploads", StaticFiles(directory=str(Path("frontend/assets/uploads"))), name="uploads")

# Instances
lobby              = Lobby()
ws_manager         = WebSocketManager()
tournament_manager = lobby.tournament_manager   # ← réutiliser celui du lobby
tournament_manager.set_ws_manager(ws_manager)
lobby._ws_manager  = ws_manager

def read_html_file(filepath: Path) -> str:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading {filepath}: {e}")
        return f"<html><body><h1>Error: {e}</h1></body></html>"

# Chat Manager
class ChatManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.usernames: Dict[str, str] = {}
        self.messages: list = []
    
    async def broadcast(self, message: dict, exclude: str = None):
        message['timestamp'] = datetime.utcnow().isoformat()
        self.messages.append(message)
        while len(self.messages) > 200:
            self.messages.pop(0)
        
        for user_id, ws in list(self.connections.items()):
            if exclude != user_id and ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_json(message)
                except:
                    pass
    
    async def add_connection(self, websocket: WebSocket, user_id: str, username: str):
        self.connections[user_id] = websocket
        self.usernames[user_id] = username
        await self.broadcast({
            'type': 'system',
            'message': f'{username} joined the lobby',
            'user_count': len(self.connections)
        })
        logger.info(f"User {username} joined chat")
    
    async def remove_connection(self, user_id: str):
        if user_id in self.connections:
            username = self.usernames.get(user_id, 'Someone')
            del self.connections[user_id]
            del self.usernames[user_id]
            await self.broadcast({
                'type': 'system',
                'message': f'{username} left the lobby',
                'user_count': len(self.connections)
            })
            logger.info(f"User {username} left chat")

chat_manager = ChatManager()

# ==================== EVENT HANDLERS ====================
@app.on_event("startup")
async def startup_event():
    await lobby.start()
    poker_logger.log_system("Poker game server started", "INFO")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
 
    # Démarrer le monitor de tournois (event loop maintenant active)
    tournament_manager.start_monitor_safe()
    for t in tournament_manager.tournaments.values():
        if t.status == TournamentStatus.IN_PROGRESS:
            for tid in t.tables:
                if tid not in lobby.tables:
                    logger.info(f"Recreating table {tid} for tournament {t.name}")
                    from backend.game_engine import PokerTable
                    from backend.models import GameType
                    blinds = t.get_current_blinds()
                    table = PokerTable(
                        table_id=tid,
                        name=f"{t.name} — Table",
                        game_type=GameType.TOURNAMENT,
                        max_players=9,
                        min_buy_in=0, max_buy_in=0,
                        small_blind=blinds.get('small_blind', 10),
                        big_blind=blinds.get('big_blind', 20),
                        tournament_id=t.id,
                    )
                    lobby.tables[tid] = table
                    # Re-ajouter les joueurs de cette table
                    for p in t.players:
                        if p.get('table_id') == tid and p.get('status') == 'registered':
                            chips = p.get('chips', 10000)
                            user_data = auth_manager.get_user_by_id(p['user_id'])
                            if user_data:
                                from backend.models import User
                                user = User(**user_data)
                                lobby.users[user.id] = user
                                import asyncio
                                asyncio.create_task(table.add_player(user, chips))
                                logger.info(f"  → {p['username']} re-seated ({chips} chips)")
    # Nettoyer les vieux avatars
    try:
        now = datetime.utcnow()
        for file in UPLOAD_DIR.glob("*"):
            if file.is_file():
                file_age = now - datetime.fromtimestamp(file.stat().st_mtime)
                if file_age.days > 30:
                    file.unlink()
                    logger.info(f"Deleted old avatar: {file.name}")
    except Exception as e:
        logger.error(f"Error cleaning avatars: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    await lobby.stop()
    poker_logger.log_system("Poker game server stopped", "INFO")

# ==================== HTML ROUTES ====================
@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = FRONTEND_DIR / "index.html"
    return HTMLResponse(content=read_html_file(index_file)) if index_file.exists() else HTMLResponse("<h1>Frontend not found</h1>")

@app.get("/lobby", response_class=HTMLResponse)
async def lobby_page():
    lobby_file = FRONTEND_DIR / "lobby.html"
    return HTMLResponse(content=read_html_file(lobby_file)) if lobby_file.exists() else HTMLResponse("<h1>Lobby not found</h1>")

@app.get("/api/tournaments/{tournament_id}/my-table")
async def get_my_tournament_table(tournament_id: str, current_user: Dict = Depends(get_current_user)):
    """Retourne la table du joueur dans un tournoi actif"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    if tournament.status != TournamentStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Tournament not in progress")
 
    # Trouver la table du joueur
    for player in tournament.players:
        if player.get('user_id') == current_user['id'] and player.get('status') == 'registered':
            table_id = player.get('table_id')
            if table_id:
                return json_response({
                    "table_id": table_id,
                    "position": player.get('position', 0),
                    "chips": player.get('chips', 0),
                })
 
    raise HTTPException(status_code=404, detail="You are not in this tournament")
'''
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# 6. main.py — AJOUTER route /api/tournaments/{id}/player-table/{user_id}
#    (pour le spectating d'un joueur spécifique)
# ═══════════════════════════════════════════════════════════════════════════════
 
MAIN_PLAYER_TABLE_ROUTE = '''
@app.get("/api/tournaments/{tournament_id}/player-table/{user_id}")
async def get_player_tournament_table(tournament_id: str, user_id: str):
    """Retourne la table d'un joueur spécifique (pour spectating)"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    for player in tournament.players:
        if player.get('user_id') == user_id and player.get('table_id'):
            return json_response({
                "table_id": player['table_id'],
                "username": player.get('username', '?'),
            })
 
    raise HTTPException(status_code=404, detail="Player not found in tournament")

@app.get("/table/{table_id}", response_class=HTMLResponse)
async def table_page(table_id: str):
    table_file = FRONTEND_DIR / "table.html"
    if not table_file.exists():
        return HTMLResponse("<h1>Table page not found</h1>")
    
    # Chercher le nom de la table si elle existe en mémoire
    table = lobby.tables.get(table_id)
    table_name = table.name if table else table_id
    
    content = read_html_file(table_file)
    script = f'<script>window.tableId = "{table_id}"; window.tableName = "{table_name}";</script>'
    content = content.replace('</head>', f'{script}</head>')
    return HTMLResponse(content=content)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    login_file = FRONTEND_DIR / "login.html"
    return HTMLResponse(content=read_html_file(login_file)) if login_file.exists() else HTMLResponse("<h1>Login page not found</h1>")

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    register_file = FRONTEND_DIR / "register.html"
    return HTMLResponse(content=read_html_file(register_file)) if register_file.exists() else HTMLResponse("<h1>Register page not found</h1>")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    admin_file = FRONTEND_DIR / "admin.html"
    return HTMLResponse(content=read_html_file(admin_file)) if admin_file.exists() else HTMLResponse("<h1>Admin page not found</h1>")

@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    profile_file = FRONTEND_DIR / "profile.html"
    return HTMLResponse(content=read_html_file(profile_file)) if profile_file.exists() else HTMLResponse("<h1>Profile page not found</h1>")

# ==================== API ROUTES ====================
@app.get("/api/server/time")
async def server_time():
    now = datetime.utcnow()
    return json_response({
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.isoformat(),
        "iso": now.isoformat()
    })

# backend/main.py - Ajouter la route /api/tables manquante
@app.get("/api/tables")
async def list_tables():
    """Liste les tables (pour compatibilité)"""
    tables = []
    for table in lobby.tables.values():
        table_info = table.get_info()
        tables.append({
            "id": table_info.id,
            "name": table_info.name,
            "game_type": table_info.game_type,
            "max_players": table_info.max_players,
            "current_players": len(table_info.players),
            "status": table_info.status,
            "small_blind": table_info.small_blind,
            "big_blind": table_info.big_blind,
            "min_buy_in": table_info.min_buy_in,
            "max_buy_in": table_info.max_buy_in
        })
    return json_response(tables)

# Auth
@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    success = auth_manager.create_user(request.username, request.password, request.email)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    user = auth_manager.authenticate(request.username, request.password)
    session_id = auth_manager.create_session(user['id'])
    
    response = json_response({"success": True, "user": user, "session_id": session_id})
    response.set_cookie(key="poker_session", value=session_id, httponly=True, secure=False, samesite="lax", max_age=604800)
    return response

@app.post("/api/auth/login")
async def login(request: LoginRequest, response: Response):
    user = auth_manager.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = auth_manager.create_session(user['id'])
    max_age = 604800 if request.remember_me else 86400
    
    response_data = json_response({"success": True, "user": user, "session_id": session_id})
    response_data.set_cookie(key="poker_session", value=session_id, httponly=True, secure=False, samesite="lax", max_age=max_age)
    return response_data

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get('poker_session')
    if session_id:
        auth_manager.delete_session(session_id)
    response = JSONResponse({"success": True})
    response.delete_cookie("poker_session")
    return response

@app.get("/api/auth/me")
async def get_me(current_user: Dict = Depends(get_current_user_optional)):
    if not current_user:
        return json_response(None)
    return json_response({
        "id": current_user.get('id'),
        "username": current_user.get('username'),
        "email": current_user.get('email'),
        "avatar": current_user.get('avatar', 'default'),
        "is_admin": current_user.get('is_admin', False)
    })

@app.put("/api/auth/me")
async def update_profile(request: UpdateProfileRequest, current_user: Dict = Depends(get_current_user)):
    update_data = {k: v for k, v in request.model_dump().items() if v is not None}
    success = auth_manager.update_user(current_user['id'], update_data)
    if not success:
        raise HTTPException(status_code=400, detail="Update failed")
    updated_user = auth_manager.get_user_by_id(current_user['id'])
    return json_response(updated_user)

@app.post("/api/auth/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)):
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max size: {MAX_AVATAR_SIZE // 1024}KB")
    
    contents = await file.read()
    try:
        mime = magic.from_buffer(contents, mime=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not detect file type: {str(e)}")
    
    if mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}")
    
    ext = mime.split('/')[1]
    if ext == 'jpeg':
        ext = 'jpg'
    
    file_hash = hashlib.md5(contents).hexdigest()[:8]
    filename = f"{current_user['id']}_{file_hash}_{int(datetime.utcnow().timestamp())}.{ext}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, 'wb') as f:
        f.write(contents)
    
    avatar_url = f"/uploads/avatars/{filename}"
    success = auth_manager.update_user(current_user['id'], {'avatar': avatar_url})
    
    if not success:
        filepath.unlink()
        raise HTTPException(status_code=500, detail="Failed to update user profile")
    
    return json_response({"avatar_url": avatar_url})

# Tournaments
@app.get("/api/tournaments")
async def list_tournaments():
    all_tournaments = tournament_manager.get_all_tournaments()
    return json_response([t.to_dict() for t in all_tournaments])

# backend/main.py - Modifier create_tournament
# backend/main.py - Modifier la route create_tournament
@app.post("/api/tournaments")
async def create_tournament(request: CreateTournamentRequest, current_user: Dict = Depends(require_admin)):
    try:
        now = datetime.utcnow()
        
        # Validation des dates
        if request.registration_start >= request.registration_end:
            raise HTTPException(status_code=400, detail="Registration end must be after registration start")
        
        # Late registration: registration_end peut être après start_time
        if request.start_time <= now:
            raise HTTPException(status_code=400, detail="Start time must be in the future")
        
        tournament = tournament_manager.create_tournament(
            name=request.name,
            description=request.description or "",
            registration_start=request.registration_start,
            registration_end=request.registration_end,
            start_time=request.start_time,
            max_players=request.max_players,
            min_players_to_start=request.min_players_to_start,
            prize_pool=request.prize_pool,
            itm_percentage=request.itm_percentage,
            blind_structure=request.blind_structure
        )
        return json_response(tournament.to_dict())
    except Exception as e:
        logger.error(f"Error creating tournament: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/tournaments/{tournament_id}/register")
async def register_tournament(tournament_id: str, current_user: Dict = Depends(get_current_user)):
    success = tournament_manager.register_player(tournament_id, current_user['id'], current_user['username'])
    if not success:
        raise HTTPException(status_code=400, detail="Cannot register for tournament")
    return json_response({"success": True})

@app.post("/api/tournaments/{tournament_id}/unregister")
async def unregister_tournament(tournament_id: str, current_user: Dict = Depends(get_current_user)):
    success = tournament_manager.unregister_player(tournament_id, current_user['id'])
    if not success:
        raise HTTPException(status_code=400, detail="Cannot unregister from tournament")
    return json_response({"success": True})

@app.get("/api/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str):
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return json_response(tournament_manager.get_tournament_info_extended(tournament))

@app.get("/api/tournaments/{tournament_id}/registered/{user_id}")
async def check_tournament_registration(tournament_id: str, user_id: str):
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return json_response({"registered": tournament.is_registered(user_id)})

@app.get("/api/tournaments/{tournament_id}/tables")
async def get_tournament_tables(tournament_id: str):
    """Liste les tables d'un tournoi"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    tables = []
    for table_id in tournament.tables:
        table = lobby.tables.get(table_id)
        if table:
            table_info = table.get_info()
            tables.append({
                "id": table_info.id,
                "name": table_info.name,
                "current_players": len(table_info.players),
                "max_players": table_info.max_players
            })
    
    return json_response(tables)

# Admin
@app.get("/api/admin/stats")
async def admin_stats(current_user: Dict = Depends(require_admin)):
    active_users = len([u for u in lobby.users.values() if u.last_active and (datetime.utcnow() - u.last_active).seconds < 300])
    return json_response({
        "total_users": len(lobby.users),
        "active_users": active_users,
        "total_tables": len(lobby.tables),
        "active_tournaments": len([t for t in tournament_manager.tournaments.values() if t.status == TournamentStatus.IN_PROGRESS]),
        "total_chips": 0,
        "total_hands": 0
    })

@app.get("/api/admin/users")
async def admin_users(search: str = "", current_user: Dict = Depends(require_admin)):
    users = list(lobby.users.values())
    if search:
        users = [u for u in users if search.lower() in u.username.lower() or (u.email and search.lower() in u.email.lower())]
    return json_response([u.model_dump() for u in users])

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: str, request: dict, current_user: Dict = Depends(require_admin)):
    user = await lobby.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for key, value in request.items():
        if hasattr(user, key) and key not in ['id', 'created_at']:
            setattr(user, key, value)
    await lobby.storage.save_user(user.model_dump())
    return json_response({"success": True})

@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, current_user: Dict = Depends(require_admin)):
    if user_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await lobby.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    del lobby.users[user_id]
    user_file = lobby.storage.users_dir / f"{user_id}.xml"
    if user_file.exists():
        user_file.unlink()
    return json_response({"success": True})

@app.put("/api/admin/users/{user_id}/role")
async def admin_toggle_role(user_id: str, request: dict, current_user: Dict = Depends(require_admin)):
    if user_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    user = await lobby.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = request.get('is_admin', False)
    await lobby.storage.save_user(user.model_dump())
    return json_response({"success": True})

@app.delete("/api/admin/tournaments/{tournament_id}")
async def admin_cancel_tournament(tournament_id: str, current_user: Dict = Depends(require_admin)):
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    tournament.status = TournamentStatus.CANCELLED
    tournament_manager.save_tournament(tournament)
    return json_response({"success": True})

# ==================== WEBSOCKET ROUTES ====================
@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    user_id = None
    username = None
 
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type', '')
 
            if msg_type == 'join':
                user_id = data.get('user_id', str(uuid.uuid4()))
                username = data.get('username', 'Guest')
                await chat_manager.add_connection(websocket, user_id, username)
                # Envoyer l'historique récent
                for msg in chat_manager.messages[-50:]:
                    try:
                        await websocket.send_json(msg)
                    except Exception:
                        break
 
            elif msg_type == 'message' and user_id:
                text = data.get('message', '').strip()
                if text:
                    await chat_manager.broadcast({
                        'type': 'message',
                        'user_id': user_id,
                        'username': username,
                        'message': text
                    })
 
            elif msg_type == 'media' and user_id:
                await chat_manager.broadcast({
                    'type': 'message',
                    'user_id': user_id,
                    'username': username,
                    'message': data.get('filename', 'media'),
                    'mediaType': data.get('mediaType'),
                    'data': data.get('data'),
                    'filename': data.get('filename')
                })
 
            elif msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
 
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Chat WS error: {e}")
    finally:
        if user_id:
            await chat_manager.remove_connection(user_id)

@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    user = auth_manager.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return json_response(user)

@app.post("/api/users")
async def create_user(request: CreateUserRequest):
    """Crée un nouvel utilisateur"""
    user = await lobby.add_user(request.username, request.email)
    return json_response({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "avatar": user.avatar,
        "is_admin": user.is_admin,
        "created_at": user.created_at
    })

# ==================== TABLE ROUTES ====================
@app.post("/api/tables")
async def create_table(request: CreateTableRequest):
    """Crée une nouvelle table (admin uniquement)"""
    table = await lobby.create_table(request)
    return json_response(table.model_dump())

@app.get("/api/tables/{table_id}")
async def get_table(table_id: str):
    """Récupère les détails d'une table"""
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    table_info = table.get_info()
    return json_response(table_info.model_dump())

@app.post("/api/tables/{table_id}/join")
async def join_table(table_id: str, request: JoinTableRequest):
    """Rejoint une table"""
    success = await lobby.join_table(request.user_id, table_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot join table")
    return json_response({"success": True})

@app.post("/api/tables/{table_id}/leave")
async def leave_table(table_id: str, user_id: str):
    """Quitte une table"""
    await lobby.leave_table(user_id)
    return json_response({"success": True})

@app.post("/api/tables/{table_id}/action")
async def player_action(table_id: str, action: PlayerActionRequest):
    """Action d'un joueur"""
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    
    await table.handle_player_action(
        action.user_id,
        action.action,
        action.amount
    )
    return json_response({"success": True})

# ==================== LOBBY ROUTES ====================
@app.get("/api/lobby")
async def lobby_info():
    """Informations du lobby"""
    info = await lobby.get_lobby_info()
    tournaments_data = []
    for t in info.tournaments:
        tournaments_data.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "max_players": t.max_players,
            "players_count": len([p for p in t.players if p.get('status') == 'registered']),
            "status": t.status,
            "start_time": t.start_time,
            "registration_start": t.registration_start,
            "registration_end": t.registration_end,
            "prize_pool": t.prize_pool,
            "itm_percentage": t.itm_percentage,
            "current_blinds": t.get_current_blinds() if hasattr(t, 'get_current_blinds') else None
        })
    
    return json_response({
        "tournaments": tournaments_data,
        "active_players": info.active_players,
        "total_players": info.total_players,
        "total_tables": info.total_tables
    })

# ==================== ADMIN ROUTES ====================
@app.put("/api/admin/tournament-settings")
async def save_tournament_settings(settings: dict, current_user: Dict = Depends(require_admin)):
    """Sauvegarde les paramètres par défaut des tournois"""
    settings_file = Path("data/tournament_settings.xml")
    root = ET.Element("tournament_settings")
    for key, value in settings.items():
        ET.SubElement(root, key).text = str(value)
    
    tree = ET.ElementTree(root)
    tree.write(settings_file, encoding='utf-8', xml_declaration=True)
    
    return json_response({"success": True})

@app.put("/api/admin/settings")
async def admin_save_settings(settings: dict, current_user: Dict = Depends(require_admin)):
    """Sauvegarde les paramètres serveur"""
    settings_file = Path("data/server_settings.xml")
    root = ET.Element("settings")
    for key, value in settings.items():
        ET.SubElement(root, key).text = str(value)
    
    tree = ET.ElementTree(root)
    tree.write(settings_file, encoding='utf-8', xml_declaration=True)
    
    return json_response({"success": True})

@app.delete("/api/admin/tables/{table_id}")
async def admin_close_table(table_id: str, current_user: Dict = Depends(require_admin)):
    """Ferme une table"""
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    
    await lobby.close_table(table_id)
    return json_response({"success": True})

# ==================== TOURNAMENT UPDATE ROUTES ====================
@app.put("/api/tournaments/{tournament_id}")
async def update_tournament(
    tournament_id: str,
    request: UpdateTournamentRequest,
    current_user: Dict = Depends(require_admin)
):
    """Met à jour un tournoi existant (admin uniquement)"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Mettre à jour les champs
    if request.name is not None:
        tournament.name = request.name
    if request.description is not None:
        tournament.description = request.description
    if request.registration_start is not None:
        tournament.registration_start = request.registration_start
    if request.registration_end is not None:
        tournament.registration_end = request.registration_end
    if request.start_time is not None:
        tournament.start_time = request.start_time
    if request.max_players is not None:
        tournament.max_players = request.max_players
    if request.min_players_to_start is not None:
        tournament.min_players_to_start = request.min_players_to_start
    if request.prize_pool is not None:
        tournament.prize_pool = request.prize_pool
    if request.itm_percentage is not None:
        tournament.itm_percentage = request.itm_percentage
    if request.blind_structure is not None:
        tournament.blind_structure = request.blind_structure
    
    tournament_manager.save_tournament(tournament)
    return json_response({"success": True, "tournament": tournament.to_dict()})

@app.delete("/api/tournaments/{tournament_id}")
async def delete_tournament(
    tournament_id: str,
    current_user: Dict = Depends(require_admin)
):
    """Supprime un tournoi (admin uniquement)"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Supprimer le fichier
    filepath = tournament_manager.tournaments_dir / f"{tournament_id}.xml"
    if filepath.exists():
        filepath.unlink()
    
    # Supprimer de la mémoire
    del tournament_manager.tournaments[tournament_id]
    
    return json_response({"success": True})

# backend/main.py - Ajouter la route pour les paramètres d'apparence
@app.put("/api/admin/appearance")
async def save_appearance_settings(settings: dict, current_user: Dict = Depends(require_admin)):
    """Sauvegarde les paramètres d'apparence"""
    settings_file = Path("data/appearance_settings.xml")
    root = ET.Element("appearance")
    for key, value in settings.items():
        ET.SubElement(root, key).text = str(value)
    
    tree = ET.ElementTree(root)
    tree.write(settings_file, encoding='utf-8', xml_declaration=True)
    
    return json_response({"success": True})

@app.get("/api/admin/appearance")
async def get_appearance_settings(current_user: Dict = Depends(require_admin)):
    """Récupère les paramètres d'apparence"""
    settings_file = Path("data/appearance_settings.xml")
    if not settings_file.exists():
        return json_response({
            "theme": "dark",
            "custom_css_url": "",
            "custom_css": ""
        })
    
    try:
        tree = ET.parse(settings_file)
        root = tree.getroot()
        return json_response({
            "theme": root.findtext("theme", "dark"),
            "custom_css_url": root.findtext("custom_css_url", ""),
            "custom_css": root.findtext("custom_css", "")
        })
    except Exception as e:
        logger.error(f"Error loading appearance settings: {e}")
        return json_response({"theme": "dark", "custom_css_url": "", "custom_css": ""})

@app.post("/api/tournaments/{tournament_id}/cancel")
async def cancel_tournament(
    tournament_id: str,
    current_user: Dict = Depends(require_admin)
):
    """Annule un tournoi (admin uniquement)"""
    tournament = tournament_manager.tournaments.get(tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    tournament.status = TournamentStatus.CANCELLED
    tournament_manager.save_tournament(tournament)
    
    return json_response({"success": True})

# ==================== AUTH EXTRA ROUTES ====================
@app.get("/api/auth/check")
async def check_auth(request: Request):
    """Vérifie si l'utilisateur est authentifié"""
    session_id = request.cookies.get('poker_session')
    if session_id:
        user_id = auth_manager.validate_session(session_id)
        if user_id:
            user = auth_manager.get_user_by_id(user_id)
            if user:
                return json_response({"authenticated": True, "user": user})
    return json_response({"authenticated": False})

@app.post("/api/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: Dict = Depends(get_current_user)
):
    """Change le mot de passe"""
    authenticated = auth_manager.authenticate(current_user['username'], request.current_password)
    if not authenticated:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    success = auth_manager.update_password(current_user['id'], request.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Password change failed")
    
    return json_response({"success": True})

# ==================== WEBSOCKET TABLE ROUTES ====================
@app.websocket("/ws/{table_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, table_id: str, user_id: str):
    await websocket.accept()
 
    table = lobby.tables.get(table_id)
    if not table:
        await websocket.send_json({"type": "error", "message": "Table not found"})
        await websocket.close()
        return
 
    # Déterminer si c'est un spectateur
    is_spectator = (user_id == 'spectator'
                    or user_id.startswith('spectator_')
                    or user_id not in table.players)
 
    # Donner un ID unique aux spectateurs
    original_uid = user_id
    if user_id == 'spectator':
        user_id = f"spectator_{uuid.uuid4().hex[:8]}"
 
    await ws_manager.connect(websocket, table_id, user_id)
    poker_logger.log_connection("connected", user_id, table_id)
 
    # Envoyer l'état initial
    try:
        state = table.get_state()
        # Masquer les cartes fermées pour les spectateurs
        if is_spectator and isinstance(state, dict) and 'players' in state:
            import copy
            state = copy.deepcopy(state)
            for p in state.get('players', []):
                p['hole_cards'] = []
        await websocket.send_json({
            "type": "game_state",
            "data": state,
            "is_spectator": is_spectator
        })
    except Exception as e:
        logger.error(f"Error sending initial state: {e}")
 
    try:
        while True:
            data = await websocket.receive_json()
 
            if is_spectator:
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                continue
 
            if data.get("type") == "action":
                action = PlayerActionRequest(
                    user_id=user_id,
                    table_id=table_id,
                    action=ActionType(data.get("action")),
                    amount=data.get("amount", 0)
                )
                await table.handle_player_action(action.user_id, action.action, action.amount)
 
                state = table.get_state()
                await ws_manager.broadcast_to_table(table_id, {
                    "type": "game_update",
                    "data": state
                })
 
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
 
    except WebSocketDisconnect:
        poker_logger.log_connection("disconnected", user_id, table_id)
    finally:
        await ws_manager.disconnect(websocket, table_id, user_id)
