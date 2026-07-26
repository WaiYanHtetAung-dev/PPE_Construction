from __future__ import annotations

from fastapi import Cookie, HTTPException, WebSocket, status

import database

SESSION_COOKIE = "ppe_session"


def get_current_user(ppe_session: str | None = Cookie(default=None)):
    """FastAPI dependency: raises 401 if there's no valid session."""
    user = database.get_user_by_token(ppe_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_admin(user=None):
    if user is not None and user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def get_user_from_ws(ws: WebSocket):
    token = ws.cookies.get(SESSION_COOKIE)
    return database.get_user_by_token(token)
