from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.api.schemas import FromOrm
from app.db.model_eligibility import eligible_model_version
from app.db.models import ModelVersion, User
from app.db.session import get_db

router = APIRouter(prefix='/organizations/{organization_id}', tags=['model catalog'])


class CatalogModelVersion(FromOrm):
    id: str
    model_key: str
    version: str


class ModelCatalogPage(BaseModel):
    items: list[CatalogModelVersion]
    total: int
    limit: int
    offset: int


def catalog_versions(db: Session):
    return select(ModelVersion.id, ModelVersion.model_key, ModelVersion.version).where(
        eligible_model_version(db)
    )


@router.get('/models', response_model=ModelCatalogPage)
def list_models(
    organization_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    require_org_role(db, user, organization_id, admin=True)
    versions = catalog_versions(db)
    total = db.scalar(select(func.count()).select_from(versions.subquery())) or 0
    items = db.execute(versions.order_by(ModelVersion.model_key, ModelVersion.version)
                       .limit(limit).offset(offset)).all()
    return ModelCatalogPage(items=items, total=total, limit=limit, offset=offset)


@router.get('/models/{model_version_id}', response_model=CatalogModelVersion)
def get_model(
    organization_id: str,
    model_version_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_org_role(db, user, organization_id, admin=True)
    version = db.execute(catalog_versions(db).where(ModelVersion.id == str(model_version_id))).one_or_none()
    if version is None:
        raise HTTPException(404, 'Model version not found')
    return version
