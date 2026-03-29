# backend/logger.py
import logging
import sys
from pathlib import Path
from datetime import datetime
import json
import traceback


class PokerLogger:
    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("poker")
        self.logger.setLevel(getattr(logging, log_level.upper()))

        fmt = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

        fh = logging.FileHandler(self.log_dir / "poker.log", encoding='utf-8')
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

        self.logger.info("=" * 50)
        self.logger.info("PokerEndPasse Server Started")
        self.logger.info("=" * 50)

    def log_game_event(self, table_id: str, event_type: str, data: dict):
        self.logger.info(f"[GAME] table={table_id} event={event_type} data={json.dumps(data, ensure_ascii=False)}")

    def log_player_action(self, table_id: str, user_id: str, username: str, action: str, amount: int = 0):
        self.logger.info(f"[ACTION] table={table_id} player={username}({user_id}) action={action} amount={amount}")

    def log_game_result(self, table_id: str, winners: list, pot: int, hand_name: str = None):
        names = [w.get('username', '?') for w in winners]
        self.logger.info(f"[RESULT] table={table_id} pot={pot} winners={names} hand={hand_name}")

    def log_hand_history(self, table_id: str, hand_data: dict):
        self.logger.info(f"[HAND_START] table={table_id} round={hand_data.get('round')}")
        for a in hand_data.get('actions', []):
            self.logger.info(f"[HAND_ACTION] {a}")
        self.logger.info(f"[HAND_END] table={table_id} pot={hand_data.get('pot')}")

    def log_error(self, error_type: str, error: Exception, context: dict = None):
        msg = f"[ERROR] {error_type}: {error}"
        if context:
            msg += f" context={json.dumps(context, ensure_ascii=False)}"
        self.logger.error(msg)
        self.logger.error(traceback.format_exc())

    def log_connection(self, event: str, user_id: str, table_id: str = None):
        suffix = f" table={table_id}" if table_id else ""
        self.logger.info(f"[CONNECTION] {event}: user={user_id}{suffix}")

    def log_system(self, message: str, level: str = "INFO"):
        getattr(self.logger, level.lower())(f"[SYSTEM] {message}")


poker_logger = PokerLogger()
