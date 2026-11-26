"""Restricted operator primitives. Call inside a transaction and protect returned tokens."""

import hashlib
from datetime import timedelta
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.contracts.assignment_snapshot import SNAPSHOT_AUDIENCE
from app.db.models import Camera, GatewayCameraScope, GatewayCredential, GatewayPrincipal, PlatformAuditLog, Site


def _operator(db):
    actor = db.scalar(text("SELECT session_user WHERE pg_has_role("
                           "session_user, to_regrole('ppe_assignment_operator'), 'MEMBER')"))
    if actor is None:
        raise PermissionError('Assignment operator role required')
    return actor


def _audit(db, actor, action, principal_id, **details):
    db.add(PlatformAuditLog(actor=actor, action=f'gateway.{action}', target_id=principal_id, details=details))


def provision(db: Session, organization_id: str, cameras: dict[str, str]) -> str:
    actor = _operator(db)
    if not cameras:
        raise ValueError('Explicit camera scope required')
    rows = db.execute(select(Camera.id, Site.id).select_from(Camera).join(Site, Site.id == Camera.site_id).where(
        Site.organization_id == organization_id, Camera.id.in_(cameras),
    )).all()
    if dict(rows) != cameras:
        raise ValueError('Invalid camera scope')
    principal = GatewayPrincipal(id=str(uuid4()), organization_id=organization_id)
    db.add(principal)
    db.flush()
    db.add_all(GatewayCameraScope(principal_id=principal.id, camera_id=camera, site_id=site)
               for camera, site in cameras.items())
    _audit(db, actor, 'provision', principal.id, camera_count=len(cameras))
    return principal.id


def rotate(db: Session, principal_id: str) -> str:
    actor = _operator(db)
    principal = db.scalar(select(GatewayPrincipal).where(GatewayPrincipal.id == principal_id).with_for_update())
    if principal is None or principal.disabled_at is not None:
        raise ValueError('Gateway principal is inactive')
    now = db.scalar(select(func.clock_timestamp()))
    active = db.scalars(select(GatewayCredential).where(
        GatewayCredential.principal_id == principal_id, GatewayCredential.revoked_at.is_(None),
        GatewayCredential.expires_at > now,
    )).all()
    if len(active) > 1:
        raise ValueError('Complete the active rotation first')
    for previous in active:
        previous.expires_at = min(previous.expires_at, now + timedelta(minutes=5))
    identifier, secret = str(uuid4()), token_urlsafe(32)
    db.add(GatewayCredential(id=identifier, principal_id=principal_id, audience=SNAPSHOT_AUDIENCE,
                             secret_sha256=hashlib.sha256(secret.encode('ascii')).hexdigest(),
                             issued_at=now, expires_at=now + timedelta(hours=24)))
    _audit(db, actor, 'rotate', principal_id, key_id=identifier)
    return f'{identifier}.{secret}'


def revoke(db: Session, principal_id: str, key_id: str | None = None) -> None:
    actor = _operator(db)
    principal = db.scalar(select(GatewayPrincipal).where(GatewayPrincipal.id == principal_id).with_for_update())
    if principal is None:
        raise ValueError('Unknown gateway principal')
    now = db.scalar(select(func.clock_timestamp()))
    if key_id is None:
        principal.disabled_at = principal.disabled_at or now
    else:
        key = db.get(GatewayCredential, key_id)
        if key is None or key.principal_id != principal_id:
            raise ValueError('Unknown gateway credential')
        key.revoked_at = key.revoked_at or now
    _audit(db, actor, 'revoke', principal_id, key_id=key_id)
