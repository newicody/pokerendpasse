# backend/security.py
"""
Module de sécurité — Corrige les 5 failles identifiées :
  1. Rate limiting sur login/register (anti brute-force)
  2. Cookies sécurisés (auto-detect HTTPS)
  3. Sanitization serveur (HTML strip sur chat/usernames)
  4. Authentification WebSocket (validation session cookie)
  5. XML injection prevention (escape des données utilisateur)
"""

import html
import re
import time
import logging
from collections import defaultdict
from typing import Optional, Dict
from fastapi import WebSocket, Request

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Rate Limiter (in-memory, par IP)
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple rate limiter par IP avec fenêtre glissante."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: Dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Retourne True si la requête est autorisée."""
        now = time.time()
        # Nettoyer les anciennes entrées
        self._hits[key] = [t for t in self._hits[key] if now - t < self.window]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True

    def get_retry_after(self, key: str) -> int:
        """Secondes avant la prochaine requête autorisée."""
        if not self._hits[key]:
            return 0
        oldest = min(self._hits[key])
        return max(0, int(self.window - (time.time() - oldest)))


# Instances globales
login_limiter = RateLimiter(max_requests=5, window_seconds=60)       # 5 tentatives/min
register_limiter = RateLimiter(max_requests=3, window_seconds=300)   # 3 inscriptions/5min
ws_connect_limiter = RateLimiter(max_requests=20, window_seconds=60) # 20 connexions WS/min


def get_client_ip(request) -> str:
    """Extrait l'IP du client (supporte les proxys)."""
    forwarded = None
    if hasattr(request, 'headers'):
        forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    if hasattr(request, 'client') and request.client:
        return request.client.host
    return '0.0.0.0'


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cookies sécurisés
# ─────────────────────────────────────────────────────────────────────────────

def get_cookie_params(request: Request) -> dict:
    """Détecte HTTPS et retourne les bons paramètres de cookie."""
    is_https = (
        request.url.scheme == 'https'
        or request.headers.get('x-forwarded-proto') == 'https'
    )
    return {
        'httponly': True,
        'secure': is_https,
        'samesite': 'lax' if not is_https else 'none',
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sanitization (HTML/XSS)
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Nettoie un texte générique : escape HTML, limite la taille."""
    if not text:
        return ''
    text = text[:max_length]
    text = html.escape(text, quote=True)
    return text.strip()


def sanitize_chat_message(message: str) -> str:
    """Nettoie un message de chat : escape HTML, supprime les balises, limite."""
    if not message:
        return ''
    # Strip HTML tags
    message = re.sub(r'<[^>]+>', '', message)
    # Escape ce qui reste
    message = html.escape(message, quote=True)
    # Limite de taille
    return message[:500].strip()


def sanitize_username(username: str) -> str:
    """Nettoie un nom d'utilisateur : alphanum + underscore, 3-20 chars."""
    if not username:
        return ''
    # Ne garder que les caractères safe
    clean = re.sub(r'[^\w\-.]', '', username)
    return clean[:20].strip()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Authentification WebSocket
# ─────────────────────────────────────────────────────────────────────────────

def authenticate_websocket(websocket: WebSocket, claimed_user_id: str) -> tuple:
    """
    Valide que le cookie de session correspond au user_id revendiqué.
    Retourne (user_id_validé, is_spectator).
    """
    from .auth import auth_manager

    # Récupérer le cookie de session
    cookies = websocket.cookies
    session_id = cookies.get('poker_session')

    if not session_id:
        logger.warning(f"WS auth: no session cookie for {claimed_user_id}")
        return claimed_user_id, True  # Spectateur

    # Valider la session
    real_user_id = auth_manager.validate_session(session_id)
    if not real_user_id:
        logger.warning(f"WS auth: invalid session for {claimed_user_id}")
        return claimed_user_id, True  # Spectateur

    # Vérifier la correspondance
    if real_user_id != claimed_user_id:
        logger.warning(f"WS auth: user_id mismatch — claimed {claimed_user_id}, session says {real_user_id}")
        # Forcer le vrai user_id
        return real_user_id, False

    return real_user_id, False


# ─────────────────────────────────────────────────────────────────────────────
# 5. XML Injection Prevention
# ─────────────────────────────────────────────────────────────────────────────

def xml_safe(text) -> str:
    """Escape un texte pour insertion sûre dans du XML."""
    if text is None:
        return ''
    s = str(text)
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    s = s.replace("'", '&apos;')
    # Supprimer les caractères de contrôle XML interdits
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    return s
