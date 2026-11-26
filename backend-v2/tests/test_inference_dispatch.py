import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx

from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.inference_dispatch import (
    MAX_RESPONSE_BYTES, CameraAssignment, DispatchError, InferenceDispatcher,
)


TOKEN = 'synthetic-dispatch-test-credential-only'
ORIGIN = 'https://worker.test'
CAMERA = UUID(int=3)


def worker_response(request):
    return {
        'schema_version': '1.0',
        'request_id': request['request_id'],
        'frame_id': request['frame_id'],
        'model_key': request['model_key'],
        'model_version': request['model_version'],
        'inference_ms': 3.5,
        'detections': [{
            'class_key': 'helmet', 'original_class': 'blue helmet', 'score': 0.9,
            'bbox_xyxy': [0, 1, 3, 4],
        }],
    }


class TestInferenceDispatch(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.frames = self.root / 'frames'
        self.frames.mkdir()
        self.queue = FrameQueue(max_cameras=1, max_bytes=512, max_frame_bytes=512)
        self.assignment = CameraAssignment(
            organization_id=UUID(int=1), site_id=UUID(int=2), camera_id=CAMERA,
            model_version_id=UUID(int=4), model_key='synthetic-test', model_version='1',
            class_map={'blue helmet': 'helmet'},
        )
        self.frame = SampledFrame(
            camera_id=str(CAMERA), data=bytes(4 * 4 * 3),
            received_at=datetime(2026, 1, 1, tzinfo=UTC), source_timestamp=0.2,
            source_frame_index=2, source_epoch=1, sampled_monotonic=10.2,
            sample_interval=0.1, width=4, height=4,
        )

    def dispatcher(self, handler, *, timeout=5):
        return InferenceDispatcher(
            self.queue, {str(CAMERA): self.assignment}, self.root, worker_origin=ORIGIN,
            token=TOKEN, timeout=timeout, transport=httpx.MockTransport(handler),
        )

    def offer(self, frame=None):
        self.assertTrue(self.queue.offer(self.frame if frame is None else frame))

    async def assert_dispatch_error(self, dispatcher, code):
        with self.assertRaises(DispatchError) as error:
            await dispatcher.dispatch_one()
        self.assertEqual(error.exception.code, code)

    async def test_authenticated_v1_request_stages_png_and_preserves_attribution(self):
        captured = []

        def handler(request):
            self.assertEqual(str(request.url), f'{ORIGIN}/internal/v1/infer')
            self.assertEqual(request.headers['authorization'], f'Bearer {TOKEN}')
            payload = json.loads(request.content)
            captured.append(payload)
            self.assertEqual(payload['schema_version'], '1.0')
            self.assertEqual(payload['model_key'], self.assignment.model_key)
            self.assertEqual(payload['model_version'], self.assignment.model_version)
            reference = payload['frame']
            self.assertRegex(reference['object_key'], r'^frames/[0-9a-f-]+\.png$')
            self.assertEqual(reference['content_type'], 'image/png')
            self.assertEqual((reference['width'], reference['height']), (4, 4))
            self.assertTrue((self.root / reference['object_key']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertNotIn('organization_id', payload)
            self.assertNotIn('site_id', payload)
            self.assertNotIn('camera_id', payload)
            return httpx.Response(200, json=worker_response(payload))

        async with self.dispatcher(handler) as dispatcher:
            self.assertIsNone(await dispatcher.dispatch_one())
            self.offer()
            result = await dispatcher.dispatch_one()
        self.assertEqual(result.assignment, self.assignment)
        for attribute in ('camera_id', 'received_at', 'source_timestamp', 'source_frame_index',
                          'source_epoch', 'sampled_monotonic', 'sample_interval', 'width', 'height'):
            self.assertEqual(getattr(result.frame, attribute), getattr(self.frame, attribute))
        self.assertFalse(hasattr(result.frame, 'data'))
        self.assertEqual(result.response.request_id, UUID(captured[0]['request_id']))
        self.assertEqual(result.response.frame_id, captured[0]['frame_id'])
        self.assertEqual(result.response.detections[0].original_class, 'blue helmet')
        self.assertEqual(list(self.frames.iterdir()), [])

    async def test_invalid_frame_or_unknown_camera_never_reaches_worker(self):
        def handler(_request):
            self.fail('Invalid frame reached the worker')

        async with self.dispatcher(handler) as dispatcher:
            self.offer(replace(self.frame, camera_id=str(UUID(int=9))))
            await self.assert_dispatch_error(dispatcher, 'unknown_camera')
            self.offer(replace(self.frame, received_at=self.frame.received_at.replace(tzinfo=None)))
            await self.assert_dispatch_error(dispatcher, 'invalid_frame')
            self.offer(replace(self.frame, data=b'wrong RGB payload size'))
            await self.assert_dispatch_error(dispatcher, 'invalid_frame')
        self.assertEqual(list(self.frames.iterdir()), [])

    async def test_rejects_malformed_responses_and_cleans_staged_files(self):
        cases = (
            ('missing schema version', lambda response: response.pop('schema_version')),
            ('unsupported schema version', lambda response: response.update(schema_version='2.0')),
            ('different request', lambda response: response.update(request_id=str(UUID(int=9)))),
            ('different frame', lambda response: response.update(frame_id='different-frame')),
            ('different model', lambda response: response.update(model_key='different-model')),
            ('different model version', lambda response: response.update(model_version='different-version')),
            ('unknown label', lambda response: response['detections'][0].update(original_class='unknown')),
            ('wrong class mapping', lambda response: response['detections'][0].update(class_key='vest')),
            ('invalid confidence', lambda response: response['detections'][0].update(score=1.01)),
            ('boolean confidence', lambda response: response['detections'][0].update(score=True)),
            ('nonfinite latency', lambda response: response.update(inference_ms=float('inf'))),
            ('out-of-frame box', lambda response: response['detections'][0].update(bbox_xyxy=[0, 1, 5, 4])),
            ('empty box', lambda response: response['detections'][0].update(bbox_xyxy=[1, 1, 1, 4])),
            ('nonfinite box', lambda response: response['detections'][0].update(bbox_xyxy=[0, 1, float('inf'), 4])),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                def handler(request):
                    response = worker_response(json.loads(request.content))
                    mutate(response)
                    return httpx.Response(200, content=json.dumps(response),
                                          headers={'Content-Type': 'application/json'})

                async with self.dispatcher(handler) as dispatcher:
                    self.offer()
                    await self.assert_dispatch_error(dispatcher, 'invalid_response')
                self.assertEqual(list(self.frames.iterdir()), [])

        for content in (b'{', b' ' * (MAX_RESPONSE_BYTES + 1)):
            def invalid_json(_request):
                return httpx.Response(200, content=content, headers={'Content-Type': 'application/json'})

            async with self.dispatcher(invalid_json) as dispatcher:
                self.offer()
                await self.assert_dispatch_error(dispatcher, 'invalid_response')
            self.assertEqual(list(self.frames.iterdir()), [])

    async def test_worker_failures_are_bounded_and_do_not_log_response_secrets(self):
        for status, code in ((401, 'unauthorized'), (403, 'unauthorized'), (503, 'unavailable'),
                             (500, 'worker_failure'), (307, 'worker_failure'), (None, 'worker_failure')):
            with self.subTest(status=status):
                calls = []

                def handler(request):
                    calls.append(request)
                    if status is None:
                        raise httpx.ConnectError('sensitive-test-response', request=request)
                    return httpx.Response(status, json={'detail': 'sensitive-test-response'},
                                          headers={'Location': 'https://redirect.test'})

                async with self.dispatcher(handler) as dispatcher:
                    self.offer()
                    with self.assertLogs('media_gateway.inference_dispatch', level='INFO') as logs:
                        await self.assert_dispatch_error(dispatcher, code)
                    self.assertIsNone(await dispatcher.dispatch_one())
                output = '\n'.join(logs.output)
                self.assertNotIn(TOKEN, output)
                self.assertNotIn(ORIGIN, output)
                self.assertNotIn('sensitive-test-response', output)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].reason, code)
                self.assertEqual(logs.records[0].correlation_id, json.loads(calls[0].content)['request_id'])
                self.assertEqual(list(self.frames.iterdir()), [])

    async def test_rejects_duplicate_json_fields_even_if_final_value_looks_valid(self):
        def handler(request):
            valid_payload = json.dumps(worker_response(json.loads(request.content)))
            return httpx.Response(
                200, content='{"schema_version":"2.0",' + valid_payload[1:],
                headers={'Content-Type': 'application/json'},
            )

        async with self.dispatcher(handler) as dispatcher:
            self.offer()
            await self.assert_dispatch_error(dispatcher, 'invalid_response')
        self.assertEqual(list(self.frames.iterdir()), [])

    async def test_timeout_cleans_pending_frame_and_allows_following_frame(self):
        seen = []

        async def handler(request):
            payload = json.loads(request.content)
            seen.append(payload)
            if len(seen) == 1:
                await asyncio.Future()
            return httpx.Response(200, json=worker_response(payload))

        async with self.dispatcher(handler, timeout=0.1) as dispatcher:
            self.offer()
            await self.assert_dispatch_error(dispatcher, 'timeout')
            self.assertEqual(list(self.frames.iterdir()), [])
            self.offer(replace(self.frame, source_frame_index=3, source_timestamp=0.3))
            result = await dispatcher.dispatch_one()
        self.assertEqual(result.frame.source_frame_index, 3)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0]['request_id'], seen[1]['request_id'])
        self.assertNotEqual(seen[0]['frame_id'], seen[1]['frame_id'])
        self.assertEqual(list(self.frames.iterdir()), [])

    async def test_overlapping_dispatch_keeps_latest_queued_frame(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            started.set()
            await release.wait()
            return httpx.Response(200, json=worker_response(json.loads(request.content)))

        async with self.dispatcher(handler) as dispatcher:
            self.offer()
            first = asyncio.create_task(dispatcher.dispatch_one())
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                self.offer(replace(self.frame, source_frame_index=3, source_timestamp=0.3))
                self.offer(replace(self.frame, source_frame_index=4, source_timestamp=0.4))
                await self.assert_dispatch_error(dispatcher, 'busy')
            finally:
                release.set()
                completed = await first
            latest = await dispatcher.dispatch_one()
        self.assertEqual(completed.frame.source_frame_index, 2)
        self.assertEqual(latest.frame.source_frame_index, 4)
        self.assertEqual(list(self.frames.iterdir()), [])

    async def test_cleanup_failure_blocks_later_dispatch_without_consuming_queue(self):
        sent = []

        def handler(request):
            payload = json.loads(request.content)
            sent.append(payload['frame']['object_key'])
            return httpx.Response(200, json=worker_response(payload))

        async with self.dispatcher(handler) as dispatcher:
            self.offer()
            with patch.object(Path, 'unlink', side_effect=PermissionError('simulated storage failure')):
                await self.assert_dispatch_error(dispatcher, 'frame_storage')
            self.assertEqual(len(sent), 1)
            self.assertTrue((self.root / sent[0]).is_file())

            following = replace(self.frame, source_frame_index=3, source_timestamp=0.3)
            self.offer(following)
            await self.assert_dispatch_error(dispatcher, 'frame_storage')
            self.assertEqual(len(sent), 1)
            self.assertEqual(self.queue.take(), following)
            self.assertEqual(len(list(self.frames.iterdir())), 1)
