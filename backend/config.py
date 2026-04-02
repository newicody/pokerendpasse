# backend/config.py - CORRECTION COMPLÈTE
"""
Configuration pour haute performance (100+ joueurs)
"""

import os
from typing import Optional


class HighLoadConfig:
    """Configuration optimisée pour haute charge"""
    
    # WebSocket
    WS_HEARTBEAT_INTERVAL = 30
    WS_HEARTBEAT_TIMEOUT = 10
    WS_MESSAGE_QUEUE_MAX = 100
    WS_BROADCAST_BATCH_SIZE = 10
    WS_MAX_CONCURRENT_BROADCASTS = 20
    
    # Game Engine
    ACTION_TIMEOUT = 20
    PAUSE_BETWEEN_HANDS = 4
    MAX_GAME_LOOP_ERRORS = 3
    
    # Tournament
    MONITOR_INTERVAL = 1  # secondes (plus réactif)
    REBALANCE_INTERVAL = 30  # secondes
    PRESTART_ABSENT_TIMEOUT = 30
    
    # Database / Storage
    USE_ASYNC_SAVE = True
    SAVE_BATCH_SIZE = 10
    SAVE_BATCH_INTERVAL = 5
    
    # Cache
    TABLE_CACHE_TTL = 30
    TOURNAMENT_CACHE_TTL = 60
    
    # Rate Limiting
    JOIN_LIMIT_PER_MINUTE = 5
    CHAT_LIMIT_PER_MINUTE = 30
    ACTION_LIMIT_PER_MINUTE = 60
    
    # Logging
    LOG_LEVEL = "INFO"
    LOG_FILE_ROTATION = "1 day"
    LOG_FILE_RETENTION = 7  # jours
    
    @classmethod
    def from_env(cls):
        """Charge depuis les variables d'environnement"""
        config = cls()
        for key in dir(cls):
            if key.isupper():
                env_val = os.getenv(f"POKER_{key}")
                if env_val is not None:
                    try:
                        # Tenter de convertir en int
                        if env_val.isdigit():
                            setattr(config, key, int(env_val))
                        elif env_val.lower() in ('true', 'false'):
                            setattr(config, key, env_val.lower() == 'true')
                        else:
                            setattr(config, key, env_val)
                    except Exception:
                        pass
        return config


config = HighLoadConfig.from_env()
