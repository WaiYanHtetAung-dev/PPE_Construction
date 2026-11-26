"""Private, read-only camera assignment listener for ADR-009."""

import asyncio
import hashlib
import hmac
import os
import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.contracts.assignment_snapshot import (
    MAX_REQUEST_BYTES, MAX_SNAPSHOT_LIFETIME, SNAPSHOT_AUDIENCE, SNAPSHOT_PATH,
    SnapshotModel, SnapshotRequest, SnapshotResponse, parse_snapshot_request,
)

NO_STORE = {'Cache-Control': 'no-store'}
AUTH = re.compile(r'Bearer ([0-9a-f-]{36})\.([A-Za-z0-9_-]{43})', re.ASCII | re.IGNORECASE)
READ = text('''
    SELECT k.secret_sha256, k.expires_at AS credential_expiry,
           statement_timestamp() AS issued_at, a.*
    FROM public.gateway_snapshot_credentials k
    LEFT JOIN public.gateway_snapshot_assignments a ON a.principal_id = k.principal_id
         AND a.organization_id = :org AND a.site_id = :site AND a.camera_id = :camera
    WHERE k.id = :key AND k.audience = :audience
''')
SnapshotReader = Callable[[str, SnapshotRequest | None], Mapping | None]


def postgres_reader(engine) -> SnapshotReader:
    if engine.dialect.name != 'postgresql':
        raise ValueError('Snapshot listener requires PostgreSQL')

    def read(key, query):
        with engine.connect() as connection:
            return connection.execute(READ, {
                'key': key, 'audience': SNAPSHOT_AUDIENCE,
                'org': str(query.organization_id) if query else None,
                'site': str(query.site_id) if query else None,
                'camera': str(query.camera_id) if query else None,
            }).mappings().one_or_none()

    return read


def _response(query, row):
    issued = row['issued_at'].astimezone(UTC)
    generation, floor = row['verification_generation'], row['revoked_through_generation']
    model = (SnapshotModel(model_version_id=UUID(row['model_version_id']), model_key=row['model_key'],
                           version=row['version']) if row['model_version_id'] else None)
    expiry = issued
    if not row['enabled']:
        decision = 'camera_disabled'
    elif model is None:
        decision = 'unassigned'
    elif generation is not None and floor == generation:
        decision = 'revoked'
    elif row['evidence_expiry'] is not None and row['evidence_expiry'] <= issued:
        decision = 'expired'
    elif row['eligible'] and generation is not None and row['evidence_expiry'] is not None:
        decision = 'eligible'
        expiry = min(issued + timedelta(seconds=MAX_SNAPSHOT_LIFETIME), row['credential_expiry'],
                     row['evidence_expiry']).astimezone(UTC)
    else:
        decision = 'unverified'
    return SnapshotResponse(**query.model_dump(), assignment_revision=row['model_revision'],
                            decision=decision, model=model,
                            class_map=row['class_map'] if decision == 'eligible' else None,
                            verification_generation=generation, revoked_through_generation=floor,
                            issued_at=issued, expires_at=expiry)


def _error(status):
    details = {401: 'Authentication required', 404: 'Camera not found', 413: 'Request too large',
               422: 'Invalid snapshot request', 429: 'Snapshot busy', 503: 'Snapshot unavailable'}
    headers = NO_STORE | ({'WWW-Authenticate': 'Bearer'} if status == 401 else {})
    return JSONResponse({'detail': details[status]}, status_code=status, headers=headers)


def create_app(read: SnapshotReader, *, dispose=lambda: None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    slots = asyncio.Semaphore(3)

    @app.post(SNAPSHOT_PATH)
    async def snapshot(request: Request):
        credential = AUTH.fullmatch(request.headers.get('authorization', ''))
        if credential is None:
            return _error(401)
        key, secret = credential.groups()
        try:
            key = str(UUID(key))
        except ValueError:
            return _error(401)
        digest = hashlib.sha256(secret.encode('ascii')).hexdigest()
        query, invalid = None, None
        try:
            async with asyncio.timeout(2):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                        invalid = 413
                        break
                    body.extend(chunk)
                if invalid is None:
                    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
                        invalid = 422
                    else:
                        query = parse_snapshot_request(bytes(body))
        except (ValueError, RecursionError):
            invalid = 422
        except TimeoutError:
            return _error(503)

        try:
            if slots.locked():
                return _error(429)
            async with slots:
                row = await run_in_threadpool(read, key, query)
            if row is None or not hmac.compare_digest(digest, row['secret_sha256']):
                return _error(401)
            if invalid is not None:
                return _error(invalid)
            if row['camera_id'] is None:
                return _error(404)
            return JSONResponse(_response(query, row).model_dump(mode='json'), headers=NO_STORE)
        except (SQLAlchemyError, ValueError):
            return _error(503)

    return app


def from_environment() -> FastAPI:
    with Path(os.environ['ASSIGNMENT_DATABASE_URL_FILE']).open(encoding='utf-8') as source:
        raw = source.read(4097).strip()
    try:
        url = make_url(raw)
        if len(raw) > 4096 or url.drivername != 'postgresql+psycopg' or url.query:
            raise ValueError
    except (ValueError, SQLAlchemyError):
        raise ValueError('Invalid assignment listener database configuration') from None
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True, pool_size=3, max_overflow=0,
                           pool_timeout=1, connect_args={'connect_timeout': 2, 'options':
                               '-c statement_timeout=1500 -c default_transaction_read_only=on'})
    return create_app(postgres_reader(engine), dispose=engine.dispose)
