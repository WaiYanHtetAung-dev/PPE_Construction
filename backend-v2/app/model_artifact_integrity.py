"""Pure artifact integrity checks shared by the verifier and isolated worker."""

import hashlib
import hmac
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.model_artifacts import valid_object_key, within_namespace


class ArtifactIdentity(Protocol):
    id: str
    model_key: str
    version: str
    artifact_ref: str
    artifact_sha256: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_version_id: UUID
    model_key: str
    version: str
    artifact_ref: str
    artifact_sha256: str
    release_id: Annotated[str, Field(min_length=1, max_length=128)]
    issued_at: AwareDatetime
    expires_at: AwareDatetime


@dataclass(frozen=True)
class VerifiedArtifact:
    manifest: Manifest
    manifest_sha256: str
    signer_key_sha256: str
    data: bytes | None


@contextmanager
def open_artifact(root: Path, key: str):
    if not valid_object_key(key):
        raise ValueError('Invalid storage key')
    # The mount root and its parents are provisioned by the operator.
    with ExitStack() as stack:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, flags)
        stack.callback(os.close, directory)
        *parents, filename = key.split('/')
        for part in parents:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Artifact entry must be a regular file')
            yield stream


def read_small(root: Path, key: str, limit: int) -> bytes:
    with open_artifact(root, key) as stream:
        result = stream.read(limit + 1)
    if len(result) > limit:
        raise ValueError('Artifact metadata exceeds size limit')
    return result


def check_artifact(root: Path, namespace: str, public_key: bytes, model: ArtifactIdentity,
                   max_bytes: int, *, capture: bool = False) -> VerifiedArtifact:
    key = model.artifact_ref
    if not within_namespace(key, namespace) or max_bytes < 1:
        raise ValueError('Artifact namespace or size limit invalid')
    payload = read_small(root, key + '.manifest.json', 65536)
    signature = read_small(root, key + '.manifest.sig', 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except InvalidSignature:
        raise ValueError('Manifest signature invalid') from None
    manifest = Manifest.model_validate_json(payload)
    now = datetime.now(timezone.utc)
    if not manifest.issued_at <= now < manifest.expires_at <= manifest.issued_at + timedelta(hours=24):
        raise ValueError('Manifest is stale or outside the permitted validity window')
    if (str(manifest.model_version_id), manifest.model_key, manifest.version,
        manifest.artifact_ref, manifest.artifact_sha256) != (
        model.id, model.model_key, model.version, key, model.artifact_sha256,
    ):
        raise ValueError('Manifest does not match registered model')
    digest = hashlib.sha256()
    count = 0
    snapshot = bytearray() if capture else None
    with open_artifact(root, key) as artifact:
        while chunk := artifact.read(min(1024 * 1024, max_bytes - count + 1)):
            count += len(chunk)
            if count > max_bytes:
                raise ValueError('Artifact exceeds size limit')
            digest.update(chunk)
            if snapshot is not None:
                snapshot.extend(chunk)
    if not count or not hmac.compare_digest(digest.hexdigest(), model.artifact_sha256):
        raise ValueError('Artifact digest mismatch')
    return VerifiedArtifact(
        manifest, hashlib.sha256(payload).hexdigest(), hashlib.sha256(public_key).hexdigest(),
        bytes(snapshot) if snapshot is not None else None,
    )
