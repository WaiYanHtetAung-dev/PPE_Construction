"""Private control-plane protocol, independent of inference v1."""

import json
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.contracts.inference import CanonicalClass, StrictModel

SNAPSHOT_PATH = '/internal/v1/camera-assignment-snapshots'
SNAPSHOT_AUDIENCE = 'camera-assignment-snapshot-v1'
MAX_REQUEST_BYTES = 2048
MAX_RESPONSE_BYTES = 512 * 1024
MAX_SNAPSHOT_LIFETIME = 10
ClassLabel = Annotated[str, StringConstraints(min_length=1, max_length=100,
                                              pattern=r'^[A-Za-z0-9][A-Za-z0-9 _.-]*$')]
Generation = Annotated[int, Field(gt=0, le=2**63 - 1)]


class SnapshotRequest(StrictModel):
    schema_version: Literal['1.0']
    organization_id: UUID
    site_id: UUID
    camera_id: UUID
    nonce: UUID


class SnapshotModel(StrictModel):
    model_version_id: UUID
    model_key: str = Field(max_length=100, pattern=r'^[a-z0-9][a-z0-9_-]*$')
    version: str = Field(max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9.+_-]*$')


class SnapshotResponse(SnapshotRequest):
    assignment_revision: int = Field(ge=0, le=2**63 - 1)
    decision: Literal['eligible', 'unassigned', 'camera_disabled', 'revoked', 'expired', 'unverified']
    model: SnapshotModel | None
    class_map: Annotated[dict[ClassLabel, CanonicalClass], Field(min_length=1, max_length=256)] | None
    verification_generation: Generation | None
    revoked_through_generation: Generation | None
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode='after')
    def validate_decision(self):
        generation, floor = self.verification_generation, self.revoked_through_generation
        if any(value.utcoffset() != timedelta(0) for value in (self.issued_at, self.expires_at)):
            raise ValueError('Snapshot timestamps must be UTC')
        if self.model is None and (self.decision not in ('unassigned', 'camera_disabled')
                                   or generation is not None or floor is not None):
            raise ValueError('Invalid unassigned snapshot')
        if self.decision == 'unassigned' and self.model is not None:
            raise ValueError('Unassigned snapshot has a model')
        if floor is not None and (generation is None or floor > generation):
            raise ValueError('Invalid revocation floor')
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if self.decision == 'eligible':
            if (self.class_map is None or generation is None or floor == generation
                    or not 0 < lifetime <= MAX_SNAPSHOT_LIFETIME):
                raise ValueError('Invalid eligible snapshot')
        elif self.class_map is not None or lifetime != 0:
            raise ValueError('Denial cannot grant a lease')
        if ((self.decision == 'revoked' and (generation is None or floor != generation))
                or (self.decision == 'expired' and (generation is None or floor == generation))):
            raise ValueError('Invalid evidence denial')
        return self


def _unique_fields(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError('Duplicate JSON field')
    return data


def _parse(model, body, limit):
    if len(body) > limit:
        raise ValueError('Snapshot body exceeds limit')
    json.loads(body, object_pairs_hook=_unique_fields)
    return model.model_validate_json(body, strict=True)


def parse_snapshot_request(body: bytes) -> SnapshotRequest:
    return _parse(SnapshotRequest, body, MAX_REQUEST_BYTES)


def parse_snapshot_response(body: bytes) -> SnapshotResponse:
    return _parse(SnapshotResponse, body, MAX_RESPONSE_BYTES)
