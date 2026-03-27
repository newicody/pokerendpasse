# backend/tournament.py - Version corrigée et complète
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import asyncio
import logging
import random
import uuid

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de gestion des absents / déconnectés
# ─────────────────────────────────────────────────────────────────────────────
ABSENT_AUTO_FOLD_TIMEOUT   = 30   # secondes avant fold automatique si absent au tour
ABSENT_GRACE_PERIOD        = 120  # secondes de reconnexion autorisées après déconnexion
ABSENT_ELIMINATE_THRESHOLD = 600  # 10 min d'absence totale → élimination (perdre les blinds)
PRESTART_ABSENT_TIMEOUT    = 120  # 2 min après démarrage pour se connecter, sinon sit-out forcé


class TournamentStatus:
    REGISTRATION = "registration"
    STARTING     = "starting"
    IN_PROGRESS  = "in_progress"
    FINISHED     = "finished"
    CANCELLED    = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Classe Tournament (modèle de données)
# ─────────────────────────────────────────────────────────────────────────────
class Tournament:
    def __init__(self, tournament_id: str, name: str,
                 registration_start: datetime, registration_end: datetime,
                 start_time: datetime, max_players: int = 100,
                 min_players_to_start: int = 4, prize_pool: int = 0,
                 itm_percentage: float = 10.0,
                 blind_structure: List[Dict] = None,
                 description: str = ""):
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
        self.level_started_at: Optional[datetime] = None   # quand le niveau actuel a commencé
        self.players: List[Dict]  = []
        self.tables: List[str]    = []
        self.winners: List[Dict]  = []
        self.created_at           = datetime.utcnow()

        # Suivi des déconnexions : {user_id: datetime de déco}
        self._disconnect_times: Dict[str, datetime] = {}
        # Suivi des sit-out : {user_id: bool}
        self._sit_out: Dict[str, bool] = {}

    # ── Inscriptions ──────────────────────────────────────────────────────────

    def can_register(self) -> bool:
        now = datetime.utcnow()
        return (self.status == TournamentStatus.REGISTRATION
                and self.registration_start <= now < self.registration_end)

    def is_registered(self, user_id: str) -> bool:
        return any(p['user_id'] == user_id and p.get('status') == 'registered'
                   for p in self.players)

    def add_player(self, user_id: str, username: str, avatar: str = None) -> bool:
        if not self.can_register():
            return False
        if len(self.players) >= self.max_players:
            return False
        if self.is_registered(user_id):
            return False
        self.players.append({
            'user_id':        user_id,
            'username':       username,
            'avatar':         avatar,
            'status':         'registered',
            'registered_at':  datetime.utcnow().isoformat(),
            'eliminated_rank': 0,
            'chips':          0,
            'table_id':       None,
            'position':       None,
        })
        return True

    def remove_player(self, user_id: str) -> bool:
        for i, p in enumerate(self.players):
            if p['user_id'] == user_id and p.get('status') == 'registered':
                del self.players[i]
                return True
        return False

    # ── Gestion des déconnexions ───────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str):
        """Appelé quand un joueur perd sa connexion WebSocket."""
        now = datetime.utcnow()
        self._disconnect_times[user_id] = now
        self._sit_out[user_id] = True
        logger.info(f"[TOURNAMENT {self.id}] Player {user_id} disconnected — sit-out activé")

    def on_player_reconnect(self, user_id: str):
        """Appelé quand un joueur se reconnecte."""
        self._disconnect_times.pop(user_id, None)
        self._sit_out[user_id] = False
        logger.info(f"[TOURNAMENT {self.id}] Player {user_id} reconnecté — sit-out levé")

    def is_sit_out(self, user_id: str) -> bool:
        return self._sit_out.get(user_id, False)

    def get_long_absent_players(self) -> List[str]:
        """Retourne les user_ids absents depuis plus de ABSENT_ELIMINATE_THRESHOLD secondes."""
        now = datetime.utcnow()
        result = []
        for uid, disc_time in self._disconnect_times.items():
            if (now - disc_time).total_seconds() >= ABSENT_ELIMINATE_THRESHOLD:
                result.append(uid)
        return result

    # ── Gestion des niveaux de blind ──────────────────────────────────────────

    def get_current_blinds(self) -> Dict:
        idx = min(self.current_level, len(self.blind_structure) - 1)
        return self.blind_structure[idx] if self.blind_structure else {'small_blind': 10, 'big_blind': 20, 'duration': 10}

    def seconds_until_next_level(self) -> Optional[int]:
        """Secondes restantes dans le niveau courant (-1 si pas démarré)."""
        if self.level_started_at is None:
            return None
        blinds    = self.get_current_blinds()
        duration  = blinds.get('duration', 10) * 60  # durée en secondes
        elapsed   = (datetime.utcnow() - self.level_started_at).total_seconds()
        remaining = duration - elapsed
        return max(0, int(remaining))

    def advance_level(self) -> bool:
        """Monte au niveau suivant. Retourne False si dernier niveau atteint."""
        if self.current_level < len(self.blind_structure) - 1:
            self.current_level   += 1
            self.level_started_at = datetime.utcnow()
            blinds = self.get_current_blinds()
            logger.info(f"[TOURNAMENT {self.id}] Niveau {self.current_level + 1} — "
                        f"Blinds {blinds['small_blind']}/{blinds['big_blind']}")
            return True
        return False

    # ── Classement / Prix ─────────────────────────────────────────────────────

    def get_registered_players(self) -> List[Dict]:
        return [p for p in self.players if p.get('status') == 'registered']

    def get_ranking(self) -> List[Dict]:
        ranking = [{
            'user_id':         p['user_id'],
            'username':        p['username'],
            'avatar':          p.get('avatar'),
            'eliminated_rank': p.get('eliminated_rank', 0),
            'status':          p.get('status', 'registered'),
            'sit_out':         self.is_sit_out(p['user_id']),
        } for p in self.players]
        ranking.sort(key=lambda x: x['eliminated_rank'] if x['eliminated_rank'] > 0 else 999)
        return ranking

    def eliminate_player(self, user_id: str, rank: int):
        for p in self.players:
            if p['user_id'] == user_id:
                p['status']          = 'eliminated'
                p['eliminated_rank'] = rank
                p['eliminated_at']   = datetime.utcnow().isoformat()
                self._sit_out.pop(user_id, None)
                self._disconnect_times.pop(user_id, None)
                break

    def calculate_prizes(self) -> List[Dict]:
        if self.prize_pool == 0:
            return []
        registered_count = len(self.get_registered_players())
        num_paid = max(1, int(registered_count * self.itm_percentage / 100))
        prizes = []
        if num_paid == 1:
            prizes.append({'rank': 1, 'percentage': 100, 'amount': self.prize_pool})
        else:
            distribution = [25, 15, 10, 8, 7, 6, 5, 4, 3, 2, 1.5, 1, 0.5]
            remaining    = self.prize_pool
            for i in range(num_paid - 1):
                pct    = distribution[i] if i < len(distribution) else 0.5
                amount = int(self.prize_pool * pct / 100)
                prizes.append({'rank': i + 1, 'percentage': pct, 'amount': amount})
                remaining -= amount
            prizes.append({
                'rank':       num_paid,
                'percentage': round(remaining / self.prize_pool * 100, 1),
                'amount':     remaining,
            })
        return prizes

    def _default_blind_structure(self) -> List[Dict]:
        return [
            {'level': 1,  'small_blind': 10,  'big_blind': 20,  'duration': 10},
            {'level': 2,  'small_blind': 15,  'big_blind': 30,  'duration': 10},
            {'level': 3,  'small_blind': 25,  'big_blind': 50,  'duration': 10},
            {'level': 4,  'small_blind': 50,  'big_blind': 100, 'duration': 10},
            {'level': 5,  'small_blind': 75,  'big_blind': 150, 'duration': 10},
            {'level': 6,  'small_blind': 100, 'big_blind': 200, 'duration': 10},
            {'level': 7,  'small_blind': 150, 'big_blind': 300, 'duration': 10},
            {'level': 8,  'small_blind': 200, 'big_blind': 400, 'duration': 10},
            {'level': 9,  'small_blind': 300, 'big_blind': 600, 'duration': 10},
            {'level': 10, 'small_blind': 400, 'big_blind': 800, 'duration': 10},
        ]

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        now = datetime.utcnow()
        blinds = self.get_current_blinds()
        secs_next = self.seconds_until_next_level()
        return {
            'id':                            self.id,
            'name':                          self.name,
            'description':                   self.description,
            'registration_start':            self.registration_start.isoformat(),
            'registration_end':              self.registration_end.isoformat(),
            'start_time':                    self.start_time.isoformat(),
            'max_players':                   self.max_players,
            'min_players_to_start':          self.min_players_to_start,
            'prize_pool':                    self.prize_pool,
            'itm_percentage':                self.itm_percentage,
            'status':                        self.status,
            'players_count':                 len(self.get_registered_players()),
            'total_players':                 len(self.players),
            'registered_players':            self.get_registered_players(),
            'ranking':                       self.get_ranking(),
            'current_level':                 self.current_level + 1,
            'current_blinds':                blinds,
            'seconds_until_next_level':      secs_next,
            'blind_structure':               self.blind_structure,
            'prizes':                        self.calculate_prizes(),
            'tables':                        self.tables,
            'winners':                       self.winners,
            'time_until_start':              int((self.start_time - now).total_seconds()) if self.start_time > now else None,
            'time_until_registration_end':   int((self.registration_end - now).total_seconds()) if self.registration_end > now else None,
            'can_register':                  self.can_register(),
            'server_now':                    now.isoformat(),  # référence UTC pour le front
        }

    def to_xml(self) -> ET.Element:
        root = ET.Element('tournament')
        ET.SubElement(root, 'id').text             = self.id
        ET.SubElement(root, 'n').text              = self.name
        ET.SubElement(root, 'description').text    = self.description
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
            for k, v in lvl.items():
                ET.SubElement(le, k).text = str(v)

        players_el = ET.SubElement(root, 'players')
        for p in self.players:
            pe = ET.SubElement(players_el, 'player')
            for k, v in p.items():
                ET.SubElement(pe, k).text = str(v) if v is not None else ''

        winners_el = ET.SubElement(root, 'winners')
        for w in self.winners:
            we = ET.SubElement(winners_el, 'winner')
            for k, v in w.items():
                ET.SubElement(we, k).text = str(v) if v is not None else ''

        tables_el = ET.SubElement(root, 'tables')
        for t in self.tables:
            ET.SubElement(tables_el, 'table').text = t

        return root

    @classmethod
    def from_xml(cls, root: ET.Element) -> 'Tournament':
        def _dt(tag):
            el = root.find(tag)
            if el is not None and el.text:
                return datetime.fromisoformat(el.text)
            return datetime.utcnow()

        def _txt(tag, default=''):
            el = root.find(tag)
            return el.text if el is not None and el.text else default

        def _int(tag, default=0):
            el = root.find(tag)
            try:
                return int(el.text) if el is not None and el.text else default
            except (ValueError, AttributeError):
                return default

        def _float(tag, default=0.0):
            el = root.find(tag)
            try:
                return float(el.text) if el is not None and el.text else default
            except (ValueError, AttributeError):
                return default

        blind_structure = []
        for lvl in root.findall('blind_structure/level'):
            blind_structure.append({
                'level':       _int_el(lvl, 'level'),
                'small_blind': _int_el(lvl, 'small_blind'),
                'big_blind':   _int_el(lvl, 'big_blind'),
                'duration':    _int_el(lvl, 'duration', 10),
            })

        t = cls(
            tournament_id      = _txt('id'),
            name               = _txt('n') or _txt('name'),
            registration_start = _dt('registration_start'),
            registration_end   = _dt('registration_end'),
            start_time         = _dt('start_time'),
            max_players        = _int('max_players', 100),
            min_players_to_start = _int('min_players', 4),
            prize_pool         = _int('prize_pool'),
            itm_percentage     = _float('itm_percentage', 10.0),
            blind_structure    = blind_structure or None,
            description        = _txt('description'),
        )
        t.status        = _txt('status', TournamentStatus.REGISTRATION)
        t.current_level = _int('current_level')

        lsa = root.find('level_started_at')
        if lsa is not None and lsa.text:
            try:
                t.level_started_at = datetime.fromisoformat(lsa.text)
            except Exception:
                t.level_started_at = None

        for pe in root.findall('players/player'):
            player = {c.tag: (c.text or '') for c in pe}
            # re-typer les champs numériques
            for field in ('eliminated_rank', 'chips', 'position'):
                try:
                    player[field] = int(player.get(field, 0) or 0)
                except (ValueError, TypeError):
                    player[field] = 0
            t.players.append(player)

        for we in root.findall('winners/winner'):
            t.winners.append({c.tag: (c.text or '') for c in we})

        for te in root.findall('tables/table'):
            if te.text:
                t.tables.append(te.text)

        return t


