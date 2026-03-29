# backend/session.py
from typing import Optional, Dict
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
from .auth import auth_manager

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict:
    session_id = request.cookies.get('poker_session')
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


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict]:
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


async def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    if not current_user.get('is_admin', False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
