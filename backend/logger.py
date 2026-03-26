# backend/logger.py
import logging
import sys
from pathlib import Path
from datetime import datetime
import json
import traceback

class PokerLogger:
    """Gestionnaire de logs personnalisé"""
    
    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Logger racine
        self.logger = logging.getLogger("poker")
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Formatter détaillé
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Handler fichier
        file_handler = logging.FileHandler(self.log_dir / "poker.log", encoding='utf-8')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Handler console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.logger.info("=" * 50)
        self.logger.info("Poker Game Server Started")
        self.logger.info("=" * 50)
    
    def log_game_event(self, table_id: str, event_type: str, data: dict):
        """Log un événement de jeu"""
        self.logger.info(
            f"[GAME] table={table_id} event={event_type} data={json.dumps(data, ensure_ascii=False)}"
        )
    
    def log_player_action(self, table_id: str, user_id: str, username: str, action: str, amount: int = 0):
        """Log une action de joueur"""
        self.logger.info(
            f"[ACTION] table={table_id} player={username}({user_id}) action={action} amount={amount}"
        )
    
    def log_game_result(self, table_id: str, winners: list, pot: int, hand_name: str = None):
        """Log le résultat d'une main"""
        winner_names = [w.get('username', 'unknown') for w in winners]
        self.logger.info(
            f"[RESULT] table={table_id} pot={pot} winners={winner_names} hand={hand_name}"
        )
    
    def log_hand_history(self, table_id: str, hand_data: dict):
        """Log l'historique complet d'une main"""
        self.logger.info(f"[HAND_START] table={table_id} round={hand_data.get('round')}")
        for action in hand_data.get('actions', []):
            self.logger.info(f"[HAND_ACTION] {action}")
        self.logger.info(f"[HAND_END] table={table_id} pot={hand_data.get('pot')}")
    
    def log_error(self, error_type: str, error: Exception, context: dict = None):
        """Log une erreur avec stack trace"""
        error_msg = f"[ERROR] {error_type}: {str(error)}"
        if context:
            error_msg += f" context={json.dumps(context, ensure_ascii=False)}"
        self.logger.error(error_msg)
        self.logger.error(traceback.format_exc())
    
    def log_connection(self, event: str, user_id: str, table_id: str = None):
        """Log une connexion/déconnexion"""
        if table_id:
            self.logger.info(f"[CONNECTION] {event}: user={user_id} table={table_id}")
        else:
            self.logger.info(f"[CONNECTION] {event}: user={user_id}")
    
    def log_system(self, message: str, level: str = "INFO"):
        """Log un message système"""
        getattr(self.logger, level.lower())(f"[SYSTEM] {message}")

# Instance globale
poker_logger = PokerLogger()
