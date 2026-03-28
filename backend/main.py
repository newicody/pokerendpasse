# backend/main.py
"""
FastAPI Application — Version corrigée
======================================
Corrections:
- Lifecycle startup/shutdown propre
- Intégration WebSocket améliorée
- Gestion pong pour heartbeat
- Meilleure gestion des erreurs
"""

import copy
from datetime import timezone
from fastapi import (
    FastAPI, File, UploadFile, HTTPException, WebSocket, 
    WebSocketDisconnect, Request, Depends, Response
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketState
from contextlib import asynccontextmanager
import os
import logging
import xml.etree.ElementTree as ET
import asyncio
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Set, Optional
import uuid
import json
import hashlib

from .utils import json_response, JSONEncoder
from .models import (
    CreateTableRequest, JoinTableRequest, PlayerActionRequest,
    ActionType, CreateUserRequest, TableStatus,
    LoginRequest, RegisterRequest, UpdateProfileRequest, ChangePasswordRequest,
    CreateTournamentRequest, RegisterTournamentRequest, UpdateTournamentRequest,
)
from .lobby import Lobby
from .websocket_manager import WebSocketManager
from .logger import poker_logger
from .auth import auth_manager
from .session import get_current_user, get_current_user_optional, require_admin
from .tournament import TournamentManager, TournamentStatus
from .security import (
    login_limiter, register_limiter, ws_connect_limiter,
    get_client_ip, get_cookie_params,
    sanitize_text, sanitize_chat_message, sanitize_username,
    authenticate_websocket, xml_safe,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Paths ──
BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
UPLOAD_DIR = Path("frontend/assets/uploads/avatars")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_AVATAR_SIZE = 2 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

# ── Instances globales ──
lobby = Lobby()
ws_manager = WebSocketManager()
tournament_manager = lobby.tournament_manager

# Connecter les managers
tournament_manager.set_ws_manager(ws_manager)
lobby._ws_manager = ws_manager
ws_manager.set_tournament_manager(tournament_manager)


# ══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    # Startup
    logger.info("Starting PokerEndPasse server...")
    
    await lobby.start()
    await ws_manager.start()
    
    logger.info("Server started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down server...")
    
    await lobby.stop()
    await ws_manager.stop()
    
    logger.info("Server stopped")


app = FastAPI(
    title="PokerEndPasse Freeroll Tournaments",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── Static files ──
if FRONTEND_DIR.exists():
    if (FRONTEND_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    if (FRONTEND_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    if (FRONTEND_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

if UPLOAD_DIR.exists():
    app.mount("/uploads/avatars", StaticFiles(directory=str(UPLOAD_DIR)), name="avatar_uploads")


def read_html_file(fp: Path) -> str:
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"<html><body><h1>Error: {e}</h1></body></html>"


# ══════════════════════════════════════════════════════════════════════════════
# CHAT MANAGER (Lobby)
# ══════════════════════════════════════════════════════════════════════════════

class ChatManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.usernames: Dict[str, str] = {}
        self.messages: list = []
        self._lock = asyncio.Lock()

    async def broadcast(self, message: dict, exclude: str = None):
        message['timestamp'] = datetime.utcnow().isoformat()
        
        async with self._lock:
            self.messages.append(message)
            while len(self.messages) > 200:
                self.messages.pop(0)
        
        for uid, ws in list(self.connections.items()):
            if exclude == uid:
                continue
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await asyncio.wait_for(ws.send_json(message), timeout=5)
            except:
                pass

    async def add_connection(self, ws: WebSocket, uid: str, username: str):
        async with self._lock:
            self.connections[uid] = ws
            self.usernames[uid] = username
        
        await self.broadcast({
            'type': 'system',
            'message': f'{username} joined',
            'user_count': len(self.connections)
        })

    async def remove_connection(self, uid: str):
        async with self._lock:
            if uid in self.connections:
                un = self.usernames.pop(uid, 'Someone')
                del self.connections[uid]
        
        await self.broadcast({
            'type': 'system',
            'message': f'{un} left',
            'user_count': len(self.connections)
        })


chat_manager = ChatManager()


# ══════════════════════════════════════════════════════════════════════════════
# PAGES HTML
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content='<script>window.location.href="/lobby";</script>')


@app.get("/lobby", response_class=HTMLResponse)
async def lobby_page():
    f = FRONTEND_DIR / "lobby.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Lobby not found</h1>")


@app.get("/table/{table_id}", response_class=HTMLResponse)
async def table_page(table_id: str):
    f = FRONTEND_DIR / "table.html"
    if not f.exists():
        return HTMLResponse("<h1>Table not found</h1>")
    
    table = lobby.tables.get(table_id)
    tname = table.name if table else table_id
    content = read_html_file(f)
    content = content.replace(
        '</head>',
        f'<script>window.tableId="{table_id}";window.tableName="{tname}";</script></head>'
    )
    return HTMLResponse(content=content)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    f = FRONTEND_DIR / "login.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Login</h1>")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    f = FRONTEND_DIR / "admin.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Admin</h1>")


@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    f = FRONTEND_DIR / "profile.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Profile</h1>")


# ══════════════════════════════════════════════════════════════════════════════
# API — Server time
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/server/time")
async def server_time():
    now = datetime.utcnow()
    return json_response({
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.isoformat()
    })


# ══════════════════════════════════════════════════════════════════════════════
# API — Auth
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(request: RegisterRequest, req: Request):
    ip = get_client_ip(req)
    if not register_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many registrations. Try again later.")
    
    clean_username = sanitize_username(request.username)
    if len(clean_username) < 3:
        raise HTTPException(status_code=400, detail="Username must be 3+ alphanumeric characters")
    
    success = auth_manager.create_user(clean_username, request.password, request.email)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    user = auth_manager.authenticate(clean_username, request.password)
    session_id = auth_manager.create_session(user['id'])
    
    cookie = get_cookie_params(req)
    resp = json_response({"success": True, "user": user, "session_id": session_id})
    resp.set_cookie(key="poker_session", value=session_id, max_age=604800, **cookie)
    return resp


@app.post("/api/auth/login")
async def login(request: LoginRequest, req: Request):
    ip = get_client_ip(req)
    if not login_limiter.is_allowed(ip):
        retry = login_limiter.get_retry_after(ip)
        raise HTTPException(status_code=429, detail=f"Too many login attempts. Retry in {retry}s.")
    
    user = auth_manager.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_id = auth_manager.create_session(user['id'])
    
    cookie = get_cookie_params(req)
    max_age = 604800 if request.remember_me else 86400
    
    resp = json_response({"success": True, "user": user, "session_id": session_id})
    resp.set_cookie(key="poker_session", value=session_id, max_age=max_age, **cookie)
    return resp


@app.post("/api/auth/logout")
async def logout(req: Request):
    session_id = req.cookies.get('poker_session')
    if session_id:
        auth_manager.invalidate_session(session_id)
    
    resp = json_response({"success": True})
    resp.delete_cookie("poker_session")
    return resp


@app.get("/api/auth/me")
async def get_me(current_user: Dict = Depends(get_current_user_optional)):
    if not current_user:
        return json_response({"authenticated": False})
    return json_response({"authenticated": True, "user": current_user})


# ══════════════════════════════════════════════════════════════════════════════
# API — Tables
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tables")
async def list_tables():
    tables = await lobby.list_tables()
    return json_response([t.model_dump() for t in tables])


@app.get("/api/tables/{table_id}")
async def get_table(table_id: str):
    table = await lobby.get_table(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    return json_response(table.model_dump())


@app.post("/api/tables/{table_id}/join")
async def join_table(table_id: str, request: JoinTableRequest):
    success = await lobby.join_table(request.user_id, table_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot join table")
    return json_response({"success": True})


@app.post("/api/tables/{table_id}/leave")
async def leave_table(table_id: str, user_id: str):
    await lobby.leave_table(user_id)
    return json_response({"success": True})


# ══════════════════════════════════════════════════════════════════════════════
# API — Tournaments
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tournaments")
async def list_tournaments():
    tournaments = tournament_manager.list_tournaments()
    result = []
    
    for t in tournaments:
        registered = t.get_registered_players()
        time_until = None
        
        if t.status == TournamentStatus.REGISTRATION:
            time_until = int((t.start_time - datetime.utcnow()).total_seconds())
        
        result.append({
            'id': t.id,
            'name': t.name,
            'description': t.description,
            'status': t.status,
            'players_count': len(registered),
            'max_players': t.max_players,
            'prize_pool': t.prize_pool,
            'start_time': t.start_time.isoformat(),
            'registration_start': t.registration_start.isoformat(),
            'registration_end': t.registration_end.isoformat(),
            'can_register': t.can_register(),
            'time_until_start': max(0, time_until) if time_until else None,
            'current_level': t.current_level,
            'current_blinds': t.get_current_blinds(),
            'seconds_until_next_level': t.seconds_until_next_level(),
            'registered_players': [
                {'user_id': p['user_id'], 'username': p['username']}
                for p in registered[:20]
            ],
        })
    
    return json_response(result)


@app.get("/api/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str):
    t = tournament_manager.get_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    registered = t.get_registered_players()
    time_until = None
    
    if t.status == TournamentStatus.REGISTRATION:
        time_until = int((t.start_time - datetime.utcnow()).total_seconds())
    
    return json_response({
        'id': t.id,
        'name': t.name,
        'description': t.description,
        'status': t.status,
        'players_count': len(registered),
        'max_players': t.max_players,
        'min_players_to_start': t.min_players_to_start,
        'prize_pool': t.prize_pool,
        'itm_percentage': t.itm_percentage,
        'starting_chips': t.starting_chips,
        'start_time': t.start_time.isoformat(),
        'registration_start': t.registration_start.isoformat(),
        'registration_end': t.registration_end.isoformat(),
        'can_register': t.can_register(),
        'time_until_start': max(0, time_until) if time_until else None,
        'current_level': t.current_level,
        'current_blinds': t.get_current_blinds(),
        'blind_structure': t.blind_structure,
        'seconds_until_next_level': t.seconds_until_next_level(),
        'tables': t.tables,
        'winners': t.winners,
        'prizes': t.calculate_prizes(),
        'ranking': t.get_ranking(),
        'registered_players': [
            {'user_id': p['user_id'], 'username': p['username'], 'avatar': p.get('avatar')}
            for p in registered
        ],
    })


@app.post("/api/tournaments/{tournament_id}/register")
async def register_tournament(tournament_id: str, request: RegisterTournamentRequest):
    t = tournament_manager.get_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    # Récupérer les infos utilisateur
    user = lobby.get_user(request.user_id)
    if not user:
        user_data = auth_manager.get_user_by_id(request.user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        username = user_data.get('username', 'Unknown')
        avatar = user_data.get('avatar')
    else:
        username = user.username
        avatar = user.avatar
    
    success = t.add_player(request.user_id, username, avatar)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot register for tournament")
    
    tournament_manager.save_tournament(t)
    return json_response({"success": True})


@app.post("/api/tournaments/{tournament_id}/unregister")
async def unregister_tournament(tournament_id: str, request: RegisterTournamentRequest):
    t = tournament_manager.get_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    success = t.remove_player(request.user_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot unregister from tournament")
    
    tournament_manager.save_tournament(t)
    return json_response({"success": True})


@app.get("/api/tournaments/{tournament_id}/my-table")
async def get_my_tournament_table(tournament_id: str, user_id: str):
    """Récupère la table du joueur dans un tournoi"""
    t = tournament_manager.get_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    for p in t.players:
        if p['user_id'] == user_id and p.get('table_id'):
            return json_response({
                "table_id": p['table_id'],
                "position": p.get('position', 0)
            })
    
    raise HTTPException(status_code=404, detail="Player not found in tournament")


# ══════════════════════════════════════════════════════════════════════════════
# API — Admin
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/admin/tournaments")
async def admin_create_tournament(request: CreateTournamentRequest, current_user: Dict = Depends(require_admin)):
    t = tournament_manager.create_tournament(
        name=request.name,
        description=request.description,
        registration_start=request.registration_start,
        registration_end=request.registration_end,
        start_time=request.start_time,
        max_players=request.max_players,
        min_players_to_start=request.min_players_to_start,
        prize_pool=request.prize_pool,
        itm_percentage=request.itm_percentage,
        blind_structure=request.blind_structure,
    )
    return json_response({"success": True, "tournament_id": t.id})


@app.put("/api/admin/tournaments/{tournament_id}")
async def admin_update_tournament(tournament_id: str, request: UpdateTournamentRequest, current_user: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tournament_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if request.name:
        t.name = request.name
    if request.description is not None:
        t.description = request.description
    if request.registration_start:
        t.registration_start = request.registration_start
    if request.registration_end:
        t.registration_end = request.registration_end
    if request.start_time:
        t.start_time = request.start_time
    if request.max_players:
        t.max_players = request.max_players
    if request.min_players_to_start:
        t.min_players_to_start = request.min_players_to_start
    if request.blind_structure:
        t.blind_structure = request.blind_structure
    
    tournament_manager.save_tournament(t)
    return json_response({"success": True})


@app.delete("/api/admin/tournaments/{tournament_id}")
async def admin_delete_tournament(tournament_id: str, current_user: Dict = Depends(require_admin)):
    tournament_manager.delete_tournament(tournament_id)
    return json_response({"success": True})


@app.get("/api/admin/stats")
async def admin_stats(current_user: Dict = Depends(require_admin)):
    return json_response(lobby.get_stats())


@app.delete("/api/admin/tables/{table_id}")
async def admin_close_table(table_id: str, current_user: Dict = Depends(require_admin)):
    if table_id not in lobby.tables:
        raise HTTPException(status_code=404)
    await lobby.close_table(table_id)
    return json_response({"success": True})


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Lobby Chat
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    user_id = None
    username = None
    
    try:
        while True:
            data = await websocket.receive_json()
            mt = data.get('type', '')
            
            if mt == 'join':
                user_id = data.get('user_id', str(uuid.uuid4()))
                username = sanitize_username(data.get('username', 'Guest'))
                await chat_manager.add_connection(websocket, user_id, username)
                
                # Envoyer les messages récents
                for msg in chat_manager.messages[-50:]:
                    try:
                        await websocket.send_json(msg)
                    except:
                        break
                        
            elif mt == 'message' and user_id:
                text = sanitize_chat_message(data.get('message', ''))
                if text:
                    await chat_manager.broadcast({
                        'type': 'message',
                        'user_id': user_id,
                        'username': username,
                        'message': text
                    })
                    
            elif mt == 'ping':
                await websocket.send_json({'type': 'pong'})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Chat WS error: {e}")
    finally:
        if user_id:
            await chat_manager.remove_connection(user_id)


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Table
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{table_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, table_id: str, user_id: str):
    await websocket.accept()
    
    # Rate limiting
    ip = get_client_ip(websocket)
    if not ws_connect_limiter.is_allowed(ip):
        await websocket.send_json({"type": "error", "message": "Too many connections"})
        await websocket.close()
        return
    
    # Authentification
    is_spectator = False
    if user_id != 'spectator' and not user_id.startswith('spectator_'):
        validated_uid, force_spectator = authenticate_websocket(websocket, user_id)
        user_id = validated_uid
        is_spectator = force_spectator
    else:
        is_spectator = True
    
    if user_id == 'spectator':
        user_id = f"spectator_{uuid.uuid4().hex[:8]}"
    
    table = lobby.tables.get(table_id)
    
    # Vérifier si le joueur est dans la table
    if not is_spectator and table and user_id not in table.players:
        is_spectator = True
    
    # Connecter au WebSocket manager
    await ws_manager.connect(websocket, table_id, user_id)
    
    # Injecter le ws_manager dans la table
    if table and not table._ws_manager:
        table.set_ws_manager(ws_manager)
    
    # Envoyer l'état initial
    if table:
        try:
            state = table.get_state(for_user_id=user_id if not is_spectator else None)
            
            if is_spectator and isinstance(state, dict):
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
            mt = data.get("type", "")
            
            if mt == "action" and not is_spectator and table:
                try:
                    action = ActionType(data.get("action"))
                    amount = data.get("amount", 0)
                    await table.handle_player_action(user_id, action, amount)
                except Exception as e:
                    logger.error(f"Action error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e)
                    })
            
            elif mt == "chat":
                un = "Spectator"
                if user_id in lobby.users:
                    un = lobby.users[user_id].username
                else:
                    ud = auth_manager.get_user_by_id(user_id)
                    if ud:
                        un = ud.get('username', user_id)
                
                msg_text = sanitize_chat_message(data.get("message", ""))
                if msg_text:
                    await ws_manager.broadcast_to_table(table_id, {
                        "type": "table_chat",
                        "user_id": user_id,
                        "username": un,
                        "message": msg_text
                    })
            
            elif mt == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif mt == "pong":
                # Réponse au heartbeat du serveur
                ws_manager.handle_pong(table_id, user_id)
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error {user_id}@{table_id}: {e}")
    finally:
        await ws_manager.disconnect(websocket, table_id, user_id)
