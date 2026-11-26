import unittest
from concurrent.futures import ThreadPoolExecutor

from media_gateway.frame_queue import FrameQueue, SampledFrame


class TestFrameQueue(unittest.TestCase):
    def test_latest_frame_preserves_turn_and_busy_camera_rejoins_at_tail(self):
        queue = FrameQueue(max_cameras=2, max_bytes=16, max_frame_bytes=8)
        self.assertTrue(queue.offer(SampledFrame('busy', b'old')))
        self.assertTrue(queue.offer(SampledFrame('quiet', b'frame')))
        self.assertTrue(queue.offer(SampledFrame('busy', b'latest')))
        self.assertEqual(queue.take(), SampledFrame('busy', b'latest'))
        self.assertTrue(queue.offer(SampledFrame('busy', b'next')))
        self.assertEqual(queue.take(), SampledFrame('quiet', b'frame'))
        self.assertEqual(queue.take(), SampledFrame('busy', b'next'))
        self.assertIsNone(queue.take())

    def test_byte_and_camera_limits_preserve_already_admitted_frames(self):
        queue = FrameQueue(max_cameras=2, max_bytes=8, max_frame_bytes=6)
        self.assertFalse(queue.offer(SampledFrame('a', b'')))
        self.assertFalse(queue.offer(SampledFrame('a', b'1234567')))
        self.assertTrue(queue.offer(SampledFrame('a', b'1234')))
        self.assertFalse(queue.offer(SampledFrame('b', b'12345')))
        self.assertTrue(queue.offer(SampledFrame('b', b'1234')))
        self.assertFalse(queue.offer(SampledFrame('a', b'12345')))
        self.assertTrue(queue.offer(SampledFrame('a', b'1')))
        self.assertFalse(queue.offer(SampledFrame('c', b'1')))
        self.assertEqual(queue.take(), SampledFrame('a', b'1'))
        self.assertTrue(queue.offer(SampledFrame('c', b'5678')))
        self.assertEqual(queue.take(), SampledFrame('b', b'1234'))
        self.assertEqual(queue.take(), SampledFrame('c', b'5678'))

    def test_concurrent_producers_cannot_exceed_byte_budget(self):
        queue = FrameQueue(max_cameras=100, max_bytes=32, max_frame_bytes=4)
        frames = [SampledFrame(str(camera), b'1234') for camera in range(100)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(queue.offer, frames))
        expected = {frame for frame, accepted in zip(frames, admitted) if accepted}
        self.assertEqual(len(expected), 8)
        self.assertEqual(set(iter(queue.take, None)), expected)
