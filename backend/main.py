# backend/main.py
"""
FastAPI Application — PokerEndPasse
====================================
Version corrigée :
- Ajout des await manquants pour save_tournament
- Bouton Options unique (profil, admin, paramètres)
- Gestion des reconnexions après redémarrage
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
    GameVariant, TournamentStatus,OrganizeTournamentRequest
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

async def check_lobby_ready():
    if not lobby._ready:
        raise HTTPException(status_code=503, detail="Server still starting, please retry")

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

@app.post("/api/admin/tables/{table_id}/start")
async def force_start_table(table_id: str, _: Dict = Depends(require_admin)):
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404)
    if table._game_task:
        return {"success": False, "message": "Game already running"}
    table._try_start_game()
    if not table._game_task:
        active = [p for p in table.players.values() if p.chips > 0]
        if len(active) >= 2:
            table._game_task = asyncio.create_task(table._game_loop())
            return {"success": True, "message": f"Game started with {len(active)} players"}
        else:
            return {"success": False, "message": f"Not enough players: {len(active)}/2"}
    return {"success": True, "message": "Game start triggered"}

@app.post("/api/auth/login")
async def login(request: LoginRequest, req: Request):
    global maintenance_mode
    ip = get_client_ip(req)
    if not login_limiter.is_allowed(ip):
        retry = login_limiter.get_retry_after(ip)
        raise HTTPException(status_code=429, detail=f"Too many attempts. Retry in {retry}s.")

    # Vérifier mode maintenance
    if maintenance_mode:
        # On ne peut pas savoir si c'est un admin avant authentification, donc on laisse passer
        # mais on pourrait vérifier après authentification et rejeter si non-admin
        pass

    user = auth_manager.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if maintenance_mode and not user.get('is_admin'):
        raise HTTPException(status_code=503, detail="Server in maintenance mode")

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

@app.get("/api/tables/{table_id}/debug")
async def debug_table(table_id: str):
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404)
    return {
        "table_id": table.id,
        "name": table.name,
        "status": table.status.value if hasattr(table.status, 'value') else str(table.status),
        "players": [
            {
                "user_id": p.user_id,
                "username": p.username,
                "status": p.status.value if hasattr(p.status, 'value') else str(p.status),
                "chips": p.chips,
                "current_bet": p.current_bet,
                "is_dealer": p.is_dealer,
                "is_small_blind": p.is_small_blind,
                "is_big_blind": p.is_big_blind,
                "is_all_in": p.is_all_in,
                "connected": table._ws_manager.is_connected(table_id, p.user_id) if table._ws_manager else False
            }
            for p in table.players.values()
        ],
        "current_actor": table._current_actor,
        "hand_round": table._hand_round,
        "street": table._street,
        "pot": table._pot,
        "community_cards": table._community_cards,
        "game_task_running": table._game_task is not None
    }

@app.get("/api/auth/me")
async def get_me(current_user: Dict = Depends(get_current_user_optional)):
    if not current_user:
        return json_response({"authenticated": False})
    return json_response({"authenticated": True, "user": current_user})


# ══════════════════════════════════════════════════════════════════════════════
# TABLES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tables", dependencies=[Depends(check_lobby_ready)])
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
    await lobby.leave_table(user_id, table_id)
    return json_response({"success": True})

# ══════════════════════════════════════════════════════════════════════════════
# TOURNAMENTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tournaments", dependencies=[Depends(check_lobby_ready)])
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
        'organizer_id': getattr(t, 'organizer_id', ''),
        'is_organizer': current_user and getattr(t, 'organizer_id', '') == current_user.get('id', ''),
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
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True})

@app.post("/api/tournaments/{tid}/unregister")
async def unregister_tournament(tid: str, request: RegisterTournamentRequest):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    t.unregister_player(request.user_id)
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True})

@app.post("/api/admin/rate-limit/reset/{user_id}")
async def reset_rate_limit(user_id: str, _: Dict = Depends(require_admin)):
    if user_id in lobby._join_attempts:
        lobby._join_attempts.pop(user_id)
    return {"success": True, "message": f"Rate limit reset for {user_id}"}

@app.post("/api/tournaments/{tid}/rejoin")
async def rejoin_tournament(tid: str, request: RegisterTournamentRequest, current_user: Dict = Depends(get_current_user)):
    """Réassigne un joueur à sa table après reconnexion."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    player = None
    for p in t.players:
        if p['user_id'] == request.user_id:
            player = p
            break

    if not player:
        raise HTTPException(status_code=404, detail="Player not registered")

    logger.info(f"Rejoin request for player {request.user_id} in tournament {tid}, status={t.status}, table_id={player.get('table_id')}")

    if t.status in (TournamentStatus.IN_PROGRESS, TournamentStatus.PAUSED):
        table_id = player.get('table_id')

        if table_id:
            table = lobby.tables.get(table_id)
            if table:
                if request.user_id in table.players:
                    logger.info(f"Player {request.user_id} already in table {table_id}")
                    return json_response({
                        "success": True,
                        "table_id": table_id,
                        "already_joined": True
                    })
                else:
                    user = auth_manager.get_user_by_id(request.user_id)
                    username = user['username'] if user else request.user_id
                    avatar = user.get('avatar') if user else None
                    chips = player.get('chips', t.starting_chips)

                    success = await lobby.join_table(request.user_id, table_id)
                    if success:
                        logger.info(f"Player {request.user_id} rejoined table {table_id}")
                        return json_response({
                            "success": True,
                            "table_id": table_id,
                            "already_joined": False
                        })
            else:
                logger.warning(f"Table {table_id} not found in lobby for player {request.user_id}")

        # Si pas de table assignée ou table inexistante, chercher une table disponible
        for existing_table_id in t.tables:
            existing_table = lobby.tables.get(existing_table_id)
            if existing_table and len(existing_table.players) < existing_table.max_players:
                user = auth_manager.get_user_by_id(request.user_id)
                username = user['username'] if user else request.user_id
                avatar = user.get('avatar') if user else None
                chips = player.get('chips', t.starting_chips)

                success = await lobby.join_table(request.user_id, existing_table_id)
                if success:
                    player['table_id'] = existing_table_id
                    await tournament_manager.save_tournament(t)
                    logger.info(f"Player {request.user_id} assigned to existing table {existing_table_id}")
                    return json_response({
                        "success": True,
                        "table_id": existing_table_id,
                        "already_joined": False
                    })

        # Si aucune table trouvée mais que le tournoi est en cours, créer une nouvelle table
        if t.tables:
            table_id = t.tables[0]
            table = lobby.tables.get(table_id)
            if table:
                success = await lobby.join_table(request.user_id, table_id)
                if success:
                    player['table_id'] = table_id
                    await tournament_manager.save_tournament(t)
                    logger.info(f"Player {request.user_id} joined first available table {table_id}")
                    return json_response({
                        "success": True,
                        "table_id": table_id,
                        "already_joined": False
                    })

    if t.status == TournamentStatus.REGISTRATION:
        return json_response({
            "success": True,
            "status": "registration",
            "message": "Tournament in registration, please re-register"
        })

    raise HTTPException(status_code=404, detail="No available table found")

