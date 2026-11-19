import hashlib
import json
import os
import statistics
import time
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

np = pytest.importorskip('numpy')
onnx = pytest.importorskip('onnx')
pytest.importorskip('onnxruntime')
Image = pytest.importorskip('PIL.Image')

from app.contracts.inference import InferenceRequest
from app.db.models import utcnow
from inference_worker.authority import create_authority
from inference_worker.contract import INFERENCE_PATH, ModelLease
from inference_worker.onnx_cpu import CpuRuntime, LABELS, PROFILE, detection
from inference_worker import service
from inference_worker.service import AuthorityClient, Storage, create_worker

LINUX = pytest.mark.skipif(os.open not in os.supports_dir_fd, reason='Worker mounts require POSIX')
INGRESS, AUTHORITY = 'i' * 32, 'a' * 32


def fixture_graph(*, empty=False, wrong_labels=False):
    h = onnx.helper
    values = np.zeros((1, 12, 8400), dtype=np.float32)
    if not empty:
        for i in range(8):
            values[0, :4, i] = (100 + 50 * i, 250, 40, 30)
            values[0, 4 + i, i] = 0.9
        for index, class_id, x, score in [(8, 0, 102, .8), (9, 1, 102, .8), (10, 3, 500, .85)]:
            values[0, :4, index] = (x, 250, 40, 30)
            values[0, 4 + class_id, index] = score
    node = h.make_node('Constant', [], ['output'], value=onnx.numpy_helper.from_array(values))
    graph = h.make_graph([node], 'synthetic-test-graph',
                         [h.make_tensor_value_info('images', onnx.TensorProto.FLOAT, [1, 3, 640, 640])],
                         [h.make_tensor_value_info('output', onnx.TensorProto.FLOAT, [1, 12, 8400])])
    model = h.make_model(graph, opset_imports=[h.make_opsetid('', 17)], ir_version=10)
    h.set_model_props(model, {'ppe.profile': PROFILE, 'ppe.labels': json.dumps(
        list(reversed(LABELS)) if wrong_labels else LABELS,
    )})
    return model.SerializeToString()


def frame_and_request():
    buffer = BytesIO()
    Image.new('RGB', (640, 320)).save(buffer, format='PNG')
    request = InferenceRequest(
        request_id=uuid4(), frame_id='synthetic-frame', model_key='finalboss', model_version='1',
        frame={'object_key': 'frames/sample.png', 'width': 640, 'height': 320, 'content_type': 'image/png'},
    )
    return buffer.getvalue(), request


def test_actual_onnx_runtime_class_mapping_coordinates_and_nms():
    runtime = CpuRuntime()
    frame, req = frame_and_request()
    with runtime.load(fixture_graph()) as model:
        results = runtime.infer(model, frame, req)
        assert len(results) == 10
        assert [row.original_class for row in results[:8]] == list(LABELS)
        assert [(row.class_key, row.attributes.get('color')) for row in results[:8]] == [
            ('helmet', 'black'), ('helmet', 'blue'), ('helmet', 'green'), ('person', None),
            ('helmet', 'red'), ('vest', None), ('helmet', 'white'), ('helmet', 'yellow'),
        ]
        assert results[0].bbox_xyxy == (80, 75, 120, 105)
        assert results[0].score == pytest.approx(.9)
        assert [item.class_key for item in results[8:]] == ['person', 'helmet']
    assert model.session is None
    with runtime.load(fixture_graph(empty=True)) as model:
        assert runtime.infer(model, frame, req) == []


def test_adapter_rejects_corrupt_images_and_unsupported_artifacts():
    runtime = CpuRuntime()
    frame, req = frame_and_request()
    for invalid in ('/weights/finalboss.onnx', b'invalid model', fixture_graph(wrong_labels=True)):
        with pytest.raises(Exception), runtime.load(invalid):
            pytest.fail('Unsupported input reached inference')
    wrong_shape = onnx.load_model_from_string(fixture_graph())
    wrong_shape.graph.output[0].type.tensor_type.shape.dim[1].dim_value = 13
    with pytest.raises(ValueError, match='shape'), runtime.load(wrong_shape.SerializeToString()):
        pytest.fail('Unsupported shape reached ORT')
    external = onnx.load_model_from_string(fixture_graph())
    tensor = external.graph.node[0].attribute[0].t
    tensor.data_location = onnx.TensorProto.EXTERNAL
    tensor.external_data.add(key='location', value='unsafe.bin')
    with pytest.raises(ValueError, match='External'), runtime.load(external.SerializeToString()):
        pytest.fail('External tensor reached ORT')
    with pytest.raises(ValueError, match='Unknown'):
        detection(8, .9, (0, 0, 1, 1))
    with runtime.load(fixture_graph()) as model:
        with pytest.raises(OSError):
            runtime.infer(model, b'corrupt-image', req)
        req.frame.width = 32
        with pytest.raises(ValueError, match='dimensions'):
            runtime.infer(model, frame, req)


