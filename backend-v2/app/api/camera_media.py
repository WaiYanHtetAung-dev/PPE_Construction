"""Authorize human camera reads and forward to a separate loopback media service."""

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_org_role
from app.config import get_settings
from app.contracts.media_preview import MAX_PREVIEW_BYTES, CameraMediaStatus
from app.db.models import Camera, Site, User
from app.db.session import get_db

router = APIRouter(prefix='/organizations/{organization_id}/cameras', tags=['camera media'])
READ_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}


def get_camera(organization_id: str, camera_id: UUID, user: Annotated[User, Depends(get_current_user)],
               db: Annotated[Session, Depends(get_db)]):
    require_org_role(db, user, organization_id)
    camera = db.scalar(select(Camera).join(Site).where(
        Camera.id == str(camera_id), Site.organization_id == organization_id,
    ))
    if camera is None:
        raise HTTPException(404, 'Camera not found')
    return camera


async def gateway_read(camera: Camera, resource: str, content_type: str, limit: int) -> bytes | None:
    settings = get_settings()
    try:
        origin = httpx.URL(settings.media_gateway_origin)
        if (origin.scheme != 'http' or origin.host != '127.0.0.1' or origin.port is None
                or origin.userinfo or origin.path not in ('', '/') or origin.query or origin.fragment):
            raise ValueError('Expected loopback media service')
        with Path(settings.media_gateway_token_file).open(encoding='ascii') as source:
            token = source.read(258).rstrip('\r\n')
        if not 32 <= len(token) <= 256 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError('Invalid media service credential')
        async with asyncio.timeout(4), httpx.AsyncClient(base_url=origin, trust_env=False,
                                                          follow_redirects=False, timeout=3) as client:
            async with client.stream(
                'GET', f'/internal/v1/cameras/{UUID(camera.id)}/{resource}',
                params={'stream_ref': camera.stream_ref},
                headers={'Authorization': f'Bearer {token}', 'Accept-Encoding': 'identity'},
            ) as response:
                if response.status_code == 404:
                    return None
                if (response.status_code != 200 or response.headers.get('content-type') != content_type
                        or response.headers.get('content-encoding', 'identity') != 'identity'):
                    raise ValueError('Invalid media service response')
                data = bytearray()
                async for chunk in response.aiter_raw(chunk_size=65536):
                    if len(data) + len(chunk) > limit:
                        raise ValueError('Oversize media response')
                    data.extend(chunk)
                return bytes(data)
    except (httpx.HTTPError, OSError, TimeoutError, ValueError):
        raise HTTPException(503, 'Camera media unavailable') from None


@router.get('/{camera_id}/media/status', response_model=CameraMediaStatus)
async def camera_status(camera: Annotated[Camera, Depends(get_camera)], response: Response):
    response.headers.update(READ_HEADERS)
    if not camera.enabled:
        return CameraMediaStatus(state='disabled')
    if not get_settings().media_gateway_origin:
        return CameraMediaStatus(state='not_monitored')
    data = await gateway_read(camera, 'status', 'application/json', 4096)
    if data is None:
        return CameraMediaStatus(state='not_monitored')
    try:
        return CameraMediaStatus.model_validate_json(data, strict=True)
    except ValueError:
        raise HTTPException(503, 'Camera media unavailable') from None


@router.get('/{camera_id}/media/preview', response_class=Response,
            responses={200: {'content': {'video/mp4': {}}}})
async def camera_preview(camera: Annotated[Camera, Depends(get_camera)]):
    if not camera.enabled or not get_settings().media_gateway_origin:
        raise HTTPException(503, 'Camera preview unavailable')
    data = await gateway_read(camera, 'preview', 'video/mp4', MAX_PREVIEW_BYTES)
    if not data or data[4:8] != b'ftyp':
        raise HTTPException(503, 'Camera preview unavailable')
    return Response(data, media_type='video/mp4', headers=READ_HEADERS)