@app.post("/api/admin/tournaments/{tid}/reconnect-all")
async def admin_reconnect_all(tid: str, _: Dict = Depends(require_admin)):
    """Force la reconnexion de tous les joueurs d'un tournoi après un crash."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)

    results = []
    for player in t.players:
        if player.get('status') == 'eliminated':
            continue

        user_id = player['user_id']
        table_id = player.get('table_id')

        if table_id:
            table = lobby.tables.get(table_id)
            if table and user_id not in table.players:
                user = auth_manager.get_user_by_id(user_id)
                username = user['username'] if user else user_id
                avatar = user.get('avatar') if user else None
                chips = player.get('chips', t.starting_chips)

                success = await lobby.join_table(user_id, table_id)
                results.append({
                    "user_id": user_id,
                    "username": username,
                    "success": success,
                    "table_id": table_id
                })
            elif not table:
                results.append({
                    "user_id": user_id,
                    "username": player['username'],
                    "success": False,
                    "error": f"Table {table_id} not found"
                })
            else:
                results.append({
                    "user_id": user_id,
                    "username": player['username'],
                    "success": True,
                    "already_in_table": True
                })

    return json_response({
        "success": True,
        "tournament": t.name,
        "results": results
    })

@app.post("/api/admin/tournaments/{tid}/restart-tables")
async def restart_tournament_tables(tid: str, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    for table_id in t.tables:
        table = lobby.tables.get(table_id)
        if table and not table._game_task:
            table._try_start_game()
    return {"success": True}

@app.get("/api/tournaments/{tid}/my-table", dependencies=[Depends(check_lobby_ready)])
async def get_my_tournament_table(tid: str, user_id: str):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    logger.info(f"[REJOIN] Looking for player {user_id} in tournament {tid} (status={t.status})")

    for p in t.players:
        if p['user_id'] == user_id:
            table_id = p.get('table_id')
            logger.info(f"[REJOIN] Player found, table_id={table_id}")

            if table_id:
                table = lobby.tables.get(table_id)
                if table:
                    if user_id in table.players:
                        logger.info(f"[REJOIN] Player already in table {table_id}")
                        return json_response({
                            "table_id": table_id,
                            "position": p.get('position', 0),
                            "table_name": table.name
                        })
                    else:
                        logger.info(f"[REJOIN] Adding player to existing table {table_id}")
                        success = await lobby.join_table(user_id, table_id)
                        if success:
                            return json_response({
                                "table_id": table_id,
                                "position": p.get('position', 0),
                                "table_name": table.name
                            })
                else:
                    # La table n'existe pas, il faut la recréer
                    logger.warning(f"[REJOIN] Table {table_id} not found, recreating...")

                    from .models import CreateTableRequest

                    table_request = CreateTableRequest(
                        name=f"{t.name} — Table",
                        tournament_id=t.id,
                        max_players=9,
                    )
                    new_table = await lobby.create_table(
                        table_request,
                        game_variant=GameVariant(t.game_variant) if t.game_variant else GameVariant.HOLDEM,
                    )

                    # Mettre à jour l'ID de la table dans le tournoi
                    for i, old_table_id in enumerate(t.tables):
                        if old_table_id == table_id:
                            t.tables[i] = new_table.id
                            break

                    # Ajouter tous les joueurs qui étaient dans cette table
                    players_to_add = [pl for pl in t.players if pl.get('table_id') == table_id]
                    for i, player in enumerate(players_to_add):
                        await lobby.join_table(player['user_id'], new_table.id)
                        player['table_id'] = new_table.id
                        player['position'] = i

                    await tournament_manager.save_tournament(t)

                    if user_id not in new_table.players:
                        await lobby.join_table(user_id, new_table.id)

                    return json_response({
                        "table_id": new_table.id,
                        "position": p.get('position', 0),
                        "table_name": new_table.name,
                        "recreated": True
                    })
            else:
                # Le joueur n'a pas de table assignée, chercher une table existante
                for existing_table_id in t.tables:
                    existing_table = lobby.tables.get(existing_table_id)
                    if existing_table and len(existing_table.players) < existing_table.max_players:
                        success = await lobby.join_table(user_id, existing_table_id)
                        if success:
                            p['table_id'] = existing_table_id
                            await tournament_manager.save_tournament(t)
                            return json_response({
                                "table_id": existing_table_id,
                                "position": len(existing_table.players) - 1,
                                "table_name": existing_table.name
                            })

                # Créer une nouvelle table si aucune n'est disponible
                from .models import CreateTableRequest
                table_request = CreateTableRequest(
                    name=f"{t.name} — Table",
                    tournament_id=t.id,
                    max_players=9,
                )
                new_table = await lobby.create_table(
                    table_request,
                    game_variant=GameVariant(t.game_variant) if t.game_variant else GameVariant.HOLDEM,
                )
                t.tables.append(new_table.id)

                await tournament_manager.save_tournament(t)
                if user_id not in new_table.players:
                    await lobby.join_table(user_id, new_table.id)
                return json_response({
                    "table_id": new_table.id,
                    "position": 0,
                    "table_name": new_table.name,
                    "created": True
                })

    raise HTTPException(status_code=404, detail="Player not found in tournament")

# ── Hand History ──────────────────────────────────────────────────────────

@app.get("/api/tables/{table_id}/history")
async def get_table_history(table_id: str, limit: int = 20, offset: int = 0):
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

@app.post("/api/tournaments/{tid}/force-reconnect")
async def force_reconnect_tournament(tid: str, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)

    players_status = []
    for p in t.players:
        if p.get('status') != 'eliminated':
            table_id = p.get('table_id')
            table = lobby.tables.get(table_id) if table_id else None
            in_table = table and p['user_id'] in table.players if table else False

            players_status.append({
                "user_id": p['user_id'],
                "username": p['username'],
                "table_id": table_id,
                "in_table": in_table,
                "chips": p.get('chips', 0)
            })

    return {
        "success": True,
        "tournament": t.name,
        "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
        "players": players_status,
        "tables": list(t.tables),
        "tables_exist": [{"id": tid, "exists": tid in lobby.tables} for tid in t.tables]
    }

@app.get("/api/tournaments/{tid}/reconnect-status")
async def tournament_reconnect_status(tid: str, user_id: str):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    player = None
    for p in t.players:
        if p['user_id'] == user_id:
            player = p
            break

    if not player:
        return json_response({
            "can_reconnect": False,
            "reason": "not_registered"
        })

    if t.status not in (TournamentStatus.IN_PROGRESS, TournamentStatus.PAUSED):
        return json_response({
            "can_reconnect": False,
            "reason": "tournament_not_active",
            "status": t.status
        })

    if player.get('status') == 'eliminated':
        return json_response({
            "can_reconnect": False,
            "reason": "eliminated"
        })

    table_id = player.get('table_id')
    table = lobby.tables.get(table_id) if table_id else None

    return json_response({
        "can_reconnect": True,
        "has_table": table is not None,
        "table_id": table_id,
        "table_exists": table is not None,
        "player_in_table": table and user_id in table.players if table else False,
        "chips": player.get('chips', 0),
        "status": player.get('status', 'registered')
    })

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

@app.post("/api/organize/create")
async def organize_create_tournament(
    request: OrganizeTournamentRequest,
    current_user: Dict = Depends(get_current_user),
):
    """Crée un tournoi en tant qu'organisateur (tout utilisateur authentifié)."""
    now = datetime.utcnow()
 
    # Limiter le nombre de tournois actifs par organisateur (anti-spam)
    user_tournaments = [
        t for t in tournament_manager.list_tournaments()
        if getattr(t, 'organizer_id', '') == current_user['id']
        and t.status in (TournamentStatus.REGISTRATION, TournamentStatus.IN_PROGRESS, TournamentStatus.PAUSED)
    ]
    if len(user_tournaments) >= 3:
        raise HTTPException(status_code=400, detail="Maximum 3 tournois actifs par organisateur")
 
    # Résoudre le blind preset
    blind_structure = BLIND_PRESETS.get(request.blind_preset, BLIND_PRESETS["standard"])
 
    reg_start = now
    reg_end = now + timedelta(minutes=request.registration_duration_minutes)
    start_time = now + timedelta(minutes=request.start_delay_minutes)
 
    # S'assurer que start_time > reg_end
    if start_time <= reg_end:
        start_time = reg_end + timedelta(minutes=5)
 
    t = tournament_manager.create_tournament(
        name=request.name,
        description=request.description or "",
        registration_start=reg_start,
        registration_end=reg_end,
        start_time=start_time,
        max_players=request.max_players,
        min_players_to_start=request.min_players_to_start,
        prize_pool=0,  # freeroll uniquement
        itm_percentage=10.0,
        blind_structure=blind_structure,
        game_variant=request.game_variant.value if hasattr(request.game_variant, 'value') else str(request.game_variant),
        starting_chips=request.starting_chips,
        organizer_id=current_user['id'],
    )
 
    # Auto-inscription de l'organisateur
    user = auth_manager.get_user_by_id(current_user['id'])
    username = user['username'] if user else current_user.get('username', '?')
    avatar = user.get('avatar') if user else None
    t.register_player(current_user['id'], username, avatar)
    await tournament_manager.save_tournament(t)
 
    logger.info(f"Tournament organized by {username}: {t.name} ({t.id})")
    return json_response({
        "success": True,
        "tournament_id": t.id,
        "name": t.name,
        "registration_end": reg_end.isoformat(),
        "start_time": start_time.isoformat(),
    })
 
 
