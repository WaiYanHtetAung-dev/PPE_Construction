import hashlib
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OrganizationMembership, SessionToken, User
from app.db.session import get_db

Bearer = HTTPBearer(auto_error=False)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(Bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Authentication required')
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token = db.get(SessionToken, token_hash)
    if not token or token.revoked_at is not None or aware(token.expires_at) <= now_utc():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Invalid or expired session')
    user = db.get(User, token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Account disabled')
    return user


def require_org_role(db: Session, user: User, org_id: str, *, admin: bool = False):
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org_id,
        OrganizationMembership.user_id == user.id,
    ))
    # Deliberately identical response for absent org and no permission.
    if membership is None or (admin and membership.role != 'admin'):
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Organization not found')
    return membership
