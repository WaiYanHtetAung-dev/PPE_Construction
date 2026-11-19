from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.api.schemas import CameraInput, CameraOutput, SiteInput, SiteOutput
from app.db.models import Camera, Site, User
from app.db.session import get_db

router = APIRouter(prefix='/organizations/{organization_id}', tags=['sites & cameras'])


@router.get('/sites', response_model=list[SiteOutput])
def list_sites(organization_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    require_org_role(db, user, organization_id)
    return db.scalars(select(Site).where(Site.organization_id == organization_id).order_by(Site.name)).all()


@router.post('/sites', response_model=SiteOutput, status_code=201)
def create_site(organization_id: str, body: SiteInput, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    require_org_role(db, user, organization_id, admin=True)
    site = Site(organization_id=organization_id, name=body.name, description=body.description)
    db.add(site)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Site already exists') from None
    db.refresh(site)
    return site


def get_tenant_site(db: Session, organization_id: str, site_id: str):
    site = db.scalar(select(Site).where(Site.id == site_id, Site.organization_id == organization_id))
    if not site:
        raise HTTPException(404, 'Site not found')
    return site


@router.get('/sites/{site_id}/cameras', response_model=list[CameraOutput])
def list_cameras(organization_id: str, site_id: str, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    require_org_role(db, user, organization_id)
    get_tenant_site(db, organization_id, site_id)
    return db.scalars(select(Camera).where(Camera.site_id == site_id).order_by(Camera.name)).all()


@router.post('/sites/{site_id}/cameras', response_model=CameraOutput, status_code=201)
def create_camera(organization_id: str, site_id: str, body: CameraInput, user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    require_org_role(db, user, organization_id, admin=True)
    get_tenant_site(db, organization_id, site_id)
    camera = Camera(site_id=site_id, **body.model_dump())
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Camera already exists') from None
    db.refresh(camera)
    return camera
