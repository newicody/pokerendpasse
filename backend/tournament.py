# backend/tournament.py
"""
Tournament Manager — PokerEndPasse
====================================
Version consolidée :
- Monitor résilient avec démarrage différé (pas dans __init__)
- Pause / Resume de tournoi
- Exclusion de joueurs
- Mute chat par joueur
- Blind clock avec level up automatique
- Rééquilibrage des tables
- Persistance XML
"""

import asyncio
import logging
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from .models import TournamentStatus, GameVariant, PlayerStatus

logger = logging.getLogger(__name__)

DEFAULT_BLIND_STRUCTURE = [
    {'level': 1, 'small_blind': 10,   'big_blind': 20,    'ante': 0, 'duration': 10},
    {'level': 2, 'small_blind': 15,   'big_blind': 30,    'ante': 0, 'duration': 10},
    {'level': 3, 'small_blind': 25,   'big_blind': 50,    'ante': 0, 'duration': 10},
    {'level': 4, 'small_blind': 50,   'big_blind': 100,   'ante': 10, 'duration': 10},
    {'level': 5, 'small_blind': 75,   'big_blind': 150,   'ante': 15, 'duration': 10},
    {'level': 6, 'small_blind': 100,  'big_blind': 200,   'ante': 25, 'duration': 10},
    {'level': 7, 'small_blind': 150,  'big_blind': 300,   'ante': 25, 'duration': 12},
    {'level': 8, 'small_blind': 200,  'big_blind': 400,   'ante': 50, 'duration': 12},
    {'level': 9, 'small_blind': 300,  'big_blind': 600,   'ante': 75, 'duration': 15},
    {'level': 10, 'small_blind': 500, 'big_blind': 1000,  'ante': 100, 'duration': 15},
    {'level': 11, 'small_blind': 750, 'big_blind': 1500,  'ante': 150, 'duration': 15},
    {'level': 12, 'small_blind': 1000,'big_blind': 2000,  'ante': 200, 'duration': 20},
]

PRESTART_ABSENT_TIMEOUT = 30  # secondes avant de marquer absents au départ


# ═══════════════════════════════════════════════════════════════════════════════
# Tournament
# ═══════════════════════════════════════════════════════════════════════════════

