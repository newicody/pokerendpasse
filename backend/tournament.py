# backend/tournament.py
"""
Gestion des tournois freeroll — Version corrigée
================================================
Corrections:
- Monitor task resilient avec auto-restart
- Meilleure gestion des erreurs
- Persistance améliorée
- Fix calcul des prix
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from pathlib import Path
import asyncio
import logging
import random
import uuid

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
ABSENT_ELIMINATE_THRESHOLD = 600   # 10 min absence → élimination
PRESTART_ABSENT_TIMEOUT = 120      # 2 min après start pour se connecter
MONITOR_ERROR_BACKOFF = 5          # Secondes d'attente après erreur monitor
MAX_MONITOR_ERRORS = 10            # Erreurs max avant pause longue


def xml_safe(text: str) -> str:
    """Échappe les caractères dangereux pour XML"""
    if not text:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


class TournamentStatus:
    REGISTRATION = "registration"
    STARTING = "starting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"


# ═════════════════════════════════════════════════════════════════════════════
# Tournament (modèle de données)
# ═════════════════════════════════════════════════════════════════════════════

class Tournament:
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
        blind_structure: List[Dict] = None,
        description: str = "",
        starting_chips: int = 10000
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
        self.blind_structure = blind_structure or self._default_blind_structure()
        self.status = TournamentStatus.REGISTRATION
        self.current_level = 0
        self.level_started_at: Optional[datetime] = None
        self.players: List[Dict] = []
        self.tables: List[str] = []
        self.winners: List[Dict] = []
        self.created_at = datetime.utcnow()
        
        # Suivi des déconnexions
        self._disconnect_times: Dict[str, datetime] = {}
        self._sit_out: Dict[str, bool] = {}

    @staticmethod
    def _default_blind_structure() -> List[Dict]:
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
            {'level': 11, 'small_blind': 750,  'big_blind': 1500,  'duration': 6},
            {'level': 12, 'small_blind': 1000, 'big_blind': 2000,  'duration': 6},
        ]

    # ── Inscription ───────────────────────────────────────────────────────────

    def can_register(self) -> bool:
        now = datetime.utcnow()
        return (
            self.status == TournamentStatus.REGISTRATION
            and self.registration_start <= now < self.registration_end
            and len(self.get_registered_players()) < self.max_players
        )

    def is_registered(self, user_id: str) -> bool:
        return any(
            p['user_id'] == user_id and p.get('status') == 'registered'
            for p in self.players
        )

    def add_player(self, user_id: str, username: str, avatar: str = None) -> bool:
        if not self.can_register():
            return False
        if self.is_registered(user_id):
            return False
        
        self.players.append({
            'user_id': user_id,
            'username': username,
            'avatar': avatar,
            'status': 'registered',
            'registered_at': datetime.utcnow().isoformat(),
            'eliminated_rank': 0,
            'chips': self.starting_chips,
            'table_id': None,
            'position': None,
        })
        return True

    def remove_player(self, user_id: str) -> bool:
        for i, p in enumerate(self.players):
            if p['user_id'] == user_id and p.get('status') == 'registered':
                del self.players[i]
                return True
        return False

    def get_registered_players(self) -> List[Dict]:
        return [p for p in self.players if p.get('status') == 'registered']

    # ── Déconnexions / Absents ────────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str):
        """Marque un joueur comme déconnecté"""
        if user_id not in self._disconnect_times:
            self._disconnect_times[user_id] = datetime.utcnow()
            self._sit_out[user_id] = True
            logger.info(f"[Tournament {self.id}] Player {user_id} disconnected")

    def on_player_reconnect(self, user_id: str):
        """Marque un joueur comme reconnecté"""
        self._disconnect_times.pop(user_id, None)
        self._sit_out.pop(user_id, None)
        logger.info(f"[Tournament {self.id}] Player {user_id} reconnected")

    def is_sit_out(self, user_id: str) -> bool:
        return self._sit_out.get(user_id, False)

    def get_long_absent_players(self) -> List[str]:
        """Retourne les joueurs absents depuis plus de ABSENT_ELIMINATE_THRESHOLD"""
        now = datetime.utcnow()
        absent = []
        
        for uid, disco_time in list(self._disconnect_times.items()):
            if (now - disco_time).total_seconds() >= ABSENT_ELIMINATE_THRESHOLD:
                # Vérifier que le joueur est toujours registered
                if any(p['user_id'] == uid and p.get('status') == 'registered' for p in self.players):
                    absent.append(uid)
        
        return absent

    # ── Blinds ────────────────────────────────────────────────────────────────

    def get_current_blinds(self) -> Dict:
        if 0 <= self.current_level < len(self.blind_structure):
            return self.blind_structure[self.current_level]
        return self.blind_structure[-1] if self.blind_structure else {
            'level': 1, 'small_blind': 10, 'big_blind': 20, 'duration': 10
        }

    def seconds_until_next_level(self) -> Optional[int]:
        if self.level_started_at is None:
            return None
        
        blinds = self.get_current_blinds()
        duration = blinds.get('duration', 10) * 60  # en secondes
        elapsed = (datetime.utcnow() - self.level_started_at).total_seconds()
        remaining = duration - elapsed
        return max(0, int(remaining))

    def advance_level(self) -> bool:
        """Monte au niveau suivant. Retourne False si dernier niveau atteint."""
        if self.current_level < len(self.blind_structure) - 1:
            self.current_level += 1
            self.level_started_at = datetime.utcnow()
            blinds = self.get_current_blinds()
            logger.info(
                f"[Tournament {self.id}] Level {self.current_level + 1} — "
                f"Blinds {blinds['small_blind']}/{blinds['big_blind']}"
            )
            return True
        return False

    # ── Classement / Prix ─────────────────────────────────────────────────────

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
            })
        
        # Trier : actifs en premier (par chips desc), puis éliminés par rang
        ranking.sort(key=lambda x: (
            0 if x['status'] == 'registered' else 1,
            -x.get('chips', 0) if x['status'] == 'registered' else x['eliminated_rank']
        ))
        
        return ranking

    def eliminate_player(self, user_id: str, rank: int):
        """Élimine un joueur avec son classement"""
        for p in self.players:
            if p['user_id'] == user_id:
                p['status'] = 'eliminated'
                p['eliminated_rank'] = rank
                p['eliminated_at'] = datetime.utcnow().isoformat()
                p['chips'] = 0
                self._sit_out.pop(user_id, None)
                self._disconnect_times.pop(user_id, None)
                logger.info(f"[Tournament {self.id}] {p['username']} eliminated at rank {rank}")
                break

    def calculate_prizes(self) -> List[Dict]:
        """Calcule la distribution des prix"""
        if self.prize_pool == 0:
            return []
        
        registered_count = len(self.get_registered_players())
        if registered_count == 0:
            registered_count = len([p for p in self.players if p.get('eliminated_rank', 0) > 0])
        
        num_paid = max(1, int(registered_count * self.itm_percentage / 100))
        
        # Distribution standard
        distribution = [50, 30, 20]  # Top 3 par défaut
        
        if num_paid > 3:
            # Distribution étendue
            distribution = [25, 15, 10, 8, 7, 6, 5, 4, 3, 2, 1.5, 1, 0.5]
        
        prizes = []
        remaining = self.prize_pool
        
        for i in range(num_paid):
            if i < len(distribution):
                pct = distribution[i]
            else:
                pct = 0.5
            
            if i == num_paid - 1:
                # Dernier payé récupère le reste
                amount = remaining
            else:
                amount = int(self.prize_pool * pct / 100)
                remaining -= amount
            
            prizes.append({
                'rank': i + 1,
                'percentage': pct,
                'amount': max(0, amount)
            })
        
        return prizes

    # ── Sérialisation XML ─────────────────────────────────────────────────────

    def to_xml(self) -> ET.Element:
        root = ET.Element('tournament')
        
        # Données de base
        fields = [
            ('id', self.id),
            ('name', self.name),
            ('description', self.description),
            ('registration_start', self.registration_start.isoformat() if self.registration_start else ''),
            ('registration_end', self.registration_end.isoformat() if self.registration_end else ''),
            ('start_time', self.start_time.isoformat() if self.start_time else ''),
            ('max_players', str(self.max_players)),
            ('min_players_to_start', str(self.min_players_to_start)),
            ('prize_pool', str(self.prize_pool)),
            ('itm_percentage', str(self.itm_percentage)),
            ('starting_chips', str(self.starting_chips)),
            ('status', self.status),
            ('current_level', str(self.current_level)),
            ('level_started_at', self.level_started_at.isoformat() if self.level_started_at else ''),
            ('created_at', self.created_at.isoformat() if self.created_at else ''),
        ]
        
        for tag, value in fields:
            el = ET.SubElement(root, tag)
            el.text = xml_safe(str(value)) if value else ''
        
        # Blind structure
        bs_el = ET.SubElement(root, 'blind_structure')
        for level in self.blind_structure:
            level_el = ET.SubElement(bs_el, 'level')
            for k, v in level.items():
                sub = ET.SubElement(level_el, str(k))
                sub.text = str(v)
        
        # Players
        players_el = ET.SubElement(root, 'players')
        for player in self.players:
            p_el = ET.SubElement(players_el, 'player')
            for k, v in player.items():
                sub = ET.SubElement(p_el, str(k))
                sub.text = xml_safe(str(v)) if v is not None else ''
        
        # Winners
        winners_el = ET.SubElement(root, 'winners')
        for winner in self.winners:
            w_el = ET.SubElement(winners_el, 'winner')
            for k, v in winner.items():
                sub = ET.SubElement(w_el, str(k))
                sub.text = xml_safe(str(v)) if v is not None else ''
        
        # Tables
        tables_el = ET.SubElement(root, 'tables')
        for tid in self.tables:
            t_el = ET.SubElement(tables_el, 'table')
            t_el.text = tid
        
        return root

    @classmethod
    def from_xml(cls, root: ET.Element) -> 'Tournament':
        """Charge un tournoi depuis XML"""
        def get_text(tag: str, default: str = '') -> str:
            el = root.find(tag)
            return el.text if el is not None and el.text else default
        
        def parse_dt(text: str) -> Optional[datetime]:
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace('Z', '+00:00'))
            except:
                return None
        
        # Blind structure
        blind_structure = []
        bs_el = root.find('blind_structure')
        if bs_el is not None:
            for level_el in bs_el.findall('level'):
                level = {}
                for child in level_el:
                    try:
                        level[child.tag] = int(child.text) if child.text else 0
                    except:
                        level[child.tag] = child.text or ''
                blind_structure.append(level)
        
        t = cls(
            tournament_id=get_text('id', str(uuid.uuid4())),
            name=get_text('name', 'Unknown'),
            registration_start=parse_dt(get_text('registration_start')) or datetime.utcnow(),
            registration_end=parse_dt(get_text('registration_end')) or datetime.utcnow(),
            start_time=parse_dt(get_text('start_time')) or datetime.utcnow(),
            max_players=int(get_text('max_players', '100')),
            min_players_to_start=int(get_text('min_players_to_start', '4')),
            prize_pool=int(get_text('prize_pool', '0')),
            itm_percentage=float(get_text('itm_percentage', '10.0')),
            starting_chips=int(get_text('starting_chips', '10000')),
            blind_structure=blind_structure or None,
            description=get_text('description', ''),
        )
        
        t.status = get_text('status', TournamentStatus.REGISTRATION)
        t.current_level = int(get_text('current_level', '0'))
        t.level_started_at = parse_dt(get_text('level_started_at'))
        t.created_at = parse_dt(get_text('created_at')) or datetime.utcnow()
        
        # Players
        players_el = root.find('players')
        if players_el is not None:
            for pe in players_el.findall('player'):
                player = {c.tag: (c.text or '') for c in pe}
                for field in ('eliminated_rank', 'chips', 'position'):
                    try:
                        player[field] = int(player.get(field, 0) or 0)
                    except:
                        player[field] = 0
                t.players.append(player)
        
        # Winners
        winners_el = root.find('winners')
        if winners_el is not None:
            for we in winners_el.findall('winner'):
                t.winners.append({c.tag: (c.text or '') for c in we})
        
        # Tables
        tables_el = root.find('tables')
        if tables_el is not None:
            for te in tables_el.findall('table'):
                if te.text:
                    t.tables.append(te.text)
        
        return t


# ═════════════════════════════════════════════════════════════════════════════
# TournamentManager
# ═════════════════════════════════════════════════════════════════════════════

class TournamentManager:
    """
    Gestionnaire de tournois avec monitor resilient.
    """
    
    def __init__(self, data_dir: str = "data", lobby=None):
        self.data_dir = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._starting: Set[str] = set()  # Tournois en cours de démarrage (évite race)
        self._monitor_task: Optional[asyncio.Task] = None
        self._ws_manager = None
        self._monitor_errors = 0
        self._should_run = False
        
        self._load_tournaments()

    def set_ws_manager(self, ws):
        self._ws_manager = ws

    def _get_ws_manager(self):
        if self._ws_manager:
            return self._ws_manager
        return getattr(self.lobby, '_ws_manager', None)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_monitor(self):
        """Démarre le monitor (appelé après que l'event loop soit actif)"""
        if self._monitor_task and not self._monitor_task.done():
            return
        
        self._should_run = True
        self._monitor_errors = 0
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Tournament monitor started")

    async def stop_monitor(self):
        """Arrête le monitor"""
        self._should_run = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Tournament monitor stopped")

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load_tournaments(self):
        """Charge tous les tournois depuis le disque"""
        for xml_file in self.tournaments_dir.glob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                t = Tournament.from_xml(tree.getroot())
                self.tournaments[t.id] = t
                logger.info(f"Tournament loaded: {t.name} [{t.status}]")
            except Exception as e:
                logger.error(f"Error loading {xml_file}: {e}")

    def save_tournament(self, tournament: Tournament):
        """Sauvegarde un tournoi sur disque"""
        try:
            root = tournament.to_xml()
            tree = ET.ElementTree(root)
            
            # Indentation si disponible
            try:
                ET.indent(tree, space='  ')
            except:
                pass
            
            path = self.tournaments_dir / f"{tournament.id}.xml"
            tree.write(path, encoding='utf-8', xml_declaration=True)
            
        except Exception as e:
            logger.error(f"Error saving tournament {tournament.id}: {e}")

    def delete_tournament(self, tournament_id: str):
        """Supprime un tournoi"""
        if tournament_id in self.tournaments:
            del self.tournaments[tournament_id]
        
        try:
            (self.tournaments_dir / f"{tournament_id}.xml").unlink(missing_ok=True)
        except:
            pass

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_tournament(self, **kwargs) -> Tournament:
        """Crée un nouveau tournoi"""
        tid = kwargs.pop('tournament_id', None) or f"tournament_{uuid.uuid4().hex[:8]}"
        
        t = Tournament(tournament_id=tid, **kwargs)
        self.tournaments[tid] = t
        self.save_tournament(t)
        
        logger.info(f"Tournament created: {t.name} ({tid})")
        return t

    def get_tournament(self, tournament_id: str) -> Optional[Tournament]:
        return self.tournaments.get(tournament_id)

    def list_tournaments(self, status: str = None) -> List[Tournament]:
        """Liste les tournois, optionnellement filtrés par status"""
        if status:
            return [t for t in self.tournaments.values() if t.status == status]
        return list(self.tournaments.values())

    # ── Monitor Loop (resilient) ──────────────────────────────────────────────

    async def _monitor_loop(self):
        """
        Boucle de monitoring avec auto-recovery.
        Vérifie chaque seconde:
        - Démarrage des tournois à l'heure
        - Avancement des blinds
        - Élimination des absents
        - Fin des tournois
        """
        logger.info("Tournament monitor loop started")
        
        while self._should_run:
            try:
                await asyncio.sleep(1)
                
                now = datetime.utcnow()
                
                for tournament in list(self.tournaments.values()):
                    try:
                        await self._process_tournament(tournament, now)
                    except Exception as e:
                        logger.error(f"Error processing tournament {tournament.id}: {e}")
                
                # Reset error counter on success
                self._monitor_errors = 0
                
            except asyncio.CancelledError:
                break
                
            except Exception as e:
                self._monitor_errors += 1
                logger.error(f"Monitor loop error #{self._monitor_errors}: {e}")
                
                if self._monitor_errors >= MAX_MONITOR_ERRORS:
                    logger.error("Too many monitor errors, pausing for 60s")
                    await asyncio.sleep(60)
                    self._monitor_errors = 0
                else:
                    await asyncio.sleep(MONITOR_ERROR_BACKOFF)
        
        logger.info("Tournament monitor loop stopped")

    async def _process_tournament(self, tournament: Tournament, now: datetime):
        """Traite un tournoi individuel"""
        
        # 1. Démarrer les tournois à l'heure
        if (tournament.status == TournamentStatus.REGISTRATION
                and tournament.start_time <= now
                and tournament.id not in self._starting):
            await self._start_tournament(tournament.id)
        
        # 2. Tournoi en cours
        elif tournament.status == TournamentStatus.IN_PROGRESS:
            
            # 2a. Avancer les blinds si nécessaire
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
            
            # 2b. Éliminer les absents longue durée
            absent_uids = tournament.get_long_absent_players()
            for uid in absent_uids:
                registered = tournament.get_registered_players()
                rank = len(registered)
                tournament.eliminate_player(uid, rank)
                self.save_tournament(tournament)
                await self._broadcast_player_eliminated(tournament, uid, rank)
            
            # 2c. Vérifier si le tournoi est fini
            remaining = tournament.get_registered_players()
            if len(remaining) <= 1:
                tournament.status = TournamentStatus.FINISHED
                if remaining:
                    tournament.winners = [{
                        'user_id': remaining[0]['user_id'],
                        'username': remaining[0]['username'],
                        'rank': 1
                    }]
                self.save_tournament(tournament)
                await self._broadcast_tournament_finished(tournament)
                logger.info(f"Tournament {tournament.name} finished!")

    # ── Actions tournoi ───────────────────────────────────────────────────────

    async def _start_tournament(self, tournament_id: str):
        """Démarre un tournoi"""
        tournament = self.tournaments.get(tournament_id)
        if not tournament:
            return
        
        if tournament_id in self._starting:
            return
        
        self._starting.add(tournament_id)
        
        try:
            registered = tournament.get_registered_players()
            
            if len(registered) < tournament.min_players_to_start:
                tournament.status = TournamentStatus.CANCELLED
                self.save_tournament(tournament)
                logger.info(f"Tournament {tournament.name} cancelled - not enough players")
                await self._broadcast_tournament_cancelled(tournament)
                return
            
            tournament.status = TournamentStatus.STARTING
            self.save_tournament(tournament)
            
            # Créer les tables
            await self._create_tournament_tables(tournament)
            
            # Démarrer
            tournament.status = TournamentStatus.IN_PROGRESS
            tournament.level_started_at = datetime.utcnow()
            self.save_tournament(tournament)
            
            logger.info(f"Tournament {tournament.name} started with {len(registered)} players")
            await self._broadcast_tournament_started(tournament)
            
            # Vérifier les absents après un délai
            asyncio.create_task(self._handle_prestart_absents(tournament))
            
        finally:
            self._starting.discard(tournament_id)

    async def _create_tournament_tables(self, tournament: Tournament):
        """Crée les tables pour un tournoi"""
        if not self.lobby:
            logger.error("Lobby not available for table creation")
            return
        
        from .models import CreateTableRequest
        
        registered = tournament.get_registered_players()
        players_per_table = 9
        num_tables = (len(registered) + players_per_table - 1) // players_per_table
        starting_chips = tournament.starting_chips
        
        # Assigner les chips
        for p in registered:
            p['chips'] = starting_chips
        
        # Mélanger
        random.shuffle(registered)
        
        for table_num in range(num_tables):
            table_request = CreateTableRequest(
                name=f"{tournament.name} — Table {table_num + 1}",
                tournament_id=tournament.id,
                max_players=players_per_table,
            )
            
            table_info = await self.lobby.create_table(table_request)
            tournament.tables.append(table_info.id)
            
            # Assigner les joueurs
            start_idx = table_num * players_per_table
            end_idx = min(start_idx + players_per_table, len(registered))
            
            for i, player in enumerate(registered[start_idx:end_idx]):
                success = await self.lobby.join_table(
                    player['user_id'],
                    table_info.id,
                    chips=starting_chips
                )
                
                if success:
                    player['table_id'] = table_info.id
                    player['position'] = i
                    logger.info(f"  → {player['username']} → table {table_num + 1} pos {i}")
                else:
                    logger.error(f"  ✗ {player['username']} could not join table")
        
        self.save_tournament(tournament)
        logger.info(f"{num_tables} tables created for {tournament.name}")

    async def _handle_prestart_absents(self, tournament: Tournament):
        """Marque les joueurs non connectés comme sit-out après le délai"""
        await asyncio.sleep(PRESTART_ABSENT_TIMEOUT)
        
        if tournament.status != TournamentStatus.IN_PROGRESS:
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
                logger.info(f"[{tournament.id}] Player {uid} absent at start → sit-out")
        
        self.save_tournament(tournament)

    # ── Événements WebSocket ──────────────────────────────────────────────────

    def on_player_disconnect(self, user_id: str, table_id: str):
        """Appelé par le WebSocketManager lors d'une déco"""
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_disconnect(user_id)
                    self.save_tournament(tournament)

    def on_player_reconnect(self, user_id: str, table_id: str):
        """Appelé par le WebSocketManager lors d'une reconnexion"""
        for tournament in self.tournaments.values():
            if (tournament.status == TournamentStatus.IN_PROGRESS
                    and table_id in tournament.tables):
                if any(p['user_id'] == user_id for p in tournament.players):
                    tournament.on_player_reconnect(user_id)
                    self.save_tournament(tournament)

    # ── Broadcasts ────────────────────────────────────────────────────────────

    async def _broadcast_level_change(self, tournament: Tournament):
        """Broadcast le changement de niveau"""
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
        """Broadcast l'élimination d'un joueur"""
        ws = self._get_ws_manager()
        if not ws:
            return
        
        player = next((p for p in tournament.players if p['user_id'] == user_id), None)
        message = {
            'type': 'tournament_player_eliminated',
            'tournament_id': tournament.id,
            'user_id': user_id,
            'username': player['username'] if player else user_id,
            'rank': rank,
        }
        
        for table_id in tournament.tables:
            await ws.broadcast_to_table(table_id, message)

    async def _broadcast_tournament_started(self, tournament: Tournament):
        """Broadcast le démarrage du tournoi"""
        ws = self._get_ws_manager()
        if not ws:
            return
        
        message = {
            'type': 'tournament_started',
            'tournament_id': tournament.id,
            'name': tournament.name,
            'players_count': len(tournament.get_registered_players()),
            'tables_count': len(tournament.tables),
        }
        
        for table_id in tournament.tables:
            await ws.broadcast_to_table(table_id, message)

    async def _broadcast_tournament_finished(self, tournament: Tournament):
        """Broadcast la fin du tournoi"""
        ws = self._get_ws_manager()
        if not ws:
            return
        
        message = {
            'type': 'tournament_finished',
            'tournament_id': tournament.id,
            'name': tournament.name,
            'winners': tournament.winners,
            'prizes': tournament.calculate_prizes(),
        }
        
        for table_id in tournament.tables:
            await ws.broadcast_to_table(table_id, message)

    async def _broadcast_tournament_cancelled(self, tournament: Tournament):
        """Broadcast l'annulation du tournoi"""
        ws = self._get_ws_manager()
        if not ws:
            return
        
        message = {
            'type': 'tournament_cancelled',
            'tournament_id': tournament.id,
            'name': tournament.name,
            'reason': 'Not enough players',
        }
        
        await ws.broadcast_to_all(message)
