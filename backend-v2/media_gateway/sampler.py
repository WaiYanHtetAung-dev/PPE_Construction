"""Sample decoded frames from a trusted media source, reconnecting on stalls."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from math import isfinite

from media_gateway.frame_queue import FrameQueue, SampledFrame
from media_gateway.video_source import DecodedFrame

FrameSource = Callable[[], AbstractAsyncContextManager[AsyncIterator[bytes | DecodedFrame]]]


async def sample_camera(
    camera_id: str,
    source: FrameSource,
    queue: FrameQueue,
    *,
    sample_interval: float,
    frame_timeout: float,
    retry_initial: float,
    retry_max: float,
) -> None:
    """Run one camera until cancelled. Source adapters own decoder cleanup."""
    if (not camera_id or not all(isfinite(value) and value > 0 for value in
                                 (sample_interval, frame_timeout, retry_initial, retry_max))
            or retry_initial > retry_max):
        raise ValueError('Invalid camera sampling configuration')

    clock = asyncio.get_running_loop().time
    next_sample = clock()
    retry_delay = retry_initial
    epoch = 0
    while True:
        epoch += 1
        connected_at = clock()
        source_due = None
        try:
            async with source() as frames:
                while True:
                    async with asyncio.timeout(frame_timeout):
                        data = await anext(frames)
                    now = clock()
                    if isinstance(data, DecodedFrame):
                        pts = data.source_timestamp
                        if source_due is None or pts >= source_due - 1e-9:
                            queue.offer(SampledFrame(
                                camera_id, data.data, data.received_at, pts, data.index, epoch,
                                now, sample_interval, data.width, data.height,
                            ))
                            source_due = pts + sample_interval
                    elif now >= next_sample:
                        queue.offer(SampledFrame(camera_id, data))
                        next_sample = now + sample_interval
        except (OSError, StopAsyncIteration):
            # A stable connection resets retries. A source that repeatedly emits one
            # frame and drops still backs off.
            if clock() - connected_at >= retry_max:
                retry_delay = retry_initial
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, retry_max)