class Tournament:
    """Représente un tournoi avec toutes ses données."""

    def __init__(
        self,
        tournament_id: str,
        name: str,
        registration_start: datetime,
        registration_end: datetime,
        start_time: datetime,
        max_players: int = 100,
        min_players_to_start: int = 4,
        prize_pool: int = 0,
        itm_percentage: float = 10.0,
        starting_chips: int = 10000,
        blind_structure: Optional[List[Dict]] = None,
        description: str = "",
        game_variant: str = "holdem",
    ):
        self.id = tournament_id
        self.name = name
        self.description = description
        self.registration_start = registration_start
        self.registration_end = registration_end
        self.start_time = start_time
        self.max_players = max_players
        self.min_players_to_start = min_players_to_start
        self.prize_pool = prize_pool
        self.itm_percentage = itm_percentage
        self.starting_chips = starting_chips
        self.game_variant = game_variant
        self.blind_structure = blind_structure or list(DEFAULT_BLIND_STRUCTURE)

        self.status = TournamentStatus.REGISTRATION
        self.players: List[Dict] = []
        self.tables: List[str] = []
        self.winners: List[Dict] = []
        self.current_level = 0
        self.level_started_at: Optional[datetime] = None
        self.created_at = datetime.utcnow()

        # Admin controls
        self._sit_out: Dict[str, datetime] = {}          # user_id → sit-out depuis
        self._disconnect_times: Dict[str, datetime] = {}  # user_id → déco depuis
        self._muted_players: Set[str] = set()             # joueurs mutés du chat
        self._excluded_players: Set[str] = set()          # joueurs exclus

    # ── Registration ──────────────────────────────────────────────────────────

    def can_register(self) -> bool:
        now = datetime.utcnow()
        return (
            self.status == TournamentStatus.REGISTRATION
            and now >= self.registration_start
            and now <= self.registration_end
            and len(self.get_registered_players()) < self.max_players
        )

    def register_player(self, user_id: str, username: str, avatar: Optional[str] = None) -> bool:
        if not self.can_register():
            return False
        if user_id in self._excluded_players:
            return False
        if any(p['user_id'] == user_id for p in self.players):
            return False
        self.players.append({
            'user_id': user_id,
            'username': username,
            'avatar': avatar,
            'status': 'registered',
            'chips': 0,
            'table_id': None,
            'position': -1,
            'eliminated_rank': 0,
            'registered_at': datetime.utcnow().isoformat(),
        })
        return True

    def unregister_player(self, user_id: str) -> bool:
        if self.status != TournamentStatus.REGISTRATION:
            return False
        self.players = [p for p in self.players if p['user_id'] != user_id]
        return True

    def get_registered_players(self) -> List[Dict]:
        return [p for p in self.players if p.get('status') != 'eliminated']

    # ── Blinds ────────────────────────────────────────────────────────────────

    def get_current_blinds(self) -> Dict:
        if not self.blind_structure:
            return {'small_blind': 10, 'big_blind': 20, 'ante': 0, 'duration': 10}
        idx = min(self.current_level, len(self.blind_structure) - 1)
        return self.blind_structure[idx]

    def advance_level(self) -> bool:
        if self.current_level < len(self.blind_structure) - 1:
            self.current_level += 1
            self.level_started_at = datetime.utcnow()
            blinds = self.get_current_blinds()
            logger.info(f"[Tournament {self.id}] Level {self.current_level + 1} — "
                       f"Blinds {blinds['small_blind']}/{blinds['big_blind']}")
            return True
        return False

    def seconds_until_next_level(self) -> Optional[int]:
        if not self.level_started_at or self.status != TournamentStatus.IN_PROGRESS:
            return None
        blinds = self.get_current_blinds()
        duration = blinds.get('duration', 10) * 60
        elapsed = (datetime.utcnow() - self.level_started_at).total_seconds()
        remaining = max(0, duration - elapsed)
        return int(remaining)

    # ── Classement / Élimination ──────────────────────────────────────────────

    def get_ranking(self) -> List[Dict]:
        ranking = []
        for p in self.players:
            ranking.append({
                'user_id': p['user_id'],
                'username': p['username'],
                'avatar': p.get('avatar'),
                'eliminated_rank': p.get('eliminated_rank', 0),
                'status': p.get('status', 'registered'),
                'chips': p.get('chips', 0),
                'sit_out': self.is_sit_out(p['user_id']),
                'muted': p['user_id'] in self._muted_players,
            })
        ranking.sort(key=lambda x: (
            0 if x['status'] == 'registered' else 1,
            -x.get('chips', 0) if x['status'] == 'registered' else x['eliminated_rank']
        ))
        return ranking

    def eliminate_player(self, user_id: str, rank: int):
        for p in self.players:
            if p['user_id'] == user_id:
                p['status'] = 'eliminated'
                p['eliminated_rank'] = rank
                p['eliminated_at'] = datetime.utcnow().isoformat()
                p['chips'] = 0
                self._sit_out.pop(user_id, None)
                self._disconnect_times.pop(user_id, None)
                logger.info(f"[Tournament {self.id}] {p['username']} éliminé (#{rank})")
                break

    # ── Sit-out / Disconnect ──────────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str):
        self._disconnect_times[user_id] = datetime.utcnow()
        self._sit_out[user_id] = datetime.utcnow()

    def on_player_reconnect(self, user_id: str):
        self._disconnect_times.pop(user_id, None)
        self._sit_out.pop(user_id, None)

    def is_sit_out(self, user_id: str) -> bool:
        return user_id in self._sit_out

    # ── Admin Controls ────────────────────────────────────────────────────────

    def pause(self):
        if self.status == TournamentStatus.IN_PROGRESS:
            self.status = TournamentStatus.PAUSED
            logger.info(f"[Tournament {self.id}] PAUSED")

    def resume(self):
        if self.status == TournamentStatus.PAUSED:
            self.status = TournamentStatus.IN_PROGRESS
            self.level_started_at = datetime.utcnow()
            logger.info(f"[Tournament {self.id}] RESUMED")

    def mute_player(self, user_id: str):
        self._muted_players.add(user_id)
        logger.info(f"[Tournament {self.id}] Player {user_id} MUTED")

    def unmute_player(self, user_id: str):
        self._muted_players.discard(user_id)

    def is_muted(self, user_id: str) -> bool:
        return user_id in self._muted_players

    def exclude_player(self, user_id: str, reason: str = ""):
        self._excluded_players.add(user_id)
        # Éliminer si en cours
        registered = self.get_registered_players()
        rank = len(registered)
        self.eliminate_player(user_id, rank)
        logger.info(f"[Tournament {self.id}] Player {user_id} EXCLUDED: {reason}")

    def is_excluded(self, user_id: str) -> bool:
        return user_id in self._excluded_players

    # ── Sérialisation XML ─────────────────────────────────────────────────────

    def to_xml(self) -> ET.Element:
        root = ET.Element('tournament')

        def _add(tag, text):
            el = ET.SubElement(root, tag)
            el.text = str(text) if text is not None else ''

        _add('id', self.id)
        _add('name', self.name)
        _add('description', self.description)
        _add('registration_start', self.registration_start.isoformat())
        _add('registration_end', self.registration_end.isoformat())
        _add('start_time', self.start_time.isoformat())
        _add('max_players', self.max_players)
        _add('min_players', self.min_players_to_start)
        _add('prize_pool', self.prize_pool)
        _add('itm_percentage', self.itm_percentage)
        _add('starting_chips', self.starting_chips)
        _add('game_variant', self.game_variant)
        _add('status', self.status if isinstance(self.status, str) else self.status.value)
        _add('current_level', self.current_level)
        _add('level_started_at', self.level_started_at.isoformat() if self.level_started_at else '')
        _add('created_at', self.created_at.isoformat())

        # Blind structure
        bs_el = ET.SubElement(root, 'blind_structure')
        for level in self.blind_structure:
            lv = ET.SubElement(bs_el, 'level')
            for k, v in level.items():
                ET.SubElement(lv, str(k)).text = str(v)

        # Players
        ps_el = ET.SubElement(root, 'players')
        for p in self.players:
            pe = ET.SubElement(ps_el, 'player')
            for k, v in p.items():
                ET.SubElement(pe, str(k)).text = str(v) if v is not None else ''

        # Winners
        ws_el = ET.SubElement(root, 'winners')
        for w in self.winners:
            we = ET.SubElement(ws_el, 'winner')
            for k, v in w.items():
                ET.SubElement(we, str(k)).text = str(v) if v is not None else ''

        # Tables
        ts_el = ET.SubElement(root, 'tables')
        for tid in self.tables:
            ET.SubElement(ts_el, 'table').text = tid

        # Admin data
        admin_el = ET.SubElement(root, 'admin')
        muted = ET.SubElement(admin_el, 'muted_players')
        muted.text = ','.join(self._muted_players) if self._muted_players else ''
        excluded = ET.SubElement(admin_el, 'excluded_players')
        excluded.text = ','.join(self._excluded_players) if self._excluded_players else ''

        return root

    @classmethod
    def from_xml(cls, root: ET.Element) -> 'Tournament':
        def _txt(tag, default=''):
            el = root.find(tag)
            return el.text if el is not None and el.text else default

        def _int(tag, default=0):
            try:
                return int(_txt(tag, str(default)))
            except (ValueError, TypeError):
                return default

        def _float(tag, default=0.0):
            try:
                return float(_txt(tag, str(default)))
            except (ValueError, TypeError):
                return default

        def _dt(tag):
            text = _txt(tag)
            if text:
                try:
                    return datetime.fromisoformat(text)
                except Exception:
                    return None
            return None

        # Blind structure
        blind_structure = []
        bs_el = root.find('blind_structure')
        if bs_el is not None:
            for lv in bs_el.findall('level'):
                level_data = {}
                for child in lv:
                    try:
                        level_data[child.tag] = int(child.text) if child.text else 0
                    except ValueError:
                        try:
                            level_data[child.tag] = float(child.text)
                        except ValueError:
                            level_data[child.tag] = child.text or ''
                blind_structure.append(level_data)

        t = cls(
            tournament_id=_txt('id'),
            name=_txt('name'),
            registration_start=_dt('registration_start') or datetime.utcnow(),
            registration_end=_dt('registration_end') or datetime.utcnow(),
            start_time=_dt('start_time') or datetime.utcnow(),
            max_players=_int('max_players', 100),
            min_players_to_start=_int('min_players', 4),
            prize_pool=_int('prize_pool'),
            itm_percentage=_float('itm_percentage', 10.0),
            starting_chips=_int('starting_chips', 10000),
            blind_structure=blind_structure or None,
            description=_txt('description'),
            game_variant=_txt('game_variant', 'holdem'),
        )

        t.status = _txt('status', TournamentStatus.REGISTRATION)
        t.current_level = _int('current_level')
        t.level_started_at = _dt('level_started_at')
        t.created_at = _dt('created_at') or datetime.utcnow()

        # Players
        for pe in root.findall('players/player'):
            player = {c.tag: (c.text or '') for c in pe}
            for f in ('eliminated_rank', 'chips', 'position'):
                try:
                    player[f] = int(player.get(f, 0) or 0)
                except (ValueError, TypeError):
                    player[f] = 0
            t.players.append(player)

        # Winners
        for we in root.findall('winners/winner'):
            t.winners.append({c.tag: (c.text or '') for c in we})

        # Tables
        for te in root.findall('tables/table'):
            if te.text:
                t.tables.append(te.text)

        # Admin data
        admin_el = root.find('admin')
        if admin_el is not None:
            muted_text = admin_el.findtext('muted_players', '')
            if muted_text:
                t._muted_players = set(muted_text.split(','))
            excluded_text = admin_el.findtext('excluded_players', '')
            if excluded_text:
                t._excluded_players = set(excluded_text.split(','))

        return t


