# backend/main.py
"""
FastAPI Application — PokerEndPasse
====================================
Consolidé avec :
- Admin : pause/resume, mute, exclude
- Quick bets endpoint
- Lifecycle propre
- Heartbeat WS
"""

import copy
from datetime import timezone
from fastapi import (
    FastAPI, File, UploadFile, HTTPException, WebSocket,
    WebSocketDisconnect, Request, Depends, Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocketState
from contextlib import asynccontextmanager
import os, logging, asyncio, uuid, json, hashlib
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Set, Optional

from .utils import json_response, JSONEncoder
from .models import (
    CreateTableRequest, JoinTableRequest, PlayerActionRequest,
    ActionType, CreateUserRequest, TableStatus, AdminActionRequest,
    LoginRequest, RegisterRequest, UpdateProfileRequest, ChangePasswordRequest,
    CreateTournamentRequest, RegisterTournamentRequest, UpdateTournamentRequest,
    GameVariant,
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
tournament_manager.set_ws_manager(ws_manager)
lobby._ws_manager = ws_manager
ws_manager.set_tournament_manager(tournament_manager)


# ══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting PokerEndPasse server...")
    await lobby.start()
    await ws_manager.start()
    logger.info("Server started successfully")
    yield
    logger.info("Shutting down...")
    await lobby.stop()
    await ws_manager.stop()
    logger.info("Server stopped")


app = FastAPI(title="PokerEndPasse Freeroll Tournaments", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── Static ──
if FRONTEND_DIR.exists():
    for sub in ("css", "js", "assets"):
        d = FRONTEND_DIR / sub
        if d.exists():
            app.mount(f"/{sub}", StaticFiles(directory=str(d)), name=sub)
if UPLOAD_DIR.exists():
    app.mount("/uploads/avatars", StaticFiles(directory=str(UPLOAD_DIR)), name="avatar_uploads")


def read_html(fp: Path) -> str:
    try:
        return fp.read_text(encoding='utf-8')
    except Exception as e:
        return f"<html><body><h1>Error: {e}</h1></body></html>"


# ══════════════════════════════════════════════════════════════════════════════
# CHAT (lobby)
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
            if uid == exclude:
                continue
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await asyncio.wait_for(ws.send_json(message), timeout=5)
            except Exception:
                pass

    async def add_connection(self, ws: WebSocket, uid: str, username: str):
        async with self._lock:
            self.connections[uid] = ws
            self.usernames[uid] = username
        await self.broadcast({'type': 'system', 'message': f'{username} joined',
                              'user_count': len(self.connections)})

    async def remove_connection(self, uid: str):
        async with self._lock:
            un = self.usernames.pop(uid, 'Someone')
            self.connections.pop(uid, None)
        await self.broadcast({'type': 'system', 'message': f'{un} left',
                              'user_count': len(self.connections)})


chat_manager = ChatManager()


# ══════════════════════════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse('<script>window.location.href="/lobby";</script>')

@app.get("/lobby", response_class=HTMLResponse)
async def lobby_page():
    return HTMLResponse(read_html(FRONTEND_DIR / "lobby.html"))

@app.get("/table/{table_id}", response_class=HTMLResponse)
async def table_page(table_id: str):
    html = read_html(FRONTEND_DIR / "table.html")
    table = lobby.tables.get(table_id)
    name = table.name if table else table_id
    html = html.replace("{{ table_id }}", table_id).replace("{{ table_name }}", name)
    return HTMLResponse(html)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(read_html(FRONTEND_DIR / "admin.html"))


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(request: RegisterRequest, req: Request):
    ip = get_client_ip(req)
    if not register_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many attempts")
    if not auth_manager.create_user(request.username, request.password, request.email):
        raise HTTPException(status_code=400, detail="Username already exists")
    return json_response({"success": True})

@app.post("/api/auth/login")
async def login(request: LoginRequest, req: Request):
    ip = get_client_ip(req)
    if not login_limiter.is_allowed(ip):
        retry = login_limiter.get_retry_after(ip)
        raise HTTPException(status_code=429, detail=f"Too many attempts. Retry in {retry}s.")
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
    sid = req.cookies.get('poker_session')
    if sid:
        auth_manager.invalidate_session(sid)
    resp = json_response({"success": True})
    resp.delete_cookie("poker_session")
    return resp

@app.get("/api/auth/me")
async def get_me(current_user: Dict = Depends(get_current_user_optional)):
    if not current_user:
        return json_response({"authenticated": False})
    return json_response({"authenticated": True, "user": current_user})


# ══════════════════════════════════════════════════════════════════════════════
# TABLES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tables")
async def list_tables():
    tables = await lobby.list_tables()
    return json_response([t.model_dump() for t in tables])

@app.get("/api/tables/{table_id}")
async def get_table(table_id: str):
    table = await lobby.get_table(table_id)
    if not table:
        raise HTTPException(status_code=404)
    return json_response(table.model_dump())

@app.post("/api/tables/{table_id}/join")
async def join_table(table_id: str, request: JoinTableRequest):
    if not await lobby.join_table(request.user_id, table_id):
        raise HTTPException(status_code=400, detail="Cannot join table")
    return json_response({"success": True})

@app.post("/api/tables/{table_id}/leave")
async def leave_table(table_id: str, user_id: str):
    await lobby.leave_table(user_id)
    return json_response({"success": True})


# ══════════════════════════════════════════════════════════════════════════════
# TOURNAMENTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tournaments")
async def list_tournaments():
    result = []
    for t in tournament_manager.list_tournaments():
        registered = t.get_registered_players()
        time_until = None
        if t.status == TournamentStatus.REGISTRATION:
            time_until = int((t.start_time - datetime.utcnow()).total_seconds())
        result.append({
            'id': t.id, 'name': t.name, 'description': t.description,
            'status': t.status, 'game_variant': t.game_variant,
            'players_count': len(registered), 'max_players': t.max_players,
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
                {'user_id': p['user_id'], 'username': p['username']} for p in registered[:20]
            ],
        })
    return json_response(result)

@app.get("/api/tournaments/{tid}")
async def get_tournament(tid: str):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    registered = t.get_registered_players()
    time_until = None
    if t.status == TournamentStatus.REGISTRATION:
        time_until = int((t.start_time - datetime.utcnow()).total_seconds())
    return json_response({
        'id': t.id, 'name': t.name, 'description': t.description,
        'status': t.status, 'game_variant': t.game_variant,
        'players_count': len(registered), 'max_players': t.max_players,
        'min_players_to_start': t.min_players_to_start,
        'prize_pool': t.prize_pool, 'itm_percentage': t.itm_percentage,
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
        'ranking': t.get_ranking(),
        'registered_players': [
            {'user_id': p['user_id'], 'username': p['username'], 'avatar': p.get('avatar')}
            for p in registered
        ],
        'tables': t.tables, 'winners': t.winners,
    })

@app.post("/api/tournaments/{tid}/register")
async def register_tournament(tid: str, request: RegisterTournamentRequest):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    user = auth_manager.get_user_by_id(request.user_id)
    username = user['username'] if user else request.user_id
    avatar = user.get('avatar') if user else None
    if not t.register_player(request.user_id, username, avatar):
        raise HTTPException(status_code=400, detail="Cannot register")
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.post("/api/tournaments/{tid}/unregister")
async def unregister_tournament(tid: str, request: RegisterTournamentRequest):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    t.unregister_player(request.user_id)
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.get("/api/tournaments/{tid}/my-table")
async def get_my_tournament_table(tid: str, user_id: str):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    for p in t.players:
        if p['user_id'] == user_id and p.get('table_id'):
            return json_response({"table_id": p['table_id'], "position": p.get('position', 0)})
    raise HTTPException(status_code=404, detail="Player not found")


# ── Hand History ──────────────────────────────────────────────────────────

@app.get("/api/tables/{table_id}/history")
async def get_table_history(table_id: str, limit: int = 20, offset: int = 0):
    """Retourne l'historique des mains d'une table"""
    from .game_engine import HISTORY_DIR
    history_dir = HISTORY_DIR / table_id
    if not history_dir.exists():
        return json_response([])
    files = sorted(history_dir.glob("hand_*.json"), reverse=True)
    result = []
    for f in files[offset:offset + limit]:
        try:
            with open(f) as fh:
                result.append(json.load(fh))
        except Exception:
            pass
    return json_response(result)

@app.get("/api/tables/{table_id}/history/{hand_number}")
async def get_hand_detail(table_id: str, hand_number: int):
    """Retourne le détail d'une main"""
    from .game_engine import HISTORY_DIR
    path = HISTORY_DIR / table_id / f"hand_{hand_number:06d}.json"
    if not path.exists():
        raise HTTPException(status_code=404)
    try:
        with open(path) as f:
            return json_response(json.load(f))
    except Exception:
        raise HTTPException(status_code=500)


# ── Tournament Results ────────────────────────────────────────────────────

@app.get("/tournament/{tid}/results", response_class=HTMLResponse)
async def tournament_results_page(tid: str):
    return HTMLResponse(read_html(FRONTEND_DIR / "tournament_results.html").replace("{{ tournament_id }}", tid))

@app.get("/api/tournaments/{tid}/results")
async def get_tournament_results(tid: str):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    return json_response({
        'id': t.id, 'name': t.name,
        'status': t.status,
        'game_variant': t.game_variant,
        'prize_pool': t.prize_pool,
        'ranking': t.get_ranking(),
        'winners': t.winners,
        'current_level': t.current_level,
        'blind_structure': t.blind_structure,
        'players_count': len(t.players),
    })


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/admin/tournaments")
async def admin_create_tournament(request: CreateTournamentRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.create_tournament(
        name=request.name, description=request.description,
        registration_start=request.registration_start,
        registration_end=request.registration_end,
        start_time=request.start_time,
        max_players=request.max_players,
        min_players_to_start=request.min_players_to_start,
        prize_pool=request.prize_pool, itm_percentage=request.itm_percentage,
        blind_structure=request.blind_structure,
        game_variant=request.game_variant.value if hasattr(request.game_variant, 'value') else str(request.game_variant),
    )
    return json_response({"success": True, "tournament_id": t.id})

@app.put("/api/admin/tournaments/{tid}")
async def admin_update_tournament(tid: str, request: UpdateTournamentRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    for field in ('name', 'description', 'registration_start', 'registration_end',
                  'start_time', 'max_players', 'min_players_to_start', 'blind_structure'):
        val = getattr(request, field, None)
        if val is not None:
            setattr(t, field, val)
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.delete("/api/admin/tournaments/{tid}")
async def admin_delete_tournament(tid: str, _: Dict = Depends(require_admin)):
    tournament_manager.delete_tournament(tid)
    return json_response({"success": True})

@app.post("/api/admin/tournaments/{tid}/pause")
async def admin_pause_tournament(tid: str, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    t.pause()
    tournament_manager.save_tournament(t)
    return json_response({"success": True, "status": t.status})

@app.post("/api/admin/tournaments/{tid}/resume")
async def admin_resume_tournament(tid: str, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    t.resume()
    tournament_manager.save_tournament(t)
    return json_response({"success": True, "status": t.status})

@app.post("/api/admin/tournaments/{tid}/mute")
async def admin_mute_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.mute_player(request.user_id)
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.post("/api/admin/tournaments/{tid}/unmute")
async def admin_unmute_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.unmute_player(request.user_id)
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.post("/api/admin/tournaments/{tid}/exclude")
async def admin_exclude_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.exclude_player(request.user_id, request.reason or "Admin decision")
    tournament_manager.save_tournament(t)
    return json_response({"success": True})

@app.get("/api/admin/stats")
async def admin_stats(_: Dict = Depends(require_admin)):
    return json_response(lobby.get_stats())

@app.get("/api/admin/users")
async def admin_list_users(_: Dict = Depends(require_admin)):
    return json_response(auth_manager.list_users())

@app.delete("/api/admin/tables/{table_id}")
async def admin_close_table(table_id: str, _: Dict = Depends(require_admin)):
    if table_id not in lobby.tables:
        raise HTTPException(status_code=404)
    await lobby.close_table(table_id)
    return json_response({"success": True})

# ── Avatar Upload ──
@app.post("/api/profile/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
    filename = f"{current_user['id']}.{ext}"
    (UPLOAD_DIR / filename).write_bytes(content)
    avatar_url = f"/uploads/avatars/{filename}"
    auth_manager.update_user(current_user['id'], avatar=avatar_url)
    return json_response({"success": True, "avatar": avatar_url})


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Chat Lobby
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    user_id = None
    try:
        while True:
            data = await websocket.receive_json()
            mt = data.get('type', '')
            if mt == 'join':
                user_id = data.get('user_id', str(uuid.uuid4()))
                username = sanitize_username(data.get('username', 'Guest'))
                await chat_manager.add_connection(websocket, user_id, username)
                for msg in chat_manager.messages[-50:]:
                    try:
                        await websocket.send_json(msg)
                    except Exception:
                        break
            elif mt == 'message' and user_id:
                text = sanitize_chat_message(data.get('message', ''))
                if text:
                    await chat_manager.broadcast({
                        'type': 'message', 'user_id': user_id,
                        'username': chat_manager.usernames.get(user_id, '?'),
                        'message': text,
                    })
            elif mt == 'ping':
                await websocket.send_json({'type': 'pong'})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Chat WS: {e}")
    finally:
        if user_id:
            await chat_manager.remove_connection(user_id)


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Table
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{table_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, table_id: str, user_id: str):
    await websocket.accept()

    ip = get_client_ip(websocket)
    if not ws_connect_limiter.is_allowed(ip):
        await websocket.send_json({"type": "error", "message": "Too many connections"})
        await websocket.close()
        return

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
    if not is_spectator and table and user_id not in table.players:
        is_spectator = True

    await ws_manager.connect(websocket, table_id, user_id)
    if table and not table._ws_manager:
        table.set_ws_manager(ws_manager)

    # Envoyer état initial
    if table:
        try:
            state = table.get_state(for_user_id=user_id if not is_spectator else None)
            if is_spectator and isinstance(state, dict):
                state = copy.deepcopy(state)
                for p in state.get('players', []):
                    p['hole_cards'] = []
            await websocket.send_json({
                "type": "game_state", "data": state, "is_spectator": is_spectator,
            })
        except Exception as e:
            logger.error(f"Initial state error: {e}")

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
                    await websocket.send_json({"type": "error", "message": str(e)})

            elif mt == "chat":
                # Vérifier si muted dans un tournoi
                if table and table.tournament_id:
                    t = tournament_manager.get_tournament(table.tournament_id)
                    if t and t.is_muted(user_id):
                        await websocket.send_json({"type": "error", "message": "Vous êtes muté"})
                        continue

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
                        "type": "table_chat", "user_id": user_id,
                        "username": un, "message": msg_text,
                    })

            elif mt == "ping":
                await websocket.send_json({"type": "pong"})

            elif mt == "pong":
                ws_manager.handle_pong(table_id, user_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error {user_id}@{table_id}: {e}")
    finally:
        await ws_manager.disconnect(websocket, table_id, user_id)