def _int_el(el: ET.Element, tag: str, default: int = 0) -> int:
    child = el.find(tag)
    try:
        return int(child.text) if child is not None and child.text else default
    except (ValueError, AttributeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# TournamentManager
# ─────────────────────────────────────────────────────────────────────────────
class TournamentManager:
    """Gestionnaire de tournois : création, démarrage, clock des blinds, absents."""

    def __init__(self, data_dir: str = "data", lobby=None):
        self.data_dir        = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._starting: set = set()
        self._monitor_task = None          # ← AJOUTÉ
        self._load_tournaments()
        # NE PAS appeler _start_monitor() ici
        # Le monitor sera démarré par start_monitor_safe() dans startup_event
    # ── Persistance ───────────────────────────────────────────────────────────


    def set_ws_manager(self, ws_manager) -> None:
        """
        Injecte le WebSocketManager.
        Appelé depuis main.py : tournament_manager.set_ws_manager(ws_manager)
        """
        self._ws_manager = ws_manager
        if hasattr(ws_manager, 'set_tournament_manager'):
            ws_manager.set_tournament_manager(self)

    def _get_ws_manager(self):
        """Récupère le ws_manager (self ou fallback lobby)."""
        ws = getattr(self, '_ws_manager', None)
        if ws:
            return ws
        return getattr(self.lobby, '_ws_manager', None)

    def _load_tournaments(self):
        for xml_file in self.tournaments_dir.glob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                t    = Tournament.from_xml(tree.getroot())
                self.tournaments[t.id] = t
                logger.info(f"Tournoi chargé : {t.name} [{t.status}]")
            except Exception as e:
                logger.error(f"Erreur chargement {xml_file}: {e}")

    def save_tournament(self, tournament: Tournament):
        root = tournament.to_xml()
        tree = ET.ElementTree(root)
        ET.indent(tree, space='')
        path = self.tournaments_dir / f"{tournament.id}.xml"
        try:
            tree.write(str(path), encoding='utf-8', xml_declaration=True)
        except Exception as e:
            logger.error(f"Erreur sauvegarde tournoi {tournament.id}: {e}")

    # ── Création ──────────────────────────────────────────────────────────────

    def create_tournament(self, name: str, registration_start: datetime,
                          registration_end: datetime, start_time: datetime,
                          max_players: int = 100, min_players_to_start: int = 4,
                          prize_pool: int = 0, itm_percentage: float = 10.0,
                          blind_structure: List[Dict] = None,
                          description: str = "") -> Tournament:
        # BUG FIX #4 : UUID au lieu de len() pour éviter les collisions
        tournament_id = f"tournament_{uuid.uuid4().hex[:8]}"

        tournament = Tournament(
            tournament_id        = tournament_id,
            name                 = name,
            registration_start   = registration_start,
            registration_end     = registration_end,
            start_time           = start_time,
            max_players          = max_players,
            min_players_to_start = min_players_to_start,
            prize_pool           = prize_pool,
            itm_percentage       = itm_percentage,
            blind_structure      = blind_structure,
            description          = description,
        )
        self.tournaments[tournament_id] = tournament
        self.save_tournament(tournament)
        logger.info(f"Tournoi créé : {name} ({tournament_id})")
        return tournament

    # ── Monitor principal ─────────────────────────────────────────────────────

    def _start_monitor(self):
        asyncio.create_task(self._monitor_tournaments())
        
    def start_monitor_safe(self):
        '''Appelé depuis startup_event quand l'event loop est active.'''
        if self._monitor_task is None:
            try:
                self._monitor_task = asyncio.create_task(self._monitor_tournaments())
                logger.info("Tournament monitor started")
            except RuntimeError as e:
                logger.error(f"Could not start monitor: {e}")
 
 
    def get_tournament_info_extended(self, tournament) -> dict:
        '''Retourne un dict enrichi pour l'API frontend.'''
        if isinstance(tournament, str):
            tournament = self.tournaments.get(tournament)
        if not tournament:
            return {}
 
        base = tournament.to_dict()
 
        # Joueurs inscrits
        registered = [p for p in tournament.players if p.get('status') == 'registered']
        base['registered_players'] = registered
 
        # Classement (éliminés triés par rang)
        base['ranking'] = sorted(
            [p for p in tournament.players if p.get('eliminated_rank', 0) > 0],
            key=lambda p: p.get('eliminated_rank', 999)
        )
 
        # Infos tables détaillées
        tables_info = []
        if self.lobby:
            for tid in tournament.tables:
                table = self.lobby.tables.get(tid)
                if table:
                    try:
                        info = table.get_info()
                        tables_info.append({
                            'id': info.id,
                            'name': info.name,
                            'current_players': len(info.players),
                            'max_players': info.max_players
                        })
                    except Exception as e:
                        logger.error(f"Error getting table info {tid}: {e}")
        base['tables_info'] = tables_info
 
        # Prizes
        try:
            base['prizes'] = tournament.get_prize_structure()
        except Exception:
            base['prizes'] = []
 
        # Temps avant début
        now = datetime.utcnow()
        if tournament.status == TournamentStatus.REGISTRATION:
            delta = (tournament.start_time - now).total_seconds()
            base['time_until_start'] = max(0, int(delta))
        else:
            base['time_until_start'] = None
 
        base['can_register'] = tournament.can_register()
 
        return base

    async def _monitor_tournaments(self):
        """
        Boucle principale toutes les secondes :
          1. Démarre les tournois à l'heure
          2. Avance les niveaux de blind
          3. Élimine les absents trop longs
          4. Gère le sit-out des joueurs déconnectés
        """
        while True:
            try:
                now = datetime.utcnow()
                for tournament in list(self.tournaments.values()):

                    # ── 1. Démarrage ──────────────────────────────────────────
                    if (tournament.status == TournamentStatus.REGISTRATION
                            and tournament.start_time <= now
                            and tournament.id not in self._starting):  # BUG FIX #3
                        asyncio.create_task(self.start_tournament(tournament.id))

                    # ── 2. Clock des blinds ───────────────────────────────────
                    if tournament.status == TournamentStatus.IN_PROGRESS:
                        secs = tournament.seconds_until_next_level()
                        if secs is not None and secs == 0:
                            advanced = tournament.advance_level()
                            self.save_tournament(tournament)
                            if advanced:
                                await self._broadcast_level_change(tournament)

                    # ── 3. Élimination des absents prolongés ──────────────────
                    if tournament.status == TournamentStatus.IN_PROGRESS:
                        long_absent = tournament.get_long_absent_players()
                        for uid in long_absent:
                            active_players = [p for p in tournament.players
                                              if p.get('status') == 'registered']
                            rank = len(active_players)
                            tournament.eliminate_player(uid, rank)
                            logger.warning(f"[{tournament.id}] Joueur {uid} éliminé pour absence prolongée — rang {rank}")
                            self.save_tournament(tournament)
                            await self._broadcast_player_eliminated(tournament, uid, rank)

            except Exception as e:
                logger.error(f"Erreur monitor tournois: {e}", exc_info=True)

            await asyncio.sleep(1)

    # ── Démarrage ─────────────────────────────────────────────────────────────

    async def start_tournament(self, tournament_id: str):
        """Démarre un tournoi (une seule fois grâce au verrou _starting)."""
        if tournament_id in self._starting:  # BUG FIX #3 — verrou
            return
        self._starting.add(tournament_id)
        try:
            tournament = self.tournaments.get(tournament_id)
            if not tournament:
                logger.error(f"Tournoi {tournament_id} introuvable")
                return

            # Déjà démarré ou annulé
            if tournament.status not in (TournamentStatus.REGISTRATION, TournamentStatus.STARTING):
                return

            registered = [p for p in tournament.players if p.get('status') == 'registered']
            if len(registered) < tournament.min_players_to_start:
                tournament.status = TournamentStatus.CANCELLED
                self.save_tournament(tournament)
                logger.warning(f"Tournoi {tournament.name} annulé : pas assez de joueurs "
                               f"({len(registered)}/{tournament.min_players_to_start})")
                return

            tournament.status         = TournamentStatus.STARTING
            tournament.level_started_at = datetime.utcnow()  # Clock niveau 1
            self.save_tournament(tournament)

            await self._create_tournament_tables(tournament)

            tournament.status = TournamentStatus.IN_PROGRESS
            self.save_tournament(tournament)
            logger.info(f"Tournoi démarré : {tournament.name} — {len(registered)} joueurs")

            # Attendre PRESTART_ABSENT_TIMEOUT puis mettre en sit-out les absents
            asyncio.create_task(self._handle_prestart_absents(tournament))

        finally:
            self._starting.discard(tournament_id)

    # ── Gestion des absents au démarrage ──────────────────────────────────────

    async def _handle_prestart_absents(self, tournament: Tournament):
        """
        Après PRESTART_ABSENT_TIMEOUT secondes, marque en sit-out tout joueur
        qui ne s'est pas connecté à sa table.
        """
        await asyncio.sleep(PRESTART_ABSENT_TIMEOUT)
        if not self.lobby:
            return

        for player in tournament.players:
            if player.get('status') != 'registered':
                continue
            uid      = player['user_id']
            table_id = player.get('table_id')
            if not table_id:
                continue

            # Vérifier si le joueur est connecté en WebSocket à sa table
            from .websocket_manager import WebSocketManager
            # Accès via lobby (instance partagée)
            ws_mgr = self._get_ws_manager()
            if ws_mgr and not ws_mgr.is_connected(table_id, uid):
                tournament.on_player_disconnect(uid)
                logger.info(f"[{tournament.id}] Joueur {uid} absent au démarrage → sit-out")

        self.save_tournament(tournament)

    # ── Événements WebSocket ───────────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str, table_id: str):
        """Appelé par le WebSocketManager lors d'une déco sur une table de tournoi."""
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_disconnect(user_id)
                    self.save_tournament(tournament)

    def on_player_reconnect(self, user_id: str, table_id: str):
        """Appelé par le WebSocketManager lors d'une reconnexion."""
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_reconnect(user_id)
                    self.save_tournament(tournament)

    # ── Création des tables ───────────────────────────────────────────────────

    async def _create_tournament_tables(self, tournament: Tournament):
        if not self.lobby:
            logger.error("Lobby non disponible pour la création des tables")
            return

        from .models import CreateTableRequest, GameType

        registered      = [p for p in tournament.players if p.get('status') == 'registered']
        players_per_table = 9
        num_tables      = (len(registered) + players_per_table - 1) // players_per_table

        # Donner les chips de départ
        for p in registered:
            p['chips'] = 10000

        # Mélanger les joueurs pour répartition aléatoire
        random.shuffle(registered)

        for table_num in range(num_tables):
            table_request = CreateTableRequest(
                name         = f"{tournament.name} — Table {table_num + 1}",
                tournament_id = tournament.id,
                max_players  = players_per_table,
            )
            table = await self.lobby.create_table(table_request)
            tournament.tables.append(table.id)

            start_idx = table_num * players_per_table
            end_idx   = min(start_idx + players_per_table, len(registered))

            for i, player in enumerate(registered[start_idx:end_idx]):
                starting_chips = player.get('chips', 10000)
                await self.lobby.join_table(player['user_id'], table.id, chips=starting_chips)
                player['table_id'] = table.id
                player['position'] = i
                player['status'] = 'registered'
                
        self.save_tournament(tournament)
        logger.info(f"{num_tables} tables créées pour {tournament.name}")

    # ── Rééquilibrage des tables ──────────────────────────────────────────────

    async def rebalance_tables(self, tournament: Tournament):
        """
        Rééquilibre les tables quand trop de joueurs sont éliminés
        et qu'une table a moins de 3 joueurs.
        """
        if not self.lobby:
            return

        table_players: Dict[str, List[Dict]] = {}
        for table_id in tournament.tables:
            table = self.lobby.tables.get(table_id)
            if table:
                table_players[table_id] = [
                    p for p in tournament.players
                    if p.get('table_id') == table_id and p.get('status') == 'registered'
                ]

        tables_sorted = sorted(table_players.items(), key=lambda x: len(x[1]))

        for table_id, players in tables_sorted:
            if len(players) < 3 and len(tournament.tables) > 1:
                # Déplacer les joueurs vers d'autres tables
                destination_tables = [t for t in tournament.tables if t != table_id]
                for player in players:
                    dest = destination_tables[0]
                    player['table_id'] = dest
                    logger.info(f"[{tournament.id}] Joueur {player['user_id']} "
                                f"déplacé de {table_id} → {dest}")
                tournament.tables.remove(table_id)
                self.save_tournament(tournament)

    # ── Broadcasts ────────────────────────────────────────────────────────────

    async def _broadcast_level_change(self, tournament: Tournament):
        """Diffuse le changement de niveau à toutes les tables du tournoi."""
        blinds = tournament.get_current_blinds()
        message = {
            'type':          'blind_level_change',
            'tournament_id': tournament.id,
            'level':         tournament.current_level + 1,
            'small_blind':   blinds['small_blind'],
            'big_blind':     blinds['big_blind'],
            'duration':      blinds.get('duration', 10),
            'seconds_until_next': tournament.seconds_until_next_level(),
        }
        if self.lobby:
            ws_mgr = self._get_ws_manager()
            if ws_mgr:
                for table_id in tournament.tables:
                    await ws_mgr.broadcast_to_table(table_id, message)

    async def _broadcast_player_eliminated(self, tournament: Tournament, user_id: str, rank: int):
        """Diffuse l'élimination d'un joueur."""
        player = next((p for p in tournament.players if p['user_id'] == user_id), {})
        message = {
            'type':          'player_eliminated',
            'tournament_id': tournament.id,
            'user_id':       user_id,
            'username':      player.get('username', '?'),
            'rank':          rank,
            'reason':        'absent',
        }
        if self.lobby:
            ws_mgr = self._get_ws_manager()
            if ws_mgr:
                for table_id in tournament.tables:
                    await ws_mgr.broadcast_to_table(table_id, message)

    # ── Helpers ───────────────────────────────────────────────────────────────

    # ── Accesseurs publics ────────────────────────────────────────────────────

    def get_all_tournaments(self) -> list:
        """Retourne tous les tournois."""
        return list(self.tournaments.values())

    def get_active_tournaments(self) -> list:
        """Tournois en cours (in_progress)."""
        return [t for t in self.tournaments.values()
                if t.status == TournamentStatus.IN_PROGRESS]

    def get_upcoming_tournaments(self) -> list:
        """Tournois en phase d'inscription."""
        return [t for t in self.tournaments.values()
                if t.status == TournamentStatus.REGISTRATION]

    def get_finished_tournaments(self) -> list:
        """Tournois terminés."""
        return [t for t in self.tournaments.values()
                if t.status == TournamentStatus.FINISHED]

    def get_tournament(self, tournament_id: str):
        """Récupère un tournoi par ID (None si absent)."""
        return self.tournaments.get(tournament_id)


    def register_player(self, tournament_id: str, user_id: str, username: str,
                        avatar: str = None) -> bool:
        t = self.tournaments.get(tournament_id)
        if not t:
            return False
        ok = t.add_player(user_id, username, avatar)
        if ok:
            self.save_tournament(t)
        return ok

    def unregister_player(self, tournament_id: str, user_id: str) -> bool:
        t = self.tournaments.get(tournament_id)
        if not t:
            return False
        ok = t.remove_player(user_id)
        if ok:
            self.save_tournament(t)
        return ok
