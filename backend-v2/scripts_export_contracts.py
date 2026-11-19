"""Export a reviewed snapshot of the public OpenAPI and model JSON Schemas."""
import json
from pathlib import Path

from app.main import app
from app.contracts.inference import InferenceRequest, InferenceResponse

folder = Path('contracts')
folder.mkdir(parents=True, exist_ok=True)
for file_name, data in [
    ('openapi.v1.json', app.openapi()),
    ('inference-request.v1.schema.json', InferenceRequest.model_json_schema()),
    ('inference-response.v1.schema.json', InferenceResponse.model_json_schema()),
]:
    (folder / file_name).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print('Exported', folder / file_name)
