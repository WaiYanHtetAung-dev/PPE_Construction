"""Construct an RTSP reader from operator-owned central-ingress configuration."""

from ipaddress import IPv4Address
from re import fullmatch

from media_gateway.video_source import decoder_process


def stream_path(value: str) -> str:
    if not fullmatch(r'[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64}){0,2}', value):
        raise ValueError('Invalid provisioned stream path')
    return value


def identifier_secret(value: str) -> str:
    if not fullmatch(r'[A-Za-z0-9_-]{16,64}', value):
        raise ValueError('Invalid media secret')
    return value


def central_rtsp_source(host: str, port: int, path: str, username: str, password: str):
    address = IPv4Address(host)
    if (not (address.is_private or address.is_loopback) or address.is_link_local
            or address.is_multicast or address.is_unspecified or address.is_reserved
            or not 1 <= port <= 65535 or not fullmatch(r'[A-Za-z0-9_-]{1,48}', username)):
        raise ValueError('Invalid central ingress configuration')
    uri = f'rtsp://{username}:{identifier_secret(password)}@{address}:{port}/{stream_path(path)}'
    return lambda: decoder_process('--central-rtsp', secret_url=uri)