@LINUX
@pytest.mark.parametrize('mode', [
    'valid', 'signature', 'digest', 'expired', 'revoked', 'disconnect', 'replace', 'identity',
])
def test_cpu_security_through_real_worker_leases(tmp_path, mode, monkeypatch):
    source = fixture_graph()
    digest = hashlib.sha256(source).hexdigest()
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes_raw()
    identity = uuid4()
    now = utcnow()
    manifest = json.dumps({
        'model_version_id': str(identity), 'model_key': 'finalboss', 'version': '1',
        'artifact_ref': 'approved/test.onnx', 'artifact_sha256': digest, 'release_id': 'synthetic',
        'issued_at': (now - timedelta(seconds=5)).isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(),
    }).encode()
    artifact = tmp_path / 'approved/test.onnx'
    artifact.parent.mkdir()
    artifact.write_bytes(b'tampered' if mode == 'digest' else source)
    artifact.with_suffix('.onnx.manifest.json').write_bytes(manifest)
    artifact.with_suffix('.onnx.manifest.sig').write_bytes(b'x'*64 if mode == 'signature' else signer.sign(manifest))
    frame, payload = frame_and_request()
    frame_path = tmp_path / payload.frame.object_key
    frame_path.parent.mkdir()
    frame_path.write_bytes(frame)
    reads, snapshots, models, calls = 0, [], [], []
    measure = mode == 'valid' and os.environ.get('PPE_MEASURE_SYNTHETIC_ONNX') == '1'
    samples = {name: [] for name in ('artifact_verification_ms', 'model_load_ms', 'inference_ms')}
    if measure:
        checker = service.check_artifact

        def timed_check(*args, **kwargs):
            started = time.perf_counter()
            result = checker(*args, **kwargs)
            samples['artifact_verification_ms'].append((time.perf_counter() - started) * 1000)
            return result

        monkeypatch.setattr(service, 'check_artifact', timed_check)

    class Observed(CpuRuntime):
        @contextmanager
        def load(self, data):
            snapshots.append(data)
            started = time.perf_counter()
            with super().load(data) as model:
                samples['model_load_ms'].append((time.perf_counter() - started) * 1000)
                models.append(model)
                yield model

        def infer(self, model, frame, request):
            calls.append(True)
            started = time.perf_counter()
            result = super().infer(model, frame, request)
            samples['inference_ms'].append((time.perf_counter() - started) * 1000)
            return result

    def resolve(query):
        nonlocal reads
        reads += 1
        if mode == 'revoked' and reads == 3:
            return None
        if mode == 'replace' and reads == 2:
            artifact.write_bytes(b'changed after verification')
        issued = utcnow() - timedelta(seconds=5) if mode == 'expired' else utcnow()
        return ModelLease(
            model_key=query.model_key, model_version=query.model_version, nonce=query.nonce,
            model_version_id=uuid4() if mode == 'identity' else identity,
            artifact_ref='approved/test.onnx', artifact_sha256=digest, verification_id=1,
            manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            signer_key_sha256=hashlib.sha256(public).hexdigest(), issued_at=issued,
            expires_at=issued + timedelta(seconds=4),
        )

    with TestClient(create_authority(AUTHORITY, resolve)) as authority:
        def transport(request):
            if mode == 'disconnect' and reads == 2:
                raise httpx.ConnectError('synthetic disconnect', request=request)
            return authority.request(request.method, request.url.path, content=request.content,
                                     headers=dict(request.headers))

        app = create_worker(
            INGRESS, AuthorityClient(httpx.Client(base_url='https://authority.test',
                                                  transport=httpx.MockTransport(transport)), AUTHORITY),
            Storage(tmp_path, 'approved', 1024**2), Storage(tmp_path, 'frames', 1024**2), public, Observed(),
        )
        with TestClient(app) as client:
            auth = {'Authorization': 'Bearer ' + INGRESS}
            response = client.post(INFERENCE_PATH, json=payload.model_dump(mode='json'), headers=auth)
            assert response.status_code == (200 if mode in ('valid', 'replace') else 503)
            if measure:
                for _ in range(4):
                    repeat = payload.model_copy(update={'request_id': uuid4()})
                    assert client.post(INFERENCE_PATH, json=repeat.model_dump(mode='json'), headers=auth).status_code == 200
            if mode == 'replace':
                assert client.post(INFERENCE_PATH, json=payload.model_dump(mode='json'), headers=auth).status_code == 503
    count = 5 if measure else 1
    assert snapshots == ([source] * count if mode in ('valid', 'replace', 'revoked', 'disconnect') else [])
    assert all(model.session is None for model in models)
    assert calls == ([True] * count if mode in ('valid', 'replace') else [])
    if measure:
        import resource

        print('Synthetic ONNX timing:', json.dumps({
            'iterations': count, 'artifact_bytes': len(source),
            'median_ms': {name: round(statistics.median(values), 3) for name, values in samples.items()},
            'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }))
