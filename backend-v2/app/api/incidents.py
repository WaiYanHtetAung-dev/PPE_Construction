from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.api.schemas import IncidentListOutput
from app.db.models import Incident, User
from app.db.session import get_db

router = APIRouter(prefix='/organizations/{organization_id}', tags=['incidents'])


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
