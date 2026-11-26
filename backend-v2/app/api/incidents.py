from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.api.schemas import IncidentListOutput, IncidentOutput
from app.db.models import AuditLog, Incident, User
from app.db.session import get_db

router = APIRouter(prefix='/organizations/{organization_id}', tags=['incidents'])


class IncidentTransition(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['acknowledged', 'resolved']


@router.get('/incidents', response_model=IncidentListOutput)
def list_incidents(
    organization_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    require_org_role(db, user, organization_id)
    condition = Incident.organization_id == organization_id
    total = db.scalar(select(func.count()).select_from(Incident).where(condition)) or 0
    items = db.scalars(select(Incident).where(condition).order_by(
        Incident.detected_at.desc(), Incident.id.desc()
    ).limit(limit).offset(offset)).all()
    return IncidentListOutput(items=items, total=total, limit=limit, offset=offset)


@router.patch('/incidents/{incident_id}/status', response_model=IncidentOutput)
def transition_incident(
    organization_id: str,
    incident_id: UUID,
    body: IncidentTransition,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_org_role(db, user, organization_id, admin=True)
    condition = (Incident.organization_id == organization_id, Incident.id == str(incident_id))
    expected = 'open' if body.status == 'acknowledged' else 'acknowledged'
    incident = db.scalar(update(Incident).where(*condition, Incident.status == expected)
                         .values(status=body.status).returning(Incident))
    if incident is None:
        current = db.scalar(select(Incident.status).where(*condition))
        if current is None:
            raise HTTPException(404, 'Incident not found')
        raise HTTPException(409, 'Invalid incident status transition')

    db.add(AuditLog(organization_id=organization_id, actor_user_id=user.id,
                    action=f'incident.{body.status}', target_type='incident', target_id=incident.id))
    db.commit()
    return incident
