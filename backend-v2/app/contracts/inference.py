"""Stable, model-agnostic inference interface. No torch/YOLO import here."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class FrameRef(StrictModel):
    # Must be an authorized object key or internal media identifier, NEVER an arbitrary URL.
    object_key: str = Field(min_length=1, max_length=500)
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    content_type: Literal['image/jpeg', 'image/png']


class InferenceOptions(StrictModel):
    confidence_threshold: float = Field(default=0.35, ge=0, le=1)


class InferenceRequest(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    request_id: UUID
    frame_id: str = Field(min_length=1, max_length=128)
    model_key: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=64)
    frame: FrameRef
    options: InferenceOptions = Field(default_factory=InferenceOptions)


CanonicalClass = Literal['person', 'helmet', 'vest']


class Detection(StrictModel):
    class_key: CanonicalClass
    original_class: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0, le=1)
    bbox_xyxy: tuple[float, float, float, float]
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_bbox(self):
        x1, y1, x2, y2 = self.bbox_xyxy
        if x1 < 0 or y1 < 0 or x1 >= x2 or y1 >= y2:
            raise ValueError('bbox_xyxy must satisfy 0 <= x1 < x2 and 0 <= y1 < y2')
        return self


class InferenceResponse(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    request_id: UUID
    frame_id: str
    model_key: str
    model_version: str
    inference_ms: float = Field(ge=0)
    detections: list[Detection]
