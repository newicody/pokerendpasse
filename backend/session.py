# backend/session.py
from typing import Optional, Dict
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import secrets
import logging
from .auth import auth_manager

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer(auto_error=False)

class SessionManager:
    """Gestionnaire de sessions pour FastAPI"""
    
    @staticmethod
    async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
    ) -> Dict:
        """Récupère l'utilisateur courant depuis la session"""
        # Vérifier le cookie de session
        session_id = request.cookies.get('poker_session')
        
        # Vérifier le token Bearer
        if not session_id and credentials:
            session_id = credentials.credentials
        
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        user_id = auth_manager.validate_session(session_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        user = auth_manager.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return user
    
    @staticmethod
    async def get_current_user_optional(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
    ) -> Optional[Dict]:
        """Récupère l'utilisateur courant si connecté"""
        try:
            return await SessionManager.get_current_user(request, credentials)
        except HTTPException:
            return None
    
    @staticmethod
    async def require_admin(current_user: Dict = Depends(get_current_user)):
        """Vérifie que l'utilisateur est admin"""
        if not current_user.get('is_admin', False):
            raise HTTPException(status_code=403, detail="Admin access required")
        return current_user

# Fonctions de dépendance
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict:
    return await SessionManager.get_current_user(request, credentials)

async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict]:
    return await SessionManager.get_current_user_optional(request, credentials)

async def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    return await SessionManager.require_admin(current_user)
