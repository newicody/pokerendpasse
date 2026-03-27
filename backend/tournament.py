# backend/tournament.py — Version complète et corrigée
"""
Gestion des tournois freeroll : Tournament + TournamentManager.
- Création, inscription, démarrage automatique
- Clock des blinds, sit-out, élimination des absents
- Rééquilibrage des tables, classement, prizes
- Persistance XML avec protection injection
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import asyncio
import logging
import random
import uuid

from .security import xml_safe

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
ABSENT_ELIMINATE_THRESHOLD = 600   # 10 min absence → élimination
PRESTART_ABSENT_TIMEOUT    = 120   # 2 min après start pour se connecter


class TournamentStatus:
    REGISTRATION = "registration"
    STARTING     = "starting"
    IN_PROGRESS  = "in_progress"
    FINISHED     = "finished"
    CANCELLED    = "cancelled"


# ═════════════════════════════════════════════════════════════════════════════
# Tournament (modèle de données)
# ═════════════════════════════════════════════════════════════════════════════

class Tournament:
    def __init__(self, tournament_id, name, registration_start, registration_end,
                 start_time, max_players=100, min_players_to_start=4,
                 prize_pool=0, itm_percentage=10.0, blind_structure=None,
                 description=""):
        self.id                   = tournament_id
        self.name                 = name
        self.description          = description
        self.registration_start   = registration_start
        self.registration_end     = registration_end
        self.start_time           = start_time
        self.max_players          = max_players
        self.min_players_to_start = min_players_to_start
        self.prize_pool           = prize_pool
        self.itm_percentage       = itm_percentage
        self.blind_structure      = blind_structure or self._default_blind_structure()
        self.status               = TournamentStatus.REGISTRATION
        self.current_level        = 0
        self.level_started_at: Optional[datetime] = None
        self.players: List[Dict]  = []
        self.tables: List[str]    = []
        self.winners: List[Dict]  = []
        self.created_at           = datetime.utcnow()
        self._disconnect_times: Dict[str, datetime] = {}
        self._sit_out: Dict[str, bool] = {}

    @staticmethod
    def _default_blind_structure():
        return [
            {'level': 1,  'small_blind': 10,   'big_blind': 20,    'duration': 10},
            {'level': 2,  'small_blind': 20,   'big_blind': 40,    'duration': 10},
            {'level': 3,  'small_blind': 30,   'big_blind': 60,    'duration': 10},
            {'level': 4,  'small_blind': 50,   'big_blind': 100,   'duration': 10},
            {'level': 5,  'small_blind': 75,   'big_blind': 150,   'duration': 10},
            {'level': 6,  'small_blind': 100,  'big_blind': 200,   'duration': 10},
            {'level': 7,  'small_blind': 150,  'big_blind': 300,   'duration': 8},
            {'level': 8,  'small_blind': 200,  'big_blind': 400,   'duration': 8},
            {'level': 9,  'small_blind': 300,  'big_blind': 600,   'duration': 8},
            {'level': 10, 'small_blind': 500,  'big_blind': 1000,  'duration': 8},
        ]

    # ── Inscription ───────────────────────────────────────────────────────────

    def can_register(self) -> bool:
        now = datetime.utcnow()
        return (self.status == TournamentStatus.REGISTRATION
                and self.registration_start <= now < self.registration_end)

    def is_registered(self, user_id: str) -> bool:
        return any(p['user_id'] == user_id and p.get('status') == 'registered'
                   for p in self.players)

    def add_player(self, user_id, username, avatar=None) -> bool:
        if not self.can_register(): return False
        if len(self.players) >= self.max_players: return False
        if self.is_registered(user_id): return False
        self.players.append({
            'user_id': user_id, 'username': username, 'avatar': avatar,
            'status': 'registered', 'registered_at': datetime.utcnow().isoformat(),
            'eliminated_rank': 0, 'chips': 0, 'table_id': None, 'position': None,
        })
        return True

    def remove_player(self, user_id) -> bool:
        for i, p in enumerate(self.players):
            if p['user_id'] == user_id and p.get('status') == 'registered':
                del self.players[i]; return True
        return False

    # ── Déconnexions / Absents ────────────────────────────────────────────────

    def on_player_disconnect(self, user_id):
        self._disconnect_times[user_id] = datetime.utcnow()
        self._sit_out[user_id] = True

    def on_player_reconnect(self, user_id):
        self._disconnect_times.pop(user_id, None)
        self._sit_out[user_id] = False

    def is_sit_out(self, user_id) -> bool:
        return self._sit_out.get(user_id, False)

    def get_long_absent_players(self) -> List[str]:
        now = datetime.utcnow()
        return [uid for uid, dt in self._disconnect_times.items()
                if (now - dt).total_seconds() >= ABSENT_ELIMINATE_THRESHOLD]

    # ── Blinds ────────────────────────────────────────────────────────────────

    def get_current_blinds(self) -> Dict:
        idx = min(self.current_level, len(self.blind_structure) - 1)
        return self.blind_structure[idx] if self.blind_structure else {'small_blind': 10, 'big_blind': 20, 'duration': 10}

    def seconds_until_next_level(self) -> Optional[int]:
        if self.level_started_at is None: return None
        duration = self.get_current_blinds().get('duration', 10) * 60
        elapsed = (datetime.utcnow() - self.level_started_at).total_seconds()
        return max(0, int(duration - elapsed))

    def advance_level(self) -> bool:
        if self.current_level < len(self.blind_structure) - 1:
            self.current_level += 1
            self.level_started_at = datetime.utcnow()
            b = self.get_current_blinds()
            logger.info(f"[{self.id}] Level {self.current_level+1} — {b['small_blind']}/{b['big_blind']}")
            return True
        return False

    # ── Classement / Prizes ───────────────────────────────────────────────────

    def get_registered_players(self) -> List[Dict]:
        return [p for p in self.players if p.get('status') == 'registered']

    def get_ranking(self) -> List[Dict]:
        active = [p for p in self.players if p.get('status') == 'registered']
        active.sort(key=lambda x: x.get('chips', 0), reverse=True)
        return active

    def eliminate_player(self, user_id, rank):
        for p in self.players:
            if p['user_id'] == user_id:
                p['status'] = 'eliminated'
                p['eliminated_rank'] = rank
                p['eliminated_at'] = datetime.utcnow().isoformat()
                self._sit_out.pop(user_id, None)
                self._disconnect_times.pop(user_id, None)
                break

    def calculate_prizes(self) -> List[Dict]:
        if self.prize_pool == 0: return []
        reg = len(self.get_registered_players()) + len([p for p in self.players if p.get('status') == 'eliminated'])
        num_paid = max(1, int(reg * self.itm_percentage / 100))
        dist = [25, 15, 10, 8, 7, 6, 5, 4, 3, 2, 1.5, 1, 0.5]
        prizes = []; remaining = self.prize_pool
        for i in range(num_paid - 1):
            pct = dist[i] if i < len(dist) else 0.5
            amount = int(self.prize_pool * pct / 100)
            prizes.append({'rank': i+1, 'percentage': pct, 'amount': amount})
            remaining -= amount
        prizes.append({'rank': num_paid, 'percentage': round(remaining/max(1,self.prize_pool)*100,1), 'amount': remaining})
        return prizes

    # Alias pour get_tournament_info_extended
    def get_prize_structure(self): return self.calculate_prizes()

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        now = datetime.utcnow()
        blinds = self.get_current_blinds()
        secs_next = self.seconds_until_next_level()
        registered = self.get_registered_players()
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'registration_start': self.registration_start.isoformat(),
            'registration_end': self.registration_end.isoformat(),
            'start_time': self.start_time.isoformat(),
            'max_players': self.max_players, 'min_players_to_start': self.min_players_to_start,
            'prize_pool': self.prize_pool, 'itm_percentage': self.itm_percentage,
            'status': self.status, 'current_level': self.current_level,
            'players_count': len(registered), 'total_players': len(self.players),
            'registered_players': registered, 'ranking': self.get_ranking(),
            'current_blinds': blinds, 'seconds_until_next_level': secs_next,
            'blind_structure': self.blind_structure,
            'prizes': self.calculate_prizes(), 'tables': self.tables,
            'winners': self.winners,
            'time_until_start': int((self.start_time-now).total_seconds()) if self.start_time>now else None,
            'can_register': self.can_register(), 'server_now': now.isoformat(),
        }

    def to_xml(self) -> ET.Element:
        root = ET.Element('tournament')
        # Utiliser xml_safe pour TOUTES les données utilisateur (Faille #5)
        ET.SubElement(root, 'id').text             = self.id
        ET.SubElement(root, 'n').text              = xml_safe(self.name)
        ET.SubElement(root, 'description').text    = xml_safe(self.description)
        ET.SubElement(root, 'registration_start').text = self.registration_start.isoformat()
        ET.SubElement(root, 'registration_end').text   = self.registration_end.isoformat()
        ET.SubElement(root, 'start_time').text     = self.start_time.isoformat()
        ET.SubElement(root, 'max_players').text    = str(self.max_players)
        ET.SubElement(root, 'min_players').text    = str(self.min_players_to_start)
        ET.SubElement(root, 'buy_in').text         = '0'
        ET.SubElement(root, 'prize_pool').text     = str(self.prize_pool)
        ET.SubElement(root, 'itm_percentage').text = str(self.itm_percentage)
        ET.SubElement(root, 'status').text         = self.status
        ET.SubElement(root, 'current_level').text  = str(self.current_level)
        ET.SubElement(root, 'created_at').text     = self.created_at.isoformat()
        if self.level_started_at:
            ET.SubElement(root, 'level_started_at').text = self.level_started_at.isoformat()

        bs = ET.SubElement(root, 'blind_structure')
        for lvl in self.blind_structure:
            le = ET.SubElement(bs, 'level')
            for k, v in lvl.items(): ET.SubElement(le, k).text = str(v)

        players_el = ET.SubElement(root, 'players')
        for p in self.players:
            pe = ET.SubElement(players_el, 'player')
            for k, v in p.items():
                # xml_safe sur le username et avatar (données utilisateur)
                if k in ('username', 'avatar'):
                    ET.SubElement(pe, k).text = xml_safe(v) if v else ''
                else:
                    ET.SubElement(pe, k).text = str(v) if v is not None else ''

        winners_el = ET.SubElement(root, 'winners')
        for w in self.winners:
            we = ET.SubElement(winners_el, 'winner')
            for k, v in w.items():
                ET.SubElement(we, k).text = xml_safe(str(v)) if v is not None else ''

        tables_el = ET.SubElement(root, 'tables')
        for t in self.tables: ET.SubElement(tables_el, 'table').text = t
        return root

    @classmethod
    def from_xml(cls, root):
        def _dt(tag):
            el = root.find(tag)
            if el is not None and el.text:
                try: return datetime.fromisoformat(el.text)
                except: pass
            return datetime.utcnow()
        def _txt(tag, default=''):
            el = root.find(tag)
            return el.text if el is not None and el.text else default
        def _int(tag, default=0):
            el = root.find(tag)
            try: return int(el.text) if el is not None and el.text else default
            except: return default
        def _float(tag, default=0.0):
            el = root.find(tag)
            try: return float(el.text) if el is not None and el.text else default
            except: return default

        blind_structure = []
        for lvl in root.findall('blind_structure/level'):
            blind_structure.append({
                'level': _int_el(lvl, 'level'), 'small_blind': _int_el(lvl, 'small_blind'),
                'big_blind': _int_el(lvl, 'big_blind'), 'duration': _int_el(lvl, 'duration', 10),
            })

        t = cls(
            tournament_id=_txt('id'), name=_txt('n') or _txt('name'),
            registration_start=_dt('registration_start'), registration_end=_dt('registration_end'),
            start_time=_dt('start_time'), max_players=_int('max_players', 100),
            min_players_to_start=_int('min_players', 4), prize_pool=_int('prize_pool'),
            itm_percentage=_float('itm_percentage', 10.0),
            blind_structure=blind_structure or None, description=_txt('description'),
        )
        t.status = _txt('status', TournamentStatus.REGISTRATION)
        t.current_level = _int('current_level')

        lsa = root.find('level_started_at')
        if lsa is not None and lsa.text:
            try: t.level_started_at = datetime.fromisoformat(lsa.text)
            except: t.level_started_at = None

        for pe in root.findall('players/player'):
            player = {c.tag: (c.text or '') for c in pe}
            for field in ('eliminated_rank', 'chips', 'position'):
                try: player[field] = int(player.get(field, 0) or 0)
                except: player[field] = 0
            t.players.append(player)

        for we in root.findall('winners/winner'):
            t.winners.append({c.tag: (c.text or '') for c in we})
        for te in root.findall('tables/table'):
            if te.text: t.tables.append(te.text)
        return t


def _int_el(el, tag, default=0):
    child = el.find(tag)
    try: return int(child.text) if child is not None and child.text else default
    except: return default


# ═════════════════════════════════════════════════════════════════════════════
# TournamentManager
# ═════════════════════════════════════════════════════════════════════════════

class TournamentManager:
    def __init__(self, data_dir="data", lobby=None):
        self.data_dir = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._starting: set = set()
        self._monitor_task = None
        self._ws_manager = None
        self._load_tournaments()
        # NE PAS appeler _start_monitor ici — pas d'event loop encore

    def set_ws_manager(self, ws):
        self._ws_manager = ws

    def _get_ws_manager(self):
        if self._ws_manager: return self._ws_manager
        return getattr(self.lobby, '_ws_manager', None)

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load_tournaments(self):
        for xml_file in self.tournaments_dir.glob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                t = Tournament.from_xml(tree.getroot())
                self.tournaments[t.id] = t
                logger.info(f"Tournament loaded: {t.name} [{t.status}]")
            except Exception as e:
                logger.error(f"Error loading {xml_file}: {e}")

    def save_tournament(self, tournament):
        root = tournament.to_xml()
        tree = ET.ElementTree(root)
        try: ET.indent(tree, space='')
        except: pass
        path = self.tournaments_dir / f"{tournament.id}.xml"
        try: tree.write(str(path), encoding='utf-8', xml_declaration=True)
        except Exception as e: logger.error(f"Save error {tournament.id}: {e}")

    # ── Création ──────────────────────────────────────────────────────────────

    def create_tournament(self, name, registration_start, registration_end,
                          start_time, max_players=100, min_players_to_start=4,
                          prize_pool=0, itm_percentage=10.0, blind_structure=None,
                          description="") -> Tournament:
        tid = f"tournament_{uuid.uuid4().hex[:8]}"
        t = Tournament(
            tournament_id=tid, name=name, registration_start=registration_start,
            registration_end=registration_end, start_time=start_time,
            max_players=max_players, min_players_to_start=min_players_to_start,
            prize_pool=prize_pool, itm_percentage=itm_percentage,
            blind_structure=blind_structure, description=description,
        )
        self.tournaments[tid] = t
        self.save_tournament(t)
        logger.info(f"Tournament created: {name} ({tid})")
        return t

    def register_player(self, tournament_id, user_id, username, avatar=None) -> bool:
        t = self.tournaments.get(tournament_id)
        if not t: return False
        ok = t.add_player(user_id, username, avatar)
        if ok: self.save_tournament(t)
        return ok

    def unregister_player(self, tournament_id, user_id) -> bool:
        t = self.tournaments.get(tournament_id)
        if not t: return False
        ok = t.remove_player(user_id)
        if ok: self.save_tournament(t)
        return ok

    # ── Monitor (démarré par startup_event) ───────────────────────────────────

    def start_monitor_safe(self):
        if self._monitor_task is None:
            try:
                self._monitor_task = asyncio.create_task(self._monitor_tournaments())
                logger.info("Tournament monitor started")
            except RuntimeError as e:
                logger.error(f"Could not start monitor: {e}")

    async def _monitor_tournaments(self):
        while True:
            try:
                now = datetime.utcnow()
                for tournament in list(self.tournaments.values()):

                    # 1. Démarrer les tournois à l'heure
                    if (tournament.status == TournamentStatus.REGISTRATION
                            and tournament.start_time <= now):
                        await self._start_tournament(tournament.id)

                    # 2. Avancer les blinds
                    elif tournament.status == TournamentStatus.IN_PROGRESS:
                        secs = tournament.seconds_until_next_level()
                        if secs is not None and secs <= 0:
                            if tournament.advance_level():
                                self.save_tournament(tournament)
                                await self._broadcast_level_change(tournament)
                                # Mettre à jour les blinds des tables
                                blinds = tournament.get_current_blinds()
                                if self.lobby:
                                    for tid in tournament.tables:
                                        table = self.lobby.tables.get(tid)
                                        if table:
                                            table.small_blind = blinds['small_blind']
                                            table.big_blind = blinds['big_blind']

                        # 3. Éliminer les absents longue durée
                        absent_uids = tournament.get_long_absent_players()
                        for uid in absent_uids:
                            registered = tournament.get_registered_players()
                            rank = len(registered)
                            tournament.eliminate_player(uid, rank)
                            self.save_tournament(tournament)
                            await self._broadcast_player_eliminated(tournament, uid, rank)

                        # 4. Vérifier si le tournoi est fini
                        remaining = tournament.get_registered_players()
                        if len(remaining) <= 1:
                            tournament.status = TournamentStatus.FINISHED
                            if remaining:
                                tournament.winners = [{'user_id': remaining[0]['user_id'],
                                                       'username': remaining[0]['username'],
                                                       'rank': 1}]
                            self.save_tournament(tournament)
                            logger.info(f"Tournament {tournament.name} finished!")

            except Exception as e:
                logger.error(f"Monitor error: {e}", exc_info=True)

            await asyncio.sleep(1)

    # ── Démarrage ─────────────────────────────────────────────────────────────

    async def _start_tournament(self, tournament_id):
        if tournament_id in self._starting: return
        self._starting.add(tournament_id)
        try:
            tournament = self.tournaments.get(tournament_id)
            if not tournament: return
            if tournament.status not in (TournamentStatus.REGISTRATION, TournamentStatus.STARTING):
                return

            registered = [p for p in tournament.players if p.get('status') == 'registered']
            if len(registered) < tournament.min_players_to_start:
                tournament.status = TournamentStatus.CANCELLED
                self.save_tournament(tournament)
                logger.warning(f"Tournament {tournament.name} cancelled: {len(registered)}/{tournament.min_players_to_start}")
                return

            tournament.status = TournamentStatus.STARTING
            tournament.level_started_at = datetime.utcnow()
            self.save_tournament(tournament)

            await self._create_tournament_tables(tournament)

            tournament.status = TournamentStatus.IN_PROGRESS
            self.save_tournament(tournament)
            logger.info(f"Tournament started: {tournament.name} — {len(registered)} players")

            asyncio.create_task(self._handle_prestart_absents(tournament))
        finally:
            self._starting.discard(tournament_id)

    async def _handle_prestart_absents(self, tournament):
        await asyncio.sleep(PRESTART_ABSENT_TIMEOUT)
        if not self.lobby: return
        ws_mgr = self._get_ws_manager()
        for player in tournament.players:
            if player.get('status') != 'registered': continue
            uid = player['user_id']
            table_id = player.get('table_id')
            if not table_id: continue
            if ws_mgr and not ws_mgr.is_connected(table_id, uid):
                tournament.on_player_disconnect(uid)
                logger.info(f"[{tournament.id}] {uid} absent at start → sit-out")
        self.save_tournament(tournament)

    # ── Tables ────────────────────────────────────────────────────────────────

    async def _create_tournament_tables(self, tournament):
        if not self.lobby:
            logger.error("Lobby not available for table creation")
            return

        from .models import CreateTableRequest

        registered = [p for p in tournament.players if p.get('status') == 'registered']
        players_per_table = 9
        num_tables = (len(registered) + players_per_table - 1) // players_per_table
        starting_chips = 10000

        for p in registered:
            p['chips'] = starting_chips

        random.shuffle(registered)

        for table_num in range(num_tables):
            table_request = CreateTableRequest(
                name=f"{tournament.name} — Table {table_num + 1}",
                tournament_id=tournament.id, max_players=players_per_table,
            )
            table_info = await self.lobby.create_table(table_request)
            tournament.tables.append(table_info.id)

            start_idx = table_num * players_per_table
            end_idx = min(start_idx + players_per_table, len(registered))

            for i, player in enumerate(registered[start_idx:end_idx]):
                # FIX CRITIQUE : passer les chips au join !
                success = await self.lobby.join_table(
                    player['user_id'], table_info.id, chips=starting_chips
                )
                if success:
                    player['table_id'] = table_info.id
                    player['position'] = i
                    logger.info(f"  → {player['username']} → table {table_num+1} pos {i} ({starting_chips})")
                else:
                    logger.error(f"  ✗ {player['username']} could not join table")

        self.save_tournament(tournament)
        logger.info(f"{num_tables} tables created for {tournament.name}")

    async def rebalance_tables(self, tournament):
        if not self.lobby: return
        table_players = {}
        for tid in tournament.tables:
            table = self.lobby.tables.get(tid)
            if table:
                table_players[tid] = [p for p in tournament.players
                                       if p.get('table_id') == tid and p.get('status') == 'registered']
        for tid, players in sorted(table_players.items(), key=lambda x: len(x[1])):
            if len(players) < 3 and len(tournament.tables) > 1:
                dests = [t for t in tournament.tables if t != tid]
                for player in players:
                    player['table_id'] = dests[0]
                tournament.tables.remove(tid)
                self.save_tournament(tournament)

    # ── WS Events ─────────────────────────────────────────────────────────────

    def on_player_disconnect(self, user_id, table_id):
        for t in self.tournaments.values():
            if t.status == TournamentStatus.IN_PROGRESS and table_id in t.tables:
                if any(p['user_id'] == user_id for p in t.players):
                    t.on_player_disconnect(user_id)
                    self.save_tournament(t)

    def on_player_reconnect(self, user_id, table_id):
        for t in self.tournaments.values():
            if t.status == TournamentStatus.IN_PROGRESS and table_id in t.tables:
                if any(p['user_id'] == user_id for p in t.players):
                    t.on_player_reconnect(user_id)
                    self.save_tournament(t)

    # ── Broadcasts ────────────────────────────────────────────────────────────

    async def _broadcast_level_change(self, tournament):
        blinds = tournament.get_current_blinds()
        msg = {'type': 'blind_level_change', 'tournament_id': tournament.id,
               'level': tournament.current_level + 1,
               'small_blind': blinds['small_blind'], 'big_blind': blinds['big_blind'],
               'duration': blinds.get('duration', 10),
               'seconds_until_next': tournament.seconds_until_next_level()}
        ws = self._get_ws_manager()
        if ws:
            for tid in tournament.tables:
                await ws.broadcast_to_table(tid, msg)

    async def _broadcast_player_eliminated(self, tournament, user_id, rank):
        player = next((p for p in tournament.players if p['user_id'] == user_id), {})
        msg = {'type': 'player_eliminated', 'tournament_id': tournament.id,
               'user_id': user_id, 'username': player.get('username', '?'), 'rank': rank}
        ws = self._get_ws_manager()
        if ws:
            for tid in tournament.tables:
                await ws.broadcast_to_table(tid, msg)

    # ── Accesseurs ────────────────────────────────────────────────────────────

    def get_all_tournaments(self): return list(self.tournaments.values())
    def get_tournament(self, tid): return self.tournaments.get(tid)

    def get_tournament_info_extended(self, tournament) -> dict:
        if isinstance(tournament, str):
            tournament = self.tournaments.get(tournament)
        if not tournament: return {}
        base = tournament.to_dict()
        base['registered_players'] = tournament.get_registered_players()
        base['ranking'] = sorted(
            [p for p in tournament.players if p.get('eliminated_rank', 0) > 0],
            key=lambda p: p.get('eliminated_rank', 999))
        tables_info = []
        if self.lobby:
            for tid in tournament.tables:
                table = self.lobby.tables.get(tid)
                if table:
                    try:
                        info = table.get_info()
                        tables_info.append({'id': info.id, 'name': info.name,
                                             'current_players': len(info.players),
                                             'max_players': info.max_players})
                    except: pass
        base['tables_info'] = tables_info
        try: base['prizes'] = tournament.calculate_prizes()
        except: base['prizes'] = []
        base['can_register'] = tournament.can_register()
        return base
