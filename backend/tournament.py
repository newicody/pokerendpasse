# backend/tournament.py - Version simplifiée
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import asyncio
import logging
import random

logger = logging.getLogger(__name__)

class TournamentStatus:
    REGISTRATION = "registration"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"

# backend/tournament.py - Modifier la classe Tournament
class Tournament:
    def __init__(self, data_dir: str = "data", lobby=None):
        self.data_dir = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._load_tournaments()
        self._start_monitor()

    def to_dict(self) -> Dict:
        now = datetime.utcnow()
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'registration_start': self.registration_start.isoformat(),
            'registration_end': self.registration_end.isoformat(),
            'start_time': self.start_time.isoformat(),
            'max_players': self.max_players,
            'min_players_to_start': self.min_players_to_start,
            'prize_pool': self.prize_pool,
            'itm_percentage': self.itm_percentage,
            'status': self.status,
            'players_count': len([p for p in self.players if p.get('status') == 'registered']),
            'total_players': len(self.players),
            'registered_players': self.get_registered_players(),
            'ranking': self.get_ranking(),
            'current_level': self.current_level + 1,
            'current_blinds': self.get_current_blinds(),
            'blind_structure': self.blind_structure,
            'prizes': self.calculate_prizes(),
            'tables': self.tables,
            'winners': self.winners,
            'time_until_start': int((self.start_time - now).total_seconds()) if self.start_time > now else None,
            'time_until_registration_end': int((self.registration_end - now).total_seconds()) if self.registration_end > now else None,
            'can_register': self.can_register()
        }    
        

    def calculate_prizes(self) -> List[Dict]:
        """Calcule la structure des prix"""
        if self.prize_pool == 0:
            return []
        
        registered_count = len([p for p in self.players if p.get('status') == 'registered'])
        num_paid = max(1, int(registered_count * self.itm_percentage / 100))
        prizes = []
        
        if num_paid == 1:
            prizes.append({'rank': 1, 'percentage': 100, 'amount': self.prize_pool})
        else:
            # Structure progressive standard pour poker
            distribution = [25, 15, 10, 8, 7, 6, 5, 4, 3, 2, 1.5, 1, 0.5]
            remaining = self.prize_pool
            
            for i in range(num_paid - 1):
                pct = distribution[i] if i < len(distribution) else 0.5
                amount = int(self.prize_pool * pct / 100)
                prizes.append({
                    'rank': i + 1,
                    'percentage': pct,
                    'amount': amount
                })
                remaining -= amount
            
            prizes.append({
                'rank': num_paid,
                'percentage': round(remaining / self.prize_pool * 100, 1),
                'amount': remaining
            })
        
        return prizes

    def _default_blind_structure(self) -> List[Dict]:
        return [
            {'level': 1, 'small_blind': 10, 'big_blind': 20, 'duration': 10},
            {'level': 2, 'small_blind': 15, 'big_blind': 30, 'duration': 10},
            {'level': 3, 'small_blind': 25, 'big_blind': 50, 'duration': 10},
            {'level': 4, 'small_blind': 50, 'big_blind': 100, 'duration': 10},
            {'level': 5, 'small_blind': 75, 'big_blind': 150, 'duration': 10},
            {'level': 6, 'small_blind': 100, 'big_blind': 200, 'duration': 10}
        ]
    
    def can_register(self) -> bool:
        """Vérifie si les inscriptions sont ouvertes (late registration incluse)"""
        now = datetime.utcnow()
        # Les inscriptions sont ouvertes jusqu'à registration_end (qui inclut late registration)
        return self.status == TournamentStatus.REGISTRATION and self.registration_start <= now < self.registration_end
    
    def is_registered(self, user_id: str) -> bool:
        return any(p['user_id'] == user_id and p.get('status') == 'registered' for p in self.players)
    
    def add_player(self, user_id: str, username: str, avatar: str = None) -> bool:
        if not self.can_register():
            return False
        if len(self.players) >= self.max_players:
            return False
        if self.is_registered(user_id):
            return False
        
        self.players.append({
            'user_id': user_id,
            'username': username,
            'avatar': avatar,
            'status': 'registered',
            'registered_at': datetime.utcnow().isoformat(),
            'eliminated_rank': 0
        })
        return True
    
    def remove_player(self, user_id: str) -> bool:
        for i, player in enumerate(self.players):
            if player['user_id'] == user_id and player.get('status') == 'registered':
                del self.players[i]
                return True
        return False
    

    def get_registered_players(self) -> List[Dict]:
        return [p for p in self.players if p.get('status') == 'registered']
    
    def get_ranking(self) -> List[Dict]:
        """Retourne le classement des joueurs"""
        ranking = []
        for player in self.players:
            ranking.append({
                'user_id': player['user_id'],
                'username': player['username'],
                'avatar': player.get('avatar'),
                'eliminated_rank': player.get('eliminated_rank', 0),
                'status': player.get('status', 'registered')
            })
        # Trier par rang d'élimination (les plus hauts rangs en premier)
        ranking.sort(key=lambda x: x['eliminated_rank'] if x['eliminated_rank'] > 0 else 999)
        return ranking
    
    def eliminate_player(self, user_id: str, rank: int):
        """Élimine un joueur et lui attribue un rang"""
        for player in self.players:
            if player['user_id'] == user_id:
                player['status'] = 'eliminated'
                player['eliminated_rank'] = rank
                player['eliminated_at'] = datetime.utcnow().isoformat()
                break
    
    def get_current_blinds(self) -> Dict:
        """Retourne les blinds actuelles"""
        if self.current_level < len(self.blind_structure):
            return self.blind_structure[self.current_level]
        return self.blind_structure[-1] if self.blind_structure else {'small_blind': 10, 'big_blind': 20}
        
