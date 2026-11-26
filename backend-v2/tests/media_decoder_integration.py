"""Exercise the real decoder with generated MP4 files and no network sources."""

import asyncio
import sys
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import av
from PIL import Image, ImageDraw

from media_gateway.frame_queue import FrameQueue
from media_gateway.sampler import sample_camera
from media_gateway.video_source import local_video_source

WIDTH, HEIGHT = 160, 64


def generate_clip(path, fps):
    with av.open(str(path), mode='w') as output:
        stream = output.add_stream('mpeg4', rate=fps)
        stream.width, stream.height, stream.pix_fmt = WIDTH, HEIGHT, 'yuv420p'
        for index in range(fps):
            image = Image.new('RGB', (WIDTH, HEIGHT), 'black')
            draw = ImageDraw.Draw(image)
            draw.text((8, 8), f'Frame {index:03d}', fill='white')
            draw.text((8, 30), f'PTS {index / fps:.3f}s', fill='white')
            frame = av.VideoFrame.from_image(image)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


class RecordingQueue(FrameQueue):
    def __init__(self):
        size = WIDTH * HEIGHT * 3
        super().__init__(max_cameras=3, max_bytes=size * 3, max_frame_bytes=size)
        self.samples = []

    def offer(self, frame):
        accepted = super().offer(frame)
        if accepted:
            self.samples.append(frame)
        return accepted


class TestSyntheticDecoder(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.clips = {fps: self.folder / f'{fps}.mp4' for fps in (10, 24, 30)}
        for fps, path in self.clips.items():
            generate_clip(path, fps)

    async def test_unavailable_local_file_fails_before_decoder_launch(self):
        for path in (self.folder / 'missing.mp4', self.folder / 'test.txt'):
            with self.subTest(path=path.name), self.assertRaises(OSError):
                async with local_video_source(path):
                    self.fail('Unavailable or unsupported source was opened')

    async def test_decoder_preserves_frame_order_and_visible_markers(self):
        async with local_video_source(self.clips[24]) as frames:
            decoded = [frame async for frame in frames]
        self.assertEqual(len(decoded), 24)
        self.assertEqual([frame.index for frame in decoded], list(range(24)))
        for index, frame in enumerate(decoded):
            self.assertAlmostEqual(frame.source_timestamp, index / 24, places=6)
            self.assertEqual((frame.width, frame.height), (WIDTH, HEIGHT))
            self.assertEqual(frame.received_at.tzinfo, UTC)
            self.assertEqual(len(frame.data), WIDTH * HEIGHT * 3)
        self.assertGreater(len({frame.data for frame in decoded}), 20)
        self.assertGreater(max(decoded[0].data), 200)

    async def test_concurrent_sampling_rates_and_recovery_from_corruption_and_eof(self):
        corrupt = self.folder / 'corrupt.mp4'
        corrupt.write_bytes(b'synthetic invalid video')
        starts = dict.fromkeys(self.clips, 0)
        queue = RecordingQueue()

        def source(fps):
            starts[fps] += 1
            return local_video_source(corrupt if fps == 24 and starts[fps] == 1 else self.clips[fps])

        tasks = [asyncio.create_task(sample_camera(
            str(fps), lambda fps=fps: source(fps), queue,
            sample_interval=0.2, frame_timeout=5, retry_initial=0.02, retry_max=0.08,
        )) for fps in self.clips]
        try:
            async with asyncio.timeout(15):
                while (not all(starts[fps] >= (3 if fps == 24 else 2) for fps in self.clips)
                       or not any(frame.camera_id == '24' and frame.source_epoch == 3
                                  for frame in queue.samples)):
                    await asyncio.sleep(0.02)
        finally:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results))

        for fps in self.clips:
            epoch = 2 if fps == 24 else 1
            samples = [frame for frame in queue.samples
                       if frame.camera_id == str(fps) and frame.source_epoch == epoch]
            self.assertEqual(len(samples), 5)
            self.assertEqual(samples[0].source_timestamp, 0)
            self.assertEqual(samples[0].source_frame_index, 0)
            for earlier, current in zip(samples, samples[1:]):
                self.assertGreater(current.source_frame_index, earlier.source_frame_index)
                self.assertGreaterEqual(current.sampled_monotonic, earlier.sampled_monotonic)
                gap = current.source_timestamp - earlier.source_timestamp
                self.assertAlmostEqual(gap, 0.2, delta=1 / fps)
            self.assertTrue(all(frame.sample_interval == 0.2 and frame.received_at.tzinfo == UTC
                                for frame in samples))
        self.assertFalse(any(frame.camera_id == '24' and frame.source_epoch == 1 for frame in queue.samples))
        self.assertEqual({frame.camera_id for frame in iter(queue.take, None)}, {'10', '24', '30'})

    async def test_stalled_decoder_is_terminated_before_retry(self):
        spawn = asyncio.create_subprocess_exec
        processes = []
        queue = RecordingQueue()

        async def stall_once(*args, **kwargs):
            if not processes:
                process = await spawn(sys.executable, '-c', 'import time; time.sleep(60)', **kwargs)
            else:
                process = await spawn(*args, **kwargs)
            processes.append(process)
            return process

        with patch('media_gateway.video_source.asyncio.create_subprocess_exec', side_effect=stall_once):
            task = asyncio.create_task(sample_camera(
                'camera', lambda: local_video_source(self.clips[10]), queue,
                sample_interval=0.2, frame_timeout=2, retry_initial=0.01, retry_max=0.03,
            ))
            try:
                async with asyncio.timeout(12):
                    while not queue.samples:
                        await asyncio.sleep(0.02)
                self.assertEqual(queue.samples[0].source_epoch, 2)
                self.assertIsNotNone(processes[0].returncode)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertTrue(all(process.returncode is not None for process in processes))
