# backend/security.py
import re
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: Dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        reqs = self._requests[key]
        self._requests[key] = [t for t in reqs if now - t < self.window]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True

    def get_retry_after(self, key: str) -> int:
        if not self._requests[key]:
            return 0
        oldest = min(self._requests[key])
        return max(0, int(self.window - (time.time() - oldest)))


login_limiter = RateLimiter(max_requests=5, window_seconds=60)
register_limiter = RateLimiter(max_requests=3, window_seconds=300)
ws_connect_limiter = RateLimiter(max_requests=20, window_seconds=60)


# ── IP Extraction ─────────────────────────────────────────────────────────────

def get_client_ip(request_or_ws) -> str:
    if hasattr(request_or_ws, 'headers'):
        forwarded = request_or_ws.headers.get('x-forwarded-for')
        if forwarded:
            return forwarded.split(',')[0].strip()
    if hasattr(request_or_ws, 'client') and request_or_ws.client:
        return request_or_ws.client.host
    return "unknown"


# ── Cookie Params ─────────────────────────────────────────────────────────────

def get_cookie_params(request) -> dict:
    return {
        'httponly': True,
        'samesite': 'lax',
        'secure': request.url.scheme == 'https',
        'path': '/',
    }


# ── Sanitization ─────────────────────────────────────────────────────────────

def sanitize_text(text: str, max_length: int = 500) -> str:
    if not text:
        return ""
    text = text[:max_length]
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return text.strip()


def sanitize_chat_message(text: str) -> str:
    return sanitize_text(text, max_length=200)


def sanitize_username(text: str) -> str:
    if not text:
        return "Guest"
    text = re.sub(r'[^a-zA-Z0-9_\-àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ ]', '', text)
    return text[:20].strip() or "Guest"


# ── WebSocket Auth ────────────────────────────────────────────────────────────

def authenticate_websocket(websocket: WebSocket, claimed_user_id: str) -> Tuple[str, bool]:
    from .auth import auth_manager
    session_id = websocket.cookies.get('poker_session') if websocket.cookies else None
    if not session_id:
        return claimed_user_id, True
    real_user_id = auth_manager.validate_session(session_id)
    if not real_user_id:
        return claimed_user_id, True
    if real_user_id != claimed_user_id:
        logger.warning(f"WS auth mismatch: claimed {claimed_user_id}, actual {real_user_id}")
        return real_user_id, False
    return real_user_id, False


# ── XML Safety ────────────────────────────────────────────────────────────────

def xml_safe(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = text.replace('"', '&quot;').replace("'", '&apos;')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text