# ═══════════════════════════════════════════════════════════════════════════════
# TournamentManager
# ═══════════════════════════════════════════════════════════════════════════════

class TournamentManager:
    """
    Gestionnaire de tournois.
    Le monitor est démarré via start_monitor() (pas dans __init__).
    """

    def __init__(self, data_dir: str = "data", lobby=None):
        self.data_dir = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._ws_manager = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._starting: Set[str] = set()
        self._load_tournaments()

    def set_ws_manager(self, ws_manager):
        self._ws_manager = ws_manager

    def _get_ws_manager(self):
        if self._ws_manager:
            return self._ws_manager
        if self.lobby and hasattr(self.lobby, '_ws_manager'):
            return self.lobby._ws_manager
        return None

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load_tournaments(self):
        for f in self.tournaments_dir.glob("*.xml"):
            try:
                tree = ET.parse(f)
                t = Tournament.from_xml(tree.getroot())
                self.tournaments[t.id] = t
                logger.info(f"Loaded tournament: {t.name} ({t.status})")
            except Exception as e:
                logger.error(f"Load tournament {f}: {e}")

    def save_tournament(self, t: Tournament):
        try:
            tree = ET.ElementTree(t.to_xml())
            tree.write(self.tournaments_dir / f"{t.id}.xml", encoding='utf-8', xml_declaration=True)
        except Exception as e:
            logger.error(f"Save tournament {t.id}: {e}")

    def delete_tournament(self, tournament_id: str):
        self.tournaments.pop(tournament_id, None)
        try:
            (self.tournaments_dir / f"{tournament_id}.xml").unlink(missing_ok=True)
        except Exception:
            pass

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_tournament(self, **kwargs) -> Tournament:
        import uuid
        tid = str(uuid.uuid4())
        t = Tournament(tournament_id=tid, **kwargs)
        self.tournaments[tid] = t
        self.save_tournament(t)
        logger.info(f"Tournament created: {t.name} ({tid})")
        return t

    def get_tournament(self, tid: str) -> Optional[Tournament]:
        return self.tournaments.get(tid)

    def list_tournaments(self) -> List[Tournament]:
        return list(self.tournaments.values())

    # ── Monitor (démarrage différé) ───────────────────────────────────────────

    def start_monitor(self):
        """Démarre le monitor — à appeler APRÈS que l'event loop est actif"""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Tournament monitor started")

    async def stop_monitor(self):
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("Tournament monitor stopped")

    async def _monitor_loop(self):
        """Boucle de surveillance : démarrage auto, blind clock, rééquilibrage"""
        while True:
            try:
                now = datetime.utcnow()
                for t in list(self.tournaments.values()):
                    # Démarrage automatique
                    if (t.status == TournamentStatus.REGISTRATION
                            and now >= t.start_time
                            and t.id not in self._starting):
                        registered = t.get_registered_players()
                        if len(registered) >= t.min_players_to_start:
                            self._starting.add(t.id)
                            asyncio.create_task(self._start_tournament(t))

                    # Blind clock
                    if t.status == TournamentStatus.IN_PROGRESS:
                        remaining = t.seconds_until_next_level()
                        if remaining is not None and remaining <= 0:
                            if t.advance_level():
                                await self._broadcast_level_change(t)
                                # Mettre à jour les blinds sur les tables
                                await self._update_table_blinds(t)
                                self.save_tournament(t)

                    # Rééquilibrage
                    if t.status == TournamentStatus.IN_PROGRESS:
                        await self.rebalance_tables(t)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Monitor error: {e}")

            await asyncio.sleep(5)

    # ── Démarrage d'un tournoi ────────────────────────────────────────────────

    async def _start_tournament(self, tournament: Tournament):
        try:
            tournament.status = TournamentStatus.IN_PROGRESS
            tournament.level_started_at = datetime.utcnow()
            await self._create_tournament_tables(tournament)
            self.save_tournament(tournament)

            # Attendre un peu puis vérifier les absents
            await asyncio.sleep(PRESTART_ABSENT_TIMEOUT)
            await self._check_absent_players(tournament)

            logger.info(f"Tournament {tournament.name} started!")
        except Exception as e:
            logger.error(f"Start tournament {tournament.id}: {e}")
            tournament.status = TournamentStatus.REGISTRATION
        finally:
            self._starting.discard(tournament.id)

    async def _create_tournament_tables(self, tournament: Tournament):
        if not self.lobby:
            logger.error("Lobby non disponible")
            return

        from .models import CreateTableRequest

        registered = [p for p in tournament.players if p.get('status') == 'registered']
        for p in registered:
            p['chips'] = tournament.starting_chips

        random.shuffle(registered)

        players_per_table = 9
        num_tables = (len(registered) + players_per_table - 1) // players_per_table

        for table_num in range(num_tables):
            table_request = CreateTableRequest(
                name=f"{tournament.name} — Table {table_num + 1}",
                tournament_id=tournament.id,
                max_players=players_per_table,
            )
            table = await self.lobby.create_table(
                table_request,
                game_variant=GameVariant(tournament.game_variant) if tournament.game_variant else GameVariant.HOLDEM,
            )
            tournament.tables.append(table.id)

            start_idx = table_num * players_per_table
            end_idx = min(start_idx + players_per_table, len(registered))

            for i, player in enumerate(registered[start_idx:end_idx]):
                await self.lobby.join_table(player['user_id'], table.id)
                player['table_id'] = table.id
                player['position'] = i
                player['status'] = 'registered'

        self.save_tournament(tournament)
        logger.info(f"{num_tables} tables créées pour {tournament.name}")

    async def _check_absent_players(self, tournament: Tournament):
        if not self.lobby:
            return
        ws_mgr = self._get_ws_manager()
        if not ws_mgr:
            return

        for player in tournament.players:
            if player.get('status') != 'registered':
                continue
            uid = player['user_id']
            table_id = player.get('table_id')
            if not table_id:
                continue
            if not ws_mgr.is_connected(table_id, uid):
                tournament.on_player_disconnect(uid)
                logger.info(f"[{tournament.id}] Player {uid} absent → sit-out")

        self.save_tournament(tournament)

    async def _update_table_blinds(self, tournament: Tournament):
        if not self.lobby:
            return
        blinds = tournament.get_current_blinds()
        for table_id in tournament.tables:
            table = self.lobby.tables.get(table_id)
            if table:
                table.update_blinds(
                    blinds['small_blind'],
                    blinds['big_blind'],
                    blinds.get('ante', 0),
                )

    # ── Rééquilibrage ─────────────────────────────────────────────────────────

    async def rebalance_tables(self, tournament: Tournament):
        """
        Rééquilibre les tables :
        1. Ferme les tables vides
        2. Si une table peut absorber tous les joueurs d'une autre → merge
        3. Si écart > 2 entre tables → déplace un joueur de la plus grande vers la plus petite
        """
        if not self.lobby or len(tournament.tables) < 2:
            return

        # Compter les joueurs actifs par table
        table_counts: Dict[str, int] = {}
        for tid in list(tournament.tables):
            table = self.lobby.tables.get(tid)
            if table:
                active = len([p for p in table.players.values()
                             if p.chips > 0 and p.status != 'eliminated'])
                table_counts[tid] = active
            else:
                # Table n'existe plus
                tournament.tables.remove(tid)

        if not table_counts:
            return

        # 1. Fermer les tables vides
        for tid in list(table_counts.keys()):
            if table_counts[tid] == 0:
                tournament.tables.remove(tid)
                await self.lobby.close_table(tid)
                del table_counts[tid]
                logger.info(f"[{tournament.id}] Table vide fermée: {tid}")

        if len(table_counts) < 2:
            return

        # 2. Merge si une table a assez peu de joueurs pour être absorbée
        sorted_tables = sorted(table_counts.items(), key=lambda x: x[1])
        smallest_tid, smallest_count = sorted_tables[0]
        largest_tid, largest_count = sorted_tables[-1]

        # Vérifier si la plus petite table peut être absorbée par une autre
        for dest_tid, dest_count in sorted_tables[1:]:
            dest_table = self.lobby.tables.get(dest_tid)
            if not dest_table:
                continue
            available_seats = dest_table.max_players - dest_count
            if available_seats >= smallest_count and smallest_count > 0:
                # Déplacer tous les joueurs de smallest vers dest
                src_table = self.lobby.tables.get(smallest_tid)
                if src_table:
                    await self._move_players(tournament, src_table, dest_table,
                                            list(src_table.players.keys()))
                    tournament.tables.remove(smallest_tid)
                    await self.lobby.close_table(smallest_tid)
                    logger.info(f"[{tournament.id}] Table {smallest_tid} fusionnée dans {dest_tid}")
                    self.save_tournament(tournament)
                    return  # un seul rééquilibrage par cycle

        # 3. Si écart > 2, déplacer un joueur
        if largest_count - smallest_count > 2:
            src_table = self.lobby.tables.get(largest_tid)
            dest_table = self.lobby.tables.get(smallest_tid)
            if src_table and dest_table:
                # Choisir le joueur avec le moins de chips (moins perturbant)
                candidates = sorted(
                    [p for p in src_table.players.values()
                     if p.chips > 0 and p.status != PlayerStatus.ELIMINATED],
                    key=lambda p: p.chips,
                )
                if candidates:
                    player = candidates[0]
                    await self._move_players(tournament, src_table, dest_table,
                                            [player.user_id])
                    logger.info(f"[{tournament.id}] Moved {player.username} from {largest_tid} to {smallest_tid}")
                    self.save_tournament(tournament)

    async def _move_players(self, tournament: Tournament,
                           src_table, dest_table, user_ids: list):
        """Déplace des joueurs d'une table à une autre"""
        ws = self._get_ws_manager()

        for uid in user_ids:
            if uid not in src_table.players:
                continue
            player_state = src_table.players[uid]
            chips = player_state.chips
            username = player_state.username
            avatar = player_state.avatar

            # Retirer de la source
            src_table.remove_player(uid)
            if self.lobby:
                self.lobby.user_to_table.pop(uid, None)

            # Ajouter à la destination
            dest_table.add_player(uid, username, chips, avatar)
            if self.lobby:
                self.lobby.user_to_table[uid] = dest_table.id

            # Mettre à jour dans le tournoi
            for p in tournament.players:
                if p['user_id'] == uid:
                    p['table_id'] = dest_table.id
                    break

            # Notifier le joueur
            if ws:
                await ws.broadcast_to_table(src_table.id, {
                    'type': 'player_moved',
                    'user_id': uid, 'username': username,
                    'to_table': dest_table.id,
                })
                # Le joueur devra se reconnecter au WS de la nouvelle table
                await ws.send_to_user(src_table.id, uid, {
                    'type': 'table_change',
                    'new_table_id': dest_table.id,
                    'new_table_name': dest_table.name,
                    'message': f'Vous avez été déplacé à {dest_table.name}',
                })

    # ── Événements WebSocket ──────────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str, table_id: str):
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_disconnect(user_id)
                    self.save_tournament(tournament)

    def on_player_reconnect(self, user_id: str, table_id: str):
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_reconnect(user_id)
                    self.save_tournament(tournament)

    # ── Broadcasts ────────────────────────────────────────────────────────────

    async def _broadcast_level_change(self, tournament: Tournament):
        ws = self._get_ws_manager()
        if not ws:
            return
        blinds = tournament.get_current_blinds()
        message = {
            'type': 'tournament_level_change',
            'tournament_id': tournament.id,
            'level': tournament.current_level + 1,
            'small_blind': blinds['small_blind'],
            'big_blind': blinds['big_blind'],
            'duration': blinds.get('duration', 10),
        }
        for table_id in tournament.tables:
            await ws.broadcast_to_table(table_id, message)

    async def _broadcast_player_eliminated(self, tournament: Tournament, user_id: str, rank: int):
        ws = self._get_ws_manager()
        if not ws:
            return
        player = next((p for p in tournament.players if p['user_id'] == user_id), None)
        if not player:
            return
        message = {
            'type': 'tournament_player_eliminated',
            'tournament_id': tournament.id,
            'user_id': user_id,
            'username': player.get('username', '?'),
            'rank': rank,
        }
        for table_id in tournament.tables:
            await ws.broadcast_to_table(table_id, message)
