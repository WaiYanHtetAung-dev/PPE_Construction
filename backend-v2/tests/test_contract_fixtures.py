"""P1-08: documented example payloads and invalid payloads remain meaningful."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.inference import InferenceRequest, InferenceResponse
from scripts.verify_contracts import verify

FIXTURES = Path(__file__).parent / 'fixtures'


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def test_valid_request_json_fixture_matches_contract():
    payload = load('inference-request.valid.json')
    parsed = InferenceRequest.model_validate(payload)
    assert parsed.frame.width == 1280
    assert parsed.schema_version == '1.0'


def test_valid_response_json_fixture_matches_contract():
    payload = load('inference-response.valid.json')
    parsed = InferenceResponse.model_validate(payload)
    assert parsed.detections[1].class_key == 'helmet'
    assert parsed.model_version == '1.0.0'


@pytest.mark.parametrize('filename', [
    'inference-request.invalid-dimensions.json',
    'inference-request.invalid-unknown-field.json',
    'inference-response.invalid-bbox.json',
])
def test_invalid_json_fixtures_are_rejected(filename):
    payload = load(filename)
    model = InferenceRequest if filename.startswith('inference-request.') else InferenceResponse
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_checked_in_contracts_match_models_and_openapi():
    assert verify() == []
