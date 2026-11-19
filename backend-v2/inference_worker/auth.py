import hmac
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def read_token(filename: str) -> str:
    with Path(filename).open(encoding='ascii') as source:
        secret = source.read(258).rstrip('\r\n')
    if not 32 <= len(secret) <= 256 or any(not 33 <= ord(char) <= 126 for char in secret):
        raise ValueError('Invalid service credential')
    return secret


def require_token(secret: str):
    if not 32 <= len(secret) <= 256 or not secret.isascii():
        raise ValueError('Invalid service credential')

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or not hmac.compare_digest(
            credentials.credentials.encode('utf-8'), secret.encode('ascii'),
        ):
            raise HTTPException(401, 'Service authentication required',
                                headers={'WWW-Authenticate': 'Bearer'})

    return authenticate


class InternalRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'Invalid internal request') from None

        return handle
