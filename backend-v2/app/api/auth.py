import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Bearer, get_current_user, now_utc
from app.api.schemas import LoginInput, MeOutput, MembershipOutput, TokenOutput
from app.config import get_settings
from app.db.models import OrganizationMembership, SessionToken, User
from app.db.session import get_db
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix='/auth', tags=['auth'])
password_hasher = PasswordHasher()


@router.post('/login', response_model=TokenOutput)
def login(body: LoginInput, db: Annotated[Session, Depends(get_db)]):
    email = str(body.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    try:
        if not user or not user.is_active or not password_hasher.verify(user.password_hash, body.password):
            raise HTTPException(401, 'Invalid credentials')
    except VerificationError:
        raise HTTPException(401, 'Invalid credentials') from None
    raw_token = secrets.token_urlsafe(48)
    expires_at = now_utc() + timedelta(hours=get_settings().session_ttl_hours)
    db.add(SessionToken(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        user_id=user.id,
        expires_at=expires_at,
    ))
    db.commit()
    return TokenOutput(access_token=raw_token, expires_at=expires_at)


@router.get('/me', response_model=MeOutput)
def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    memberships = db.scalars(select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.id
    )).all()
    return MeOutput(id=user.id, email=user.email, memberships=[
        MembershipOutput.model_validate(m) for m in memberships
    ])


@router.post('/logout', status_code=204)
def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(Bearer)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token = db.get(SessionToken, token_hash)
    if token and token.user_id == user.id:
        token.revoked_at = now_utc()
        db.commit()
    return None
