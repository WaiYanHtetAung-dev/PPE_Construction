from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.api.model_catalog import CatalogModelVersion
from app.api.schemas import FromOrm
from app.db.models import (
    AuditLog, Camera, CameraModelAssignment, CameraModelHistory, ModelVersion, Site, User, utcnow,
)
from app.db.session import get_db

router = APIRouter(
    prefix='/organizations/{organization_id}/cameras/{camera_id}/model',
    tags=['camera model assignments'],
)
CurrentUser = Annotated[User, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_version_id: UUID | None
    expected_revision: int = Field(strict=True, ge=0, le=2**63 - 1)


class AssignmentOutput(BaseModel):
    revision: int
    model_version: CatalogModelVersion | None


class HistoryEntry(FromOrm):
    revision: int
    actor_user_id: str
    previous_model_version_id: str | None
    model_version_id: str | None
    created_at: datetime


def tenant_camera(organization_id: str, camera_id: UUID):
    return select(Camera).join(Site).where(
        Camera.id == str(camera_id), Site.organization_id == organization_id,
    )


def assignment_output(revision: int, version: ModelVersion | None) -> AssignmentOutput:
    return AssignmentOutput(
        revision=revision,
        model_version=CatalogModelVersion.model_validate(version) if version else None,
    )


@router.get('', response_model=AssignmentOutput)
def get_assignment(organization_id: str, camera_id: UUID, user: CurrentUser, db: Database):
    require_org_role(db, user, organization_id, admin=True)
    row = db.execute(
        tenant_camera(organization_id, camera_id)
        .outerjoin(CameraModelAssignment, CameraModelAssignment.camera_id == Camera.id)
        .outerjoin(ModelVersion, ModelVersion.id == CameraModelAssignment.model_version_id)
        .add_columns(ModelVersion)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, 'Camera not found')
    camera, version = row
    return assignment_output(camera.model_revision, version)


@router.put('', response_model=AssignmentOutput)
def put_assignment(
    organization_id: str, camera_id: UUID, body: AssignmentInput, user: CurrentUser, db: Database,
):
    require_org_role(db, user, organization_id, admin=True)
    camera = db.scalar(tenant_camera(organization_id, camera_id).with_for_update(of=Camera))
    if camera is None:
        raise HTTPException(404, 'Camera not found')
    if camera.model_revision != body.expected_revision:
        raise HTTPException(409, 'Assignment revision has changed')

    model_id = str(body.model_version_id) if body.model_version_id else None
    version = None
    if model_id is not None:
        version = db.scalar(select(ModelVersion).where(
            ModelVersion.id == model_id, ModelVersion.inference_eligible.is_(True),
        ))
        if version is None:
            raise HTTPException(404, 'Model version not found')

    current = db.get(CameraModelAssignment, camera.id)
    previous = current.model_version_id if current else None
    if previous == model_id:
        return assignment_output(camera.model_revision, version)

    timestamp = utcnow()
    if model_id is None:
        db.delete(current)
    elif current is None:
        db.add(CameraModelAssignment(
            camera_id=camera.id, model_version_id=model_id, assigned_at=timestamp,
        ))
    else:
        current.model_version_id = model_id
        current.assigned_at = timestamp

    camera.model_revision += 1
    db.add_all([
        CameraModelHistory(
            camera_id=camera.id, organization_id=organization_id, revision=camera.model_revision,
            actor_user_id=user.id, previous_model_version_id=previous,
            model_version_id=model_id, created_at=timestamp,
        ),
        AuditLog(organization_id=organization_id, actor_user_id=user.id,
                 action='camera.model_unassign' if model_id is None else 'camera.model_assign',
                 target_type='camera', target_id=camera.id, created_at=timestamp),
    ])
    response = assignment_output(camera.model_revision, version)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, 'Could not save camera model assignment') from None
    return response


@router.get('/history', response_model=list[HistoryEntry])
def list_history(
    organization_id: str, camera_id: UUID, user: CurrentUser, db: Database,
    before_revision: Annotated[int | None, Query(ge=1, le=2**63 - 1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    require_org_role(db, user, organization_id, admin=True)
    if db.scalar(tenant_camera(organization_id, camera_id).with_only_columns(Camera.id)) is None:
        raise HTTPException(404, 'Camera not found')
    query = select(CameraModelHistory).where(
        CameraModelHistory.organization_id == organization_id,
        CameraModelHistory.camera_id == str(camera_id),
    )
    if before_revision is not None:
        query = query.where(CameraModelHistory.revision < before_revision)
    return db.scalars(query.order_by(CameraModelHistory.revision.desc()).limit(limit)).all()
