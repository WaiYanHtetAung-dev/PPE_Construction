from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import get_settings
from app.contracts.inference import CanonicalClass
from app.db.models import ModelVersion, PlatformAuditLog, PlatformPublisher, User
from app.db.session import get_db
from app.model_artifacts import within_namespace


class RegistryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'Invalid model registration metadata') from None

        return handle


router = APIRouter(prefix='/platform', tags=['platform models'], route_class=RegistryRoute)
ClassLabel = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9 _.-]*$')
]


class ModelRegistration(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_key: str = Field(max_length=100, pattern=r'^[a-z0-9][a-z0-9_-]*$')
    version: str = Field(max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9.+_-]*$')
    artifact_ref: str = Field(min_length=1, max_length=500)
    artifact_sha256: str = Field(pattern=r'^[0-9a-fA-F]{64}$')
    class_map: dict[ClassLabel, CanonicalClass] = Field(min_length=1, max_length=256)


class RegisteredModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_key: str
    version: str
    inference_eligible: bool


@router.post('/model-versions', response_model=RegisteredModel, status_code=201, responses={
    401: {'description': 'Authentication required'},
    403: {'description': 'Platform publisher permission required'},
    409: {'description': 'Model version already registered'},
    422: {'description': 'Invalid model registration metadata'},
})
def register_model(
    body: ModelRegistration,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if db.get(PlatformPublisher, user.id) is None:
        raise HTTPException(403, 'Platform publisher permission required')
    namespace = get_settings().model_artifact_namespace
    if not within_namespace(body.artifact_ref, namespace):
        raise HTTPException(422, 'Artifact reference is outside the approved namespace')

    record = ModelVersion(**body.model_dump())
    record.artifact_sha256 = record.artifact_sha256.lower()
    db.add(record)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        original = error.orig
        constraint = getattr(getattr(original, 'diag', None), 'constraint_name', None)
        if constraint == 'uq_model_key_version' or (
            db.get_bind().dialect.name == 'sqlite'
            and 'UNIQUE constraint failed: model_versions.model_key, model_versions.version' in str(original)
        ):
            raise HTTPException(409, 'Model version already registered') from None
        raise HTTPException(500, 'Model registration failed') from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(500, 'Model registration failed') from None

    db.add(PlatformAuditLog(
        actor=user.id,
        action='model_version.register',
        target_id=record.id,
        details={'inference_eligible': False},
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, 'Model registration failed') from None
    return RegisteredModel(id=record.id, model_key=record.model_key,
                           version=record.version, inference_eligible=False)
