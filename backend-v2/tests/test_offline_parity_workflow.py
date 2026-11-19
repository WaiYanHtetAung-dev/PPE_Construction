import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from infra.onnx_export.compare_parity import compare_capture
from infra.onnx_export.corpus import load_corpus
from infra.onnx_export import run_offline


def build_corpus(root, path):
    rows = []
    for i, (width, height, ratio, purpose) in enumerate([
        (640, 640, '1:1', 'empty'), (1280, 720, '16:9', 'multiple_people'),
        (1280, 720, '16:9', 'overlapping_ppe'),
    ]):
        name = f'image-{i}.png'
        binary = f'synthetic-{i}'.encode()
        (root / name).write_bytes(binary)
        rows.append({'id': str(i), 'file': name, 'sha256': hashlib.sha256(binary).hexdigest(),
                     'usage_authorization': 'synthetic-fixture', 'width': width, 'height': height,
                     'aspect_ratio': ratio, 'purpose': purpose})
    manifest = {'schema_version': '1.0', 'approval': 'synthetic-only',
                'de_identified': True, 'samples': rows}
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def test_corpus_checks_fingerprint_and_geometry(tmp_path):
    samples = tmp_path / 'images'
    samples.mkdir()
    path = tmp_path / 'corpus.json'
    manifest = build_corpus(samples, path)
    loaded, digest = load_corpus(path, samples)
    assert loaded == manifest and digest == hashlib.sha256(path.read_bytes()).hexdigest()
    (samples / 'image-1.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='digest'):
        load_corpus(path, samples)
    manifest['samples'][1]['aspect_ratio'] = '1:1'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='aspect'):
        load_corpus(path, samples)


