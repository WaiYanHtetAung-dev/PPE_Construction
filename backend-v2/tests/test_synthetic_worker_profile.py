from math import isfinite

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from inference_worker.contract import INFERENCE_PATH
from tests.synthetic_worker_profile import WORKER_PHASES, measure, service, worker_factory


def test_timings_follow_sync_request_and_stay_off_failure_responses(monkeypatch):
    app = FastAPI()

    @app.post(INFERENCE_PATH)
    def infer(fail: bool = False):
        for phase in WORKER_PHASES:
            with measure(phase):
                pass
        if fail:
            raise HTTPException(503, 'Unavailable')
        return {'synthetic': True}

    monkeypatch.setattr(service, 'from_environment', lambda: app)
    with TestClient(worker_factory()) as client:
        response = client.post(INFERENCE_PATH)
        assert response.status_code == 200
        assert response.json() == {'synthetic': True}
        for phase in WORKER_PHASES:
            value = float(response.headers[f'x-ppe-test-{phase}-ms'])
            assert isfinite(value) and value >= 0
        failed = client.post(INFERENCE_PATH, params={'fail': 'true'})
        assert failed.status_code == 503
        assert all(f'x-ppe-test-{phase}-ms' not in failed.headers for phase in WORKER_PHASES)
