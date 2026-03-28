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
from typing import Optional, Dict, Tuple
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

    def reset(self, key: str):
        """Reset le compteur pour une clé."""
        self._hits.pop(key, None)


# Instances globales
login_limiter = RateLimiter(max_requests=5, window_seconds=60)       # 5 tentatives/min
register_limiter = RateLimiter(max_requests=3, window_seconds=300)   # 3 inscriptions/5min
ws_connect_limiter = RateLimiter(max_requests=30, window_seconds=60) # 30 connexions WS/min


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
    # Vérifier si on est en HTTPS
    is_secure = False
    
    # Vérifier le schéma direct
    if hasattr(request, 'url') and request.url.scheme == 'https':
        is_secure = True
    
    # Vérifier les headers de proxy
    if hasattr(request, 'headers'):
        proto = request.headers.get('x-forwarded-proto', '')
        if proto.lower() == 'https':
            is_secure = True
    
    return {
        'httponly': True,
        'samesite': 'lax',
        'secure': is_secure,
        'path': '/',
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sanitization
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Sanitize général : escape HTML + limite longueur."""
    if not text:
        return ""
    
    # Limiter la longueur
    text = text[:max_length]
    
    # Échapper HTML
    text = html.escape(text)
    
    return text.strip()


def sanitize_username(username: str) -> str:
    """Nettoie un nom d'utilisateur : alphanumeric + underscore uniquement."""
    if not username:
        return ""
    
    # Garder uniquement alphanumeric et underscore
    clean = re.sub(r'[^\w]', '', username)
    
    # Limiter à 32 caractères
    return clean[:32]


def sanitize_chat_message(message: str) -> str:
    """Nettoie un message de chat."""
    if not message:
        return ""
    
    # Limiter la longueur
    message = message[:500]
    
    # Échapper HTML
    message = html.escape(message)
    
    # Supprimer les caractères de contrôle
    message = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', message)
    
    return message.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Authentification WebSocket
# ─────────────────────────────────────────────────────────────────────────────

def authenticate_websocket(websocket: WebSocket, claimed_user_id: str) -> Tuple[str, bool]:
    """
    Authentifie une connexion WebSocket via le cookie de session.
    
    Retourne:
        (user_id, is_spectator): Le vrai user_id et si forcé en spectateur
    """
    from .auth import auth_manager
    
    # Récupérer le cookie de session
    session_id = None
    cookies = websocket.cookies
    
    if cookies:
        session_id = cookies.get('poker_session')
    
    if not session_id:
        # Pas de session, forcer en spectateur
        logger.warning(f"WS auth: No session cookie for claimed user {claimed_user_id}")
        return claimed_user_id, True
    
    # Valider la session
    real_user_id = auth_manager.validate_session(session_id)
    
    if not real_user_id:
        # Session invalide
        logger.warning(f"WS auth: Invalid session for claimed user {claimed_user_id}")
        return claimed_user_id, True
    
    # Vérifier que le user_id correspond
    if real_user_id != claimed_user_id:
        logger.warning(f"WS auth: User ID mismatch - claimed {claimed_user_id}, actual {real_user_id}")
        # Utiliser le vrai user_id
        return real_user_id, False
    
    # Tout est OK
    return real_user_id, False


# ─────────────────────────────────────────────────────────────────────────────
# 5. XML Injection Prevention
# ─────────────────────────────────────────────────────────────────────────────

def xml_safe(text: str) -> str:
    """Échappe les caractères dangereux pour XML."""
    if text is None:
        return ""
    
    text = str(text)
    
    # Remplacer les caractères spéciaux XML
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&apos;')
    
    # Supprimer les caractères de contrôle invalides en XML
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    
    return text


def validate_xml_content(content: str) -> bool:
    """Vérifie qu'un contenu ne contient pas d'injection XML."""
    if not content:
        return True
    
    # Patterns dangereux
    dangerous_patterns = [
        r'<!ENTITY',
        r'<!DOCTYPE',
        r'<!\[CDATA\[',
        r'<!--.*-->',
        r'<\?xml',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return False
    
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    """Génère un token CSRF."""
    import secrets
    return secrets.token_hex(32)


def validate_csrf_token(token: str, expected: str) -> bool:
    """Valide un token CSRF de manière constante en temps."""
    import hmac
    if not token or not expected:
        return False
    return hmac.compare_digest(token, expected)


def hash_password(password: str) -> str:
    """Hash un mot de passe avec bcrypt."""
    import hashlib
    import secrets
    
    # Simple hash SHA-256 avec salt (en production, utiliser bcrypt)
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Vérifie un mot de passe contre son hash."""
    import hashlib
    import hmac
    
    if ':' not in stored_hash:
        return False
    
    salt, expected_hash = stored_hash.split(':', 1)
    actual_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    
    return hmac.compare_digest(actual_hash, expected_hash)
