"""Read-only eligibility authority. Run separately from the business API."""

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from inference_worker.auth import InternalRoute, read_token, require_token
from inference_worker.contract import LEASE_PATH, MAX_LEASE_SECONDS, LeaseRequest, ModelLease

CURRENT_LEASE = text("""
    SELECT m.model_key, m.version AS model_version, m.id AS model_version_id,
           m.artifact_ref, m.artifact_sha256, e.manifest_sha256, e.signer_key_sha256,
           e.id AS verification_id, statement_timestamp() AS issued_at,
           least(e.expires_at, statement_timestamp() + :ttl * interval '1 second') AS expires_at
    FROM public.model_versions m
    JOIN public.eligible_model_versions eligible ON eligible.model_version_id = m.id
    JOIN public.model_verifications e ON e.id = (
        SELECT max(v.id) FROM public.model_verifications v WHERE v.model_version_id = m.id
    )
    WHERE m.model_key = :model_key AND m.version = :model_version
""")


def create_authority(secret: str, resolve: Callable[[LeaseRequest], ModelLease | None]) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter(route_class=InternalRoute)

    @router.post(LEASE_PATH, response_model=ModelLease, dependencies=[Depends(require_token(secret))])
    def issue(identity: LeaseRequest, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        try:
            lease = resolve(identity)
        except SQLAlchemyError:
            raise HTTPException(503, 'Eligibility unavailable') from None
        if lease is None:
            raise HTTPException(404, 'No current eligibility', headers={'Cache-Control': 'no-store'})
        return lease

    app.include_router(router)
    return app


def postgres_resolver(engine, ttl: int):
    if engine.dialect.name != 'postgresql' or not 1 <= ttl <= MAX_LEASE_SECONDS:
        raise ValueError('Invalid eligibility authority database or lease configuration')

    def resolve(identity: LeaseRequest) -> ModelLease | None:
        with engine.connect() as db:
            row = db.execute(CURRENT_LEASE, identity.model_dump() | {'ttl': ttl}).mappings().one_or_none()
        return ModelLease.model_validate(dict(row) | {'nonce': identity.nonce}) if row is not None else None

    return resolve


def from_environment() -> FastAPI:
    with Path(os.environ['ELIGIBILITY_DATABASE_URL_FILE']).open(encoding='utf-8') as source:
        url = source.read(4097).strip()
    if not url or len(url) > 4096:
        raise ValueError('Invalid eligibility authority database configuration')
    try:
        database_url = make_url(url)
    except ArgumentError:
        raise ValueError('Invalid eligibility authority database configuration') from None
    if database_url.drivername != 'postgresql+psycopg':
        raise ValueError('Eligibility authority requires PostgreSQL with psycopg')
    engine = create_engine(
        database_url, hide_parameters=True, pool_pre_ping=True, pool_size=2, max_overflow=0,
        pool_timeout=2, connect_args={
            'connect_timeout': 2, 'options': '-c statement_timeout=2000 -c default_transaction_read_only=on',
        },
    )
    return create_authority(
        read_token(os.environ['ELIGIBILITY_TOKEN_FILE']),
        postgres_resolver(engine, int(os.environ.get('ELIGIBILITY_LEASE_SECONDS', '5'))),
    )
