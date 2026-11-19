"""Verify checked-in API/inference snapshots match current code.

Run after dependency install: python scripts/verify_contracts.py
If schema intentionally changed, first run scripts_export_contracts.py and review diff.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# This is a pure schema check; never open a real database.
os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')

from app.main import app
from app.contracts.inference import InferenceRequest, InferenceResponse

EXPECTED = {
    'openapi.v1.json': app.openapi(),
    'inference-request.v1.schema.json': InferenceRequest.model_json_schema(),
    'inference-response.v1.schema.json': InferenceResponse.model_json_schema(),
}


def verify() -> list[str]:
    differences = []
    for file_name, actual in EXPECTED.items():
        path = ROOT / 'contracts' / file_name
        if not path.exists() or json.loads(path.read_text(encoding='utf-8')) != actual:
            differences.append(file_name)
    return differences


if __name__ == '__main__':
    differences = verify()
    if differences:
        print('Contract snapshots need review/regeneration:', ', '.join(differences))
        raise SystemExit(1)
    print('PASS: public OpenAPI and inference v1 snapshots match code')
