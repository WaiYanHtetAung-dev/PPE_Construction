"""Phase 1 schema. IDs are canonical UUID strings; no model weights or RTSP passwords here."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint, false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationMembership(Base):
    __tablename__ = 'organization_memberships'
    __table_args__ = (
        UniqueConstraint('organization_id', 'user_id', name='uq_memberships_org_user'),
        CheckConstraint("role IN ('admin', 'operator', 'viewer')", name='valid_role'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    role: Mapped[str] = mapped_column(String(16), nullable=False)


class SessionToken(Base):
    __tablename__ = 'session_tokens'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Site(Base):
    __tablename__ = 'sites'
    __table_args__ = (UniqueConstraint('organization_id', 'name', name='uq_sites_org_name'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Camera(Base):
    __tablename__ = 'cameras'
    __table_args__ = (UniqueConstraint('site_id', 'name', name='uq_cameras_site_name'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    model_revision: Mapped[int] = mapped_column(BigInteger, server_default='0', nullable=False)
    # An opaque path/identifier handled later by the media service; NOT a real RTSP URL.
    stream_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    __tablename__ = 'model_versions'
    __table_args__ = (UniqueConstraint('model_key', 'version', name='uq_model_key_version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    class_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inference_eligible: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlatformPublisher(Base):
    __tablename__ = 'platform_publishers'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)


class PlatformAuditLog(Base):
    __tablename__ = 'platform_audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CameraModelAssignment(Base):
    __tablename__ = 'camera_model_assignments'
    camera_id: Mapped[str] = mapped_column(ForeignKey('cameras.id', ondelete='CASCADE'), primary_key=True)
    model_version_id: Mapped[str] = mapped_column(ForeignKey('model_versions.id'), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CameraModelHistory(Base):
    __tablename__ = 'camera_model_history'
    __table_args__ = (CheckConstraint('revision > 0', name='positive_revision'),)

    camera_id: Mapped[str] = mapped_column(ForeignKey('cameras.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    previous_model_version_id: Mapped[str | None] = mapped_column(ForeignKey('model_versions.id'))
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey('model_versions.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Incident(Base):
    __tablename__ = 'incidents'
    __table_args__ = (
        CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name='valid_status'),
        Index('ix_incident_org_created', 'organization_id', 'created_at'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), nullable=False)
    site_id: Mapped[str] = mapped_column(ForeignKey('sites.id'), nullable=False)
    camera_id: Mapped[str | None] = mapped_column(ForeignKey('cameras.id'), nullable=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey('model_versions.id'))
    status: Mapped[str] = mapped_column(String(16), default='open', nullable=False)
    violation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceAsset(Base):
    __tablename__ = 'evidence_assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey('incidents.id', ondelete='CASCADE'), index=True)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
