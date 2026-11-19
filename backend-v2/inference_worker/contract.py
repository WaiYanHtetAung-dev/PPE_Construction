from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.contracts.inference import StrictModel

LEASE_PATH = '/internal/v1/model-eligibility'
INFERENCE_PATH = '/internal/v1/infer'
MAX_LEASE_SECONDS = 10
Sha256 = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class ModelIdentity(StrictModel):
    model_key: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=64)


class LeaseRequest(ModelIdentity):
    nonce: UUID


class ModelLease(LeaseRequest):
    schema_version: Literal['1.0'] = '1.0'
    model_version_id: UUID
    artifact_ref: str = Field(min_length=1, max_length=500)
    artifact_sha256: Sha256
    manifest_sha256: Sha256
    signer_key_sha256: Sha256
    verification_id: int = Field(gt=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @property
    def id(self) -> str:
        return str(self.model_version_id)

    @property
    def version(self) -> str:
        return self.model_version

    def evidence(self):
        return (self.id, self.model_key, self.model_version, self.artifact_ref,
                self.artifact_sha256, self.manifest_sha256, self.signer_key_sha256, self.verification_id)
