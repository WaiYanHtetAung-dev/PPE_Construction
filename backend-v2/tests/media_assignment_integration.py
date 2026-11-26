import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx

from media_gateway.assignment_resolver import AssignmentResolver, CameraScope
from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.inference_dispatch import DispatchError, InferenceDispatcher


class TestMediaAssignment(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        (self.root / 'frames').mkdir()
        self.queue = FrameQueue(max_cameras=3, max_bytes=576, max_frame_bytes=192)
        org = uuid4()
        self.scopes = [CameraScope(org, uuid4(), uuid4()) for _ in range(3)]
        self.cameras = [str(scope.camera_id) for scope in self.scopes]
        self.models = {key: {'model_version_id': str(uuid4()), 'model_key': key, 'version': '1'} for key in ('a', 'b')}
        self.states = dict(zip(self.cameras, (('a', 1, 1, None, 'eligible'),
                                             ('a', 1, 1, None, 'eligible'),
                                             ('b', 1, 2, None, 'eligible'))))
        self.clock = 0
        self.issued = datetime.now(UTC)
        self.token = f'{uuid4()}.{token_urlsafe(32)}'

    def frame(self, camera):
        return SampledFrame(camera, b'\x00' * 192, self.issued, 0.0, 0, 1,
                            self.clock, 0.2, 8, 8)

    def snapshot(self, request):
        assert request.headers['Authorization'] == f'Bearer {self.token}'
        body = json.loads(request.content)
        model, revision, generation, floor, decision = self.states[body['camera_id']]
        eligible = decision == 'eligible'
        return httpx.Response(200, json=body | {
            'assignment_revision': revision, 'model': self.models[model], 'decision': decision,
            'class_map': {'person': 'person'} if eligible else None,
            'verification_generation': generation, 'revoked_through_generation': floor,
            'issued_at': self.issued.isoformat(),
            'expires_at': (self.issued + timedelta(seconds=10 if eligible else 0)).isoformat(),
        })

    def resolver(self, handler=None):
        return AssignmentResolver(self.queue, self.scopes, control_origin='https://control.test', token=self.token,
                                  supported_class_maps=[{'person': 'person'}],
                                  transport=httpx.MockTransport(handler or self.snapshot), clock=lambda: self.clock)

    def dispatcher(self, resolver, handler):
        return InferenceDispatcher(self.queue, resolver, self.root, worker_origin='https://worker.test',
                                   token=token_urlsafe(32), transport=httpx.MockTransport(handler))

    @staticmethod
    def inference(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={key: body[key] for key in (
            'schema_version', 'model_key', 'model_version', 'request_id', 'frame_id',
        )} | {'inference_ms': 1.0, 'detections': []})

    async def test_three_cameras_switch_without_rebinding_queued_frames(self):
        first, second, third = self.cameras
        async with self.resolver() as resolver, self.dispatcher(resolver, self.inference) as dispatcher:
            self.assertFalse(self.queue.offer(self.frame(first)))
            self.assertEqual(await asyncio.gather(*(resolver.refresh(key) for key in self.cameras)), [True] * 3)
            for key in self.cameras:
                self.assertTrue(self.queue.offer(self.frame(key)))
            self.states[first] = ('b', 2, 2, None, 'eligible')
            self.assertTrue(await resolver.refresh(first))
            self.assertTrue(self.queue.offer(self.frame(first)))
            seen = [await dispatcher.dispatch_one() for _ in self.cameras]
            self.assertEqual([(row.frame.camera_id, row.response.model_key) for row in seen],
                             [(second, 'a'), (third, 'b'), (first, 'b')])
            self.states[first] = ('a', 1, 1, None, 'eligible')
            self.assertFalse(await resolver.refresh(first))
            self.assertFalse(self.queue.offer(self.frame(first)))
            self.assertIsNotNone(resolver.current(second))

    async def test_inflight_revocation_fences_siblings_and_allows_fresh_reverification(self):
        first, second, third = self.cameras
        started, finish = asyncio.Event(), asyncio.Event()

        async def blocked(request):
            started.set()
            await finish.wait()
            return self.inference(request)

        async with self.resolver() as resolver, self.dispatcher(resolver, blocked) as dispatcher:
            await asyncio.gather(*(resolver.refresh(key) for key in self.cameras))
            self.assertTrue(self.queue.offer(self.frame(first)))
            self.assertTrue(self.queue.offer(self.frame(second)))
            task = asyncio.create_task(dispatcher.dispatch_one())
            await asyncio.wait_for(started.wait(), timeout=2)
            try:
                self.states[second] = ('a', 1, 1, 1, 'revoked')
                self.assertFalse(await resolver.refresh(second))
                self.assertIsNone(self.queue.take())
                self.assertIsNone(resolver.current(first))
                self.assertIsNotNone(resolver.current(third))
            finally:
                finish.set()
                with self.assertRaisesRegex(DispatchError, 'assignment_invalidated'):
                    await task
            self.assertFalse(await resolver.refresh(first))  # Old positive predates the known floor.
            self.states[first] = ('a', 1, 3, 1, 'eligible')
            self.assertTrue(await resolver.refresh(first))
            self.assertIsNone(resolver.current(second))
        self.assertEqual(list((self.root / 'frames').iterdir()), [])

    async def test_poll_deadline_expiry_and_credential_denial(self):
        first, second, third = self.cameras
        state = {'mode': 'healthy'}

        def transport(request):
            if state['mode'] == 'deadline':
                self.clock += 2
            if state['mode'] == 'unauthorized':
                return httpx.Response(401)
            return self.snapshot(request)

        async with self.resolver(transport) as resolver:
            await asyncio.gather(*(resolver.refresh(key) for key in self.cameras))
            self.clock = 5
            state['mode'] = 'deadline'
            self.assertFalse(await resolver.refresh(first))
            self.assertEqual(self.clock, 7)
            self.assertFalse(self.queue.offer(self.frame(first)))
            self.clock = 10
            self.assertFalse(self.queue.offer(self.frame(second)))
            state['mode'] = 'healthy'
            self.assertTrue(await resolver.refresh(second))
            state['mode'] = 'unauthorized'
            self.assertFalse(await resolver.refresh(third))
            self.assertIsNone(resolver.current(second))

    async def test_bad_binding_map_and_late_response_after_key_reload(self):
        first = self.cameras[0]
        arrived, release = asyncio.Event(), asyncio.Event()
        state = {'mode': 'healthy'}

        async def transport(request):
            response = self.snapshot(request)
            payload = response.json()
            if state['mode'] == 'nonce':
                payload['nonce'] = str(uuid4())
            elif state['mode'] == 'map':
                payload['class_map'] = {'helmet': 'helmet'}
            elif state['mode'] == 'late':
                arrived.set()
                await release.wait()
            return httpx.Response(200, json=payload)

        async with self.resolver(transport) as resolver:
            for mode in ('nonce', 'map'):
                state['mode'] = 'healthy'
                self.assertTrue(await resolver.refresh(first))
                state['mode'] = mode
                self.assertFalse(await resolver.refresh(first))
                self.assertIsNone(resolver.current(first))
            state['mode'] = 'late'
            pending = asyncio.create_task(resolver.refresh(first))
            try:
                await asyncio.wait_for(arrived.wait(), timeout=1)
                self.assertFalse(await resolver.refresh(first))
                self.token = f'{uuid4()}.{token_urlsafe(32)}'
                resolver.reload_credential(self.token)
            finally:
                release.set()
                self.assertFalse(await pending)
            self.assertIsNone(resolver.current(first))
            state['mode'] = 'healthy'
            self.assertTrue(await resolver.refresh(first))
