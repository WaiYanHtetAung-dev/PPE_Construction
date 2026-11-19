from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class FromOrm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class TokenOutput(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: datetime


class MembershipOutput(FromOrm):
    organization_id: str
    role: str


class MeOutput(BaseModel):
    id: str
    email: EmailStr
    memberships: list[MembershipOutput]


class SiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class SiteOutput(FromOrm):
    id: str
    organization_id: str
    name: str
    description: str | None
    created_at: datetime


class CameraInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    stream_ref: str = Field(pattern=r'^stream:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$', min_length=8, max_length=255)
    enabled: bool = True


class CameraOutput(FromOrm):
    id: str
    site_id: str
    name: str
    stream_ref: str
    enabled: bool
    created_at: datetime


class IncidentOutput(FromOrm):
    id: str
    organization_id: str
    site_id: str
    camera_id: str | None
    model_version_id: str | None
    status: str
    violation_type: str
    detected_at: datetime
    created_at: datetime


class IncidentListOutput(BaseModel):
    items: list[IncidentOutput]
    total: int
    limit: int
    offset: int
