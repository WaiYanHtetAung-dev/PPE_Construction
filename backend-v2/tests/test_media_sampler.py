import asyncio
import unittest
from contextlib import asynccontextmanager

from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.sampler import sample_camera


class TestMediaSampler(unittest.IsolatedAsyncioTestCase):
    async def test_one_two_and_three_synthetic_sources_keep_camera_identity(self):
        for count in (1, 2, 3):
            with self.subTest(camera_count=count):
                await self.check_sources(count)

    async def check_sources(self, count):
        queue = FrameQueue(max_cameras=count, max_bytes=count * 8, max_frame_bytes=8)
        observed = [asyncio.Event() for _ in range(count)]
        closed = set()

        @asynccontextmanager
        async def source(index):
            async def frames():
                yield f'frame-{index}'.encode('ascii')
                observed[index].set()
                await asyncio.Future()

            try:
                yield frames()
            finally:
                closed.add(index)

        tasks = [asyncio.create_task(sample_camera(
            f'camera-{index}', lambda index=index: source(index), queue,
            sample_interval=0.05, frame_timeout=5, retry_initial=0.01, retry_max=0.1,
        )) for index in range(count)]
        try:
            await asyncio.wait_for(asyncio.gather(*(entry.wait() for entry in observed)), timeout=3)
            self.assertEqual(set(iter(queue.take, None)), {
                SampledFrame(f'camera-{index}', f'frame-{index}'.encode('ascii'))
                for index in range(count)
            })
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(closed, set(range(count)))

    async def test_retry_after_error_and_stall_and_close_on_cancellation(self):
        queue = FrameQueue(max_cameras=1, max_bytes=16, max_frame_bytes=16)
        connected = asyncio.Event()
        attempts = closed = 0

        @asynccontextmanager
        async def source():
            nonlocal attempts, closed
            attempts += 1
            attempt = attempts

            async def frames():
                if attempt == 1:
                    raise OSError('Synthetic disconnect')
                if attempt == 3:
                    yield b'sample'
                    connected.set()
                await asyncio.Future()

            try:
                yield frames()
            finally:
                closed += 1

        task = asyncio.create_task(sample_camera(
            'camera', source, queue, sample_interval=0.01, frame_timeout=0.02,
            retry_initial=0.01, retry_max=0.03,
        ))
        try:
            await asyncio.wait_for(connected.wait(), timeout=3)
            self.assertEqual(queue.take(), SampledFrame('camera', b'sample'))
            self.assertEqual((attempts, closed), (3, 2))
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(closed, 3)
