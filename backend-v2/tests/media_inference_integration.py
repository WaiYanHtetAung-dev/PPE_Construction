"""Decode fixture video and invoke the verified ONNX worker without network access."""

import asyncio
import hashlib
import os
import unittest
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from PIL import Image

from app.model_artifact_integrity import Manifest
from inference_worker.authority import create_authority
from inference_worker.contract import ModelLease
from inference_worker.onnx_cpu import LABELS, CpuRuntime, detection
from inference_worker.service import AuthorityClient, Storage, create_worker
from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.inference_dispatch import CameraAssignment, DispatchError, InferenceDispatcher
from media_gateway.sampler import sample_camera
from media_gateway.video_source import local_video_source
from tests.media_decoder_integration import HEIGHT, WIDTH, generate_clip
from tests.test_onnx_cpu import fixture_graph

FRAME_BYTES = WIDTH * HEIGHT * 3
MODEL_KEY, MODEL_VERSION = 'synthetic-media-test', '1'


class ObservedRuntime(CpuRuntime):
    def __init__(self):
        self.rendered_pixels = {}

    def infer(self, model, frame, request):
        detections = super().infer(model, frame, request)
        with Image.open(BytesIO(frame)) as image:
            self.rendered_pixels[request.request_id] = image.tobytes()
        return detections


@contextmanager
def ephemeral_worker(root, frame_root, model_id):
    artifact_ref = 'synthetic/detector.onnx'
    artifact = root / artifact_ref
    artifact.parent.mkdir(parents=True)
    artifact_data = fixture_graph()
    artifact.write_bytes(artifact_data)
    artifact_digest = hashlib.sha256(artifact_data).hexdigest()
    signer = Ed25519PrivateKey.generate()
    public_key = signer.public_key().public_bytes_raw()
    now = datetime.now(UTC)
    manifest = Manifest(
        model_version_id=model_id, model_key=MODEL_KEY, version=MODEL_VERSION,
        artifact_ref=artifact_ref, artifact_sha256=artifact_digest, release_id='synthetic-test-only',
        issued_at=now - timedelta(seconds=5), expires_at=now + timedelta(minutes=10),
    ).model_dump_json().encode()
    artifact.with_suffix('.onnx.manifest.json').write_bytes(manifest)
    artifact.with_suffix('.onnx.manifest.sig').write_bytes(signer.sign(manifest))
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    key_digest = hashlib.sha256(public_key).hexdigest()
    ingress_token, authority_token = token_urlsafe(32), token_urlsafe(32)
    control = {'revoked': False}

    def resolve(query):
        if control['revoked'] or (query.model_key, query.model_version) != (MODEL_KEY, MODEL_VERSION):
            return None
        issued = datetime.now(UTC)
        return ModelLease(
            **query.model_dump(), model_version_id=model_id, artifact_ref=artifact_ref,
            artifact_sha256=artifact_digest, manifest_sha256=manifest_digest,
            signer_key_sha256=key_digest, verification_id=1,
            issued_at=issued, expires_at=issued + timedelta(seconds=5),
        )

    runtime = ObservedRuntime()
    with TestClient(create_authority(authority_token, resolve)) as authority:
        def route_lease(request):
            return authority.request(request.method, request.url.path, content=request.content,
                                     headers=dict(request.headers))

        authority_http = httpx.Client(base_url='https://authority.test',
                                      transport=httpx.MockTransport(route_lease))
        with authority_http:
            worker = create_worker(
                ingress_token, AuthorityClient(authority_http, authority_token),
                Storage(root, 'synthetic', 1024**2), Storage(frame_root, 'frames', 1024**2),
                public_key, runtime,
            )
            yield worker, ingress_token, control, runtime


@unittest.skipUnless(os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW'),
                     'Verified worker frame and artifact reads require POSIX directory descriptors')
