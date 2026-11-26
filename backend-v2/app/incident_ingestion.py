"""Private ingest entry point for a trusted PPE rules workload."""

import hashlib
import hmac
import os
from datetime import timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Camera, Incident, IncidentOutbox, Site
from app.db.session import get_db


class ConfirmedViolation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    event_id: UUID
    organization_id: UUID
    site_id: UUID
    camera_id: UUID
    detected_at: AwareDatetime
    violation_type: Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,59}$')]


class IngestResult(BaseModel):
    incident_id: UUID


def create_ingestion(secret: str) -> FastAPI:
    if not 32 <= len(secret) <= 256 or any(not 33 <= ord(char) <= 126 for char in secret):
        raise ValueError('Invalid ingestion credential')
    secret_bytes = secret.encode('ascii')
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), secret_bytes):
            raise HTTPException(401, 'Service authentication required', headers={'WWW-Authenticate': 'Bearer'})

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content={'detail': 'Invalid internal request'})

    @app.post('/internal/v1/incidents', response_model=IngestResult, status_code=201,
              dependencies=[Depends(authenticate)])
    def ingest(event: ConfirmedViolation, response: Response, db: Annotated[Session, Depends(get_db)]):
        event_id = str(event.event_id)
        detected_at = event.detected_at.astimezone(timezone.utc)
        canonical = event.model_copy(update={'detected_at': detected_at}).model_dump_json()
        digest = hashlib.sha256(canonical.encode()).hexdigest()

        prior = db.get(IncidentOutbox, event_id)
        if prior is None:
            camera = db.scalar(select(Camera.id).join(Site).where(
                Camera.id == str(event.camera_id), Site.id == str(event.site_id),
                Site.organization_id == str(event.organization_id),
            ))
            if camera is None:
                raise HTTPException(404, 'Camera not found')
            try:
                incident = Incident(organization_id=str(event.organization_id), site_id=str(event.site_id),
                                    camera_id=camera, detected_at=detected_at,
                                    violation_type=event.violation_type)
                db.add(incident)
                db.flush()
                db.add(IncidentOutbox(event_id=event_id, incident_id=incident.id, payload_sha256=digest))
                db.commit()
                return IngestResult(incident_id=UUID(incident.id))
            except IntegrityError:
                db.rollback()
                prior = db.get(IncidentOutbox, event_id)
                if prior is None:
                    raise

        if prior.payload_sha256 != digest:
            raise HTTPException(409, 'Event identifier already used')
        response.status_code = 200
        return IngestResult(incident_id=UUID(prior.incident_id))

    return app


def from_environment() -> FastAPI:
    with Path(os.environ['INCIDENT_INGESTION_TOKEN_FILE']).open(encoding='ascii') as source:
        return create_ingestion(source.read(258).rstrip('\r\n'))