@pytest.mark.parametrize('release', ['8.4.102', '8.4.96'])
def test_export_profiles_only_launch_restricted_local_image(tmp_path, monkeypatch, release):
    checkpoint = tmp_path / 'synthetic.pt'
    checkpoint.write_bytes(b'not a checkpoint')
    profiles = tmp_path / 'toolchains.json'
    image = 'local/exporter@sha256:' + 'a' * 64
    profiles.write_text(json.dumps({release: {'image': image, 'lock_sha256': 'b' * 64, 'approval': 'review-id'}}))
    destination = tmp_path / 'outputs'
    approvals = tmp_path / 'approvals'
    approvals.mkdir()
    source_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    for record_id, purpose, bindings in (
        ('synthetic-rights-id', 'checkpoint-rights', {'checkpoint_sha256': source_sha}),
        ('review-id', 'exporter-toolchain', {'version': release, 'image': image, 'lock_sha256': 'b' * 64}),
    ):
        (approvals / (record_id + '.json')).write_text(json.dumps({
            'id': record_id, 'purpose': purpose, 'status': 'approved', 'bindings': bindings,
        }))
    calls = []
    monkeypatch.setattr(sys, 'argv', ['run_offline', str(checkpoint), str(destination),
                                       '--toolchains', str(profiles), '--version', release,
                                       '--approval-dir', str(approvals), '--rights-approval', 'synthetic-rights-id'])
    monkeypatch.setattr(run_offline, 'EXPECTED', hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    monkeypatch.setattr(run_offline.os, 'getuid', lambda: 10001, raising=False)
    def simulate(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout=json.dumps([{'Os': 'linux', 'Architecture': 'amd64',
                                                   'RepoDigests': [image], 'Config': {}}]))

    monkeypatch.setattr(run_offline.subprocess, 'run', simulate)
    run_offline.main()
    assert calls[0] == ['docker', 'image', 'inspect', image]
    assert '/tool/preflight.py' in calls[1]
    assert not any('/input/finalboss.pt' in item for item in calls[1])
    cli = calls[2]
    assert {'--network=none', '--pull=never', '--read-only', '--cap-drop=ALL'} <= set(cli)
    assert cli[-4:] == [release, 'b' * 64, 'export', 'synthetic-rights-id']
    assert str(checkpoint.resolve()) + ',target=/input/finalboss.pt,readonly' in ' '.join(cli)
    assert not any('DATABASE_URL' in option for option in cli)
    assert checkpoint.read_bytes() == b'not a checkpoint'
    monkeypatch.setattr(sys, 'argv', [*sys.argv[:2], str(tmp_path / 'probe-output'), *sys.argv[3:], '--preflight-only'])
    calls.clear()
    run_offline.main()
    assert len(calls) == 2 and not (tmp_path / 'probe-output').exists()


def test_parity_report_fails_score_or_corpus_drift():
    person = {'class_id': 3, 'score': .8, 'bbox_xyxy': [10, 10, 20, 20]}
    person2 = {'class_id': 3, 'score': .9, 'bbox_xyxy': [40, 20, 50, 30]}
    shared = {
        'corpus_sha256': 'a' * 64,
        'samples': {'empty': {'purpose': 'empty', 'aspect_ratio': '1:1'},
                    'people': {'purpose': 'multiple_people', 'aspect_ratio': '16:9'}},
        'detections': {'empty': [], 'people': [person, person2]},
    }
    v1 = shared | {'mode': 'v1-default', 'predictor_options': {'rect': True}}
    onnx = shared | {'mode': 'verified-worker'}
    assert compare_capture(v1, onnx, 'v1-default')['passed']
    changed = onnx | {'detections': {'empty': [], 'people': [dict(person, score=.75), person2]}}
    assert not compare_capture(v1, changed, 'v1-default')['passed']
    with pytest.raises(ValueError, match='corpus'):
        compare_capture(v1, onnx | {'corpus_sha256': 'b' * 64}, 'v1-default')


def test_worker_capture_rejects_wrong_live_candidate_digest():
    pytest.importorskip('onnxruntime')
    pytest.importorskip('onnx')
    from app.contracts.inference import Detection
    from infra.onnx_export.capture_worker import raw_detection, require_evidence

    row = Detection(original_class='black helmet', class_key='helmet',
                    attributes={'color': 'black'}, score=0.9, bbox_xyxy=(1, 1, 2, 2))
    assert raw_detection(row)['class_id'] == 0
    with pytest.raises(ValueError, match='color'):
        raw_detection(row.model_copy(update={'attributes': {'color': 'blue'}}))

    def respond(request):
        now = datetime.now(timezone.utc)
        ask = json.loads(request.content)
        return httpx.Response(200, json=ask | {
            'model_version_id': str(uuid4()), 'artifact_ref': 'approved/model.onnx',
            'artifact_sha256': 'a' * 64, 'manifest_sha256': 'b' * 64, 'signer_key_sha256': 'c' * 64,
            'verification_id': 1, 'issued_at': now.isoformat(),
            'expires_at': (now + timedelta(seconds=5)).isoformat(),
        })

    with httpx.Client(base_url='https://eligibility-authority', transport=httpx.MockTransport(respond)) as client:
        assert require_evidence(client, 'a' * 32, 'model', '1', 'a' * 64)[-1] == 1
        with pytest.raises(ValueError, match='candidate digest'):
            require_evidence(client, 'a' * 32, 'model', '1', 'd' * 64)


def test_export_review_does_not_confuse_missing_artifact_and_onnx_validation(tmp_path):
    pytest.importorskip('onnxruntime')
    pytest.importorskip('onnx')
    from infra.onnx_export.compare_exports import examine
    from tests.test_onnx_cpu import fixture_graph

    assert examine(tmp_path, '8.4.102')['status'] == 'NOT TESTED'
    artifact = fixture_graph()
    (tmp_path / 'finalboss.onnx').write_bytes(artifact)
    report = {
        'versions': {'ultralytics': '8.4.102'},
        'source_sha256': run_offline.EXPECTED, 'lock_sha256': 'a' * 64,
        'artifact_sha256': hashlib.sha256(artifact).hexdigest(), 'artifact_bytes': len(artifact),
        'exporter_image': 'local/synthetic@sha256:' + 'b' * 64,
        'input_output_shapes': [[[1, 3, 640, 640]], [[1, 12, 8400]]],
        'preprocessing': 'synthetic metadata', 'nms': {'embedded': False},
    }
    (tmp_path / 'export.json').write_text(json.dumps(report), encoding='utf-8')
    result = examine(tmp_path, '8.4.102')
    assert result['status'] == 'PASS' and result['runtime'].startswith('Requires')
    with pytest.raises(ValueError, match='toolchain'):
        examine(tmp_path, '8.4.96')
    (tmp_path / 'finalboss.onnx').write_bytes(b'replaced')
    with pytest.raises(ValueError, match='digest'):
        examine(tmp_path, '8.4.102')
