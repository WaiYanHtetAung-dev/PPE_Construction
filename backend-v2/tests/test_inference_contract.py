from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.inference import Detection, FrameRef, InferenceRequest, InferenceResponse


def test_request_contract():
    req = InferenceRequest(
        request_id=uuid4(), frame_id='cam-01-00001', model_key='ppe-yolo', model_version='1.0.0',
        frame=FrameRef(object_key='frames/cam-01/0001.jpg', width=1280, height=720, content_type='image/jpeg'),
    )
    assert req.options.confidence_threshold == 0.35
    assert req.schema_version == '1.0'


def test_response_contract():
    request_id = uuid4()
    resp = InferenceResponse(
        request_id=request_id, frame_id='frame-1', model_key='ppe-yolo', model_version='1.0.0',
        inference_ms=15.4, detections=[Detection(
            class_key='helmet', original_class='yellow helmet', score=.91,
            bbox_xyxy=(20, 40, 90, 120), attributes={'color': 'yellow'}
        )]
    )
    assert resp.detections[0].class_key == 'helmet'
    assert resp.request_id == request_id


def test_unknown_classes_are_rejected():
    with pytest.raises(ValidationError):
        Detection(class_key='safety-shoe', original_class='safety-shoe', score=.5, bbox_xyxy=(1, 2, 3, 4))


def test_invalid_bbox_is_rejected():
    with pytest.raises(ValidationError):
        Detection(class_key='person', original_class='person', score=.9, bbox_xyxy=(100, 30, 10, 90))
