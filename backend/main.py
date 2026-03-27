# backend/main.py — Version complète avec 5 failles sécurité corrigées
import copy
from datetime import timezone
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketState
import os, logging, xml.etree.ElementTree as ET, asyncio
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Set
import uuid, json, hashlib

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

app = FastAPI(title="PokerEndPasse Freeroll Tournaments", version="2.0.0")

UPLOAD_DIR = Path("frontend/assets/uploads/avatars")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_AVATAR_SIZE = 2 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

if FRONTEND_DIR.exists():
    if (FRONTEND_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    if (FRONTEND_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    if (FRONTEND_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
if UPLOAD_DIR.exists():
    app.mount("/uploads/avatars", StaticFiles(directory=str(UPLOAD_DIR)), name="avatar_uploads")

# ── Instances ──
lobby = Lobby()
ws_manager = WebSocketManager()
tournament_manager = lobby.tournament_manager
tournament_manager.set_ws_manager(ws_manager)
lobby._ws_manager = ws_manager

def read_html_file(fp):
    try:
        with open(fp, 'r', encoding='utf-8') as f: return f.read()
    except Exception as e: return f"<html><body><h1>Error: {e}</h1></body></html>"

# ── Chat Manager (lobby) ──
class ChatManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.usernames: Dict[str, str] = {}
        self.messages: list = []
    async def broadcast(self, message, exclude=None):
        message['timestamp'] = datetime.utcnow().isoformat()
        self.messages.append(message)
        while len(self.messages) > 200: self.messages.pop(0)
        for uid, ws in list(self.connections.items()):
            if exclude != uid and ws.client_state == WebSocketState.CONNECTED:
                try: await asyncio.wait_for(ws.send_json(message), timeout=5)
                except: pass
    async def add_connection(self, ws, uid, username):
        self.connections[uid] = ws; self.usernames[uid] = username
        await self.broadcast({'type':'system','message':f'{username} joined','user_count':len(self.connections)})
    async def remove_connection(self, uid):
        if uid in self.connections:
            un = self.usernames.pop(uid, 'Someone'); del self.connections[uid]
            await self.broadcast({'type':'system','message':f'{un} left','user_count':len(self.connections)})

chat_manager = ChatManager()

# ══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    await lobby.start()
    poker_logger.log_system("Server started", "INFO")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tournament_manager.start_monitor_safe()
    # Crash recovery
    for t in tournament_manager.tournaments.values():
        if t.status == TournamentStatus.IN_PROGRESS:
            for tid in t.tables:
                if tid not in lobby.tables:
                    logger.info(f"[RECOVERY] Recreating table {tid}")
                    from .game_engine import PokerTable
                    from .models import GameType
                    blinds = t.get_current_blinds()
                    table = PokerTable(table_id=tid, name=t.name,
                                       game_type=GameType.TOURNAMENT, max_players=9,
                                       min_buy_in=0, max_buy_in=0,
                                       small_blind=blinds.get('small_blind', 10),
                                       big_blind=blinds.get('big_blind', 20),
                                       tournament_id=t.id)
                    table.set_ws_manager(ws_manager)
                    lobby.tables[tid] = table
                    for p in t.players:
                        if p.get('table_id') == tid and p.get('status') == 'registered':
                            ud = auth_manager.get_user_by_id(p['user_id'])
                            if ud:
                                from .models import User
                                user = User(**ud); lobby.users[user.id] = user
                                asyncio.create_task(table.add_player(user, p.get('chips', 10000)))

@app.on_event("shutdown")
async def shutdown_event():
    await lobby.stop()

# ══════════════════════════════════════════════════════════════════════════════
# HTML ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index():
    f = FRONTEND_DIR / "index.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Frontend not found</h1>")

@app.get("/lobby", response_class=HTMLResponse)
async def lobby_page():
    f = FRONTEND_DIR / "lobby.html"
    return HTMLResponse(content=read_html_file(f)) if f.exists() else HTMLResponse("<h1>Lobby not found</h1>")

@app.get("/table/{table_id}", response_class=HTMLResponse)
async def table_page(table_id: str):
    f = FRONTEND_DIR / "table.html"
    if not f.exists(): return HTMLResponse("<h1>Table not found</h1>")
    table = lobby.tables.get(table_id)
    tname = table.name if table else table_id
    content = read_html_file(f)
    content = content.replace('</head>', f'<script>window.tableId="{table_id}";window.tableName="{tname}";</script></head>')
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
    return json_response({"time": now.strftime("%H:%M:%S"), "datetime": now.isoformat()})

# ══════════════════════════════════════════════════════════════════════════════
# API — Auth (FAILLE #1 : rate limiting, FAILLE #2 : secure cookies)
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/auth/register")
async def register(request: RegisterRequest, req: Request):
    # FAILLE #1 : Rate limit register
    ip = get_client_ip(req)
    if not register_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many registrations. Try again later.")
    # FAILLE #3 : Sanitize username
    clean_username = sanitize_username(request.username)
    if len(clean_username) < 3:
        raise HTTPException(status_code=400, detail="Username must be 3+ alphanumeric characters")
    success = auth_manager.create_user(clean_username, request.password, request.email)
    if not success: raise HTTPException(status_code=400, detail="Username already exists")
    user = auth_manager.authenticate(clean_username, request.password)
    session_id = auth_manager.create_session(user['id'])
    # FAILLE #2 : Secure cookies
    cookie = get_cookie_params(req)
    resp = json_response({"success": True, "user": user, "session_id": session_id})
    resp.set_cookie(key="poker_session", value=session_id, max_age=604800, **cookie)
    return resp

@app.post("/api/auth/login")
async def login(request: LoginRequest, req: Request):
    # FAILLE #1 : Rate limit login
    ip = get_client_ip(req)
    if not login_limiter.is_allowed(ip):
        retry = login_limiter.get_retry_after(ip)
        raise HTTPException(status_code=429, detail=f"Too many login attempts. Retry in {retry}s.")
    user = auth_manager.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session_id = auth_manager.create_session(user['id'])
    max_age = 604800 if request.remember_me else 86400
    cookie = get_cookie_params(req)
    resp = json_response({"success": True, "user": user, "session_id": session_id})
    resp.set_cookie(key="poker_session", value=session_id, max_age=max_age, **cookie)
    return resp

@app.post("/api/auth/logout")
async def logout(request: Request):
    sid = request.cookies.get('poker_session')
    if sid: auth_manager.delete_session(sid)
    resp = JSONResponse({"success": True}); resp.delete_cookie("poker_session"); return resp

@app.get("/api/auth/me")
async def get_me(current_user: Dict = Depends(get_current_user_optional)):
    if not current_user: return json_response(None)
    return json_response({"id": current_user.get('id'), "username": current_user.get('username'),
                           "email": current_user.get('email'), "avatar": current_user.get('avatar', 'default'),
                           "is_admin": current_user.get('is_admin', False)})

@app.put("/api/auth/me")
async def update_profile(request: UpdateProfileRequest, current_user: Dict = Depends(get_current_user)):
    update_data = {k: v for k, v in request.model_dump().items() if v is not None}
    if 'username' in update_data:
        update_data['username'] = sanitize_username(update_data['username'])
    success = auth_manager.update_user(current_user['id'], update_data)
    if not success: raise HTTPException(status_code=400, detail="Update failed")
    return json_response(auth_manager.get_user_by_id(current_user['id']))

@app.post("/api/auth/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)):
    file.file.seek(0, 2); fsize = file.file.tell(); file.file.seek(0)
    if fsize > MAX_AVATAR_SIZE: raise HTTPException(status_code=400, detail="File too large")
    contents = await file.read()
    try:
        import magic
        mime = magic.from_buffer(contents, mime=True)
    except: raise HTTPException(status_code=400, detail="Could not detect type")
    if mime not in ALLOWED_IMAGE_TYPES: raise HTTPException(status_code=400, detail=f"Type not allowed: {mime}")
    ext = 'jpg' if mime == 'image/jpeg' else mime.split('/')[1]
    fhash = hashlib.md5(contents).hexdigest()[:8]
    filename = f"{current_user['id']}_{fhash}_{int(datetime.utcnow().timestamp())}.{ext}"
    fp = UPLOAD_DIR / filename
    with open(fp, 'wb') as f: f.write(contents)
    avatar_url = f"/uploads/avatars/{filename}"
    ok = auth_manager.update_user(current_user['id'], {'avatar': avatar_url})
    if not ok: fp.unlink(); raise HTTPException(status_code=500, detail="Failed")
    return json_response({"avatar_url": avatar_url})

@app.get("/api/auth/check")
async def check_auth(request: Request):
    sid = request.cookies.get('poker_session')
    if sid:
        uid = auth_manager.validate_session(sid)
        if uid:
            user = auth_manager.get_user_by_id(uid)
            if user: return json_response({"authenticated": True, "user": user})
    return json_response({"authenticated": False})

@app.post("/api/auth/change-password")
async def change_password(request: ChangePasswordRequest, current_user: Dict = Depends(get_current_user)):
    if not auth_manager.authenticate(current_user['username'], request.current_password):
        raise HTTPException(status_code=401, detail="Current password incorrect")
    if not auth_manager.update_password(current_user['id'], request.new_password):
        raise HTTPException(status_code=400, detail="Password change failed")
    return json_response({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Users / Tables / Lobby
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    user = auth_manager.get_user_by_id(user_id)
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return json_response(user)

@app.get("/api/tables")
async def list_tables():
    return json_response([{"id": t.get_info().id, "name": t.get_info().name,
                            "current_players": len(t.get_info().players), "max_players": t.max_players,
                            "status": t.status} for t in lobby.tables.values()])

@app.get("/api/tables/{table_id}")
async def get_table(table_id: str):
    table = lobby.tables.get(table_id)
    if not table: raise HTTPException(status_code=404, detail="Table not found")
    return json_response(table.get_info().model_dump())

@app.post("/api/tables/{table_id}/leave")
async def leave_table(table_id: str, user_id: str):
    await lobby.leave_table(user_id); return json_response({"success": True})

@app.get("/api/lobby")
async def lobby_info():
    info = await lobby.get_lobby_info()
    td = [{"id": t.id, "name": t.name, "description": t.description, "max_players": t.max_players,
           "players_count": len([p for p in t.players if p.get('status')=='registered']),
           "status": t.status, "start_time": t.start_time,
           "registration_start": t.registration_start, "registration_end": t.registration_end,
           "prize_pool": t.prize_pool, "itm_percentage": t.itm_percentage,
           "current_blinds": t.get_current_blinds() if hasattr(t,'get_current_blinds') else None}
          for t in info.tournaments]
    return json_response({"tournaments": td, "active_players": info.active_players,
                           "total_players": info.total_players, "total_tables": info.total_tables})

# ══════════════════════════════════════════════════════════════════════════════
# API — Tournaments
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/tournaments")
async def list_tournaments():
    return json_response([t.to_dict() for t in tournament_manager.get_all_tournaments()])

@app.post("/api/tournaments")
async def create_tournament(request: CreateTournamentRequest, current_user: Dict = Depends(require_admin)):
    t = tournament_manager.create_tournament(
        name=sanitize_text(request.name, 100), description=sanitize_text(request.description or "", 500),
        registration_start=request.registration_start, registration_end=request.registration_end,
        start_time=request.start_time, max_players=request.max_players,
        min_players_to_start=request.min_players_to_start,
        prize_pool=request.prize_pool, itm_percentage=request.itm_percentage,
        blind_structure=request.blind_structure)
    return json_response(t.to_dict())

@app.get("/api/tournaments/{tid}")
async def get_tournament(tid: str):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404, detail="Tournament not found")
    return json_response(tournament_manager.get_tournament_info_extended(t))

@app.post("/api/tournaments/{tid}/register")
async def register_tournament(tid: str, current_user: Dict = Depends(get_current_user)):
    ok = tournament_manager.register_player(tid, current_user['id'], current_user['username'], current_user.get('avatar'))
    if not ok: raise HTTPException(status_code=400, detail="Cannot register")
    return json_response({"success": True})

@app.post("/api/tournaments/{tid}/unregister")
async def unregister_tournament(tid: str, current_user: Dict = Depends(get_current_user)):
    ok = tournament_manager.unregister_player(tid, current_user['id'])
    if not ok: raise HTTPException(status_code=400, detail="Cannot unregister")
    return json_response({"success": True})

@app.get("/api/tournaments/{tid}/tables")
async def get_tournament_tables(tid: str):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404, detail="Tournament not found")
    tables = []
    for table_id in t.tables:
        table = lobby.tables.get(table_id)
        if table:
            info = table.get_info()
            tables.append({"id": info.id, "name": info.name, "current_players": len(info.players), "max_players": info.max_players})
    return json_response(tables)

@app.get("/api/tournaments/{tid}/my-table")
async def get_my_table(tid: str, current_user: Dict = Depends(get_current_user)):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404, detail="Tournament not found")
    for p in t.players:
        if p.get('user_id') == current_user['id'] and p.get('status') == 'registered' and p.get('table_id'):
            return json_response({"table_id": p['table_id'], "position": p.get('position', 0), "chips": p.get('chips', 0)})
    raise HTTPException(status_code=404, detail="Not in tournament")

@app.get("/api/tournaments/{tid}/player-table/{user_id}")
async def get_player_table(tid: str, user_id: str):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404, detail="Tournament not found")
    for p in t.players:
        if p.get('user_id') == user_id and p.get('table_id'):
            return json_response({"table_id": p['table_id'], "username": p.get('username', '?')})
    raise HTTPException(status_code=404, detail="Player not found")

@app.put("/api/tournaments/{tid}")
async def update_tournament(tid: str, request: UpdateTournamentRequest, current_user: Dict = Depends(require_admin)):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404, detail="Tournament not found")
    for field in ['name','description','registration_start','registration_end','start_time',
                  'max_players','min_players_to_start','prize_pool','itm_percentage','blind_structure']:
        val = getattr(request, field, None)
        if val is not None: setattr(t, field, val)
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.delete("/api/tournaments/{tid}")
async def delete_tournament(tid: str, current_user: Dict = Depends(require_admin)):
    if tid not in tournament_manager.tournaments: raise HTTPException(status_code=404)
    fp = tournament_manager.tournaments_dir / f"{tid}.xml"
    if fp.exists(): fp.unlink()
    del tournament_manager.tournaments[tid]
    return json_response({"success": True})