@app.get("/api/organize/my-tournaments")
async def organize_my_tournaments(current_user: Dict = Depends(get_current_user)):
    """Liste les tournois créés par l'utilisateur courant."""
    my_tournaments = []
    for t in tournament_manager.list_tournaments():
        if getattr(t, 'organizer_id', '') == current_user['id']:
            registered = t.get_registered_players()
            my_tournaments.append({
                'id': t.id,
                'name': t.name,
                'status': t.status.value if hasattr(t.status, 'value') else str(t.status),
                'game_variant': t.game_variant,
                'players_count': len(registered),
                'max_players': t.max_players,
                'min_players_to_start': t.min_players_to_start,
                'registration_end': t.registration_end.isoformat() if t.registration_end else None,
                'start_time': t.start_time.isoformat() if t.start_time else None,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'current_level': t.current_level,
                'tables_count': len(t.tables),
            })
    return json_response(my_tournaments)
 
 
@app.put("/api/organize/{tid}")
async def organize_update_tournament(
    tid: str,
    request: UpdateTournamentRequest,
    current_user: Dict = Depends(get_current_user),
):
    """Modifie un tournoi (seulement l'organisateur ou un admin)."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    is_organizer = getattr(t, 'organizer_id', '') == current_user['id']
    is_admin = current_user.get('is_admin', False)
    if not is_organizer and not is_admin:
        raise HTTPException(status_code=403, detail="Seul l'organisateur peut modifier ce tournoi")
 
    # On ne peut modifier que pendant les inscriptions
    if t.status != TournamentStatus.REGISTRATION and not is_admin:
        raise HTTPException(status_code=400, detail="Le tournoi ne peut plus être modifié")
 
    for field_name in ('name', 'description', 'max_players', 'min_players_to_start'):
        val = getattr(request, field_name, None)
        if val is not None:
            setattr(t, field_name, val)
 
    await tournament_manager.save_tournament(t)
    return json_response({"success": True})
 
 
@app.post("/api/organize/{tid}/cancel")
async def organize_cancel_tournament(
    tid: str,
    current_user: Dict = Depends(get_current_user),
):
    """Annule un tournoi (seulement l'organisateur ou un admin)."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    is_organizer = getattr(t, 'organizer_id', '') == current_user['id']
    is_admin = current_user.get('is_admin', False)
    if not is_organizer and not is_admin:
        raise HTTPException(status_code=403, detail="Seul l'organisateur peut annuler ce tournoi")
 
    if t.status == TournamentStatus.FINISHED:
        raise HTTPException(status_code=400, detail="Tournoi déjà terminé")
 
    # Si en cours → pause puis cancel
    if t.status == TournamentStatus.IN_PROGRESS:
        t.pause()
 
    t.status = TournamentStatus.CANCELLED
    await tournament_manager.save_tournament(t)
 
    logger.info(f"Tournament {t.name} cancelled by organizer {current_user['id']}")
    return json_response({"success": True, "status": "cancelled"})
 
 
@app.post("/api/organize/{tid}/pause")
async def organize_pause_tournament(
    tid: str,
    current_user: Dict = Depends(get_current_user),
):
    """Pause un tournoi en cours (organisateur ou admin)."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    is_organizer = getattr(t, 'organizer_id', '') == current_user['id']
    is_admin = current_user.get('is_admin', False)
    if not is_organizer and not is_admin:
        raise HTTPException(status_code=403)
 
    if t.status != TournamentStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Le tournoi n'est pas en cours")
 
    t.pause()
    await tournament_manager.save_tournament(t)
    return json_response({"success": True, "status": "paused"})
 
 
@app.post("/api/organize/{tid}/resume")
async def organize_resume_tournament(
    tid: str,
    current_user: Dict = Depends(get_current_user),
):
    """Reprend un tournoi en pause (organisateur ou admin)."""
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
 
    is_organizer = getattr(t, 'organizer_id', '') == current_user['id']
    is_admin = current_user.get('is_admin', False)
    if not is_organizer and not is_admin:
        raise HTTPException(status_code=403)
 
    if t.status != TournamentStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Le tournoi n'est pas en pause")
 
    t.resume()
    await tournament_manager.save_tournament(t)
    return json_response({"success": True, "status": "in_progress"})

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
        starting_chips=request.starting_chips,
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
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
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
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True, "status": t.status})

@app.post("/api/admin/tournaments/{tid}/resume")
async def admin_resume_tournament(tid: str, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404)
    t.resume()
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True, "status": t.status})

@app.post("/api/admin/tournaments/{tid}/mute")
async def admin_mute_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.mute_player(request.user_id)
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True})

@app.post("/api/admin/tournaments/{tid}/unmute")
async def admin_unmute_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.unmute_player(request.user_id)
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
    return json_response({"success": True})

@app.post("/api/admin/tournaments/{tid}/exclude")
async def admin_exclude_player(tid: str, request: AdminActionRequest, _: Dict = Depends(require_admin)):
    t = tournament_manager.get_tournament(tid)
    if not t or not request.user_id:
        raise HTTPException(status_code=404)
    t.exclude_player(request.user_id, request.reason or "Admin decision")
    await tournament_manager.save_tournament(t)  # <-- AJOUT await
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

@app.get("/api/tables/{table_id}/players")
async def get_table_players(table_id: str):
    table = lobby.tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404)
    return {
        "table_id": table.id,
        "table_name": table.name,
        "players": [
            {
                "user_id": p.user_id,
                "username": p.username,
                "chips": p.chips,
                "position": p.position,
                "status": p.status.value if hasattr(p.status, 'value') else str(p.status)
            }
            for p in table.players.values()
        ],
        "player_count": len(table.players),
        "spectators": list(table.spectators)
    }

@app.websocket("/ws/{table_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, table_id: str, user_id: str):
    await websocket.accept()

    ip = get_client_ip(websocket)
    if not ws_connect_limiter.is_allowed(ip):
        await websocket.send_json({"type": "error", "message": "Too many connections"})
        await websocket.close()
        return

    table = lobby.tables.get(table_id)
    if not table:
        await websocket.send_json({"type": "error", "message": "Table not found"})
        await websocket.close()
        return

    is_spectator = False
    real_user_id = user_id

    session_id = websocket.cookies.get('poker_session') if websocket.cookies else None
    if session_id:
        validated_user_id = auth_manager.validate_session(session_id)
        if validated_user_id:
            real_user_id = validated_user_id
            if validated_user_id != user_id:
                logger.info(f"WS auth: using authenticated user {validated_user_id} instead of {user_id}")
        else:
            logger.warning(f"WS auth: invalid session for {user_id}")
            is_spectator = True
    else:
        is_spectator = True
        real_user_id = f"spectator_{uuid.uuid4().hex[:8]}"

    table = lobby.tables.get(table_id)
    if not table:
        await websocket.send_json({"type": "error", "message": "Table no longer exists"})
        await websocket.close()
        return

    if not is_spectator and real_user_id not in table.players:
        logger.info(f"User {real_user_id} not in table {table_id}, switching to spectator")
        is_spectator = True

    logger.info(f"WS connection: user={real_user_id}, table={table_id}, is_spectator={is_spectator}")

    await ws_manager.connect(websocket, table_id, real_user_id)
    if table and not table._ws_manager:
        table.set_ws_manager(ws_manager)

    try:
        state = table.get_state(for_user_id=real_user_id if not is_spectator else None)
        if is_spectator and isinstance(state, dict):
            import copy
            state = copy.deepcopy(state)
            for p in state.get('players', []):
                p['hole_cards'] = []
        await websocket.send_json({
            "type": "game_state",
            "data": state,
            "is_spectator": is_spectator,
            "user_id": real_user_id
        })
    except Exception as e:
        logger.error(f"Initial state error: {e}")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')

            table = lobby.tables.get(table_id)
            if not table:
                await websocket.send_json({"type": "error", "message": "Table no longer exists"})
                await websocket.close()
                break

            if msg_type == 'action':
                action_str = data.get('action')
                amount = data.get('amount', 0)
                try:
                    action = ActionType(action_str)
                    await table.handle_player_action(real_user_id, action, amount)
                except ValueError:
                    logger.warning(f"Invalid action: {action_str}")
                except Exception as e:
                    logger.error(f"Action error: {e}")

            elif msg_type == 'chat':
                message = data.get('message', '').strip()
                if message and not is_spectator:
                    muted = False
                    if table.tournament_id and tournament_manager:
                        t = tournament_manager.get_tournament(table.tournament_id)
                        if t and t.is_muted(real_user_id):
                            muted = True
                    if not muted:
                        await ws_manager.broadcast_to_table(table_id, {
                            'type': 'table_chat',
                            'user_id': real_user_id,
                            'username': data.get('username', '?'),
                            'message': message,
                        })

            elif msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})


            elif msg_type == 'request_full_state':
                try:
                    import copy
                    state = table.get_state(for_user_id=real_user_id if not is_spectator else None)
                    if is_spectator and isinstance(state, dict):
                        state = copy.deepcopy(state)
                        for p in state.get('players', []):
                            p['hole_cards'] = []
                    qb = None
                    if not is_spectator and state.get('current_actor') == real_user_id:
                        from .game_engine import QuickBetCalculator
                        player_obj = table.players.get(real_user_id)
                        if player_obj:
                            current_bet = max((p.current_bet for p in table.players.values()), default=0)
                            to_call = current_bet - player_obj.current_bet
                            qb = QuickBetCalculator.calculate(
                                pot=table._pot + sum(p.current_bet for p in table.players.values()),
                                big_blind=table.big_blind, current_bet=to_call,
                                player_chips=player_obj.chips, min_raise=table._min_raise,
                            )
                    msg_out = {"type": "game_state", "data": state, "is_spectator": is_spectator, "user_id": real_user_id}
                    if qb:
                        msg_out["quick_bets"] = qb
                    await websocket.send_json(msg_out)
                except Exception as e:
                    logger.error(f"request_full_state error: {e}")

            elif msg_type == 'request_full_state':
                # FIX#17 — Renvoyer l'état complet de la table au joueur reconnecté
                try:
                    import copy
                    state = table.get_state(for_user_id=real_user_id if not is_spectator else None)
                    if is_spectator and isinstance(state, dict):
                        state = copy.deepcopy(state)
                        for p in state.get('players', []):
                            p['hole_cards'] = []
 
                    # Recalculer les quick_bets si c'est le tour du joueur
                    qb = None
                    if not is_spectator and state.get('current_actor') == real_user_id:
                        from .game_engine import QuickBetCalculator
                        player_obj = table.players.get(real_user_id)
                        if player_obj:
                            current_bet = max(
                                (p.current_bet for p in table.players.values()), default=0
                            )
                            to_call = current_bet - player_obj.current_bet
                            qb = QuickBetCalculator.calculate(
                                pot=table._pot + sum(p.current_bet for p in table.players.values()),
                                big_blind=table.big_blind,
                                current_bet=to_call,
                                player_chips=player_obj.chips,
                                min_raise=table._min_raise,
                            )
 
                    msg_out = {
                        "type": "game_state",
                        "data": state,
                        "is_spectator": is_spectator,
                        "user_id": real_user_id,
                    }
                    if qb:
                        msg_out["quick_bets"] = qb
 
                    await websocket.send_json(msg_out)
                    logger.info(f"[WS] Sent full state to {real_user_id} on request_full_state")
                except Exception as e:
                    logger.error(f"request_full_state error for {real_user_id}: {e}")


    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(websocket, table_id, real_user_id)


# ══════════════════════════════════════════════════════════════════════════════
# MONITOR STATUS (admin)
# ══════════════════════════════════════════════════════════════════════════════

# ===== ADMIN ACTIONS AVANCÉES =====

# Variable globale pour le mode maintenance (ajouter en début de fichier)
maintenance_mode = False

@app.post("/api/admin/maintenance/toggle")
async def toggle_maintenance(_: Dict = Depends(require_admin)):
    """Active ou désactive le mode maintenance global."""
    global maintenance_mode
    maintenance_mode = not maintenance_mode
    return json_response({"success": True, "maintenance": maintenance_mode})

@app.get("/api/admin/connected-users")
async def get_connected_users(_: Dict = Depends(require_admin)):
    """Liste tous les utilisateurs connectés via WebSocket."""
    users = set()
    if ws_manager:
        for table_conns in ws_manager._connections.values():
            for uid in table_conns.keys():
                users.add(uid)
    return json_response({"users": list(users)})

@app.post("/api/admin/restart-tables")
async def admin_restart_tables(_: Dict = Depends(require_admin)):
    """Redémarre toutes les tables actives (relance les game loops)."""
    restarted = 0
    for table_id, table in lobby.tables.items():
        # Compter les joueurs actifs
        active_players = [p for p in table.players.values() if p.chips > 0 and p.status != PlayerStatus.ELIMINATED]
        if len(active_players) < 2:
            continue

        # Annuler la tâche existante si elle tourne
        if table._game_task:
            old_task = table._game_task
            table._game_task = None
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0.5)  # laisser le temps à la main de se terminer proprement

        # Démarrer une nouvelle boucle
        table._game_task = asyncio.create_task(table._game_loop())
        restarted += 1
    return json_response({"success": True, "restarted_tables": restarted})

@app.post("/api/admin/rate-limit")
async def set_rate_limit(request: Request, _: Dict = Depends(require_admin)):
    """Modifie dynamiquement les limites de taux."""
    data = await request.json()
    max_requests = data.get('max_requests')
    window_seconds = data.get('window_seconds')
    if max_requests is None or window_seconds is None:
        raise HTTPException(status_code=400, detail="Missing parameters")
    from .security import login_limiter, register_limiter, ws_connect_limiter
    login_limiter.max_requests = max_requests
    login_limiter.window = window_seconds
    register_limiter.max_requests = max_requests
    register_limiter.window = window_seconds
    ws_connect_limiter.max_requests = max_requests
    ws_connect_limiter.window = window_seconds
    return json_response({"success": True})

# ===== PROFIL UTILISATEUR (non-admin) =====

@app.post("/api/profile/email")
async def update_email(request: Request, current_user: Dict = Depends(get_current_user)):
    data = await request.json()
    email = data.get('email')
    if not email or '@' not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    auth_manager.update_user(current_user['id'], email=email)
    return json_response({"success": True})

@app.post("/api/profile/password")
async def change_password(request: Request, current_user: Dict = Depends(get_current_user)):
    data = await request.json()
    old_password = data.get('current_password')
    new_password = data.get('new_password')
    if not old_password or not new_password:
        raise HTTPException(status_code=400, detail="Both passwords required")

    # Récupérer l'utilisateur et son hash
    user = auth_manager.get_user_by_id(current_user['id'])
    # Note : auth_manager ne stocke pas le hash dans l'objet retourné, il faut lire depuis le XML
    # On va ajouter une méthode interne dans auth_manager pour vérifier le mot de passe
    if not auth_manager.verify_password(current_user['id'], old_password):
        raise HTTPException(status_code=401, detail="Invalid current password")

    # Mettre à jour le hash
    new_hash = auth_manager._hash_password(new_password)
    auth_manager.update_user(current_user['id'], password_hash=new_hash)
    return json_response({"success": True})


@app.get("/api/admin/monitor-status")
async def monitor_status(_: Dict = Depends(require_admin)):
    return {
        "monitor_running": tournament_manager._monitor_task is not None,
        "monitor_task_done": tournament_manager._monitor_task.done() if tournament_manager._monitor_task else None,
        "save_task_running": tournament_manager._save_task is not None,
        "tournaments_count": len(tournament_manager.tournaments),
        "tournaments_status": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                "players": len(t.get_registered_players()),
                "start_time": t.start_time.isoformat(),
                "can_start": t.status == "registration" and datetime.utcnow() >= t.start_time and len(t.get_registered_players()) >= t.min_players_to_start
            }
            for t in tournament_manager.list_tournaments()
        ]
    }