class TestSyntheticMediaInference(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.frame_root = self.root / 'frame-store'
        (self.frame_root / 'frames').mkdir(parents=True)
        self.model_id = uuid4()

    def assignment(self):
        class_map = {
            label: detection(index, 1.0, (1, 1, 2, 2)).class_key for index, label in enumerate(LABELS)
        }
        return CameraAssignment(uuid4(), uuid4(), uuid4(), self.model_id, MODEL_KEY,
                                MODEL_VERSION, class_map)

    def dispatcher(self, worker, token, queue, assignments):
        return InferenceDispatcher(
            queue, {str(item.camera_id): item for item in assignments}, self.frame_root,
            worker_origin='https://worker.test', token=token, timeout=10,
            transport=httpx.ASGITransport(app=worker),
        )

    async def test_three_decoders_dispatch_verified_onnx_without_cross_camera_mix(self):
        assignments = [self.assignment() for _ in range(3)]
        by_camera = {str(item.camera_id): item for item in assignments}
        queue = FrameQueue(max_cameras=3, max_bytes=FRAME_BYTES * 3, max_frame_bytes=FRAME_BYTES)
        expected = {camera: {} for camera in by_camera}

        for fps, assignment in zip((10, 24, 30), assignments):
            generate_clip(self.root / f'{assignment.camera_id}.mp4', fps)

        async def collect_samples(assignment):
            camera = str(assignment.camera_id)
            finished = asyncio.Event()

            @asynccontextmanager
            async def source():
                async with local_video_source(self.root / f'{camera}.mp4') as decoded:
                    async def frames():
                        async for frame in decoded:
                            expected[camera][frame.index] = frame
                            yield frame
                        finished.set()

                    yield frames()

            task = asyncio.create_task(sample_camera(
                camera, source, queue, sample_interval=0.2, frame_timeout=5,
                retry_initial=30, retry_max=30,
            ))
            try:
                await asyncio.wait_for(finished.wait(), timeout=12)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        await asyncio.gather(*(collect_samples(item) for item in assignments))

        with ephemeral_worker(self.root / 'models', self.frame_root, self.model_id) as (
            worker, token, _, runtime,
        ):
            async with self.dispatcher(worker, token, queue, assignments) as dispatch:
                results = [await dispatch.dispatch_one() for _ in range(3)]
                self.assertIsNone(await dispatch.dispatch_one())
            seen_cameras = set()
            for result in results:
                self.assertIsNotNone(result)
                frame, response = result.frame, result.response
                camera = str(frame.camera_id)
                seen_cameras.add(camera)
                self.assertEqual(result.assignment, by_camera[camera])
                self.assertEqual(frame.received_at.tzinfo, UTC)
                self.assertEqual(frame.source_epoch, 1)
                self.assertEqual(frame.sample_interval, 0.2)
                self.assertAlmostEqual(frame.source_timestamp, 0.8, delta=0.1)
                original = expected[camera][frame.source_frame_index]
                self.assertEqual(frame.received_at, original.received_at)
                self.assertEqual(original.source_timestamp, frame.source_timestamp)
                self.assertEqual((frame.width, frame.height), (WIDTH, HEIGHT))
                self.assertEqual(runtime.rendered_pixels[response.request_id], original.data)
                self.assertEqual((response.schema_version, response.model_key, response.model_version),
                                 ('1.0', MODEL_KEY, MODEL_VERSION))
                self.assertTrue(response.detections)
                for item in response.detections:
                    self.assertEqual(item.class_key, by_camera[camera].class_map[item.original_class])
                    self.assertGreaterEqual(item.score, 0)
                    self.assertLessEqual(item.score, 1)
                    x1, y1, x2, y2 = item.bbox_xyxy
                    self.assertTrue(0 <= x1 < x2 <= WIDTH and 0 <= y1 < y2 <= HEIGHT)

            self.assertEqual(seen_cameras, set(by_camera))
            self.assertEqual(len({item.response.request_id for item in results}), 3)
            self.assertEqual(len({item.response.frame_id for item in results}), 3)
            self.assertEqual(len(set(runtime.rendered_pixels.values())), 3)
        self.assertEqual(list((self.frame_root / 'frames').iterdir()), [])

    async def test_worker_enforces_token_and_current_eligibility(self):
        assignment = self.assignment()
        camera = str(assignment.camera_id)
        path = self.root / 'fixture.mp4'
        generate_clip(path, 10)
        async with local_video_source(path) as frames:
            frame = await anext(frames)
        sampled = SampledFrame(
            camera, frame.data, frame.received_at, frame.source_timestamp, frame.index, 1,
            asyncio.get_running_loop().time(), 0.2, frame.width, frame.height,
        )
        queue = FrameQueue(max_cameras=1, max_bytes=FRAME_BYTES, max_frame_bytes=FRAME_BYTES)

        with ephemeral_worker(self.root / 'models', self.frame_root, self.model_id) as (
            worker, token, control, runtime,
        ):
            unknown_version = replace(assignment, model_version='missing')
            for selected, credential, revoked, error in (
                (assignment, token_urlsafe(32), False, 'unauthorized'),
                (unknown_version, token, False, 'unavailable'),
                (assignment, token, True, 'unavailable'),
            ):
                with self.subTest(error=error, revoked=revoked):
                    control['revoked'] = revoked
                    self.assertTrue(queue.offer(sampled))
                    async with self.dispatcher(worker, credential, queue, [selected]) as dispatch:
                        with self.assertRaises(DispatchError) as failure:
                            await dispatch.dispatch_one()
                    self.assertEqual(failure.exception.code, error)
                    self.assertEqual(list((self.frame_root / 'frames').iterdir()), [])
            self.assertEqual(runtime.rendered_pixels, {})