class TournamentManager:
    """Gestionnaire de tournois"""
    
    def __init__(self, data_dir: str = "data", lobby=None):
        self.data_dir = Path(data_dir)
        self.tournaments_dir = self.data_dir / "tournaments"
        self.tournaments_dir.mkdir(parents=True, exist_ok=True)
        self.tournaments: Dict[str, Tournament] = {}
        self.lobby = lobby
        self._load_tournaments()
        self._start_monitor()
        
    def create_tournament(self, name: str, registration_start: datetime,
                          registration_end: datetime, start_time: datetime,
                          max_players: int = 100, min_players_to_start: int = 4,
                          prize_pool: int = 0, itm_percentage: float = 10.0,
                          blind_structure: List[Dict] = None,
                          description: str = "") -> Tournament:
        """Crée un nouveau tournoi"""
        tournament_id = f"tournament_{len(self.tournaments) + 1}"
        
        tournament = Tournament(
            tournament_id=tournament_id,
            name=name,
            registration_start=registration_start,
            registration_end=registration_end,
            start_time=start_time,
            max_players=max_players,
            min_players_to_start=min_players_to_start,
            prize_pool=prize_pool,
            itm_percentage=itm_percentage,
            blind_structure=blind_structure
        )
        tournament.description = description
        
        self.tournaments[tournament_id] = tournament
        self.save_tournament(tournament)
        
        # Planifier le démarrage si la date est dans le futur
        if start_time > datetime.utcnow():
            asyncio.create_task(self._schedule_start(tournament))
        
        logger.info(f"Tournament created: {name}")
        return tournament


    async def _create_tournament_tables(self, tournament: Tournament):
        """Crée les tables pour le tournoi"""
        if not self.lobby:
            logger.error("Lobby not available for tournament table creation")
            return
    
        from .models import CreateTableRequest, GameType
    
        registered_players = [p for p in tournament.players if p.get('status') == 'registered']
        players_per_table = 9
        num_tables = (len(registered_players) + players_per_table - 1) // players_per_table
    
        # Initialiser les joueurs avec 1000 chips
        for player in registered_players:
            player['chips'] = 1000
    
        for table_num in range(num_tables):
            # Créer une table pour le tournoi
            table_request = CreateTableRequest(
                name=f"{tournament.name} - Table {table_num + 1}",
                tournament_id=tournament.id,
                max_players=players_per_table
            )
        
            table = await self.lobby.create_table(table_request)
            tournament.tables.append(table.id)
        
            # Assigner les joueurs à la table
            start_idx = table_num * players_per_table
            end_idx = min(start_idx + players_per_table, len(registered_players))
        
            for i, player in enumerate(registered_players[start_idx:end_idx]):
                # Ajouter le joueur à la table
                from .models import JoinTableRequest
                join_request = JoinTableRequest(user_id=player['user_id'])
                await self.lobby.join_table(join_request.user_id, table.id)
            
                # Mettre à jour le joueur dans le tournoi
                player['table_id'] = table.id
                player['position'] = i
                player['status'] = 'playing'
    
        self.save_tournament(tournament)
        logger.info(f"Created {num_tables} tables for tournament {tournament.name}")

    async def start_tournament(self, tournament_id: str):
        """Démarre un tournoi"""
        tournament = self.tournaments.get(tournament_id)
        if not tournament:
            logger.error(f"Tournament {tournament_id} not found")
            return
    
        registered_players = [p for p in tournament.players if p.get('status') == 'registered']
    
        if len(registered_players) < tournament.min_players_to_start:
            tournament.status = TournamentStatus.CANCELLED
            self.save_tournament(tournament)
            logger.warning(f"Tournament {tournament.name} cancelled: not enough players")
            return
    
        tournament.status = TournamentStatus.STARTING
        self.save_tournament(tournament)
    
        # Créer les tables pour le tournoi
        await self._create_tournament_tables(tournament)
    
        tournament.status = TournamentStatus.IN_PROGRESS
        self.save_tournament(tournament)
    
        logger.info(f"Tournament started: {tournament.name} with {len(registered_players)} players")
        # backend/tournament.py - Modifier to_dict


    async def _schedule_start(self, tournament: Tournament):
        """Planifie le démarrage du tournoi"""
        now = datetime.utcnow()
        
        # Attendre jusqu'à la fin des inscriptions ou l'heure de début
        if tournament.start_time > now:
            delay = (tournament.start_time - now).total_seconds()
            logger.info(f"Tournament {tournament.name} starts in {delay:.0f} seconds")
            await asyncio.sleep(delay)
        
        await self.start_tournament(tournament.id)

    def _start_monitor(self):
        """Démarre le moniteur de tournois"""
        asyncio.create_task(self._monitor_tournaments())
    
    async def _monitor_tournaments(self):
        """Monitore les tournois pour les démarrer"""
        while True:
            try:
                now = datetime.utcnow()
                for tournament in self.tournaments.values():
                    # Vérifier si le tournoi doit démarrer
                    if (tournament.status == TournamentStatus.REGISTRATION and 
                        tournament.start_time <= now):
                        await self.start_tournament(tournament.id)
                    
                    # Vérifier si les inscriptions sont terminées et le tournoi doit être préparé
                    if (tournament.status == TournamentStatus.REGISTRATION and 
                        tournament.registration_end <= now and 
                        tournament.start_time > now):
                        # Préparer le tournoi (créer les tables)
                        await self._prepare_tournament(tournament)
                
                await asyncio.sleep(1)  # Vérifier chaque seconde
            except Exception as e:
                logger.error(f"Error in tournament monitor: {e}")
                await asyncio.sleep(5)

    async def _prepare_tournament(self, tournament: Tournament):
        """Prépare un tournoi avant son démarrage"""
        if len([p for p in tournament.players if p.get('status') == 'registered']) >= tournament.min_players_to_start:
            # Assez de joueurs, planifier le démarrage
            asyncio.create_task(self._schedule_start(tournament))
        else:
            tournament.status = TournamentStatus.CANCELLED
            self.save_tournament(tournament)
            logger.warning(f"Tournament {tournament.name} cancelled: not enough players")

    # backend/tournament.py - Ajouter la méthode pour équilibrer les tables
    async def rebalance_tables(self, tournament: Tournament):
        """Rééquilibre les tables après des éliminations"""
        if not self.lobby:
            return
        
        # Récupérer toutes les tables du tournoi
        tables = []
        for table_id in tournament.tables:
            table = self.lobby.tables.get(table_id)
            if table:
                tables.append(table)
        
        if len(tables) <= 1:
            return
        
        # Compter les joueurs par table
        table_players = [(t, len([p for p in t.players.values() if p.status == PlayerStatus.ACTIVE])) 
                         for t in tables]
        
        # Trouver la moyenne
        avg_players = sum(count for _, count in table_players) / len(table_players)
        
        # Tables avec trop de joueurs
        full_tables = [(t, count) for t, count in table_players if count > avg_players + 1]
        # Tables avec trop peu de joueurs
        empty_tables = [(t, count) for t, count in table_players if count < avg_players - 1]
        
        # Déplacer des joueurs des tables pleines vers les tables vides
        for full_table, full_count in full_tables:
            for empty_table, empty_count in empty_tables:
                if full_count - 1 > avg_players and empty_count + 1 < avg_players:
                    # Prendre un joueur de full_table et le mettre dans empty_table
                    players = list(full_table.players.values())
                    if players:
                        player = random.choice(players)
                        await self.lobby.leave_table(player.user_id)
                        await self.lobby.join_table(player.user_id, empty_table.id)
                        logger.info(f"Moved player {player.username} from {full_table.name} to {empty_table.name}")
                        break

    def _load_tournaments(self):
        """Charge les tournois depuis XML"""
        for filepath in self.tournaments_dir.glob("*.xml"):
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
                
                tournament = Tournament(
                    tournament_id=root.findtext('id'),
                    name=root.findtext('name'),
                    registration_start=datetime.fromisoformat(root.findtext('registration_start')),
                    registration_end=datetime.fromisoformat(root.findtext('registration_end')),
                    start_time=datetime.fromisoformat(root.findtext('start_time')),
                    max_players=int(root.findtext('max_players', '100')),
                    min_players_to_start=int(root.findtext('min_players_to_start', '4'))
                )
                tournament.description = root.findtext('description', '')
                tournament.status = root.findtext('status', 'registration')
                tournament.current_level = int(root.findtext('current_level', '0'))
                
                # Charger les joueurs
                for player_elem in root.findall('players/player'):
                    tournament.players.append({
                        'user_id': player_elem.findtext('user_id'),
                        'username': player_elem.findtext('username'),
                        'avatar': player_elem.findtext('avatar'),
                        'status': player_elem.findtext('status', 'registered'),
                        'registered_at': player_elem.findtext('registered_at'),
                        'eliminated_rank': int(player_elem.findtext('eliminated_rank', '0'))
                    })
                
                # Charger les gagnants
                for winner_elem in root.findall('winners/winner'):
                    tournament.winners.append({
                        'user_id': winner_elem.findtext('user_id'),
                        'username': winner_elem.findtext('username'),
                        'rank': int(winner_elem.findtext('rank'))
                    })
                
                self.tournaments[tournament.id] = tournament
                
            except Exception as e:
                logger.error(f"Error loading tournament {filepath}: {e}")
    
    def save_tournament(self, tournament: Tournament):
        filepath = self.tournaments_dir / f"{tournament.id}.xml"
        root = ET.Element("tournament")
        ET.SubElement(root, "id").text = tournament.id
        ET.SubElement(root, "name").text = tournament.name
        ET.SubElement(root, "description").text = tournament.description
        ET.SubElement(root, "registration_start").text = tournament.registration_start.isoformat()
        ET.SubElement(root, "registration_end").text = tournament.registration_end.isoformat()
        ET.SubElement(root, "start_time").text = tournament.start_time.isoformat()
        ET.SubElement(root, "max_players").text = str(tournament.max_players)
        ET.SubElement(root, "min_players_to_start").text = str(tournament.min_players_to_start)
        ET.SubElement(root, "status").text = tournament.status
        ET.SubElement(root, "current_level").text = str(tournament.current_level)
        
        players_elem = ET.SubElement(root, "players")
        for player in tournament.players:
            player_elem = ET.SubElement(players_elem, "player")
            ET.SubElement(player_elem, "user_id").text = player['user_id']
            ET.SubElement(player_elem, "username").text = player['username']
            if player.get('avatar'):
                ET.SubElement(player_elem, "avatar").text = player['avatar']
            ET.SubElement(player_elem, "status").text = player.get('status', 'registered')
            ET.SubElement(player_elem, "registered_at").text = player.get('registered_at', datetime.utcnow().isoformat())
            ET.SubElement(player_elem, "eliminated_rank").text = str(player.get('eliminated_rank', 0))
        
        winners_elem = ET.SubElement(root, "winners")
        for winner in tournament.winners:
            winner_elem = ET.SubElement(winners_elem, "winner")
            ET.SubElement(winner_elem, "user_id").text = winner['user_id']
            ET.SubElement(winner_elem, "username").text = winner['username']
            ET.SubElement(winner_elem, "rank").text = str(winner['rank'])
        
        tree = ET.ElementTree(root)
        tree.write(filepath, encoding='utf-8', xml_declaration=True)
    
    # backend/tournament.py - Ajouter cette méthode dans TournamentManager
    async def start_tournament(self, tournament_id: str):
        """Démarre un tournoi"""
        tournament = self.tournaments.get(tournament_id)
        if not tournament:
            logger.error(f"Tournament {tournament_id} not found")
            return
        
        registered_players = [p for p in tournament.players if p.get('status') == 'registered']
        
        if len(registered_players) < tournament.min_players_to_start:
            tournament.status = TournamentStatus.CANCELLED
            self.save_tournament(tournament)
            logger.warning(f"Tournament {tournament.name} cancelled: not enough players")
            return
        
        tournament.status = TournamentStatus.STARTING
        self.save_tournament(tournament)
        
        # Créer les tables pour le tournoi
        await self._create_tournament_tables(tournament)
        
        tournament.status = TournamentStatus.IN_PROGRESS
        self.save_tournament(tournament)
        
        logger.info(f"Tournament started: {tournament.name} with {len(registered_players)} players")    

    def register_player(self, tournament_id: str, user_id: str, username: str) -> bool:
        """Inscrit un joueur au tournoi"""
        tournament = self.tournaments.get(tournament_id)
        if not tournament:
            return False
    
        # Vérifier si déjà inscrit
        if tournament.is_registered(user_id):
            return False
    
        # Vérifier si inscriptions ouvertes
        if not tournament.can_register():
            return False
    
        # Vérifier la limite de joueurs
        if len(tournament.players) >= tournament.max_players:
            return False
    
        tournament.players.append({
            'user_id': user_id,
            'username': username,
            'avatar': None,
            'status': 'registered',
            'registered_at': datetime.utcnow().isoformat(),
            'eliminated_rank': 0
        })
    
        self.save_tournament(tournament)
        logger.info(f"Player {username} registered for tournament {tournament.name}")
        return True
    
    def unregister_player(self, tournament_id: str, user_id: str) -> bool:
        """Désinscrit un joueur du tournoi"""
        tournament = self.tournaments.get(tournament_id)
        if not tournament:
            return False
    
        for i, player in enumerate(tournament.players):
            if player.get('user_id') == user_id and player.get('status') == 'registered':
                del tournament.players[i]
                self.save_tournament(tournament)
                logger.info(f"Player {user_id} unregistered from tournament {tournament.name}")
                return True
    
        return False
    
    def get_active_tournaments(self) -> List[Dict]:
        return [t.to_dict() for t in self.tournaments.values() 
                if t.status in [TournamentStatus.REGISTRATION, TournamentStatus.IN_PROGRESS]]
    
    def get_upcoming_tournaments(self) -> List[Dict]:
        now = datetime.utcnow()
        return [t.to_dict() for t in self.tournaments.values() 
                if t.registration_start > now and t.status == TournamentStatus.REGISTRATION]