@app.post("/api/tournaments/{tid}/cancel")
async def cancel_tournament(tid: str, current_user: Dict = Depends(require_admin)):
    t = tournament_manager.tournaments.get(tid)
    if not t: raise HTTPException(status_code=404)
    t.status = TournamentStatus.CANCELLED; tournament_manager.save_tournament(t)
    return json_response({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# API — Admin
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/admin/stats")
async def admin_stats(current_user: Dict = Depends(require_admin)):
    return json_response({"total_users": len(lobby.users), "total_tables": len(lobby.tables),
                           "active_tournaments": len([t for t in tournament_manager.tournaments.values() if t.status==TournamentStatus.IN_PROGRESS])})

@app.get("/api/admin/users")
async def admin_users(search: str = "", current_user: Dict = Depends(require_admin)):
    users = list(lobby.users.values())
    if search:
        s = search.lower()
        users = [u for u in users if s in u.username.lower() or (u.email and s in u.email.lower())]
    return json_response([{"id": u.id, "username": u.username, "email": u.email, "is_admin": u.is_admin} for u in users])

@app.delete("/api/admin/tables/{table_id}")
async def admin_close_table(table_id: str, current_user: Dict = Depends(require_admin)):
    if table_id not in lobby.tables: raise HTTPException(status_code=404)
    await lobby.close_table(table_id); return json_response({"success": True})

@app.put("/api/admin/settings")
async def admin_save_settings(settings: dict, current_user: Dict = Depends(require_admin)):
    sf = Path("data/server_settings.xml"); root = ET.Element("settings")
    for k, v in settings.items(): ET.SubElement(root, k).text = xml_safe(str(v))
    ET.ElementTree(root).write(sf, encoding='utf-8', xml_declaration=True)
    return json_response({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Lobby Chat
# ══════════════════════════════════════════════════════════════════════════════
@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    user_id = None; username = None
    try:
        while True:
            data = await websocket.receive_json()
            mt = data.get('type', '')
            if mt == 'join':
                user_id = data.get('user_id', str(uuid.uuid4()))
                username = sanitize_username(data.get('username', 'Guest'))
                await chat_manager.add_connection(websocket, user_id, username)
                for msg in chat_manager.messages[-50:]:
                    try: await websocket.send_json(msg)
                    except: break
            elif mt == 'message' and user_id:
                # FAILLE #3 : Sanitize chat server-side
                text = sanitize_chat_message(data.get('message', ''))
                if text: await chat_manager.broadcast({'type':'message','user_id':user_id,'username':username,'message':text})
            elif mt == 'ping': await websocket.send_json({'type':'pong'})
    except WebSocketDisconnect: pass
    except Exception as e: logger.error(f"Chat WS: {e}")
    finally:
        if user_id: await chat_manager.remove_connection(user_id)

# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Table (FAILLE #4 : auth WS)
# ══════════════════════════════════════════════════════════════════════════════
@app.websocket("/ws/{table_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, table_id: str, user_id: str):
    await websocket.accept()

    # FAILLE #1 : Rate limit WS connections
    ip = get_client_ip(websocket)
    if not ws_connect_limiter.is_allowed(ip):
        await websocket.send_json({"type": "error", "message": "Too many connections"})
        await websocket.close(); return

    # FAILLE #4 : Authentifier le WebSocket via cookie de session
    if user_id != 'spectator' and not user_id.startswith('spectator_'):
        validated_uid, force_spectator = authenticate_websocket(websocket, user_id)
        user_id = validated_uid
        is_spectator = force_spectator
    else:
        is_spectator = True

    if user_id == 'spectator': user_id = f"spectator_{uuid.uuid4().hex[:8]}"

    table = lobby.tables.get(table_id)
    # Même si authentifié, spectateur si pas dans les joueurs de la table
    if not is_spectator and table and user_id not in table.players:
        is_spectator = True

    await ws_manager.connect(websocket, table_id, user_id)

    # Injecter ws_manager
    if table and not table._ws_manager: table.set_ws_manager(ws_manager)

    # État initial
    if table:
        try:
            state = table.get_state()
            if is_spectator and isinstance(state, dict):
                state = copy.deepcopy(state)
                for p in state.get('players', []): p['hole_cards'] = []
            await websocket.send_json({"type":"game_state","data":state,"is_spectator":is_spectator})
        except Exception as e: logger.error(f"Initial state: {e}")

    try:
        while True:
            data = await websocket.receive_json()
            mt = data.get("type", "")

            if mt == "action" and not is_spectator and table:
                await table.handle_player_action(user_id, ActionType(data.get("action")), data.get("amount", 0))

            elif mt == "chat":
                # FAILLE #3 : Sanitize table chat server-side
                un = "Spectator"
                if user_id in lobby.users: un = lobby.users[user_id].username
                else:
                    ud = auth_manager.get_user_by_id(user_id)
                    if ud: un = ud.get('username', user_id)
                msg_text = sanitize_chat_message(data.get("message", ""))
                if msg_text:
                    await ws_manager.broadcast_to_table(table_id, {
                        "type":"table_chat","user_id":user_id,"username":un,"message":msg_text})

            elif mt == "ping": await websocket.send_json({"type":"pong"})

    except WebSocketDisconnect: pass
    except Exception as e: logger.error(f"WS {user_id}@{table_id}: {e}")
    finally:
        await ws_manager.disconnect(websocket, table_id, user_id)
